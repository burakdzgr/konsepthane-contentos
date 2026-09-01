"""The automated Brief Composition Engine (design implementation-order 11).

Deterministically assembles the exact pinned Phase-3 artifacts (selected
idea, READY evidence pack, search-intent analysis) into a bounded
projection, optionally asks the provider-neutral AI boundary for
model-assisted WORDING of the writing contract (purpose BRIEF_COMPOSITION,
strict structured output), deterministically merges the system-owned
requirements the model can never remove, and materializes ONE DRAFT
ContentBrief through the existing Task-11 BriefService — the single
canonical persistence path (version allocation, supersession, claim
persistence, content hash, structure guard, and every acceptance gate stay
exactly where Task 11 put them).

The engine never accepts a brief, never transitions workflow, and never
mutates any upstream artifact. It depends only on the provider-neutral
protocol (tests use the deterministic fake provider; OpenAI stays behind
contentos.ai.providers). A structure-guard failure on the composed
sections is an artifact/gate result — the DRAFT persists for inspection,
nothing retries automatically.
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
from contentos.briefs.enums import BriefClaimKind
from contentos.briefs.errors import (
    BriefClaimEvidenceError,
    BriefCompositionMaterializationError,
    BriefConflictError,
    BriefInputError,
    BriefProvenanceError,
    BriefStatusConflictError,
    CompositionPreconditionError,
    IncompleteBriefMaterializationError,
    InvalidCompositionAttemptError,
)
from contentos.briefs.generation_schemas import (
    BRIEF_COMPOSITION_INPUT_REFS_SCHEMA,
    BRIEF_COMPOSITION_SCHEMA_NAME,
    BRIEF_COMPOSITION_SCHEMA_VERSION,
    BriefCompositionV1,
)
from contentos.briefs.models import ContentBrief
from contentos.briefs.repository import BriefRepository
from contentos.briefs.service import BriefService, validate_composition_attempt
from contentos.briefs.structure_guard import (
    DEFAULT_BRIEF_STRUCTURE_POLICY,
    BriefStructurePolicy,
)
from contentos.briefs.values import (
    BRIEF_COMPOSER_NAME,
    BRIEF_COMPOSER_VERSION,
    MAX_EXCLUSION_LENGTH,
    MAX_UNCERTAINTY_NOTE_LENGTH,
    MAX_UNCERTAINTY_NOTES,
    AcceptanceCriterion,
    BriefClaimInput,
    BriefDraftInput,
    BriefSection,
    InternalLinkNeed,
    MediaNeed,
)
from contentos.evidence_packs.enums import (
    ContradictionResolutionStatus,
    ContradictionSeverity,
    EvidenceItemRole,
    EvidencePackSufficiency,
)
from contentos.evidence_packs.repository import EvidencePackRepository
from contentos.ideas.originality import find_fake_ugc_violations
from contentos.ideas.policy import DEFAULT_IDEA_ORIGINALITY_POLICY
from contentos.opportunities.enums import OpportunityDisposition
from contentos.research.enums import VerificationStatus
from contentos.research.models import ResearchEvidence
from contentos.sources.models import Source
from contentos.workflow.enums import WorkflowState
from contentos.workflow.repository import WorkflowRepository

BRIEF_COMPOSITION_TEMPLATE_NAME = "brief-composition"
BRIEF_COMPOSITION_TEMPLATE_VERSION = "1"

# Deterministic bounded evidence-projection policy (option B of the
# accepted contract): items are ordered by pack role priority, then claim
# cluster, then evidence identity; RETRACTED evidence is excluded from the
# AI-selectable set; anything beyond the cap is omitted with an explicit
# recorded count — the model can never reference what it did not receive.
EVIDENCE_PROJECTION_POLICY_NAME = "brief-evidence-projection"
EVIDENCE_PROJECTION_POLICY_VERSION = "1"
MAX_PROJECTED_EVIDENCE = 30
MAX_EVIDENCE_STATEMENT_CHARS = 500
MAX_OUTPUT_TOKENS = 8_000

_ROLE_PRIORITY = {
    EvidenceItemRole.KEY_FACT: 0,
    EvidenceItemRole.SUPPORTING: 1,
    EvidenceItemRole.CONTRADICTING: 2,
    EvidenceItemRole.CONTEXT: 3,
    EvidenceItemRole.CAUTION: 4,
}

# Mandatory policy acceptance criteria: the model may add criteria but can
# never remove or override these keys (an override is VALIDATION_FAILED).
MANDATORY_ACCEPTANCE_CRITERIA: tuple[tuple[str, str], ...] = (
    ("policy-sections", "Taslak, zorunlu bölüm sözleşmesinin tamamını karşılamalı."),
    (
        "policy-claims",
        "Taslak, iddia/kanıt haritasının dışına çıkan olgusal iddia içermemeli.",
    ),
    (
        "policy-uncertainty",
        "Taslak, belirsizlik notlarındaki sınırlamaları korumalı ve kesinliğe çevirmemeli.",
    ),
    ("policy-exclusions", "Taslak, tüm yasaklara (exclusions) uymalı."),
    (
        "policy-no-fake-ugc",
        "Taslak, gerçek kullanıcı yorumu/deneyimi/puanı üretmemeli veya ima etmemeli.",
    ),
    (
        "policy-no-invented-signals",
        "Taslak, eksik arama sinyallerini uydurulmuş değerlere çevirmemeli.",
    ),
    (
        "policy-no-single-source-copy",
        "Taslak, tek bir kaynağın yapısını veya ifadesini kopyalamamalı.",
    ),
)

# Versioned by BRIEF_COMPOSITION_TEMPLATE_NAME/VERSION; substantive changes
# REQUIRE a version bump (instructions are never hashed or persisted).
_TEMPLATE_V1 = """\
You compose the WRITING CONTRACT (a ContentBrief) for one Konsepthane
editorial concept. Konsepthane is a Turkish practical celebration/event
planning publication. You receive the selected idea, an evidence
projection (exact evidence units with ids), search-intent context, and
pack cautions. RESEARCH, DO NOT TRANSLATE-AND-REPUBLISH.

