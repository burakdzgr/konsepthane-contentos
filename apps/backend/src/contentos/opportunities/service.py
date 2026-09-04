"""Phase 2 -> Phase 3 research promotion (accepted design §2, ADR 0008).

One eligible NormalizedDocument root is durably promoted into
EditorialWorkItem + EditorialOpportunity + the initial research input, in one
caller-owned transaction. The service flushes; the caller commits.

Promotion identity: `editorial_opportunities.promotion_root_document_id` is
UNIQUE at the database level, so one promoted document root can never yield
two work items — regardless of retries or races. The same document may still
be attached later as supporting/context input to a *different* opportunity:
input roles and promotion identity are separate concepts by design.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.core.context import is_valid_request_id
from contentos.discovery.models import DiscoveryItem
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.duplicates.repository import DuplicateDecisionRepository
from contentos.fetching.snapshots import FetchSnapshot
from contentos.normalization.enums import NormalizationStatus
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.enums import (
    OpportunityActor,
    OpportunityDisposition,
    ResearchInputRole,
    ScoreEligibility,
)
from contentos.opportunities.errors import (
    CommissioningConflictError,
    CommissioningGateError,
    InvalidPromotionInputError,
    OpportunityError,
    OpportunityNotFoundError,
    PromotionConflictError,
    PromotionNotEligibleError,
    PromotionRootNotFoundError,
    RejectionConflictError,
)
from contentos.opportunities.models import (
    EditorialOpportunity,
    OpportunityResearchInput,
    OpportunityScore,
)
from contentos.opportunities.repository import OpportunityRepository
from contentos.sources.models import Source
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState, WorkItemOrigin
from contentos.workflow.repository import WorkflowRepository
from contentos.workflow.service import WorkflowService

# ADR 0008 gate: automatic promotion eligibility by effective decision outcome.
ELIGIBLE_OUTCOMES = frozenset(
    {
        DuplicateDecisionOutcome.UNIQUE,
        DuplicateDecisionOutcome.RELATED,
        DuplicateDecisionOutcome.UPDATE_EXISTING,
    }
)

MAX_TOPIC_SUMMARY_LENGTH = 1000
MAX_LABEL_LENGTH = 200
MAX_OVERRIDE_REASON_LENGTH = 1000
MAX_INPUT_NOTE_LENGTH = 2000

PROMOTION_KIND_RESEARCH = "research_intake"
PROMOTION_KIND_DUPLICATE_OVERRIDE = "duplicate_override"


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """Durable identities of one promotion; `created` is False on idempotent retry."""

    work_item_id: uuid.UUID
    opportunity_id: uuid.UUID
    duplicate_outcome: DuplicateDecisionOutcome
    created: bool


@dataclass(frozen=True, slots=True)
class _PromotionChain:
    document: NormalizedDocument
    decision: DuplicateDecision
    snapshot: FetchSnapshot
    item: DiscoveryItem
    source: Source


class ResearchPromotionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._opportunities = OpportunityRepository(session)
        self._decisions = DuplicateDecisionRepository(session)
        self._workflow = WorkflowService(session)
        self._workflow_repository = WorkflowRepository(session)

    def promote_research(
        self,
        normalized_document_id: uuid.UUID,
        *,
        actor_origin: WorkflowActorOrigin = WorkflowActorOrigin.SYSTEM,
        title_working_label: str | None = None,
        topic_summary: str | None = None,
        request_id: str | None = None,
    ) -> PromotionResult:
        """Automatically promote one eligible research root (hard stops binding).

        DUPLICATE and REJECT (and a missing decision) are hard stops here,
        always: this path can never perform the operator duplicate override.
        """
        label_override = _validate_optional_text(
            "title_working_label", title_working_label, MAX_LABEL_LENGTH
        )
        topic_override = _validate_optional_text(
            "topic_summary", topic_summary, MAX_TOPIC_SUMMARY_LENGTH
        )

        chain = self._resolve_chain(normalized_document_id)
        outcome = chain.decision.decision
        if outcome not in ELIGIBLE_OUTCOMES:
            raise PromotionNotEligibleError(
                f"effective duplicate decision '{outcome.value}' is a hard stop "
                "for automatic promotion"
            )

        existing = self._opportunities.get_by_promotion_root(chain.document.id)
        if existing is not None:
            return self._existing_result(existing, WorkItemOrigin.RESEARCH_INTAKE, outcome)

        label = label_override or _derive_text(chain, MAX_LABEL_LENGTH)
        topic = topic_override or _derive_text(chain, MAX_TOPIC_SUMMARY_LENGTH)
        update_reference = None
        role = ResearchInputRole.PRIMARY_SIGNAL
        if outcome is DuplicateDecisionOutcome.UPDATE_EXISTING:
            role = ResearchInputRole.UPDATE_SIGNAL
            # Truthful: an update/refresh signal per the pinned decision. No
            # production inventory connector exists, so no target article
            # identity is ever claimed.
            update_reference = f"update/refresh signal per duplicate decision {chain.decision.id}"

        return self._create_promotion(
            chain,
            promotion_kind=PROMOTION_KIND_RESEARCH,
            work_item_origin=WorkItemOrigin.RESEARCH_INTAKE,
            actor_origin=actor_origin,
            creation_reason=(
                f"promoted from eligible Phase 2 research (duplicate outcome: {outcome.value})"
            ),
            label=label,
            topic=topic,
            update_reference=update_reference,
            input_role=role,
            input_note=None,
            request_id=request_id,
        )

    def promote_duplicate_override(
        self,
        normalized_document_id: uuid.UUID,
        *,
        reason: str,
        distinct_angle: str,
        request_id: str | None = None,
    ) -> PromotionResult:
        """Operator-only promotion of an effective-DUPLICATE root.

        Requires a mandatory reason and a demonstrably distinct angle. The
        DUPLICATE decision is never mutated and never claimed wrong: it stays
        pinned on the creation event and the research input. REJECT has no
        override.
        """
        cleaned_reason = _validate_required_text("reason", reason, MAX_OVERRIDE_REASON_LENGTH)
        cleaned_angle = _validate_required_text(
            "distinct_angle", distinct_angle, MAX_TOPIC_SUMMARY_LENGTH
        )

        chain = self._resolve_chain(normalized_document_id)
        outcome = chain.decision.decision
        if outcome is DuplicateDecisionOutcome.REJECT:
            raise PromotionNotEligibleError("effective duplicate decision 'reject' has no override")
        if outcome is not DuplicateDecisionOutcome.DUPLICATE:
            raise InvalidPromotionInputError(
                "the duplicate override applies only to an effective 'duplicate' "
                "decision; use promote_research for eligible outcomes"
            )

        existing = self._opportunities.get_by_promotion_root(chain.document.id)
        if existing is not None:
            return self._existing_result(existing, WorkItemOrigin.OPERATOR, outcome)

        return self._create_promotion(
            chain,
            promotion_kind=PROMOTION_KIND_DUPLICATE_OVERRIDE,
            work_item_origin=WorkItemOrigin.OPERATOR,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            creation_reason=cleaned_reason,
            label=cleaned_angle[:MAX_LABEL_LENGTH],
            topic=cleaned_angle,
            update_reference=None,
            input_role=ResearchInputRole.PRIMARY_SIGNAL,
            input_note=(f"operator duplicate override with distinct angle: {cleaned_angle}")[
                :MAX_INPUT_NOTE_LENGTH
            ],
            request_id=request_id,
        )

    def _create_promotion(
        self,
        chain: _PromotionChain,
        *,
        promotion_kind: str,
        work_item_origin: WorkItemOrigin,
        actor_origin: WorkflowActorOrigin,
        creation_reason: str,
        label: str,
        topic: str,
        update_reference: str | None,
        input_role: ResearchInputRole,
        input_note: str | None,
        request_id: str | None,
    ) -> PromotionResult:
        outcome = chain.decision.decision
        artifact_refs: dict[str, Any] = {
            "promotion": promotion_kind,
            "normalized_document_id": str(chain.document.id),
            "duplicate_decision_id": str(chain.decision.id),
            "duplicate_outcome": outcome.value,
            "fetch_snapshot_id": str(chain.snapshot.id),
            "discovery_item_id": str(chain.item.id),
            "source_id": str(chain.source.id),
        }
        try:
            with self._session.begin_nested():
                work_item = self._workflow.create_work_item(
                    origin=work_item_origin,
                    title_working_label=label,
                    reason=creation_reason,
                    actor_origin=actor_origin,
                    locale=chain.item.locale,
                    market=chain.source.market,
                    artifact_refs=artifact_refs,
                    request_id=request_id,
                )
                opportunity = self._opportunities.insert_opportunity(
                    EditorialOpportunity(
                        work_item_id=work_item.id,
                        promotion_root_document_id=chain.document.id,
                        topic_summary=topic,
                        update_of_reference=update_reference,
                        disposition=OpportunityDisposition.OPEN,
                    )
                )
                self._opportunities.insert_research_input(
                    OpportunityResearchInput(
                        opportunity_id=opportunity.id,
                        normalized_document_id=chain.document.id,
                        duplicate_decision_id=chain.decision.id,
                        role=input_role,
                        added_by=OpportunityActor(actor_origin.value),
                        note=input_note,
                        added_at=datetime.now(UTC),
                    )
                )
        except IntegrityError:
            # Uniqueness race: another transaction promoted this root first.
            # The database is the final authority; recover deterministically.
            winner = self._opportunities.get_by_promotion_root(chain.document.id)
            if winner is not None:
                return self._existing_result(winner, work_item_origin, outcome)
            raise PromotionConflictError(
                "promotion conflicts with concurrently written state"
            ) from None
        return PromotionResult(
            work_item_id=work_item.id,
            opportunity_id=opportunity.id,
            duplicate_outcome=outcome,
            created=True,
        )

    def _existing_result(
        self,
        existing: EditorialOpportunity,
        expected_origin: WorkItemOrigin,
        outcome: DuplicateDecisionOutcome,
    ) -> PromotionResult:
        """Idempotent retry returns the durable result; incompatible retry fails."""
        work_item = self._workflow_repository.get_by_id(existing.work_item_id)
        assert work_item is not None  # RESTRICT FK guarantees existence
        if work_item.origin is not expected_origin:
            raise PromotionConflictError(
                "this research root is already promoted with incompatible "
                f"semantics (existing origin: '{work_item.origin.value}')"
            )
        return PromotionResult(
            work_item_id=existing.work_item_id,
            opportunity_id=existing.id,
            duplicate_outcome=outcome,
            created=False,
        )

    def _resolve_chain(self, normalized_document_id: uuid.UUID) -> _PromotionChain:
        """Validate the durable Phase 2 chain; absence is never a pass."""
        document = self._session.get(NormalizedDocument, normalized_document_id)
        if document is None:
            raise PromotionRootNotFoundError(
                f"no normalized document with id {normalized_document_id}"
            )
        if document.normalization_status is not NormalizationStatus.SUCCEEDED:
            raise PromotionNotEligibleError("promotion requires a SUCCEEDED normalized document")
        decision = self._decisions.get_effective_for_document(document.id)
        if decision is None:
            raise PromotionNotEligibleError(
                "no duplicate decision exists for this document; absence of a "
                "decision is not a pass"
            )
        snapshot = self._session.get(FetchSnapshot, document.fetch_snapshot_id)
        item = (
            self._session.get(DiscoveryItem, snapshot.discovery_item_id)
            if snapshot is not None
            else None
        )
        source = self._session.get(Source, item.source_id) if item is not None else None
        if snapshot is None or item is None or source is None:
            raise PromotionNotEligibleError(
                "the provenance chain for this document is not resolvable"
            )
        return _PromotionChain(
            document=document,
            decision=decision,
            snapshot=snapshot,
            item=item,
            source=source,
        )


def _derive_text(chain: _PromotionChain, limit: int) -> str:
    """Deterministic operator-facing text from the chain's own metadata."""
    for candidate in (chain.document.title, chain.item.title_hint, chain.item.canonical_url):
        if candidate and candidate.strip():
            return candidate.strip()[:limit]
    return str(chain.document.id)[:limit]


