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
)
from contentos.opportunities.errors import (
    InvalidPromotionInputError,
    PromotionConflictError,
    PromotionNotEligibleError,
    PromotionRootNotFoundError,
)
from contentos.opportunities.models import EditorialOpportunity, OpportunityResearchInput
from contentos.opportunities.repository import OpportunityRepository
from contentos.sources.models import Source
from contentos.workflow.enums import WorkflowActorOrigin, WorkItemOrigin
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
