"""The Editor engine (`editor/1`) — PHASE4_EDITOR_ARCHITECTURE.md §4.

Deterministically projects the EXACT pinned draft, its claim usages, the
accepted brief contract, and the claims' evidence STATEMENTS into a
bounded leak-free projection, asks the provider-neutral AI boundary for
`editor-review/1` FINDINGS (purpose EDITOR_REVIEW — the model never
outputs a verdict), validates every finding anchor against the projected
identities (a violating output is a durable VALIDATION_FAILED attempt
with zero review rows), and materializes exactly one immutable
EditorialReview per SUCCEEDED attempt through
`ReviewService.create_review` — the single canonical persistence path,
which also recomputes the deterministic drift guard and computes the
verdict from the merged findings.

The engine never transitions workflow (humans advance out of EDITING),
never calls a provider when preconditions fail, and never receives
source bodies, clean_text, raw payloads, or secrets. Findings are policy
signals: never Evidence, never facts.
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
from contentos.briefs.models import ContentBrief
from contentos.briefs.repository import BriefRepository
from contentos.drafts.models import ContentDraft
from contentos.drafts.repository import DraftRepository
from contentos.research.models import ResearchEvidence
from contentos.reviews.enums import FindingDimension, FindingOrigin, FindingSeverity
from contentos.reviews.errors import (
    IncompleteReviewMaterializationError,
    ReviewConflictError,
    ReviewGenerationMaterializationError,
    ReviewInputError,
)
from contentos.reviews.generation_schemas import (
    EDITOR_REVIEW_INPUT_REFS_SCHEMA,
    EDITOR_REVIEW_SCHEMA_NAME,
    EDITOR_REVIEW_SCHEMA_VERSION,
    EditorReviewV1,
)
from contentos.reviews.integrity import DRIFT_FINDING_PREFIX
from contentos.reviews.models import EditorialReview
from contentos.reviews.policies import DEFAULT_EDITOR_VERDICT_POLICY, EditorVerdictPolicy
from contentos.reviews.repository import ReviewRepository
from contentos.reviews.service import ReviewService
from contentos.reviews.values import (
    EDITOR_ENGINE_NAME,
    EDITOR_ENGINE_VERSION,
    ReviewFindingInput,
)
from contentos.sources.models import Source

EDITOR_REVIEW_TEMPLATE_NAME = "editor-review"
EDITOR_REVIEW_TEMPLATE_VERSION = "1"

MAX_EVIDENCE_STATEMENT_CHARS = 500
MAX_OUTPUT_TOKENS = 8_000

# Versioned by EDITOR_REVIEW_TEMPLATE_NAME/VERSION; substantive changes
# REQUIRE a version bump (instructions are never hashed or persisted).
_TEMPLATE_V1 = """\
Sen Konsepthane için Türkçe içerikleri değerlendiren bir EDİTÖRSÜN.
Görevin, sana verilen TASLAĞI yalnızca birlikte verilen brief
sözleşmesine, iddialara (claims) ve kanıt cümlelerine göre incelemek ve
BULGULAR (findings) üretmek. Kurallar bağlayıcıdır:

1. YALNIZCA projeksiyondaki bilgiye göre yargıla. Kendi bilginden olgu,
   sayı, tarih veya dış kaynak EKLEME; dış bilgiye dayanan bulgu YASAK.
2. Karar (verdict) ÜRETME — sen yalnızca bulgu yazarsın; karar
   deterministik politikayla hesaplanır.
3. claim_faithfulness: iddiaya bağlanmış metin, iddianın (ve kanıt
   cümlelerinin) söylediğinden daha kesin veya daha geniş konuşuyorsa
   bulgu yaz; emin değilsen dürüst bir şiddetle yine bulgu yaz.
4. exclusion_compliance: brief'in exclusions listesini ihlal eden her
   blok için bulgu yaz.
5. objective_fit: bölümler brief'in hedefini/kitlesini karşılamıyorsa;
   uncertainty_framing: çekince dili yumuşatılmışsa;
   clarity_style: anlaşılmaz, tekrar eden veya çeviri kokan metin için.
6. Her bulgu için: benzersiz slug finding_key, dimension, severity
   (blocking/major/minor — dürüst ol), kısa açıklama ve mümkünse
   block_id / claim_ref çapası. Yalnızca projeksiyonda VAR OLAN block_id
   ve claim id'leri kullan.
7. Metinlerde URL, HTML, script YOK. Bulgu yoksa boş liste döndür —
   bulgu uydurma.
