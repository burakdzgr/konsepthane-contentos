"""Read-only projections for Phase-5 human decisions.

Decision EVENTS exactly as recorded, with reviewer identities resolved to
display names (credential and token material is unreachable by
construction — these views join `users` for names only), plus the derived
hash-bound approval status.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.api.read_models.editorial import _FrozenModel
from contentos.auth.models import User
from contentos.decisions.enums import DecisionKind
from contentos.decisions.models import HumanDecision
from contentos.decisions.service import DecisionService
from contentos.workflow.models import EditorialWorkItem

# Decisions are rare human events; the cap is generous and truthful.
MAX_DECISIONS_PER_WORK_ITEM = 100


class ReviewerView(_FrozenModel):
    id: uuid.UUID
    username: str
    display_name: str


class DecisionView(_FrozenModel):
    id: uuid.UUID
    decision: DecisionKind
    reviewer: ReviewerView
    reason: str
    qa_report_id: uuid.UUID
    content_draft_id: uuid.UUID
    editorial_review_id: uuid.UUID
    content_hash: str
    revokes_decision_id: uuid.UUID | None
    request_id: str | None
    created_at: datetime


class ApprovalStatusView(_FrozenModel):
    approved: bool
    # True only while the ACTIVE draft still carries the approved hash.
    current: bool
    decision_id: uuid.UUID | None
    approved_content_hash: str | None
    active_content_hash: str | None


class DecisionListPage(_FrozenModel):
    work_item_id: uuid.UUID
    decisions: list[DecisionView]
    total: int
    truncated: bool
    approval_status: ApprovalStatusView


def list_work_item_decisions(session: Session, work_item_id: uuid.UUID) -> DecisionListPage | None:
    if session.get(EditorialWorkItem, work_item_id) is None:
        return None
    service = DecisionService(session)
    decisions = service.list_decisions(work_item_id)
    reviewer_ids = {decision.reviewer_user_id for decision in decisions}
    reviewers: dict[uuid.UUID, User] = {}
    if reviewer_ids:
        for user in session.execute(select(User).where(User.id.in_(reviewer_ids))).scalars():
            reviewers[user.id] = user

    def _view(decision: HumanDecision) -> DecisionView:
        user = reviewers[decision.reviewer_user_id]
        return DecisionView(
            id=decision.id,
            decision=decision.decision,
            reviewer=ReviewerView(
                id=user.id, username=user.username, display_name=user.display_name
            ),
            reason=decision.reason,
            qa_report_id=decision.qa_report_id,
            content_draft_id=decision.content_draft_id,
            editorial_review_id=decision.editorial_review_id,
            content_hash=decision.content_hash,
            revokes_decision_id=decision.revokes_decision_id,
            request_id=decision.request_id,
            created_at=decision.created_at,
        )

    status = service.approval_status(work_item_id)
    return DecisionListPage(
        work_item_id=work_item_id,
        decisions=[_view(decision) for decision in decisions[:MAX_DECISIONS_PER_WORK_ITEM]],
        total=len(decisions),
        truncated=len(decisions) > MAX_DECISIONS_PER_WORK_ITEM,
        approval_status=ApprovalStatusView(
            approved=status.approved,
            current=status.current,
            decision_id=status.decision_id,
            approved_content_hash=status.approved_content_hash,
            active_content_hash=status.active_content_hash,
        ),
    )
