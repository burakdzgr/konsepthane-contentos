"""Reviewer decision commands at the Phase 4 terminal (Phase 5 G3).

These are the ONLY routes guarded by the REVIEWER role (the pipeline
routers require the operator role). Each command follows the artifact-gate
pattern: durable append-only HumanDecision record -> commit ->
WorkflowService transition with the decision pinned and the named actor
recorded -> commit. There is deliberately NO route that sets state
directly, and none of these can be reached without an authenticated
ACTIVE reviewer session (ADR 0004: AI or worker identity can never
approve)."""

import uuid
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from contentos.api.security import require_reviewer
from contentos.auth.models import User
from contentos.core.context import get_request_id, is_valid_request_id
from contentos.db.session import get_db_session
from contentos.decisions.enums import DecisionKind
from contentos.decisions.errors import (
    DecisionConflictError,
    DecisionInputError,
    DecisionPreconditionError,
)
from contentos.decisions.models import HumanDecision
from contentos.decisions.service import DecisionService, decision_artifact_refs
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.errors import (
    InvalidWorkflowInputError,
    InvalidWorkflowTransitionError,
)
from contentos.workflow.service import WorkflowService

router = APIRouter(prefix="/internal/editorial")

MAX_REASON_LENGTH = 1000

DecisionRecorder = Callable[[str | None], HumanDecision]


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)


class RoutedDecisionRequest(BaseModel):
    """Decisions that route the package back carry a BOUNDED choice."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
    responsible_state: Literal["drafting", "editing", "qa_review"] = "drafting"


class DecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["decided"]
    decision: DecisionKind
    human_decision_id: uuid.UUID
    work_item_id: uuid.UUID
    work_item_state: WorkflowState
    reviewer_username: str


def _current_request_id() -> str | None:
    candidate = get_request_id()
    return candidate if is_valid_request_id(candidate) else None


def _decide(
    session: Session,
    work_item_id: uuid.UUID,
    reviewer: User,
    *,
    record: "DecisionRecorder",
    to_state: WorkflowState,
    responsible_state: WorkflowState | None,
) -> DecisionResponse:
    request_id = _current_request_id()
    try:
        decision = record(request_id)
    except DecisionPreconditionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except DecisionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except DecisionInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    # The durable decision record is the artifact gate: commit it first.
    session.commit()
    try:
        item = WorkflowService(session).transition(
            work_item_id,
            to_state,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason=decision.reason,
            artifact_refs=decision_artifact_refs(decision),
            request_id=request_id,
            responsible_state=responsible_state,
            actor_user_id=reviewer.id,
        )
    except (InvalidWorkflowTransitionError, InvalidWorkflowInputError) as error:
        # The decision stays durable history; the transition conflict is
        # surfaced truthfully for the operator to resolve.
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    return DecisionResponse(
        status="decided",
        decision=decision.decision,
        human_decision_id=decision.id,
        work_item_id=item.id,
        work_item_state=item.current_state,
        reviewer_username=reviewer.username,
    )


@router.post("/work-items/{work_item_id}/approve", response_model=DecisionResponse)
def approve(
    session: Annotated[Session, Depends(get_db_session)],
    reviewer: Annotated[User, Depends(require_reviewer)],
    work_item_id: uuid.UUID,
    body: DecisionRequest,
) -> DecisionResponse:
    """The named human approval (ADR 0004): requires the ACTIVE ready QA
    report over the unchanged ACTIVE draft; pins the exact package."""
    service = DecisionService(session)
    return _decide(
        session,
        work_item_id,
        reviewer,
        record=lambda request_id: service.record_approval(
            work_item_id, reviewer=reviewer, reason=body.reason, request_id=request_id
        ),
        to_state=WorkflowState.APPROVED,
        responsible_state=None,
    )


@router.post("/work-items/{work_item_id}/request-changes", response_model=DecisionResponse)
def request_changes(
    session: Annotated[Session, Depends(get_db_session)],
    reviewer: Annotated[User, Depends(require_reviewer)],
    work_item_id: uuid.UUID,
    body: RoutedDecisionRequest,
) -> DecisionResponse:
    """Human rework decision from AWAITING_HUMAN_REVIEW, routed through the
    responsible-state foundation with a bounded choice."""
    service = DecisionService(session)
    return _decide(
        session,
        work_item_id,
        reviewer,
        record=lambda request_id: service.record_changes_requested(
            work_item_id, reviewer=reviewer, reason=body.reason, request_id=request_id
        ),
        to_state=WorkflowState.CHANGES_REQUESTED,
        responsible_state=WorkflowState(body.responsible_state),
    )


@router.post("/work-items/{work_item_id}/reject-package", response_model=DecisionResponse)
def reject_package(
    session: Annotated[Session, Depends(get_db_session)],
    reviewer: Annotated[User, Depends(require_reviewer)],
    work_item_id: uuid.UUID,
    body: DecisionRequest,
) -> DecisionResponse:
    """Human rejection of the reviewed package with a required reason."""
    service = DecisionService(session)
    return _decide(
        session,
        work_item_id,
        reviewer,
        record=lambda request_id: service.record_rejection(
            work_item_id, reviewer=reviewer, reason=body.reason, request_id=request_id
        ),
        to_state=WorkflowState.REJECTED,
        responsible_state=None,
    )


@router.post("/work-items/{work_item_id}/revoke-approval", response_model=DecisionResponse)
def revoke_approval(
    session: Annotated[Session, Depends(get_db_session)],
    reviewer: Annotated[User, Depends(require_reviewer)],
    work_item_id: uuid.UUID,
    body: RoutedDecisionRequest,
) -> DecisionResponse:
    """Revoke a standing approval (APPROVED -> CHANGES_REQUESTED). The
    approval record is never edited — the revocation references it."""
    service = DecisionService(session)
    return _decide(
        session,
        work_item_id,
        reviewer,
        record=lambda request_id: service.record_approval_revocation(
            work_item_id, reviewer=reviewer, reason=body.reason, request_id=request_id
        ),
        to_state=WorkflowState.CHANGES_REQUESTED,
        responsible_state=WorkflowState(body.responsible_state),
    )
