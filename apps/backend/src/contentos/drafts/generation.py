"""The Writer engine (`writer/1`) — accepted Phase 4 design §2/§8–§10.

Deterministically projects the EXACT accepted brief and its pinned
artifacts into a bounded `WriterInputProjection`, asks the
provider-neutral AI boundary for a `writer-draft/1` structured draft
(purpose WRITER_DRAFT), validates the output through the SAME
deterministic Writer policies the persistence path enforces (a violating
model output is VALIDATION_FAILED with zero draft rows), and materializes
exactly one immutable ContentDraft per SUCCEEDED attempt through
`DraftService.create_generated_draft` — the single canonical persistence
path.

The engine never transitions workflow, never touches upstream artifacts,
and never receives source bodies, `clean_text`, raw payloads, headers,
or secrets: the model can only phrase what the projection carries, and
every evidence-derived datum stays attached to its ResearchEvidence
identity through the claim projection.

Idempotency mirrors Tasks 9/10/12: same identity + same retry_number
reuses the durable attempt (no provider call) and returns its draft; a
SUCCEEDED attempt whose draft materialization is missing is a typed
`IncompleteDraftMaterializationError` recovered ONLY by an explicit
`retry_number + 1`; a deterministic persistence rejection of valid output
keeps the attempt's real status (`DraftGenerationMaterializationError`).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.ai.dto import GenerationRequest
from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.models import AiGenerationAttempt
from contentos.ai.protocol import StructuredGenerationProvider
from contentos.ai.service import StructuredGenerationService
from contentos.ai.validation import StructuredOutputSpec
from contentos.briefs.enums import BriefStatus
from contentos.briefs.models import BriefClaim, ContentBrief
from contentos.briefs.repository import BriefRepository
from contentos.drafts.enums import DraftBlockKind
from contentos.drafts.errors import (
    DraftConflictError,
    DraftGenerationMaterializationError,
    DraftInputError,
    DraftPolicyViolationError,
    DraftPreconditionError,
    IncompleteDraftMaterializationError,
)
from contentos.drafts.generation_schemas import (
    WRITER_DRAFT_INPUT_REFS_SCHEMA,
    WRITER_DRAFT_SCHEMA_NAME,
    WRITER_DRAFT_SCHEMA_VERSION,
    WriterDraftV1,
)
from contentos.drafts.models import ContentDraft
from contentos.drafts.policies import (
    DEFAULT_WRITER_ORIGINALITY_POLICY,
    DEFAULT_WRITER_VALIDATION_POLICY,
    HandlingRequirement,
    WriterOriginalityPolicy,
    WriterValidationPolicy,
    build_required_handling_manifest,
    validate_claim_semantics,
    validate_handling_coverage,
    validate_originality,
)
from contentos.drafts.repository import DraftRepository
from contentos.drafts.service import DraftService
from contentos.drafts.values import (
    WRITER_ENGINE_NAME,
    WRITER_ENGINE_VERSION,
    DraftBlock,
    DraftBodyInput,
    DraftSection,
)
from contentos.evidence_packs.repository import EvidencePackRepository
from contentos.ideas.models import Idea
from contentos.research.models import ResearchEvidence
from contentos.reviews.repository import ReviewRepository
from contentos.search_intent.models import SearchIntentAnalysis
from contentos.sources.models import Source
from contentos.workflow.enums import WorkflowState
from contentos.workflow.repository import WorkflowRepository

WRITER_DRAFT_TEMPLATE_NAME = "writer-draft"
WRITER_DRAFT_TEMPLATE_VERSION = "2"

MAX_EVIDENCE_STATEMENT_CHARS = 500
MAX_OUTPUT_TOKENS = 16_000

# Versioned by WRITER_DRAFT_TEMPLATE_NAME/VERSION; substantive changes
# REQUIRE a version bump (instructions are never hashed or persisted).
_TEMPLATE_V1 = """\
Sen Konsepthane için Türkçe içerik üreten bir YAZARSIN. Görevin, sana
verilen KABUL EDİLMİŞ yazım sözleşmesini (brief) özgün, doğal ve akıcı
Türkçe bir TASLAĞA dönüştürmek. Kurallar bağlayıcıdır:

1. SADECE brief'teki iddiaları (claims) kullan. Kendi bilginden tarih,
   sayı, istatistik, fiyat veya doğrulanabilir olgu EKLEME. Sayı içeren
   her blok ilgili claim_refs ile bağlanmalı.