You MUST:
- synthesize across ALL supplied evidence units;
- follow the selected idea's original angle;
- propose a Konsepthane-specific useful section structure that does NOT
  mirror any single source's heading order or outline;
- treat source statements as evidence to reference by id, never prose to
  rewrite;
- classify every claim honestly (factual and source_assertion claims MUST
  reference at least one supplied evidence id; inference and
  editorial_judgment MUST be labeled as such; never upgrade an
  observation or instruction to sourced factual truth);
- carry uncertainty and cautions into the contract, never erase them.

You MUST NOT:
- invent facts, statistics, quotes, interviews, customer experiences,
  testimonials, ratings, or any user-generated content;
- invent search volume, trends, rankings, keyword difficulty, or
  published Konsepthane inventory;
- claim media rights, source verification, or legal/medical certainty;
- reference any evidence id that was not supplied;
- write the article itself — no paragraphs, no prose body, no final
  headline.
"""


@dataclass(frozen=True, slots=True)
class BriefCompositionResult:
    """Typed engine outcome; failed attempts stay durable with no brief."""

    attempt: AiGenerationAttempt
    status: GenerationStatus
    brief: ContentBrief | None
    attempt_created: bool
    brief_created: bool
    reused: bool
    structure_guard_outcome: str | None


@dataclass(frozen=True, slots=True)
class _CompositionContext:
    work_item_id: uuid.UUID
    opportunity_id: uuid.UUID
    idea_id: uuid.UUID
    pack_id: uuid.UUID
    intent_id: uuid.UUID
    allowlisted_evidence_ids: frozenset[str]
    disputed_evidence_ids: frozenset[str]
    projected_units: list[dict[str, Any]]
    omitted_count: int
    excluded_retracted: int
    contradictions: list[dict[str, Any]]
    deterministic_exclusions: list[str]
    mandatory_uncertainty: list[str]
    planning_dimensions: dict[str, Any] | None
    idea_projection: dict[str, Any]
    intent_projection: dict[str, Any]
    pack_projection: dict[str, Any]


class BriefCompositionEngine:
    """Transport-neutral engine; flushes only — the caller commits."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._briefs = BriefService(session)
        self._repository = BriefRepository(session)
        self._workflow_repo = WorkflowRepository(session)
        self._packs = EvidencePackRepository(session)
        self._generation = StructuredGenerationService(session)

    def compose(
        self,
        work_item_id: uuid.UUID,
        *,
        idea_id: uuid.UUID,
        evidence_pack_id: uuid.UUID,
        search_intent_analysis_id: uuid.UUID,
        provider: StructuredGenerationProvider,
        retry_number: int = 0,
        structure_policy: BriefStructurePolicy = DEFAULT_BRIEF_STRUCTURE_POLICY,
        supersede_reason: str | None = None,
        request_id: str | None = None,
    ) -> BriefCompositionResult:
        context = self._resolve_context(
            work_item_id, idea_id, evidence_pack_id, search_intent_analysis_id
        )

        # Pre-provider short-circuit: the accepted brief identity already
        # exists for the automated composer — no AI cost is spent on an
        # artifact Task 11 would reject as a same-identity conflict.
        existing = self._repository.get_by_identity(
            work_item_id,
            idea_id,
            evidence_pack_id,
            search_intent_analysis_id,
            BRIEF_COMPOSER_NAME,
            BRIEF_COMPOSER_VERSION,
        )
        if existing is not None:
            return self._reuse_existing_brief(existing, context)

        request = self._build_request(context, structure_policy, retry_number)
        spec: StructuredOutputSpec[BriefCompositionV1] = StructuredOutputSpec(
            schema_name=BRIEF_COMPOSITION_SCHEMA_NAME,
            schema_version=BRIEF_COMPOSITION_SCHEMA_VERSION,
            model_type=BriefCompositionV1,
            domain_validator=_CompositionValidator(
                allowlisted_evidence_ids=context.allowlisted_evidence_ids,
                disputed_evidence_ids=context.disputed_evidence_ids,
                mandatory_criterion_keys=frozenset(key for key, _ in MANDATORY_ACCEPTANCE_CRITERIA),
            ),
        )
        execution = self._generation.execute(request, spec, provider)

        if execution.status is not GenerationStatus.SUCCEEDED:
            return BriefCompositionResult(
                attempt=execution.attempt,
                status=execution.status,
                brief=None,
                attempt_created=execution.created,
                brief_created=False,
                reused=False,
                structure_guard_outcome=None,
            )
        if execution.created:
            assert execution.payload is not None
            draft = self._build_draft_input(context, execution.payload)
            try:
                result = self._briefs.create_composed_draft(
                    work_item_id,
                    idea_id=idea_id,
                    evidence_pack_id=evidence_pack_id,
                    search_intent_analysis_id=search_intent_analysis_id,
                    draft=draft,
                    composition_attempt=execution.attempt,
                    structure_policy=structure_policy,
                    supersede_reason=supersede_reason,
                    request_id=request_id,
                )
            except (
                BriefClaimEvidenceError,
                BriefConflictError,
                BriefInputError,
                BriefProvenanceError,
                BriefStatusConflictError,
            ) as error:
                # The completed AI attempt keeps its real SUCCEEDED status;
                # this is a deterministic persistence-time rejection.
                raise BriefCompositionMaterializationError(
                    f"structurally valid AI output was rejected by brief persistence: {error}"
                ) from error
            brief = result.brief
            return BriefCompositionResult(
                attempt=execution.attempt,
                status=execution.status,
                brief=brief,
                attempt_created=True,
                brief_created=result.created,
                reused=not result.created,
                structure_guard_outcome=brief.structure_guard_result.get("outcome"),
            )
        return self._resolve_reused_attempt(execution.attempt, context)

    # --- internal -----------------------------------------------------------

    def _reuse_existing_brief(
        self, brief: ContentBrief, context: _CompositionContext
    ) -> BriefCompositionResult:
        if brief.composition_attempt_id is None:
            raise InvalidCompositionAttemptError(
                "an automated-composer brief exists without a composition attempt; "
                "history is inconsistent"
            )
        attempt = self._session.get(AiGenerationAttempt, brief.composition_attempt_id)
        if attempt is None:  # pragma: no cover - RESTRICT FK guarantees this
            raise InvalidCompositionAttemptError("the composition attempt is unresolvable")
        validate_composition_attempt(
            attempt,
            work_item_id=context.work_item_id,
            idea_id=context.idea_id,
            evidence_pack_id=context.pack_id,
            search_intent_analysis_id=context.intent_id,
        )
        return BriefCompositionResult(
            attempt=attempt,
            status=attempt.status,
            brief=brief,
            attempt_created=False,
            brief_created=False,
            reused=True,
            structure_guard_outcome=brief.structure_guard_result.get("outcome"),
        )

    def _resolve_reused_attempt(
        self, attempt: AiGenerationAttempt, context: _CompositionContext
    ) -> BriefCompositionResult:
        validate_composition_attempt(
            attempt,
            work_item_id=context.work_item_id,
            idea_id=context.idea_id,
            evidence_pack_id=context.pack_id,
            search_intent_analysis_id=context.intent_id,
        )
        # Serialize materialization on the attempt row (read lock only).
        self._session.execute(
            select(AiGenerationAttempt.id)
            .where(AiGenerationAttempt.id == attempt.id)
            .with_for_update()
        )
        brief = self._repository.get_by_composition_attempt(attempt.id)
        if brief is not None:
            return BriefCompositionResult(
                attempt=attempt,
                status=attempt.status,
                brief=brief,
                attempt_created=False,
                brief_created=False,
                reused=True,
                structure_guard_outcome=brief.structure_guard_result.get("outcome"),
            )
        raise IncompleteBriefMaterializationError(
            "this SUCCEEDED composition attempt has no materialized brief and "
            "its raw output was (by design) never persisted; request a new "
            "provider invocation explicitly with retry_number + 1"
        )

    def _resolve_context(
        self,
        work_item_id: uuid.UUID,
        idea_id: uuid.UUID,
        evidence_pack_id: uuid.UUID,
        search_intent_analysis_id: uuid.UUID,
    ) -> _CompositionContext:
        work_item = self._workflow_repo.get_by_id(work_item_id)
        if work_item is None:
            raise CompositionPreconditionError(f"no editorial work item with id {work_item_id}")
        if work_item.current_state is not WorkflowState.BRIEFING:
            raise CompositionPreconditionError(
                "brief composition requires the work item to be in BRIEFING "
                f"(current: {work_item.current_state.value})"
            )
        upstream = self._briefs._resolve_upstream(  # noqa: SLF001 - same-package reuse
            work_item, idea_id, evidence_pack_id, search_intent_analysis_id
        )
        if upstream.opportunity.disposition is not OpportunityDisposition.COMMISSIONED:
            raise CompositionPreconditionError(
                "brief composition requires a COMMISSIONED opportunity "
                f"(current: {upstream.opportunity.disposition.value})"
            )
        from contentos.ideas.service import IdeaService

        effective = IdeaService(self._session).get_effective_selection(upstream.opportunity.id)
        if effective is None or effective.id != idea_id:
            raise CompositionPreconditionError(
                "the pinned idea is no longer the current effective selection"
            )
        if upstream.pack.sufficiency is not EvidencePackSufficiency.READY:
            raise CompositionPreconditionError(
                "brief composition requires a READY evidence pack "
                f"(persisted: {upstream.pack.sufficiency.value}); no model "
                "tokens are spent composing a knowingly unusable brief"
            )

        contradictions = self._packs.list_contradictions(upstream.pack.id)
        unresolved_blocking = [
            row
            for row in contradictions
            if row.severity is ContradictionSeverity.BLOCKING
            and row.resolution_status is ContradictionResolutionStatus.UNRESOLVED
        ]
        if unresolved_blocking:
            raise CompositionPreconditionError(
                "the pack is READY yet carries an unresolved BLOCKING "
                "contradiction; impossible state, failing closed"
            )

        projected, omitted, excluded_retracted, disputed, unit_projections = self._project_evidence(
            upstream.pack.id
        )
        contradiction_projection = [
            {
                "contradiction_id": str(row.id),
                "claim_key": row.claim_key,
                "severity": row.severity.value,
                "resolution_status": row.resolution_status.value,
                "nature": row.nature,
                "handling_recommendation": row.handling_recommendation,
                "evidence_side_a": list(row.evidence_side_a),
                "evidence_side_b": list(row.evidence_side_b),
            }
            for row in contradictions
        ]
        deterministic_exclusions = _deterministic_exclusions(upstream.pack)
        mandatory_uncertainty = _mandatory_uncertainty(
            upstream.pack, upstream.intent, contradictions
        )
        idea = upstream.idea
        dimensions = idea.planning_dimensions.get("dimensions") or None
        return _CompositionContext(
            work_item_id=work_item.id,
            opportunity_id=upstream.opportunity.id,
            idea_id=idea.id,
            pack_id=upstream.pack.id,
            intent_id=upstream.intent.id,
            allowlisted_evidence_ids=frozenset(projected),
            disputed_evidence_ids=frozenset(disputed),
            projected_units=unit_projections,
            omitted_count=omitted,
            excluded_retracted=excluded_retracted,
            contradictions=contradiction_projection,
            deterministic_exclusions=deterministic_exclusions,
            mandatory_uncertainty=mandatory_uncertainty,
            planning_dimensions=dimensions,
            idea_projection={
                "working_title": idea.working_title,
                "angle": idea.angle,
                "audience": idea.audience,
                "value_proposition": idea.value_proposition,
                "content_type": idea.content_type.value,
                "exclusions": idea.exclusions,
                "planning_dimensions": idea.planning_dimensions,
            },
            intent_projection={
                "primary_intent": upstream.intent.primary_intent,
                "secondary_intents": upstream.intent.secondary_intents,
                "query_concepts": upstream.intent.query_concepts,
                "page_purpose": upstream.intent.page_purpose,
                "likely_format": upstream.intent.likely_format,
                "missing_signals": upstream.intent.missing_signals,
                "cannibalization_status": upstream.intent.cannibalization_status.value,
                "cannibalization_scope": (
                    "ContentOS-internal only; published inventory not accessible"
                ),
                "related_references": upstream.intent.related_references,
            },
            pack_projection={
                "sufficiency": upstream.pack.sufficiency.value,
                "source_diversity": upstream.pack.source_diversity,
                "staleness_notes": upstream.pack.staleness_notes,
                "locale_limitations": upstream.pack.locale_limitations,
                "licensing_cautions": upstream.pack.licensing_cautions,
            },
        )

    def _project_evidence(
        self, pack_id: uuid.UUID
    ) -> tuple[list[str], int, int, list[str], list[dict[str, Any]]]:
        items = self._packs.list_items(pack_id)
        ordered = sorted(
            items,
            key=lambda item: (
                _ROLE_PRIORITY[item.role],
                item.claim_cluster,
                str(item.research_evidence_id),
            ),
        )
        projected_ids: list[str] = []
        disputed: list[str] = []
        unit_projections: list[dict[str, Any]] = []
        excluded_retracted = 0
        usable_beyond_cap = 0
        for item in ordered:
            evidence = self._session.get(ResearchEvidence, item.research_evidence_id)
            if evidence is None:  # pragma: no cover - RESTRICT FK guarantees this
                raise BriefProvenanceError("pack evidence is no longer resolvable")
            if evidence.verification_status is VerificationStatus.RETRACTED:
                excluded_retracted += 1
                continue
            if len(projected_ids) >= MAX_PROJECTED_EVIDENCE:
                usable_beyond_cap += 1
                continue
            source = self._session.get(Source, evidence.source_id)
            if source is None:  # pragma: no cover - RESTRICT FK guarantees this
                raise BriefProvenanceError("evidence source is no longer resolvable")
            evidence_id = str(evidence.id)
            projected_ids.append(evidence_id)
            if evidence.verification_status is VerificationStatus.DISPUTED:
                disputed.append(evidence_id)
            unit_projections.append(
                {
                    "research_evidence_id": evidence_id,
                    "pack_role": item.role.value,
                    "claim_cluster": item.claim_cluster,
                    "display_note": item.display_note,
                    "evidence_type": evidence.evidence_type.value,
                    "statement": evidence.statement[:MAX_EVIDENCE_STATEMENT_CHARS],
                    "verification_status": evidence.verification_status.value,
                    "source_id": str(source.id),
                    "source_slug": source.slug,
                    "source_trust_tier": source.trust_tier.value,
                    "fetched_at": evidence.fetched_at.isoformat(),
                    "confidence": (
                        float(evidence.confidence) if evidence.confidence is not None else None
                    ),
                    "licensing_notes": evidence.licensing_notes,
                }
            )
        return projected_ids, usable_beyond_cap, excluded_retracted, disputed, unit_projections

    def _build_request(
        self,
        context: _CompositionContext,
        structure_policy: BriefStructurePolicy,
        retry_number: int,
    ) -> GenerationRequest:
        input_refs = {
            "schema": BRIEF_COMPOSITION_INPUT_REFS_SCHEMA,
            "work_item_id": str(context.work_item_id),
            "opportunity_id": str(context.opportunity_id),
            "idea_id": str(context.idea_id),
            "evidence_pack_id": str(context.pack_id),
            "search_intent_analysis_id": str(context.intent_id),
            "projected_evidence_ids": sorted(context.allowlisted_evidence_ids),
            "omitted_evidence_count": context.omitted_count,
            "excluded_retracted_count": context.excluded_retracted,
            "contradiction_ids": [entry["contradiction_id"] for entry in context.contradictions],
            "composer_name": BRIEF_COMPOSER_NAME,
            "composer_version": BRIEF_COMPOSER_VERSION,
            "structure_policy_name": structure_policy.name,
            "structure_policy_version": structure_policy.version,
            "projection_policy_name": EVIDENCE_PROJECTION_POLICY_NAME,
            "projection_policy_version": EVIDENCE_PROJECTION_POLICY_VERSION,
        }
        input_projection = {
            "idea": context.idea_projection,
            "search_intent": context.intent_projection,
            "evidence_pack": context.pack_projection,
            "evidence_units": context.projected_units,
            "omitted_evidence_count": context.omitted_count,
            "contradictions": context.contradictions,
            "mandatory_exclusions": context.deterministic_exclusions,
            "mandatory_uncertainty_notes": context.mandatory_uncertainty,
            "mandatory_acceptance_criteria": [
                {"key": key, "requirement": requirement}
                for key, requirement in MANDATORY_ACCEPTANCE_CRITERIA
            ],
        }
        return GenerationRequest(
            purpose=GenerationPurpose.BRIEF_COMPOSITION,
            schema_name=BRIEF_COMPOSITION_SCHEMA_NAME,
            schema_version=BRIEF_COMPOSITION_SCHEMA_VERSION,
            template_name=BRIEF_COMPOSITION_TEMPLATE_NAME,
            template_version=BRIEF_COMPOSITION_TEMPLATE_VERSION,
            input_refs=input_refs,
            input_projection=input_projection,
            generation_bounds={"max_output_tokens": MAX_OUTPUT_TOKENS},
            retry_number=retry_number,
            instructions=_TEMPLATE_V1,
        )

    def _build_draft_input(
        self, context: _CompositionContext, payload: BriefCompositionV1
    ) -> BriefDraftInput:
        """Merge, never replace: system-owned requirements always survive."""
        exclusions = list(context.deterministic_exclusions)
        for extra in payload.additional_exclusions:
            if extra not in exclusions:
                exclusions.append(extra)
        uncertainty = list(context.mandatory_uncertainty)
        for note in payload.additional_uncertainty_notes:
            if note not in uncertainty:
                uncertainty.append(note)
        if len(uncertainty) > MAX_UNCERTAINTY_NOTES:
            uncertainty = uncertainty[:MAX_UNCERTAINTY_NOTES]
            if len(context.mandatory_uncertainty) > MAX_UNCERTAINTY_NOTES:
                raise CompositionPreconditionError(
                    "mandatory uncertainty notes exceed the persistence limit"
                )
        criteria = [
            AcceptanceCriterion(key=key, requirement=requirement)
            for key, requirement in MANDATORY_ACCEPTANCE_CRITERIA
        ]
        criteria.extend(
            AcceptanceCriterion(key=entry.key, requirement=entry.requirement)
            for entry in payload.acceptance_criteria
        )
        return BriefDraftInput(
            intent_summary=payload.intent_summary,
            content_objective=payload.content_objective,
            required_sections=tuple(
                BriefSection(
                    key=section.key,
                    heading_guidance=section.heading_guidance,
                    purpose=section.purpose,
                )
                for section in payload.required_sections
            ),
            optional_sections=tuple(
                BriefSection(
                    key=section.key,
                    heading_guidance=section.heading_guidance,
                    purpose=section.purpose,
                )
                for section in payload.optional_sections
            ),
            claims=tuple(
                BriefClaimInput(
                    claim_key=claim.claim_key,
                    claim_text=claim.claim_text,
                    claim_kind=claim.claim_kind,
                    handling=claim.handling,
                    evidence_ids=tuple(
                        uuid.UUID(evidence_id) for evidence_id in claim.evidence_ids
                    ),
                )
                for claim in payload.claims
            ),
            title_direction=payload.title_direction,
            title_constraints=tuple(payload.title_constraints),
            practical_requirements=context.planning_dimensions,
            extra_exclusions=tuple(exclusions),
            uncertainty_notes=tuple(uncertainty),
            internal_link_needs=tuple(
                InternalLinkNeed(topic=need.topic, purpose=need.purpose)
                for need in payload.internal_link_needs
            ),
            media_needs=tuple(
                MediaNeed(role=need.role, purpose=need.purpose, constraints=need.constraints)
                for need in payload.media_needs
            ),
            faq_questions=tuple(payload.faq_questions),
            acceptance_criteria=tuple(criteria),
        )