def _validate_required_text(name: str, value: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidPromotionInputError(f"{name} must not be empty")
    cleaned = value.strip()
    if len(cleaned) > limit:
        raise InvalidPromotionInputError(f"{name} exceeds the {limit}-character limit")
    return cleaned


def _validate_optional_text(name: str, value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return _validate_required_text(name, value, limit)


@dataclass(frozen=True, slots=True)
class CommissionResult:
    """`commissioned` is False on an idempotent no-op re-commissioning."""

    opportunity: EditorialOpportunity
    opportunity_score_id: uuid.UUID | None
    commissioned: bool


def commissioning_admits(
    *,
    disposition: OpportunityDisposition | None,
    work_item_state: WorkflowState | None,
    score_eligibility: ScoreEligibility | None,
    override_gate: bool = False,
) -> bool:
    """The ONE commissioning gate predicate (design §18, ADR 0010).

    Shared by the commissioning command and every read model that decides
    whether to offer the commissioning affordance, so an operator is never
    shown a button the domain will refuse. Pure: no session, no I/O.

    Default (no override): admits only an OPEN opportunity whose work item
    sits in IDEA_SCORING and whose EFFECTIVE durable score is
    COMMISSIONABLE. NOT_COMMISSIONABLE and NEEDS_OPERATOR_REVIEW fail closed.

    `override_gate` (ADR 0010): a NAMED operator may commission over a
    NOT_COMMISSIONABLE / NEEDS_OPERATOR_REVIEW score with a required reason,
    because engine v1 measures the SOURCE BASE (recency, source count,
    trust, evidence), never topic value — the human is the topic judge. The
    override is recorded durably on the transition. No score is STILL never
    a pass, override or not: nothing may be commissioned unevaluated.
    """
    if disposition is not OpportunityDisposition.OPEN:
        return False
    if work_item_state is not WorkflowState.IDEA_SCORING:
        return False
    if score_eligibility is None:
        return False
    return override_gate or score_eligibility is ScoreEligibility.COMMISSIONABLE


def _explain_gate_refusal(
    opportunity: EditorialOpportunity, work_item: Any, score: OpportunityScore | None
) -> OpportunityError:
    """Name the FIRST sub-rule of `commissioning_admits` that failed.

    Only reached when the predicate refused, so exactly one branch applies;
    the typed error distinguishes a durable-history contradiction
    (conflict) from a failed score gate."""
    if opportunity.disposition is not OpportunityDisposition.OPEN:
        return CommissioningConflictError(
            f"a {opportunity.disposition.value!r} opportunity cannot be commissioned"
        )
    if work_item.current_state is not WorkflowState.IDEA_SCORING:
        return CommissioningConflictError(
            "commissioning requires the work item to be in IDEA_SCORING "
            f"(current: {work_item.current_state.value})"
        )
    if score is None:
        return CommissioningGateError(
            "no durable opportunity score exists; absence of a score is never a pass"
        )
    return CommissioningGateError(
        "the effective score's eligibility is "
        f"{score.eligibility.value!r}; only COMMISSIONABLE commissions by "
        "default — a named operator may pass override_gate with a reason "
        "(ADR 0010)"
    )


class OpportunityCommissioningService:
    """The explicit HUMAN commissioning command (design §18).

    IDEA_SCORING -> EVIDENCE_BUILDING is an operator decision: no Celery
    job, scoring evaluation, or idea generation may ever call this
    automatically. Task 14 exposes it; today it is a transport-neutral
    domain command under the private single-operator boundary.

    Gate rule (reported): only a durable effective score with eligibility
    COMMISSIONABLE commissions by default. No score is never a pass.
    NOT_COMMISSIONABLE and NEEDS_OPERATOR_REVIEW fail closed UNLESS the
    named operator passes `override_gate=True` with a reason (ADR 0010);
    the override and the overridden verdict are then recorded on the
    EVIDENCE_BUILDING entry event's artifact_refs.

    The service flushes; the caller commits (a workflow failure or caller
    rollback leaves the opportunity OPEN — no half-commissioned state).
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = OpportunityRepository(session)
        self._workflow_repo = WorkflowRepository(session)

    def commission_opportunity(
        self,
        opportunity_id: uuid.UUID,
        *,
        reason: str,
        request_id: str | None = None,
        override_gate: bool = False,
    ) -> CommissionResult:
        cleaned_reason = _validate_required_text("reason", reason, MAX_OVERRIDE_REASON_LENGTH)
        if request_id is not None and not is_valid_request_id(request_id):
            raise InvalidPromotionInputError("request_id is not a valid correlation identifier")
        opportunity = self._repository.get_by_id(opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(f"no opportunity with id {opportunity_id}")
        # Serialize the decision on the canonical work-item row.
        work_item = self._workflow_repo.get_by_id_for_update(opportunity.work_item_id)
        if work_item is None:  # pragma: no cover - RESTRICT FK guarantees this
            raise OpportunityNotFoundError("opportunity has no resolvable work item")
        # The opportunity was read BEFORE the lock wait; a concurrent
        # commissioning may have committed while we blocked. Re-read it so
        # the loser of the race resolves idempotently instead of acting on
        # a stale OPEN disposition.
        self._session.refresh(opportunity)

        if opportunity.disposition is OpportunityDisposition.COMMISSIONED:
            return self._resolve_idempotent(opportunity, work_item)
        score = self._repository.get_effective_score(opportunity.id)
        if not commissioning_admits(
            disposition=opportunity.disposition,
            work_item_state=work_item.current_state,
            score_eligibility=score.eligibility if score is not None else None,
            override_gate=override_gate,
        ):
            raise _explain_gate_refusal(opportunity, work_item, score)
        assert score is not None  # the predicate never admits an unscored opportunity
        overridden = override_gate and score.eligibility is not ScoreEligibility.COMMISSIONABLE

        now = datetime.now(UTC)
        opportunity.disposition = OpportunityDisposition.COMMISSIONED
        opportunity.disposition_reason = cleaned_reason
        opportunity.disposition_at = now
        opportunity.disposition_by = OpportunityActor.OPERATOR
        WorkflowService(self._session).transition(
            work_item.id,
            WorkflowState.EVIDENCE_BUILDING,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason=cleaned_reason,
            artifact_refs={
                "opportunity_id": str(opportunity.id),
                "opportunity_score_id": str(score.id),
                # ADR 0010: the gate verdict the human overrode stays visible
                # forever next to the decision; absent when the gate passed.
                **(
                    {
                        "commissioning_gate_override": "true",
                        "overridden_score_eligibility": score.eligibility.value,
                        "overridden_score_band": score.overall_band.value,
                    }
                    if overridden
                    else {}
                ),
            },
            request_id=request_id,
        )
        self._session.flush()
        return CommissionResult(
            opportunity=opportunity, opportunity_score_id=score.id, commissioned=True
        )

    def _resolve_idempotent(
        self, opportunity: EditorialOpportunity, work_item: Any
    ) -> CommissionResult:
        """No-op only when history consistently records the commissioning."""
        entry = self._workflow_repo.get_latest_entry_event(
            work_item.id, WorkflowState.EVIDENCE_BUILDING
        )
        if (
            entry is None
            or entry.from_state is not WorkflowState.IDEA_SCORING
            or entry.artifact_refs.get("opportunity_id") != str(opportunity.id)
        ):
            raise CommissioningConflictError(
                "the opportunity is COMMISSIONED but the workflow history does "
                "not consistently record the commissioning transition"
            )
        score_ref = entry.artifact_refs.get("opportunity_score_id")
        return CommissionResult(
            opportunity=opportunity,
            opportunity_score_id=uuid.UUID(score_ref) if score_ref else None,
            commissioned=False,
        )


@dataclass(frozen=True, slots=True)
class RejectionResult:
    """`rejected` is False on an idempotent no-op re-rejection."""

    opportunity: EditorialOpportunity
    rejected: bool


class OpportunityRejectionService:
    """The explicit HUMAN opportunity-rejection command (design §11/§19).

    Rule (reported): rejection applies only to an OPEN opportunity whose
    work item is in IDEA_SCORING — the stage where the operator decides
    against pursuing a scored opportunity. Later-stage abandonment goes
    through the workflow's own BLOCKED/REJECTED paths on the work item,
    never through a broad disposition override here.

    The service flushes; the caller commits (rollback leaves the
    opportunity OPEN — no half-rejected state).
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = OpportunityRepository(session)
        self._workflow_repo = WorkflowRepository(session)

    def reject_opportunity(
        self,
        opportunity_id: uuid.UUID,
        *,
        reason: str,
        request_id: str | None = None,
    ) -> RejectionResult:
        cleaned_reason = _validate_required_text("reason", reason, MAX_OVERRIDE_REASON_LENGTH)
        if request_id is not None and not is_valid_request_id(request_id):
            raise InvalidPromotionInputError("request_id is not a valid correlation identifier")
        opportunity = self._repository.get_by_id(opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(f"no opportunity with id {opportunity_id}")
        # Serialize on the canonical work-item row, then re-read: a
        # concurrent duplicate command converges to the idempotent no-op.
        work_item = self._workflow_repo.get_by_id_for_update(opportunity.work_item_id)
        if work_item is None:  # pragma: no cover - RESTRICT FK guarantees this
            raise OpportunityNotFoundError("opportunity has no resolvable work item")
        self._session.refresh(opportunity)

        if opportunity.disposition is OpportunityDisposition.REJECTED:
            return self._resolve_idempotent(opportunity, work_item)
        if opportunity.disposition is not OpportunityDisposition.OPEN:
            raise RejectionConflictError(
                f"a {opportunity.disposition.value!r} opportunity cannot be rejected"
            )
        if work_item.current_state is not WorkflowState.IDEA_SCORING:
            raise RejectionConflictError(
                "opportunity rejection requires the work item to be in "
                f"IDEA_SCORING (current: {work_item.current_state.value})"
            )

        now = datetime.now(UTC)
        opportunity.disposition = OpportunityDisposition.REJECTED
        opportunity.disposition_reason = cleaned_reason
        opportunity.disposition_at = now
        opportunity.disposition_by = OpportunityActor.OPERATOR
        WorkflowService(self._session).transition(
            work_item.id,
            WorkflowState.REJECTED,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason=cleaned_reason,
            artifact_refs={"opportunity_id": str(opportunity.id)},
            request_id=request_id,
        )
        self._session.flush()
        return RejectionResult(opportunity=opportunity, rejected=True)

    def _resolve_idempotent(
        self, opportunity: EditorialOpportunity, work_item: Any
    ) -> RejectionResult:
        """No-op only when history consistently records the rejection."""
        entry = self._workflow_repo.get_latest_entry_event(work_item.id, WorkflowState.REJECTED)
        if (
            entry is None
            or entry.from_state is not WorkflowState.IDEA_SCORING
            or entry.artifact_refs.get("opportunity_id") != str(opportunity.id)
        ):
            raise RejectionConflictError(
                "the opportunity is REJECTED but the workflow history does "
                "not consistently record the rejection transition"
            )
        return RejectionResult(opportunity=opportunity, rejected=False)