2. source_assertion türü iddiaları daima kaynağa atıfla aktar ("...
   kaynağa göre", "... belirtiyor"); asla çıplak gerçek gibi yazma.
3. inference türü iddiaları çıkarım diliyle yaz ("olabilir",
   "görünüyor"); kesinliğe çevirme.
4. required_handling listesindeki HER kaydı en az bir blokta
   uncertainty_refs ile karşıla; uyarıları asla yumuşatma veya silme.
5. Bölüm anahtarları brief'in bölüm sözleşmesine uymalı; zorunlu her
   bölüm tam bir kez bulunmalı.
6. Metinde URL, HTML, script, marka linki YOK. İç bağlantı ihtiyaçları
   internal_link_need bloklarıyla, görsel ihtiyaçları media_need
   bloklarıyla (indeks referanslı) verilir.
7. Kanıt cümlelerini KOPYALAMA; kendi cümlelerinle, özgün yapıda yaz.
   ARAŞTIR, ÇEVİRİP-YAYINLAMA.
8. Brief'teki exclusions listesine kesinlikle uy. Sahte kullanıcı
   yorumu/deneyimi üretme; eksik arama sinyallerini değer uydurarak
   doldurma.
9. Ton: brief'in hedef kitlesine uygun, doğal, pratik ve yardımsever
   Türkçe. Çeviri kokusu yok, kaynak yapısı taklidi yok.
10. editorial_findings listesi doluysa bu bir YENİDEN YAZIMDIR: her
    bulguyu ilgili yerde gider; bulgular talimattır, asla yeni olgu
    kaynağı değildir.
Çıktı: yalnızca writer-draft/1 şemasına uyan JSON.
"""


@dataclass(frozen=True, slots=True)
class WriterGenerationResult:
    """`reused` is True when a durable attempt/draft satisfied the call."""

    attempt: AiGenerationAttempt
    status: GenerationStatus
    draft: ContentDraft | None
    attempt_created: bool
    draft_created: bool
    reused: bool


@dataclass(frozen=True, slots=True)
class _WriterContext:
    brief: ContentBrief
    work_item_id: uuid.UUID
    claims: list[BriefClaim]
    claims_by_id: dict[str, BriefClaim]
    manifest: list[HandlingRequirement]
    evidence_statements: list[str]
    projection: dict[str, Any]
    input_refs: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _WriterOutputValidator:
    """Deterministic context-aware domain validation (Task-8 hook).

    Runs the SAME Writer policies persistence enforces, against frozen
    context — a violating model output becomes VALIDATION_FAILED with
    zero draft rows, never a materialization error.
    """

    brief: ContentBrief
    claims_by_id: dict[str, BriefClaim]
    manifest: list[HandlingRequirement]
    evidence_statements: list[str]
    required_keys: frozenset[str]
    optional_keys: frozenset[str]
    link_needs: int
    media_needs: int
    validation_policy: WriterValidationPolicy
    originality_policy: WriterOriginalityPolicy

    def __call__(self, payload: WriterDraftV1) -> str | None:
        try:
            body = payload_to_body_input(payload)
            cleaned = body.cleaned()
        except DraftInputError:
            return "invalid_body_structure"

        body_keys = [section["key"] for section in cleaned["sections"]]
        if any(key not in body_keys for key in self.required_keys):
            return "missing_required_section"
        if any(key not in self.required_keys | self.optional_keys for key in body_keys):
            return "section_outside_contract"
        for section in cleaned["sections"]:
            for block in section["blocks"]:
                for claim_ref in block["claim_refs"]:
                    if claim_ref not in self.claims_by_id:
                        return "unknown_claim_ref"
                if block["kind"] == DraftBlockKind.INTERNAL_LINK_NEED.value:
                    if block["link_need_ref"] >= self.link_needs:
                        return "unknown_link_need"
                if block["kind"] == DraftBlockKind.MEDIA_NEED.value:
                    if block["media_need_ref"] >= self.media_needs:
                        return "unknown_media_need"
        try:
            validate_handling_coverage(self.manifest, cleaned, self.validation_policy)
            validate_claim_semantics(cleaned, self.claims_by_id, self.validation_policy)
            validate_originality(
                cleaned,
                payload.title_proposal,
                self.evidence_statements,
                self.brief,
                self.originality_policy,
            )
        except DraftPolicyViolationError:
            return "writer_policy_violation"
        return None


def payload_to_body_input(payload: WriterDraftV1) -> DraftBodyInput:
    """Schema -> the canonical persistence DTO (system fields stay ours)."""
    return DraftBodyInput(
        sections=tuple(
            DraftSection(
                key=section.key,
                heading=section.heading,
                blocks=tuple(
                    DraftBlock(
                        block_id=block.block_id,
                        kind=DraftBlockKind(block.kind),
                        text=block.text,
                        claim_refs=tuple(uuid.UUID(ref) for ref in block.claim_refs),
                        uncertainty_refs=tuple(block.uncertainty_refs),
                        link_need_ref=block.link_need_ref,
                        media_need_ref=block.media_need_ref,
                    )
                    for block in section.blocks
                ),
            )
            for section in payload.sections
        )
    )


class WriterEngine:
    """Transport-neutral engine; flushes only — the caller commits."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._briefs = BriefRepository(session)
        self._packs = EvidencePackRepository(session)
        self._drafts = DraftRepository(session)
        self._service = DraftService(session)
        self._workflow = WorkflowRepository(session)
        self._generation = StructuredGenerationService(session)

    def generate_draft(
        self,
        content_brief_id: uuid.UUID,
        *,
        provider: StructuredGenerationProvider,
        retry_number: int = 0,
        supersede_reason: str | None = None,
        request_id: str | None = None,
        validation_policy: WriterValidationPolicy = DEFAULT_WRITER_VALIDATION_POLICY,
        originality_policy: WriterOriginalityPolicy = DEFAULT_WRITER_ORIGINALITY_POLICY,
    ) -> WriterGenerationResult:
        context = self._resolve_context(content_brief_id, validation_policy, originality_policy)

        request = GenerationRequest(
            purpose=GenerationPurpose.WRITER_DRAFT,
            schema_name=WRITER_DRAFT_SCHEMA_NAME,
            schema_version=WRITER_DRAFT_SCHEMA_VERSION,
            template_name=WRITER_DRAFT_TEMPLATE_NAME,
            template_version=WRITER_DRAFT_TEMPLATE_VERSION,
            input_refs=context.input_refs,
            input_projection=context.projection,
            generation_bounds={"max_output_tokens": MAX_OUTPUT_TOKENS},
            retry_number=retry_number,
            instructions=_TEMPLATE_V1,
        )
        brief = context.brief
        spec: StructuredOutputSpec[WriterDraftV1] = StructuredOutputSpec(
            schema_name=WRITER_DRAFT_SCHEMA_NAME,
            schema_version=WRITER_DRAFT_SCHEMA_VERSION,
            model_type=WriterDraftV1,
            domain_validator=_WriterOutputValidator(
                brief=brief,
                claims_by_id=context.claims_by_id,
                manifest=context.manifest,
                evidence_statements=context.evidence_statements,
                required_keys=frozenset(str(entry.get("key")) for entry in brief.required_sections),
                optional_keys=frozenset(str(entry.get("key")) for entry in brief.optional_sections),
                link_needs=len(brief.internal_link_needs),
                media_needs=len(brief.media_needs),
                validation_policy=validation_policy,
                originality_policy=originality_policy,
            ),
        )
        execution = self._generation.execute(request, spec, provider)

        if execution.status is not GenerationStatus.SUCCEEDED:
            return WriterGenerationResult(
                attempt=execution.attempt,
                status=execution.status,
                draft=None,
                attempt_created=execution.created,
                draft_created=False,
                reused=False,
            )
        if execution.created:
            assert execution.payload is not None
            body = payload_to_body_input(execution.payload)
            try:
                creation = self._service.create_generated_draft(
                    content_brief_id,
                    body,
                    generation_attempt=execution.attempt,
                    title_proposal=execution.payload.title_proposal,
                    supersede_reason=supersede_reason,
                    request_id=request_id,
                    validation_policy=validation_policy,
                    originality_policy=originality_policy,
                )
            except (DraftConflictError, DraftInputError) as error:
                # The completed AI attempt keeps its real SUCCEEDED status;
                # this is a deterministic persistence-time rejection.
                raise DraftGenerationMaterializationError(
                    f"valid Writer output was rejected by draft persistence: {error}"
                ) from error
            return WriterGenerationResult(
                attempt=execution.attempt,
                status=execution.status,
                draft=creation.draft,
                attempt_created=True,
                draft_created=creation.created,
                reused=not creation.created,
            )
        return self._resolve_reused_attempt(execution.attempt)

    # --- internal -----------------------------------------------------------

    def _resolve_reused_attempt(self, attempt: AiGenerationAttempt) -> WriterGenerationResult:
        # Serialize materialization on the attempt row (read lock only).
        self._session.execute(
            select(AiGenerationAttempt.id)
            .where(AiGenerationAttempt.id == attempt.id)
            .with_for_update()
        )
        draft = self._drafts.get_by_generation_attempt(attempt.id)
        if draft is not None:
            return WriterGenerationResult(
                attempt=attempt,
                status=attempt.status,
                draft=draft,
                attempt_created=False,
                draft_created=False,
                reused=True,
            )
        raise IncompleteDraftMaterializationError(
            "this SUCCEEDED writer attempt has no materialized draft and its "
            "raw output was (by design) never persisted; request a new "
            "provider invocation explicitly with retry_number + 1"
        )

    def _resolve_context(
        self,
        content_brief_id: uuid.UUID,
        validation_policy: WriterValidationPolicy,
        originality_policy: WriterOriginalityPolicy,
    ) -> _WriterContext:
        """Preconditions + deterministic bounded projection — zero AI cost
        is spent on a contract the persistence path would refuse."""
        brief = self._briefs.get_brief(content_brief_id)
        if brief is None:
            raise DraftPreconditionError(f"no content brief with id {content_brief_id}")
        if brief.status is not BriefStatus.ACCEPTED_FOR_DRAFTING:
            raise DraftPreconditionError(
                "writer generation requires the EXACT accepted brief version "
                f"(brief status: {brief.status.value})"
            )
        work_item = self._workflow.get_by_id(brief.work_item_id)
        if work_item is None:  # pragma: no cover - RESTRICT FK guarantees this
            raise DraftPreconditionError("the brief has no resolvable work item")
        if work_item.current_state is not WorkflowState.DRAFTING:
            raise DraftPreconditionError(
                "writer generation requires the work item to be in DRAFTING "
                f"(current: {work_item.current_state.value})"
            )
        pack = self._packs.get_pack(brief.evidence_pack_id)
        if pack is None:  # pragma: no cover - RESTRICT FK guarantees this
            raise DraftPreconditionError("the brief has no resolvable evidence pack")
        idea = self._session.get(Idea, brief.idea_id)
        intent = self._session.get(SearchIntentAnalysis, brief.search_intent_analysis_id)
        if idea is None or intent is None:  # pragma: no cover - RESTRICT FKs
            raise DraftPreconditionError("the brief's pinned artifacts are unresolvable")

        claims = self._briefs.list_claims(brief.id)
        claims_by_id = {str(claim.id): claim for claim in claims}
        contradictions = self._packs.list_contradictions(pack.id)
        manifest = build_required_handling_manifest(brief, pack, contradictions, claims)

        # Rework feedback (Editor loop): when this DRAFTING cycle was entered
        # from CHANGES_REQUESTED and the durable rework entry pins an
        # editorial review, that review's findings travel to the Writer as
        # bounded ids + text — a policy signal, never a new fact channel.
        editorial_findings: list[dict[str, Any]] = []
        rework_review_id: str | None = None
        drafting_entry = self._workflow.get_latest_entry_event(work_item.id, WorkflowState.DRAFTING)
        if drafting_entry is not None and (
            drafting_entry.from_state is WorkflowState.CHANGES_REQUESTED
        ):
            rework_entry = self._workflow.get_latest_entry_event(
                work_item.id, WorkflowState.CHANGES_REQUESTED
            )
            raw_review_id = (
                (rework_entry.artifact_refs or {}).get("editorial_review_id")
                if rework_entry is not None
                else None
            )
            if isinstance(raw_review_id, str):
                try:
                    parsed_review_id = uuid.UUID(raw_review_id)
                except ValueError:
                    parsed_review_id = None
                if parsed_review_id is not None:
                    for finding in ReviewRepository(self._session).list_findings(parsed_review_id):
                        editorial_findings.append(
                            {
                                "finding_key": finding.finding_key,
                                "dimension": finding.dimension.value,
                                "severity": finding.severity.value,
                                "block_id": finding.block_id,
                                "brief_claim_id": (
                                    str(finding.brief_claim_id)
                                    if finding.brief_claim_id is not None
                                    else None
                                ),
                                "description": finding.description,
                                "recommendation": finding.recommendation,
                            }
                        )
                    if editorial_findings:
                        rework_review_id = raw_review_id

        # Flat evidence units (the composition-engine pattern): claims carry
        # evidence IDS only; the bounded unit list lives at the projection
        # root so nesting stays within the boundary's depth limits.
        claim_projection: list[dict[str, Any]] = []
        evidence_units: list[dict[str, Any]] = []
        evidence_statements: list[str] = []
        seen_evidence: set[str] = set()
        for claim in claims:
            evidence_ids: list[str] = []
            for link in self._briefs.list_claim_evidence(claim.id):
                evidence = self._session.get(ResearchEvidence, link.research_evidence_id)
                if evidence is None:  # pragma: no cover - RESTRICT FK
                    continue
                evidence_ids.append(str(evidence.id))
                if str(evidence.id) in seen_evidence:
                    continue
                seen_evidence.add(str(evidence.id))
                source = self._session.get(Source, evidence.source_id)
                statement = evidence.statement[:MAX_EVIDENCE_STATEMENT_CHARS]
                evidence_statements.append(statement)
                evidence_units.append(
                    {
                        "research_evidence_id": str(evidence.id),
                        "statement": statement,
                        "verification_status": evidence.verification_status.value,
                        "source_slug": source.slug if source is not None else None,
                        "trust_tier": (source.trust_tier.value if source is not None else None),
                        "fetched_at": evidence.fetched_at.isoformat(),
                    }
                )
            claim_projection.append(
                {
                    "brief_claim_id": str(claim.id),
                    "claim_key": claim.claim_key,
                    "claim_text": claim.claim_text,
                    "claim_kind": claim.claim_kind.value,
                    "handling": claim.handling,
                    "evidence_ids": evidence_ids,
                }
            )

        projection: dict[str, Any] = {
            "brief": {
                "target_audience": brief.target_audience,
                "intent_summary": brief.intent_summary,
                "original_angle": brief.original_angle,
                "content_objective": brief.content_objective,
                "title_guidance": brief.title_guidance,
                "required_sections": brief.required_sections,
                "optional_sections": brief.optional_sections,
                "practical_requirements": brief.practical_requirements,
                "exclusions": list(brief.exclusions),
                "faq_questions": list(brief.faq_questions),
                "acceptance_criteria": brief.acceptance_criteria,
                "internal_link_needs": brief.internal_link_needs,
                "media_needs": brief.media_needs,
                "locale": brief.locale,
                "market": brief.market,
            },
            "claims": claim_projection,
            "evidence_units": evidence_units,
            "required_handling": [
                {
                    "handling_id": entry.handling_id,
                    "kind": entry.kind,
                    "description": entry.description,
                }
                for entry in manifest
            ],
            "contradictions": [
                {
                    "contradiction_id": str(entry.id),
                    "claim_key": entry.claim_key,
                    "nature": entry.nature,
                    "severity": entry.severity.value,
                    "resolution_status": entry.resolution_status.value,
                    "handling_recommendation": entry.handling_recommendation,
                }
                for entry in contradictions
            ],
            "search_intent": {
                "primary_intent": intent.primary_intent,
                "secondary_intents": list(intent.secondary_intents),
                "query_concepts": list(intent.query_concepts),
                "page_purpose": intent.page_purpose,
                "likely_format": intent.likely_format,
                "missing_signals": list(intent.missing_signals),
            },
            "idea": {
                "working_title": idea.working_title,
                "angle": idea.angle,
                "audience": idea.audience,
                "value_proposition": idea.value_proposition,
                "planning_dimensions": idea.planning_dimensions,
                "exclusions": list(idea.exclusions),
            },
            "work_item": {
                "title_working_label": work_item.title_working_label,
                "locale": work_item.locale,
                "market": work_item.market,
            },
            "editorial_findings": editorial_findings,
        }
        input_refs = {
            "schema": WRITER_DRAFT_INPUT_REFS_SCHEMA,
            "content_brief_id": str(brief.id),
            "work_item_id": str(brief.work_item_id),
            "idea_id": str(brief.idea_id),
            "evidence_pack_id": str(brief.evidence_pack_id),
            "search_intent_analysis_id": str(brief.search_intent_analysis_id),
            "brief_claim_ids": sorted(claims_by_id),
            "handling_ids": sorted(entry.handling_id for entry in manifest),
            "engine_name": WRITER_ENGINE_NAME,
            "engine_version": WRITER_ENGINE_VERSION,
            "validation_policy": f"{validation_policy.name}/{validation_policy.version}",
            "originality_policy": f"{originality_policy.name}/{originality_policy.version}",
        }
        if rework_review_id is not None:
            input_refs["rework_review_id"] = rework_review_id
        return _WriterContext(
            brief=brief,
            work_item_id=brief.work_item_id,
            claims=claims,
            claims_by_id=claims_by_id,
            manifest=manifest,
            evidence_statements=evidence_statements,
            projection=projection,
            input_refs=input_refs,
        )