@dataclass(frozen=True, slots=True)
class _CompositionValidator:
    """Deterministic context-aware domain validation (Task-8 hook).

    Any violation rejects the WHOLE structured output as VALIDATION_FAILED
    with zero brief rows — before an attempt is ever considered successful.
    """

    allowlisted_evidence_ids: frozenset[str]
    disputed_evidence_ids: frozenset[str]
    mandatory_criterion_keys: frozenset[str]

    def __call__(self, payload: BriefCompositionV1) -> str | None:
        claim_keys: set[str] = set()
        for claim in payload.claims:
            if claim.claim_key in claim_keys:
                return "duplicate_claim_keys"
            claim_keys.add(claim.claim_key)
            if len(set(claim.evidence_ids)) != len(claim.evidence_ids):
                return "duplicate_claim_evidence"
            for evidence_id in claim.evidence_ids:
                if evidence_id not in self.allowlisted_evidence_ids:
                    # Unknown, outside-projection, retracted, or omitted:
                    # the model can only cite what it actually received.
                    return "evidence_not_allowlisted"
            if (
                claim.claim_kind in (BriefClaimKind.FACTUAL, BriefClaimKind.SOURCE_ASSERTION)
                and not claim.evidence_ids
            ):
                return "required_evidence_missing"
            if (
                claim.claim_kind is BriefClaimKind.FACTUAL
                and claim.evidence_ids
                and all(
                    evidence_id in self.disputed_evidence_ids for evidence_id in claim.evidence_ids
                )
                and not (claim.handling or "").strip()
            ):
                return "disputed_without_handling"

        section_keys: set[str] = set()
        for section in list(payload.required_sections) + list(payload.optional_sections):
            if section.key in section_keys:
                # Stricter composition-only rule: required and optional
                # keys must not collide across the combined contract.
                return "duplicate_section_keys"
            section_keys.add(section.key)

        criterion_keys: set[str] = set()
        for criterion in payload.acceptance_criteria:
            if criterion.key in criterion_keys:
                return "duplicate_criterion_keys"
            criterion_keys.add(criterion.key)
            if criterion.key in self.mandatory_criterion_keys:
                # The model may never override a mandatory policy criterion.
                return "mandatory_criterion_override"

        if _fake_ugc_violation(payload):
            return "fake_ugc"
        return None


