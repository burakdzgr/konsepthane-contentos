"""Brief draft creation, supersession, and the §9.3 acceptance command.

`create_draft` persists ONE immutable brief version (brief + claims +
evidence links + structure-guard result, atomically) pinned to exact
upstream artifact versions. `accept_for_drafting` is the explicit OPERATOR
command that runs EVERY accepted acceptance gate, mutates DRAFT ->
ACCEPTED_FOR_DRAFTING with an audited status event, and requests the
BRIEFING -> DRAFTING workflow transition pinning the exact brief — all in
one caller-owned transaction (a workflow failure rolls everything back).

Acceptance is an editorial decision, never publication approval (ADR 0004
untouched). No model composition happens here (Task 12 owns it); the
explicit persistence path records composition_attempt_id = NULL.

The service flushes; the caller commits.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.hashing import sha256_hex
from contentos.ai.models import AiGenerationAttempt
from contentos.briefs.enums import (
    BriefActorOrigin,
    BriefClaimKind,
    BriefStatus,
    StructureGuardOutcome,
)
from contentos.briefs.errors import (
    BriefAcceptanceGateError,
    BriefClaimEvidenceError,
    BriefConflictError,
    BriefInputError,
    BriefNotFoundError,
    BriefProvenanceError,
    BriefStatusConflictError,
    BriefStructureGuardError,
    BriefUpstreamMismatchError,
    InvalidCompositionAttemptError,
)
from contentos.briefs.generation_schemas import BRIEF_COMPOSITION_INPUT_REFS_SCHEMA
from contentos.briefs.models import (
    BriefClaim,
    BriefClaimEvidence,
    BriefStatusEvent,
    ContentBrief,
)
from contentos.briefs.repository import BriefRepository
from contentos.briefs.structure_guard import (
    DEFAULT_BRIEF_STRUCTURE_POLICY,
    BriefStructurePolicy,
    SourceStructure,
    evaluate_structure_guard,
)
from contentos.briefs.values import (
    BRIEF_COMPOSER_NAME,
    BRIEF_COMPOSER_VERSION,
    MAX_ACCEPTANCE_CRITERIA,
    MAX_CLAIM_EVIDENCE_LINKS,
    MAX_CLAIM_HANDLING_LENGTH,
    MAX_CLAIM_KEY_LENGTH,
    MAX_CLAIM_TEXT_LENGTH,
    MAX_CLAIMS,
    MAX_CONTENT_OBJECTIVE_LENGTH,
    MAX_EXCLUSION_LENGTH,
    MAX_EXCLUSIONS,
    MAX_FAQ_QUESTION_LENGTH,
    MAX_FAQ_QUESTIONS,
    MAX_INTENT_SUMMARY_LENGTH,
    MAX_LINK_NEEDS,
    MAX_MEDIA_NEEDS,
    MAX_TITLE_CONSTRAINT_LENGTH,
    MAX_TITLE_CONSTRAINTS,
    MAX_TITLE_DIRECTION_LENGTH,
    MAX_UNCERTAINTY_NOTE_LENGTH,
    MAX_UNCERTAINTY_NOTES,
    AcceptanceCriterion,
    BriefDraftInput,
    InternalLinkNeed,
    MediaNeed,
    clean_sections,
    clean_string_list,
)
from contentos.core.context import is_valid_request_id
from contentos.discovery.models import DiscoveryItem
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.duplicates.repository import DuplicateDecisionRepository
from contentos.evidence_packs.enums import (
    ContradictionResolutionStatus,
    ContradictionSeverity,
    EvidencePackSufficiency,
)
from contentos.evidence_packs.models import EvidencePack
from contentos.evidence_packs.repository import EvidencePackRepository
from contentos.fetching.snapshots import FetchSnapshot
from contentos.ideas.enums import OriginalityStatus
from contentos.ideas.models import Idea
from contentos.ideas.service import IdeaService
from contentos.ideas.values import validate_planning_dimensions
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.enums import OpportunityDisposition
from contentos.opportunities.models import EditorialOpportunity
from contentos.opportunities.repository import OpportunityRepository
from contentos.research.enums import VerificationStatus
from contentos.research.models import ResearchEvidence
from contentos.search_intent.models import SearchIntentAnalysis
from contentos.search_intent.repository import SearchIntentRepository
from contentos.sources.models import Source
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.models import EditorialWorkItem
from contentos.workflow.repository import WorkflowRepository
from contentos.workflow.service import WorkflowService

# The explicit composer identity of the manual/deterministic persistence
# path. Task 12 freezes the real automated brief-composer identity — this
# path never pretends that engine has already run.
MANUAL_COMPOSER_NAME = "manual-brief-input"
MANUAL_COMPOSER_VERSION = "1"

BRIEF_CONTENT_SCHEMA_VERSION = 1

MAX_ENGINE_NAME_LENGTH = 100
MAX_ENGINE_VERSION_LENGTH = 50
MAX_REASON_LENGTH = 1000

# The audited operator duplicate-override marker written by Task 3's
# promotion service into the work item's creation event.
PROMOTION_OVERRIDE_KIND = "duplicate_override"

# The two errors _require_current_selection may raise, chosen by phase.
BriefSelectionError = BriefUpstreamMismatchError | BriefAcceptanceGateError


@dataclass(frozen=True, slots=True)
class BriefDraftResult:
    brief: ContentBrief
    created: bool
    superseded_brief_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class BriefAcceptance:
    """`accepted` is False on an idempotent no-op re-acceptance."""

    brief: ContentBrief
    accepted: bool


@dataclass(frozen=True, slots=True)
class _Upstream:
    opportunity: EditorialOpportunity
    idea: Idea
    pack: EvidencePack
    intent: SearchIntentAnalysis


class BriefService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = BriefRepository(session)
        self._workflow_repo = WorkflowRepository(session)
        self._opportunities = OpportunityRepository(session)
        self._packs = EvidencePackRepository(session)
        self._intents = SearchIntentRepository(session)

    # --- draft creation -----------------------------------------------------

    def create_draft(
        self,
        work_item_id: uuid.UUID,
        *,
        idea_id: uuid.UUID,
        evidence_pack_id: uuid.UUID,
        search_intent_analysis_id: uuid.UUID,
        draft: BriefDraftInput,
        engine_name: str = MANUAL_COMPOSER_NAME,
        engine_version: str = MANUAL_COMPOSER_VERSION,
        structure_policy: BriefStructurePolicy = DEFAULT_BRIEF_STRUCTURE_POLICY,
        supersede_reason: str | None = None,
        request_id: str | None = None,
    ) -> BriefDraftResult:
        """Manual/deterministic path: composition_attempt_id stays NULL."""
        if engine_name == BRIEF_COMPOSER_NAME:
            raise BriefInputError(
                "the automated composer identity requires a validated "
                "BRIEF_COMPOSITION attempt; use the composition engine"
            )
        return self._create_draft(
            work_item_id,
            idea_id=idea_id,
            evidence_pack_id=evidence_pack_id,
            search_intent_analysis_id=search_intent_analysis_id,
            draft=draft,
            engine_name=engine_name,
            engine_version=engine_version,
            structure_policy=structure_policy,
            supersede_reason=supersede_reason,
            request_id=request_id,
            composition_attempt=None,
        )

    def create_composed_draft(
        self,
        work_item_id: uuid.UUID,
        *,
        idea_id: uuid.UUID,
        evidence_pack_id: uuid.UUID,
        search_intent_analysis_id: uuid.UUID,
        draft: BriefDraftInput,
        composition_attempt: AiGenerationAttempt,
        structure_policy: BriefStructurePolicy = DEFAULT_BRIEF_STRUCTURE_POLICY,
        supersede_reason: str | None = None,
        request_id: str | None = None,
    ) -> BriefDraftResult:
        """Automated-composer path: pins the exact SUCCEEDED attempt.

        Never a generic attempt-injection surface: the attempt's purpose,
        status, and persisted input provenance are validated against the
        exact upstream identity before any persistence.
        """
        validate_composition_attempt(
            composition_attempt,
            work_item_id=work_item_id,
            idea_id=idea_id,
            evidence_pack_id=evidence_pack_id,
            search_intent_analysis_id=search_intent_analysis_id,
        )
        return self._create_draft(
            work_item_id,
            idea_id=idea_id,
            evidence_pack_id=evidence_pack_id,
            search_intent_analysis_id=search_intent_analysis_id,
            draft=draft,
            engine_name=BRIEF_COMPOSER_NAME,
            engine_version=BRIEF_COMPOSER_VERSION,
            structure_policy=structure_policy,
            supersede_reason=supersede_reason,
            request_id=request_id,
            composition_attempt=composition_attempt,
        )

    def _create_draft(
        self,
        work_item_id: uuid.UUID,
        *,
        idea_id: uuid.UUID,
        evidence_pack_id: uuid.UUID,
        search_intent_analysis_id: uuid.UUID,
        draft: BriefDraftInput,
        engine_name: str,
        engine_version: str,
        structure_policy: BriefStructurePolicy,
        supersede_reason: str | None,
        request_id: str | None,
        composition_attempt: AiGenerationAttempt | None,
    ) -> BriefDraftResult:
        work_item = self._workflow_repo.get_by_id_for_update(work_item_id)
        if work_item is None:
            raise BriefUpstreamMismatchError(f"no editorial work item with id {work_item_id}")
        if work_item.current_state is not WorkflowState.BRIEFING:
            raise BriefInputError(
                "a brief draft can be created only while the work item is in "
                f"BRIEFING (current: {work_item.current_state.value})"
            )
        upstream = self._resolve_upstream(
            work_item, idea_id, evidence_pack_id, search_intent_analysis_id
        )
        self._require_current_selection(upstream, BriefUpstreamMismatchError)
        cleaned_engine_name = _required_text("engine_name", engine_name, MAX_ENGINE_NAME_LENGTH)
        cleaned_engine_version = _required_text(
            "engine_version", engine_version, MAX_ENGINE_VERSION_LENGTH
        )
        validated_request_id = _validate_request_id(request_id)

        content = self._build_content(upstream, draft)
        pack_member_ids = {
            item.research_evidence_id for item in self._packs.list_items(upstream.pack.id)
        }
        claims = self._validate_claims(draft, pack_member_ids)
        guard_result = self._run_structure_guard(
            upstream, content["required_sections"], structure_policy
        )
        content_hash = _content_hash(
            content=content,
            structure_guard_result=guard_result,
            structure_policy_snapshot=structure_policy.snapshot(),
            claims=claims,
        )

        existing = self._repository.get_by_identity(
            work_item.id,
            upstream.idea.id,
            upstream.pack.id,
            upstream.intent.id,
            cleaned_engine_name,
            cleaned_engine_version,
        )
        if existing is not None:
            if existing.content_hash == content_hash:
                return BriefDraftResult(brief=existing, created=False, superseded_brief_id=None)
            raise BriefConflictError(
                "this exact brief identity already exists with different content; "
                "change a pinned upstream version or the composer version"
            )

        active = self._repository.get_active_brief(work_item.id)
        if active is not None and active.status is BriefStatus.ACCEPTED_FOR_DRAFTING:
            raise BriefStatusConflictError(
                "an ACCEPTED_FOR_DRAFTING brief exists; it can be superseded only "
                "after an explicit editorial return to BRIEFING/revision"
            )
        cleaned_supersede_reason: str | None = None
        if active is not None:
            if supersede_reason is None or not supersede_reason.strip():
                raise BriefInputError("superseding the active draft requires an explicit reason")
            cleaned_supersede_reason = _required_text(
                "supersede_reason", supersede_reason, MAX_REASON_LENGTH
            )

        try:
            with self._session.begin_nested():
                if active is not None:
                    active.status = BriefStatus.SUPERSEDED
                    self._session.flush()
                brief = self._repository.insert_brief(
                    ContentBrief(
                        work_item_id=work_item.id,
                        version=self._repository.next_version(work_item.id),
                        idea_id=upstream.idea.id,
                        evidence_pack_id=upstream.pack.id,
                        search_intent_analysis_id=upstream.intent.id,
                        locale=work_item.locale,
                        market=work_item.market,
                        target_audience=content["target_audience"],
                        intent_summary=content["intent_summary"],
                        original_angle=content["original_angle"],
                        title_guidance=content["title_guidance"],
                        content_objective=content["content_objective"],
                        required_sections=content["required_sections"],
                        optional_sections=content["optional_sections"],
                        practical_requirements=content["practical_requirements"],
                        exclusions=content["exclusions"],
                        uncertainty_notes=content["uncertainty_notes"],
                        internal_link_needs=content["internal_link_needs"],
                        media_needs=content["media_needs"],
                        faq_questions=content["faq_questions"],
                        acceptance_criteria=content["acceptance_criteria"],
                        structure_guard_result=guard_result,
                        structure_policy_snapshot=structure_policy.snapshot(),
                        status=BriefStatus.DRAFT,
                        composition_attempt_id=(
                            composition_attempt.id if composition_attempt is not None else None
                        ),
                        engine_name=cleaned_engine_name,
                        engine_version=cleaned_engine_version,
                        content_hash=content_hash,
                    )
                )
                for claim in claims:
                    claim_row = self._repository.insert_claim(
                        BriefClaim(
                            brief_id=brief.id,
                            claim_key=claim["claim_key"],
                            claim_text=claim["claim_text"],
                            claim_kind=BriefClaimKind(claim["claim_kind"]),
                            handling=claim["handling"],
                        )
                    )
                    for evidence_id in claim["evidence_ids"]:
                        self._repository.insert_claim_evidence(
                            BriefClaimEvidence(
                                claim_id=claim_row.id,
                                research_evidence_id=uuid.UUID(evidence_id),
                            )
                        )
                if active is not None:
                    assert cleaned_supersede_reason is not None
                    self._repository.append_status_event(
                        BriefStatusEvent(
                            brief_id=active.id,
                            from_status=BriefStatus.DRAFT,
                            to_status=BriefStatus.SUPERSEDED,
                            actor_origin=BriefActorOrigin.OPERATOR,
                            reason=cleaned_supersede_reason,
                            request_id=validated_request_id,
                            replacement_brief_id=brief.id,
                            occurred_at=datetime.now(UTC),
                        )
                    )
        except IntegrityError:
            winner = self._repository.get_by_identity(
                work_item.id,
                upstream.idea.id,
                upstream.pack.id,
                upstream.intent.id,
                cleaned_engine_name,
                cleaned_engine_version,
            )
            if winner is not None and winner.content_hash == content_hash:
                return BriefDraftResult(brief=winner, created=False, superseded_brief_id=None)
            raise BriefConflictError(
                "brief persistence conflicted with concurrently written state"
            ) from None
        return BriefDraftResult(
            brief=brief,
            created=True,
            superseded_brief_id=active.id if active is not None else None,
        )

    # --- acceptance command -------------------------------------------------

    def accept_for_drafting(
        self,
        brief_id: uuid.UUID,
        *,
        reason: str,
        request_id: str | None = None,
    ) -> BriefAcceptance:
        brief = self._repository.get_brief(brief_id)
        if brief is None:
            raise BriefNotFoundError(f"no content brief with id {brief_id}")
        cleaned_reason = _required_text("reason", reason, MAX_REASON_LENGTH)
        validated_request_id = _validate_request_id(request_id)
        work_item = self._workflow_repo.get_by_id_for_update(brief.work_item_id)
        if work_item is None:  # pragma: no cover - RESTRICT FK guarantees this
            raise BriefUpstreamMismatchError("brief has no resolvable work item")

        if brief.status is BriefStatus.SUPERSEDED:
            raise BriefStatusConflictError("a SUPERSEDED brief cannot be accepted")
        if brief.status is BriefStatus.ACCEPTED_FOR_DRAFTING:
            return self._resolve_idempotent_acceptance(brief, work_item)

        # Gate 14: canonical stage.
        if work_item.current_state is not WorkflowState.BRIEFING:
            raise BriefAcceptanceGateError(
                "acceptance requires the work item to be in BRIEFING "
                f"(current: {work_item.current_state.value})"
            )
        # Gates 7/9: full pinned chain revalidated, selection still current.
        upstream = self._resolve_upstream(
            work_item, brief.idea_id, brief.evidence_pack_id, brief.search_intent_analysis_id
        )
        self._require_current_selection(upstream, BriefAcceptanceGateError)
        # Gate 10: idea originality — FAILED and NOT_CHECKABLE fail closed.
        if upstream.idea.originality_status is not OriginalityStatus.PASSED:
            raise BriefAcceptanceGateError(
                "the pinned idea's originality status "
                f"{upstream.idea.originality_status.value!r} does not pass the "
                "accepted boundary (NOT_CHECKABLE never silently passes)"
            )
        # Gate 1: commissioned opportunity (never mutated here).
        if upstream.opportunity.disposition is not OpportunityDisposition.COMMISSIONED:
            raise BriefAcceptanceGateError(
                "acceptance requires a COMMISSIONED opportunity "
                f"(current: {upstream.opportunity.disposition.value})"
            )
        # Gate 2: duplicate gate resolved and not a hard stop.
        self._require_duplicate_gate(work_item, upstream.opportunity)
        # Gates 4/6: claim/evidence map + blocking contradictions.
        claims = self._repository.list_claims(brief.id)
        claim_links = {claim.id: self._repository.list_claim_evidence(claim.id) for claim in claims}
        pack_member_ids = {
            item.research_evidence_id for item in self._packs.list_items(upstream.pack.id)
        }
        self._require_claim_gates(upstream, claims, claim_links, pack_member_ids)
        # Gate 3: exact pinned pack READY.
        if upstream.pack.sufficiency is not EvidencePackSufficiency.READY:
            raise BriefAcceptanceGateError(
                "acceptance requires the pinned evidence pack to be READY "
                f"(persisted: {upstream.pack.sufficiency.value})"
            )
        # Gate 11: structural copyright guard.
        self._require_structure_guard(brief)
        # Gate 12: whole-version content integrity.
        self._require_content_integrity(brief, claims, claim_links)
        # Gate 13: composition attempt, when present.
        self._require_composition_attempt(brief)

        # Mutation: status + audit + explicit workflow transition, atomically.
        now = datetime.now(UTC)
        brief.status = BriefStatus.ACCEPTED_FOR_DRAFTING
        self._repository.append_status_event(
            BriefStatusEvent(
                brief_id=brief.id,
                from_status=BriefStatus.DRAFT,
                to_status=BriefStatus.ACCEPTED_FOR_DRAFTING,
                actor_origin=BriefActorOrigin.OPERATOR,
                reason=cleaned_reason,
                request_id=validated_request_id,
                replacement_brief_id=None,
                occurred_at=now,
            )
        )
        artifact_refs: dict[str, Any] = {
            "content_brief_id": str(brief.id),
            "idea_id": str(brief.idea_id),
            "evidence_pack_id": str(brief.evidence_pack_id),
            "search_intent_analysis_id": str(brief.search_intent_analysis_id),
        }
        if brief.composition_attempt_id is not None:
            artifact_refs["composition_attempt_id"] = str(brief.composition_attempt_id)
        WorkflowService(self._session).transition(
            work_item.id,
            WorkflowState.DRAFTING,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason=cleaned_reason,
            artifact_refs=artifact_refs,
            request_id=validated_request_id,
        )
        self._session.flush()
        return BriefAcceptance(brief=brief, accepted=True)

    # --- internal -----------------------------------------------------------

    def _resolve_idempotent_acceptance(
        self, brief: ContentBrief, work_item: EditorialWorkItem
    ) -> BriefAcceptance:
        if work_item.current_state is not WorkflowState.DRAFTING:
            raise BriefStatusConflictError(
                "the brief is ACCEPTED_FOR_DRAFTING but its work item is "
                f"{work_item.current_state.value!r}; history is inconsistent"
            )
        entry = self._workflow_repo.get_latest_entry_event(work_item.id, WorkflowState.DRAFTING)
        if entry is None or entry.artifact_refs.get("content_brief_id") != str(brief.id):
            raise BriefStatusConflictError(
                "the DRAFTING transition does not pin this exact brief; history is inconsistent"
            )
        return BriefAcceptance(brief=brief, accepted=False)

    def _resolve_upstream(
        self,
        work_item: EditorialWorkItem,
        idea_id: uuid.UUID,
        evidence_pack_id: uuid.UUID,
        search_intent_analysis_id: uuid.UUID,
    ) -> _Upstream:
        opportunity = self._opportunities.get_by_work_item_id(work_item.id)
        if opportunity is None:
            raise BriefUpstreamMismatchError("the work item has no opportunity")
        idea = self._session.get(Idea, idea_id)
        if idea is None:
            raise BriefUpstreamMismatchError(f"no idea version with id {idea_id}")
        if idea.opportunity_id != opportunity.id:
            raise BriefUpstreamMismatchError("the idea belongs to a different opportunity")
        pack = self._packs.get_pack(evidence_pack_id)
        if pack is None:
            raise BriefUpstreamMismatchError(f"no evidence pack with id {evidence_pack_id}")
        if pack.opportunity_id != opportunity.id:
            raise BriefUpstreamMismatchError("the evidence pack belongs to a different opportunity")
        # A generic pack (idea_id NULL) is permitted; a pinned pack must
        # pin THIS exact idea version. Nothing is fabricated.
        if pack.idea_id is not None and pack.idea_id != idea.id:
            raise BriefUpstreamMismatchError("the evidence pack pins a different idea version")
        intent = self._intents.get_by_id(search_intent_analysis_id)
        if intent is None:
            raise BriefUpstreamMismatchError(
                f"no search intent analysis with id {search_intent_analysis_id}"
            )
        if intent.opportunity_id != opportunity.id:
            raise BriefUpstreamMismatchError(
                "the search intent analysis belongs to a different opportunity"
            )
        if intent.idea_id != idea.id:
            raise BriefUpstreamMismatchError(
                "the search intent analysis pins a different idea version"
            )
        return _Upstream(opportunity=opportunity, idea=idea, pack=pack, intent=intent)

    def _require_current_selection(
        self, upstream: _Upstream, error: type[BriefSelectionError]
    ) -> None:
        effective = IdeaService(self._session).get_effective_selection(upstream.opportunity.id)
        if effective is None or effective.id != upstream.idea.id:
            raise error("the pinned idea is no longer the current effective selection")

    def _require_duplicate_gate(
        self, work_item: EditorialWorkItem, opportunity: EditorialOpportunity
    ) -> None:
        """Reuse Task-3 admission semantics; never a second algorithm.

        Every admitted input's pinned decision must still resolve and never
        be REJECT. The CURRENT effective decision for the promotion root is
        revalidated: REJECT is always a hard stop; DUPLICATE is a hard stop
        unless the work item's creation event records the audited operator
        duplicate override (which stays distinguishable forever).
        """
        for research_input in self._opportunities.list_research_inputs(opportunity.id):
            pinned = self._session.get(DuplicateDecision, research_input.duplicate_decision_id)
            if pinned is None:  # pragma: no cover - RESTRICT FK guarantees this
                raise BriefProvenanceError("a pinned duplicate decision is unresolvable")
            if pinned.decision is DuplicateDecisionOutcome.REJECT:
                raise BriefAcceptanceGateError(
                    "an admitted research input pins a REJECT duplicate decision"
                )
        effective = DuplicateDecisionRepository(self._session).get_effective_for_document(
            opportunity.promotion_root_document_id
        )
        if effective is None:
            raise BriefAcceptanceGateError("the promotion root has no effective duplicate decision")
        if effective.decision is DuplicateDecisionOutcome.REJECT:
            raise BriefAcceptanceGateError(
                "the promotion root's effective duplicate decision is REJECT"
            )
        if effective.decision is DuplicateDecisionOutcome.DUPLICATE:
            events = self._workflow_repo.list_events(work_item.id)
            creation_refs = events[0].artifact_refs if events else {}
            if creation_refs.get("promotion") != PROMOTION_OVERRIDE_KIND:
                raise BriefAcceptanceGateError(
                    "the effective duplicate decision is DUPLICATE and no audited "
                    "operator override exists"
                )

    def _require_claim_gates(
        self,
        upstream: _Upstream,
        claims: list[BriefClaim],
        claim_links: dict[uuid.UUID, list[BriefClaimEvidence]],
        pack_member_ids: set[uuid.UUID],
    ) -> None:
        blocking_sides: set[str] = set()
        for contradiction in self._packs.list_contradictions(upstream.pack.id):
            if (
                contradiction.severity is ContradictionSeverity.BLOCKING
                and contradiction.resolution_status is ContradictionResolutionStatus.UNRESOLVED
            ):
                blocking_sides.update(contradiction.evidence_side_a)
                blocking_sides.update(contradiction.evidence_side_b)

        for claim in claims:
            links = claim_links.get(claim.id, [])
            evidence_rows: list[ResearchEvidence] = []
            for link in links:
                if link.research_evidence_id not in pack_member_ids:
                    raise BriefClaimEvidenceError(
                        f"claim {claim.claim_key!r} links evidence outside the pinned pack"
                    )
                evidence_rows.append(self._require_evidence_provenance(link.research_evidence_id))
            if claim.claim_kind in (BriefClaimKind.FACTUAL, BriefClaimKind.SOURCE_ASSERTION):
                usable = [
                    row
                    for row in evidence_rows
                    if row.verification_status is not VerificationStatus.RETRACTED
                ]
                if not usable:
                    raise BriefAcceptanceGateError(
                        f"claim {claim.claim_key!r} ({claim.claim_kind.value}) has no "
                        "non-retracted eligible evidence"
                    )
                if (
                    all(row.verification_status is VerificationStatus.DISPUTED for row in usable)
                    and not (claim.handling or "").strip()
                ):
                    raise BriefAcceptanceGateError(
                        f"claim {claim.claim_key!r} rests only on DISPUTED evidence "
                        "and records no handling; disagreement must stay visible"
                    )
            if claim.claim_kind is BriefClaimKind.FACTUAL and any(
                str(row.id) in blocking_sides for row in evidence_rows
            ):
                raise BriefAcceptanceGateError(
                    f"claim {claim.claim_key!r} links evidence inside an UNRESOLVED "
                    "BLOCKING contradiction; cautious wording cannot bypass it"
                )

    def _require_evidence_provenance(self, evidence_id: uuid.UUID) -> ResearchEvidence:
        """ADR 0007: revalidate the whole chain, never assume FK existence."""
        evidence = self._session.get(ResearchEvidence, evidence_id)
        if evidence is None:
            raise BriefProvenanceError(f"research evidence {evidence_id} is unresolvable")
        document = self._session.get(NormalizedDocument, evidence.normalized_document_id)
        snapshot = (
            self._session.get(FetchSnapshot, document.fetch_snapshot_id)
            if document is not None
            else None
        )
        item = (
            self._session.get(DiscoveryItem, snapshot.discovery_item_id)
            if snapshot is not None
            else None
        )
        source = self._session.get(Source, item.source_id) if item is not None else None
        if document is None or snapshot is None or item is None or source is None:
            raise BriefProvenanceError(
                f"the provenance chain for evidence {evidence_id} does not resolve"
            )
        return evidence

    def _require_structure_guard(self, brief: ContentBrief) -> None:
        outcome = brief.structure_guard_result.get("outcome")
        if outcome == StructureGuardOutcome.PASSED.value:
            return
        if (
            outcome == StructureGuardOutcome.NOT_CHECKABLE.value
            and not brief.structure_policy_snapshot.get("not_checkable_blocks_acceptance", True)
        ):
            return
        raise BriefStructureGuardError(
            f"the structural copyright guard outcome is {outcome!r}; acceptance "
            "is blocked by the persisted policy"
        )

    def _require_content_integrity(
        self,
        brief: ContentBrief,
        claims: list[BriefClaim],
        claim_links: dict[uuid.UUID, list[BriefClaimEvidence]],
    ) -> None:
        recomputed = _content_hash(
            content={
                "target_audience": brief.target_audience,
                "intent_summary": brief.intent_summary,
                "original_angle": brief.original_angle,
                "title_guidance": brief.title_guidance,
                "content_objective": brief.content_objective,
                "required_sections": brief.required_sections,
                "optional_sections": brief.optional_sections,
                "practical_requirements": brief.practical_requirements,
                "exclusions": brief.exclusions,
                "uncertainty_notes": brief.uncertainty_notes,
                "internal_link_needs": brief.internal_link_needs,
                "media_needs": brief.media_needs,
                "faq_questions": brief.faq_questions,
                "acceptance_criteria": brief.acceptance_criteria,
            },
            structure_guard_result=brief.structure_guard_result,
            structure_policy_snapshot=brief.structure_policy_snapshot,
            claims=[
                {
                    "claim_key": claim.claim_key,
                    "claim_text": claim.claim_text,
                    "claim_kind": claim.claim_kind.value,
                    "handling": claim.handling,
                    "evidence_ids": sorted(
                        str(link.research_evidence_id) for link in claim_links.get(claim.id, [])
                    ),
                }
                for claim in claims
            ],
        )
        if recomputed != brief.content_hash:
            raise BriefConflictError(
                "the brief's persisted content no longer matches its content hash; "
                "the version was mutated out of band"
            )

    def _require_composition_attempt(self, brief: ContentBrief) -> None:
        if brief.composition_attempt_id is None:
            return
        attempt = self._session.get(AiGenerationAttempt, brief.composition_attempt_id)
        if attempt is None:  # pragma: no cover - RESTRICT FK guarantees this
            raise BriefProvenanceError("the composition attempt is unresolvable")
        if (
            attempt.status is not GenerationStatus.SUCCEEDED
            or attempt.purpose is not GenerationPurpose.BRIEF_COMPOSITION
        ):
            raise BriefAcceptanceGateError(
                "the composition attempt must be a SUCCEEDED BRIEF_COMPOSITION attempt"
            )

    def _build_content(self, upstream: _Upstream, draft: BriefDraftInput) -> dict[str, Any]:

        idea = upstream.idea
        # target_audience and original_angle are DERIVED from the exact
        # pinned idea (which the intent analysis restates), never caller
        # text that could contradict the selected concept.
        title_guidance: dict[str, Any] = {
            "idea_working_title": idea.working_title,
            "direction": _optional_text(
                "title_direction", draft.title_direction, MAX_TITLE_DIRECTION_LENGTH
            ),
            "constraints": clean_string_list(
                "title_constraints",
                draft.title_constraints,
                max_items=MAX_TITLE_CONSTRAINTS,
                max_length=MAX_TITLE_CONSTRAINT_LENGTH,
            ),
        }
        # Every idea prohibition is retained; the brief may only add more.
        exclusions = list(idea.exclusions)
        for extra in clean_string_list(
            "extra_exclusions",
            draft.extra_exclusions,
            max_items=MAX_EXCLUSIONS,
            max_length=MAX_EXCLUSION_LENGTH,
        ):
            if extra not in exclusions:
                exclusions.append(extra)
        if len(exclusions) > MAX_EXCLUSIONS:
            raise BriefInputError("combined exclusions exceed the limit")
        required_sections = clean_sections("required_sections", draft.required_sections)
        if not required_sections:
            raise BriefInputError("required_sections must not be empty")
        return {
            "target_audience": idea.audience,
            "intent_summary": _required_text(
                "intent_summary", draft.intent_summary, MAX_INTENT_SUMMARY_LENGTH
            ),
            "original_angle": idea.angle,
            "title_guidance": title_guidance,
            "content_objective": _required_text(
                "content_objective", draft.content_objective, MAX_CONTENT_OBJECTIVE_LENGTH
            ),
            "required_sections": required_sections,
            "optional_sections": clean_sections("optional_sections", draft.optional_sections),
            "practical_requirements": validate_planning_dimensions(draft.practical_requirements),
            "exclusions": exclusions,
            "uncertainty_notes": clean_string_list(
                "uncertainty_notes",
                draft.uncertainty_notes,
                max_items=MAX_UNCERTAINTY_NOTES,
                max_length=MAX_UNCERTAINTY_NOTE_LENGTH,
            ),
            "internal_link_needs": _clean_needs(
                "internal_link_needs", draft.internal_link_needs, MAX_LINK_NEEDS
            ),
            "media_needs": _clean_needs("media_needs", draft.media_needs, MAX_MEDIA_NEEDS),
            "faq_questions": clean_string_list(
                "faq_questions",
                draft.faq_questions,
                max_items=MAX_FAQ_QUESTIONS,
                max_length=MAX_FAQ_QUESTION_LENGTH,
            ),
            "acceptance_criteria": _clean_criteria(draft.acceptance_criteria),
        }

    def _validate_claims(
        self, draft: BriefDraftInput, pack_member_ids: set[uuid.UUID]
    ) -> list[dict[str, Any]]:
        """Early deterministic claim-map validation: no partial drafts.

        FACTUAL / SOURCE_ASSERTION without evidence is rejected AT CREATION
        (the chosen persistence philosophy — reported): such a map could
        never pass acceptance, so no misleading draft is persisted.
        Evidence outside the pinned pack and unresolvable provenance are
        equally creation-time rejections.
        """
        if not draft.claims:
            raise BriefInputError("a brief needs at least one claim")
        if len(draft.claims) > MAX_CLAIMS:
            raise BriefInputError(f"claims exceed the limit of {MAX_CLAIMS}")
        cleaned: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for claim in draft.claims:
            if not isinstance(claim.claim_kind, BriefClaimKind):
                raise BriefInputError("claim_kind must be a BriefClaimKind value")
            key = _required_text("claim_key", claim.claim_key, MAX_CLAIM_KEY_LENGTH)
            if key in seen_keys:
                raise BriefInputError(f"duplicate claim key {key!r}")
            seen_keys.add(key)
            text_value = _required_text("claim_text", claim.claim_text, MAX_CLAIM_TEXT_LENGTH)
            handling = _optional_text("claim handling", claim.handling, MAX_CLAIM_HANDLING_LENGTH)
            if len(claim.evidence_ids) > MAX_CLAIM_EVIDENCE_LINKS:
                raise BriefClaimEvidenceError(f"claim {key!r} exceeds the evidence-link limit")
            if len(set(claim.evidence_ids)) != len(claim.evidence_ids):
                raise BriefClaimEvidenceError(f"claim {key!r} links the same evidence twice")
            for evidence_id in claim.evidence_ids:
                if evidence_id not in pack_member_ids:
                    raise BriefClaimEvidenceError(
                        f"claim {key!r} links evidence outside the pinned evidence pack"
                    )
                self._require_evidence_provenance(evidence_id)
            if (
                claim.claim_kind in (BriefClaimKind.FACTUAL, BriefClaimKind.SOURCE_ASSERTION)
                and not claim.evidence_ids
            ):
                raise BriefClaimEvidenceError(
                    f"claim {key!r} ({claim.claim_kind.value}) requires at least one "
                    "linked ResearchEvidence row; a source URL is never verification"
                )
            cleaned.append(
                {
                    "claim_key": key,
                    "claim_text": text_value,
                    "claim_kind": claim.claim_kind.value,
                    "handling": handling,
                    "evidence_ids": sorted(str(value) for value in claim.evidence_ids),
                }
            )
        return cleaned

    def _run_structure_guard(
        self,
        upstream: _Upstream,
        required_sections: list[dict[str, str]],
        policy: BriefStructurePolicy,
    ) -> dict[str, Any]:
        sources: list[SourceStructure] = []
        for research_input in self._opportunities.list_research_inputs(upstream.opportunity.id):
            document = self._session.get(NormalizedDocument, research_input.normalized_document_id)
            if document is None:  # pragma: no cover - RESTRICT FK guarantees this
                continue
            sources.append(
                SourceStructure(
                    normalized_document_id=document.id,
                    headings=[
                        str(heading.get("text", ""))
                        for heading in document.headings
                        if isinstance(heading, dict)
                    ],
                )
            )
        labels = [section["heading_guidance"] for section in required_sections]
        return evaluate_structure_guard(labels, sources, policy)


def validate_composition_attempt(
    attempt: AiGenerationAttempt,
    *,
    work_item_id: uuid.UUID,
    idea_id: uuid.UUID,
    evidence_pack_id: uuid.UUID,
    search_intent_analysis_id: uuid.UUID,
) -> None:
    """Never trust the FK or the caller: revalidate the durable attempt."""
    if attempt.purpose is not GenerationPurpose.BRIEF_COMPOSITION:
        raise InvalidCompositionAttemptError(
            f"attempt purpose {attempt.purpose.value!r} cannot back a composed brief"
        )
    if attempt.status is not GenerationStatus.SUCCEEDED:
        raise InvalidCompositionAttemptError(
            f"only a SUCCEEDED attempt can back a brief (got {attempt.status.value!r})"
        )
    refs = attempt.input_refs
    if (
        refs.get("schema") != BRIEF_COMPOSITION_INPUT_REFS_SCHEMA
        or refs.get("work_item_id") != str(work_item_id)
        or refs.get("idea_id") != str(idea_id)
        or refs.get("evidence_pack_id") != str(evidence_pack_id)
        or refs.get("search_intent_analysis_id") != str(search_intent_analysis_id)
    ):
        raise InvalidCompositionAttemptError(
            "the attempt's persisted input provenance does not match this exact brief identity"
        )


def _content_hash(
    *,
    content: dict[str, Any],
    structure_guard_result: dict[str, Any],
    structure_policy_snapshot: dict[str, Any],
    claims: list[dict[str, Any]],
) -> str:
    """Whole-version semantic hash: brief content + claim map + structure."""
    return sha256_hex(
        {
            "schema": BRIEF_CONTENT_SCHEMA_VERSION,
            "content": content,
            "structure_guard_result": structure_guard_result,
            "structure_policy_snapshot": structure_policy_snapshot,
            "claims": sorted(claims, key=lambda claim: claim["claim_key"]),
        }
    )


def _clean_needs(
    name: str,
    needs: tuple[InternalLinkNeed, ...] | tuple[MediaNeed, ...],
    max_items: int,
) -> list[dict[str, Any]]:
    if len(needs) > max_items:
        raise BriefInputError(f"{name} exceeds the limit of {max_items} entries")
    return [need.cleaned() for need in needs]


def _clean_criteria(criteria: tuple[AcceptanceCriterion, ...]) -> list[dict[str, str]]:
    if len(criteria) > MAX_ACCEPTANCE_CRITERIA:
        raise BriefInputError(
            f"acceptance_criteria exceeds the limit of {MAX_ACCEPTANCE_CRITERIA} entries"
        )
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for criterion in criteria:
        entry = criterion.cleaned()
        if entry["key"] in seen:
            raise BriefInputError(f"duplicate acceptance criterion key {entry['key']!r}")
        seen.add(entry["key"])
        cleaned.append(entry)
    return cleaned


def _required_text(name: str, value: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BriefInputError(f"{name} must not be empty")
    cleaned = " ".join(value.split())
    if len(cleaned) > limit:
        raise BriefInputError(f"{name} exceeds the {limit}-character limit")
    return cleaned


def _optional_text(name: str, value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return _required_text(name, value, limit)


def _validate_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not is_valid_request_id(value):
        raise BriefInputError("request_id is not a valid correlation identifier")
    return value
