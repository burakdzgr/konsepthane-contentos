"""DecisionService: the human decision surface at the Phase 4 terminal.

Gates (PHASE5_GOVERNANCE_ARCHITECTURE.md §2):
- decisions exist only in AWAITING_HUMAN_REVIEW (revocation in
  APPROVED); the reviewer identity comes ONLY from the authenticated
  session (a User row with the reviewer role — enforced at the API
  boundary and re-checked here);
- approve requires the ACTIVE `ready_for_human_review` QA report to
  cover the ACTIVE draft AND the entry-pinned content hash to still
  match the ACTIVE draft (a changed package cannot ride an old QA pass);
- every decision is an append-only record pinning the exact package,
  written and FLUSHED before the caller commits and transitions.

`approval_is_current` is the hash-bound validity primitive: the latest
approval not referenced by a later revocation, and only while the ACTIVE
draft still carries the approved hash.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.auth.enums import UserRole
from contentos.auth.models import User
from contentos.auth.service import user_has_role
from contentos.core.context import is_valid_request_id
from contentos.decisions.enums import DecisionKind
from contentos.decisions.errors import (
    DecisionConflictError,
    DecisionInputError,
    DecisionPreconditionError,
)
from contentos.decisions.models import HumanDecision
from contentos.drafts.repository import DraftRepository
from contentos.qa.enums import QaOutcome
from contentos.qa.models import QaReport
from contentos.qa.repository import QaRepository
from contentos.reviews.repository import ReviewRepository
from contentos.workflow.enums import WorkflowState
from contentos.workflow.repository import WorkflowRepository

MAX_REASON_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class DecisionPackage:
    """The exact package a decision is being made about."""

    work_item_id: uuid.UUID
    report: QaReport
    content_draft_id: uuid.UUID
    editorial_review_id: uuid.UUID
    content_hash: str


@dataclass(frozen=True, slots=True)
class ApprovalStatus:
    """The derived approval state of one work item."""

    approved: bool
    current: bool
    decision_id: uuid.UUID | None
    approved_content_hash: str | None
    active_content_hash: str | None


class DecisionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._workflow = WorkflowRepository(session)
        self._qa = QaRepository(session)
        self._drafts = DraftRepository(session)
        self._reviews = ReviewRepository(session)

    # --- package resolution ---------------------------------------------------

    def resolve_package(
        self, work_item_id: uuid.UUID, *, expected_state: WorkflowState
    ) -> DecisionPackage:
        work_item = self._workflow.get_by_id(work_item_id)
        if work_item is None:
            raise DecisionPreconditionError(f"no editorial work item with id {work_item_id}")
        if work_item.current_state is not expected_state:
            raise DecisionPreconditionError(
                f"this decision requires {expected_state.value} "
                f"(current: {work_item.current_state.value})"
            )
        report = self._qa.get_active_report(work_item_id)
        active_draft = self._drafts.get_active_draft(work_item_id)
        active_review = self._reviews.get_active_review(work_item_id)
        if report is None or active_draft is None or active_review is None:
            raise DecisionPreconditionError(
                "the work item has no complete ACTIVE package "
                "(QA report + draft + editor review) to decide on"
            )
        if report.content_draft_id != active_draft.id:
            raise DecisionPreconditionError(
                "the ACTIVE QA report does not cover the ACTIVE draft; re-run QA first"
            )
        return DecisionPackage(
            work_item_id=work_item_id,
            report=report,
            content_draft_id=active_draft.id,
            editorial_review_id=active_review.id,
            content_hash=active_draft.content_hash,
        )

    # --- decisions ------------------------------------------------------------

    def record_approval(
        self,
        work_item_id: uuid.UUID,
        *,
        reviewer: User,
        reason: str,
        request_id: str | None = None,
    ) -> HumanDecision:
        package = self.resolve_package(
            work_item_id, expected_state=WorkflowState.AWAITING_HUMAN_REVIEW
        )
        if package.report.outcome is not QaOutcome.READY_FOR_HUMAN_REVIEW:
            raise DecisionPreconditionError(
                "approval requires the ACTIVE QA report outcome to be "
                f"'ready_for_human_review' (current: {package.report.outcome.value})"
            )
        entry = self._workflow.get_latest_entry_event(
            work_item_id, WorkflowState.AWAITING_HUMAN_REVIEW
        )
        pinned_hash = (entry.artifact_refs or {}).get("content_hash") if entry else None
        if pinned_hash != package.content_hash:
            raise DecisionPreconditionError(
                "the package changed since it entered human review "
                "(content hash mismatch); re-run QA before approving"
            )
        return self._record(package, DecisionKind.APPROVED, reviewer, reason, request_id, None)

    def record_changes_requested(
        self,
        work_item_id: uuid.UUID,
        *,
        reviewer: User,
        reason: str,
        request_id: str | None = None,
    ) -> HumanDecision:
        package = self.resolve_package(
            work_item_id, expected_state=WorkflowState.AWAITING_HUMAN_REVIEW
        )
        return self._record(
            package, DecisionKind.CHANGES_REQUESTED, reviewer, reason, request_id, None
        )

    def record_rejection(
        self,
        work_item_id: uuid.UUID,
        *,
        reviewer: User,
        reason: str,
        request_id: str | None = None,
    ) -> HumanDecision:
        package = self.resolve_package(
            work_item_id, expected_state=WorkflowState.AWAITING_HUMAN_REVIEW
        )
        return self._record(package, DecisionKind.REJECTED, reviewer, reason, request_id, None)

    def record_approval_revocation(
        self,
        work_item_id: uuid.UUID,
        *,
        reviewer: User,
        reason: str,
        request_id: str | None = None,
    ) -> HumanDecision:
        package = self.resolve_package(work_item_id, expected_state=WorkflowState.APPROVED)
        approval = self._latest_unrevoked_approval(work_item_id)
        if approval is None:
            raise DecisionConflictError("no current approval exists to revoke")
        return self._record(
            package,
            DecisionKind.APPROVAL_REVOKED,
            reviewer,
            reason,
            request_id,
            approval.id,
        )

    # --- validity primitive ---------------------------------------------------

    def approval_status(self, work_item_id: uuid.UUID) -> ApprovalStatus:
        approval = self._latest_unrevoked_approval(work_item_id)
        active_draft = self._drafts.get_active_draft(work_item_id)
        active_hash = active_draft.content_hash if active_draft is not None else None
        if approval is None:
            return ApprovalStatus(
                approved=False,
                current=False,
                decision_id=None,
                approved_content_hash=None,
                active_content_hash=active_hash,
            )
        return ApprovalStatus(
            approved=True,
            current=approval.content_hash == active_hash,
            decision_id=approval.id,
            approved_content_hash=approval.content_hash,
            active_content_hash=active_hash,
        )

    def list_decisions(self, work_item_id: uuid.UUID) -> list[HumanDecision]:
        return list(
            self._session.execute(
                select(HumanDecision)
                .where(HumanDecision.work_item_id == work_item_id)
                .order_by(HumanDecision.created_at, HumanDecision.id)
            ).scalars()
        )

    # --- internals ------------------------------------------------------------

    def _latest_unrevoked_approval(self, work_item_id: uuid.UUID) -> HumanDecision | None:
        decisions = self.list_decisions(work_item_id)
        revoked_ids = {
            decision.revokes_decision_id
            for decision in decisions
            if decision.decision is DecisionKind.APPROVAL_REVOKED
        }
        approvals = [
            decision
            for decision in decisions
            if decision.decision is DecisionKind.APPROVED and decision.id not in revoked_ids
        ]
        return approvals[-1] if approvals else None

    def _record(
        self,
        package: DecisionPackage,
        kind: DecisionKind,
        reviewer: User,
        reason: str,
        request_id: str | None,
        revokes_decision_id: uuid.UUID | None,
    ) -> HumanDecision:
        # Defense in depth behind the API-layer role guard: a decision row
        # can never carry a non-reviewer (or inactive) identity.
        if not reviewer.is_active or not user_has_role(reviewer, UserRole.REVIEWER):
            raise DecisionPreconditionError(
                "decisions require an ACTIVE user holding the reviewer role"
            )
        decision = HumanDecision(
            work_item_id=package.work_item_id,
            reviewer_user_id=reviewer.id,
            decision=kind,
            reason=_required_reason(reason),
            qa_report_id=package.report.id,
            content_draft_id=package.content_draft_id,
            editorial_review_id=package.editorial_review_id,
            content_hash=package.content_hash,
            revokes_decision_id=revokes_decision_id,
            request_id=_validate_request_id(request_id),
        )
        self._session.add(decision)
        self._session.flush()
        return decision


def decision_artifact_refs(decision: HumanDecision) -> dict[str, Any]:
    """The exact pins every decision-gated transition carries."""
    return {
        "human_decision_id": str(decision.id),
        "qa_report_id": str(decision.qa_report_id),
        "content_draft_id": str(decision.content_draft_id),
        "editorial_review_id": str(decision.editorial_review_id),
        "content_hash": decision.content_hash,
        "reviewer_user_id": str(decision.reviewer_user_id),
    }


def _validate_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not is_valid_request_id(value):
        raise DecisionInputError("request_id is not a valid correlation identifier")
    return value


def _required_reason(value: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned or len(cleaned) > MAX_REASON_LENGTH:
        raise DecisionInputError(f"reason must be 1..{MAX_REASON_LENGTH} characters")
    return cleaned