def _fake_ugc_violation(payload: BriefCompositionV1) -> bool:
    """Reuse the existing deterministic fake-UGC pattern policy."""
    fields: dict[str, str] = {
        "intent_summary": payload.intent_summary,
        "content_objective": payload.content_objective,
        "title_direction": payload.title_direction or "",
    }
    for index, section in enumerate(
        list(payload.required_sections) + list(payload.optional_sections)
    ):
        fields[f"section_{index}"] = f"{section.heading_guidance} {section.purpose}"
    for index, claim in enumerate(payload.claims):
        fields[f"claim_{index}"] = f"{claim.claim_text} {claim.handling or ''}"
    for index, note in enumerate(payload.additional_uncertainty_notes):
        fields[f"note_{index}"] = note
    for index, question in enumerate(payload.faq_questions):
        fields[f"faq_{index}"] = question
    return bool(find_fake_ugc_violations(fields, DEFAULT_IDEA_ORIGINALITY_POLICY))


def _deterministic_exclusions(pack: Any) -> list[str]:
    """Licensing/reference-only cautions surface automatically as
    prohibitions the model can never remove."""
    exclusions: list[str] = []
    for caution in pack.licensing_cautions:
        text = f"Lisans/kullanım uyarısı: {caution.get('caution', '')}".strip()
        text = " ".join(text.split())[:MAX_EXCLUSION_LENGTH]
        if text and text not in exclusions:
            exclusions.append(text)
    return exclusions