Çıktı: yalnızca editor-review/1 şemasına uyan JSON.
"""


@dataclass(frozen=True, slots=True)
class EditorGenerationResult:
    """`reused` is True when a durable attempt/review satisfied the call."""

    attempt: AiGenerationAttempt
    status: GenerationStatus
    review: EditorialReview | None
    attempt_created: bool
    review_created: bool
    reused: bool


@dataclass(frozen=True, slots=True)
class _EditorContext:
    work_item_id: uuid.UUID
    draft: ContentDraft
    brief: ContentBrief
    block_ids: frozenset[str]
    usable_claim_ids: frozenset[str]
    projection: dict[str, Any]
    input_refs: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _EditorOutputValidator:
    """Deterministic context-aware domain validation: every anchor must
    resolve inside the projected draft; reserved keys are forbidden."""

    block_ids: frozenset[str]
    usable_claim_ids: frozenset[str]

    def __call__(self, payload: EditorReviewV1) -> str | None:
        seen: set[str] = set()
        for finding in payload.findings:
            if finding.finding_key in seen:
                return "duplicate_finding_key"
            seen.add(finding.finding_key)
            if finding.finding_key.startswith(DRIFT_FINDING_PREFIX):
                return "reserved_finding_key"
            if finding.block_id is not None and finding.block_id not in self.block_ids:
                return "unknown_block_ref"
            if finding.claim_ref is not None and finding.claim_ref not in self.usable_claim_ids:
                return "unknown_claim_ref"
        return None


def payload_to_findings(payload: EditorReviewV1) -> list[ReviewFindingInput]:
    """Schema -> the canonical persistence DTOs (origin is OURS, and the
    text-safety ban re-runs inside the service via cleaned())."""
    return [
        ReviewFindingInput(
            finding_key=finding.finding_key,
            dimension=FindingDimension(finding.dimension),
            severity=FindingSeverity(finding.severity),
            origin=FindingOrigin.MODEL_SIGNAL,
            description=finding.description,
            recommendation=finding.recommendation,
            block_id=finding.block_id,
            brief_claim_id=(
                uuid.UUID(finding.claim_ref) if finding.claim_ref is not None else None
            ),
        )
        for finding in payload.findings
    ]


class EditorEngine:
    """Transport-neutral engine; flushes only — the caller commits."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._briefs = BriefRepository(session)
        self._drafts = DraftRepository(session)
        self._reviews = ReviewRepository(session)
        self._service = ReviewService(session)
        self._generation = StructuredGenerationService(session)

    def generate_review(
        self,
        work_item_id: uuid.UUID,
        *,
        provider: StructuredGenerationProvider,
        retry_number: int = 0,
        supersede_reason: str | None = None,
        request_id: str | None = None,
        verdict_policy: EditorVerdictPolicy = DEFAULT_EDITOR_VERDICT_POLICY,
    ) -> EditorGenerationResult:
        context = self._resolve_context(work_item_id, verdict_policy)

        request = GenerationRequest(
            purpose=GenerationPurpose.EDITOR_REVIEW,
            schema_name=EDITOR_REVIEW_SCHEMA_NAME,
            schema_version=EDITOR_REVIEW_SCHEMA_VERSION,
            template_name=EDITOR_REVIEW_TEMPLATE_NAME,
            template_version=EDITOR_REVIEW_TEMPLATE_VERSION,
            input_refs=context.input_refs,
            input_projection=context.projection,
            generation_bounds={"max_output_tokens": MAX_OUTPUT_TOKENS},
            retry_number=retry_number,
            instructions=_TEMPLATE_V1,
        )
        spec: StructuredOutputSpec[EditorReviewV1] = StructuredOutputSpec(
            schema_name=EDITOR_REVIEW_SCHEMA_NAME,
            schema_version=EDITOR_REVIEW_SCHEMA_VERSION,
            model_type=EditorReviewV1,
            domain_validator=_EditorOutputValidator(
                block_ids=context.block_ids,
                usable_claim_ids=context.usable_claim_ids,
            ),
        )
        execution = self._generation.execute(request, spec, provider)

        if execution.status is not GenerationStatus.SUCCEEDED:
            return EditorGenerationResult(
                attempt=execution.attempt,
                status=execution.status,
                review=None,
                attempt_created=execution.created,
                review_created=False,
                reused=False,
            )
        if execution.created:
            assert execution.payload is not None
            try:
                creation = self._service.create_review(
                    work_item_id,
                    payload_to_findings(execution.payload),
                    generation_attempt=execution.attempt,
                    supersede_reason=supersede_reason,
                    request_id=request_id,
                    verdict_policy=verdict_policy,
                )
            except (ReviewConflictError, ReviewInputError) as error:
                # The completed AI attempt keeps its real SUCCEEDED status;
                # this is a deterministic persistence-time rejection.
                raise ReviewGenerationMaterializationError(
                    f"valid Editor output was rejected by review persistence: {error}"
                ) from error
            return EditorGenerationResult(
                attempt=execution.attempt,
                status=execution.status,
                review=creation.review,
                attempt_created=True,
                review_created=creation.created,
                reused=not creation.created,
            )
        return self._resolve_reused_attempt(execution.attempt)

    # --- internal -----------------------------------------------------------

    def _resolve_reused_attempt(self, attempt: AiGenerationAttempt) -> EditorGenerationResult:
        # Serialize materialization on the attempt row (read lock only).
        self._session.execute(
            select(AiGenerationAttempt.id)
            .where(AiGenerationAttempt.id == attempt.id)
            .with_for_update()
        )
        review = self._reviews.get_by_generation_attempt(attempt.id)
        if review is not None:
            return EditorGenerationResult(
                attempt=attempt,
                status=attempt.status,
                review=review,
                attempt_created=False,
                review_created=False,
                reused=True,
            )
        raise IncompleteReviewMaterializationError(
            "this SUCCEEDED editor attempt has no materialized review and its "
            "raw output was (by design) never persisted; request a new "
            "provider invocation explicitly with retry_number + 1"
        )

    def _resolve_context(
        self, work_item_id: uuid.UUID, verdict_policy: EditorVerdictPolicy
    ) -> _EditorContext:
        """Preconditions + deterministic bounded projection — zero AI cost
        is spent on a state the persistence path would refuse."""
        draft, brief = self._service.resolve_reviewable_draft(work_item_id)

        usages = self._drafts.list_claim_usages(draft.id)
        usable_claim_ids = sorted({str(usage.brief_claim_id) for usage in usages})
        claims = [
            claim
            for claim in self._briefs.list_claims(brief.id)
            if str(claim.id) in set(usable_claim_ids)
        ]

        # Flat evidence units (the proven Writer pattern): claims carry
        # evidence IDS only; the bounded unit list lives at the root.
        claim_projection: list[dict[str, Any]] = []
        evidence_units: list[dict[str, Any]] = []
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
                evidence_units.append(
                    {
                        "research_evidence_id": str(evidence.id),
                        "statement": evidence.statement[:MAX_EVIDENCE_STATEMENT_CHARS],
                        "verification_status": evidence.verification_status.value,
                        "source_slug": source.slug if source is not None else None,
                        "trust_tier": (source.trust_tier.value if source is not None else None),
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

        # Flat block projection (the boundary's nesting-depth limit forbids
        # the raw nested body): section order and block order are preserved;
        # claim bindings travel via claim_usages, handling discharges via
        # uncertainty_discharges — all at the projection root.
        draft_sections: list[dict[str, Any]] = []
        draft_blocks: list[dict[str, Any]] = []
        uncertainty_discharges: list[dict[str, Any]] = []
        for section in draft.body.get("sections", []):
            draft_sections.append({"key": section.get("key"), "heading": section.get("heading")})
            for block in section.get("blocks", []):
                draft_blocks.append(
                    {
                        "section_key": section.get("key"),
                        "block_id": block.get("block_id"),
                        "kind": block.get("kind"),
                        "text": block.get("text"),
                    }
                )
                for handling_ref in block.get("uncertainty_refs", []):
                    uncertainty_discharges.append(
                        {"block_id": block.get("block_id"), "handling_id": handling_ref}
                    )
        block_ids = frozenset(str(block["block_id"]) for block in draft_blocks)
        projection: dict[str, Any] = {
            "draft": {
                "title_proposal": draft.title_proposal,
                "body_schema_version": draft.body_schema_version,
            },
            "draft_sections": draft_sections,
            "draft_blocks": draft_blocks,
            "uncertainty_discharges": uncertainty_discharges,
            "claim_usages": [
                {
                    "brief_claim_id": str(usage.brief_claim_id),
                    "section_key": usage.section_key,
                    "block_id": usage.block_id,
                }
                for usage in usages
            ],
            "claims": claim_projection,
            "evidence_units": evidence_units,
            "brief": {
                "target_audience": brief.target_audience,
                "intent_summary": brief.intent_summary,
                "original_angle": brief.original_angle,
                "content_objective": brief.content_objective,
                "required_sections": brief.required_sections,
                "optional_sections": brief.optional_sections,
                "exclusions": list(brief.exclusions),
                "uncertainty_notes": list(brief.uncertainty_notes),
                "locale": brief.locale,
                "market": brief.market,
            },
        }
        input_refs = {
            "schema": EDITOR_REVIEW_INPUT_REFS_SCHEMA,
            "work_item_id": str(work_item_id),
            "content_draft_id": str(draft.id),
            "draft_version": draft.version,
            "draft_content_hash": draft.content_hash,
            "content_brief_id": str(brief.id),
            "brief_claim_ids": usable_claim_ids,
            "engine_name": EDITOR_ENGINE_NAME,
            "engine_version": EDITOR_ENGINE_VERSION,
            "verdict_policy": verdict_policy.version,
        }
        return _EditorContext(
            work_item_id=work_item_id,
            draft=draft,
            brief=brief,
            block_ids=block_ids,
            usable_claim_ids=frozenset(usable_claim_ids),
            projection=projection,
            input_refs=input_refs,
        )