def _mandatory_uncertainty(pack: Any, intent: Any, contradictions: list[Any]) -> list[str]:
    """The system-owned uncertainty set the model can never delete."""
    notes: list[str] = []

    def add(note: str) -> None:
        cleaned = " ".join(note.split())[:MAX_UNCERTAINTY_NOTE_LENGTH]
        if cleaned and cleaned not in notes:
            notes.append(cleaned)

    for entry in pack.staleness_notes:
        add(f"Kanıt tazeliği sınırlı: {entry.get('research_evidence_id')} ({entry.get('basis')})")
    for entry in pack.locale_limitations.get("mismatches", []):
        add(
            "Yerel kapsam sınırı: kanıt "
            f"{entry.get('research_evidence_id')} locale {entry.get('locale')}"
        )
    if intent.missing_signals:
        add("Eksik arama sinyalleri: " + ", ".join(intent.missing_signals))
    add(
        "Yayınlanmış Konsepthane envanteri doğrulanmadı; site çapında "
        "çakışma değerlendirmesi yapılamaz "
        f"(cannibalization: {intent.cannibalization_status.value})."
    )
    for row in contradictions:
        if row.resolution_status is ContradictionResolutionStatus.UNRESOLVED:
            add(f"Çözülmemiş çelişki ({row.claim_key}): temkinli ifade gerekli.")
        else:
            add(
                f"Çelişki kaydı ({row.claim_key}): {row.resolution_status.value}; "
                "kararlaştırılan ele alışı koru."
            )
    return notes
