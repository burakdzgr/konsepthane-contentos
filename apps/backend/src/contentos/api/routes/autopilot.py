"""Autopilot mode and trail (ADR 0012).

GET  /internal/autopilot            -> current mode, accountable operator,
                                       recent trail
PUT  /internal/autopilot/mode       -> named operator switches the mode
                                       (reason required); switching ON arms
                                       the worker sweep
POST /internal/autopilot/sweep      -> re-arm the sweep explicitly
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from contentos.api.security import require_operator
from contentos.auth.models import User
from contentos.autopilot.enums import AutopilotEventKind, AutopilotMode
from contentos.autopilot.service import (
    AutopilotService,
    InvalidAutopilotInputError,
)
from contentos.core.context import get_request_id, is_valid_request_id
from contentos.db.session import get_db_session

router = APIRouter(prefix="/internal/autopilot")

MAX_EVENTS = 100


class AutopilotEventView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    work_item_id: uuid.UUID | None
    kind: AutopilotEventKind
    action: str | None
    mode: AutopilotMode
    detail: dict[str, Any]
    created_at: datetime


class AutopilotStateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: AutopilotMode
    actor_user_id: uuid.UUID | None
    actor_display_name: str | None
    reason: str | None
    updated_at: datetime | None
    events: list[AutopilotEventView]


class SetModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: AutopilotMode
    reason: str = Field(min_length=1, max_length=1000)


class SweepResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["armed", "off"]
    mode: AutopilotMode


def _request_id() -> str | None:
    candidate = get_request_id()
    return candidate if is_valid_request_id(candidate) else None


def _view(session: Session, limit: int) -> AutopilotStateResponse:
    service = AutopilotService(session)
    state = service.state()
    actor = session.get(User, state.actor_user_id) if state.actor_user_id else None
    return AutopilotStateResponse(
        mode=state.mode,
        actor_user_id=state.actor_user_id,
        actor_display_name=actor.display_name if actor is not None else None,
        reason=state.reason,
        updated_at=state.updated_at,
        events=[
            AutopilotEventView(
                id=event.id,
                work_item_id=event.work_item_id,
                kind=event.kind,
                action=event.action,
                mode=event.mode,
                detail=dict(event.detail),
                created_at=event.created_at,
            )
            for event in service.recent_events(limit)
        ],
    )


@router.get("", response_model=AutopilotStateResponse)
def autopilot_state(
    session: Annotated[Session, Depends(get_db_session)],
    _operator: Annotated[User, Depends(require_operator)],
    limit: int = 50,
) -> AutopilotStateResponse:
    return _view(session, max(1, min(limit, MAX_EVENTS)))


@router.put("/mode", response_model=AutopilotStateResponse)
def set_autopilot_mode(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    operator: Annotated[User, Depends(require_operator)],
    body: SetModeRequest,
) -> AutopilotStateResponse:
    """A NAMED decision: the operator becomes accountable for every
    acceptance the autopilot makes while the mode is on."""
    try:
        AutopilotService(session).set_mode(
            body.mode, actor_user_id=operator.id, reason=body.reason, request_id=_request_id()
        )
    except InvalidAutopilotInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    if body.mode is not AutopilotMode.OFF:
        _arm(request)
    return _view(session, 50)


@router.post("/sweep", response_model=SweepResponse)
def arm_autopilot_sweep(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    _operator: Annotated[User, Depends(require_operator)],
) -> SweepResponse:
    mode = AutopilotService(session).mode()
    if mode is AutopilotMode.OFF:
        return SweepResponse(status="off", mode=mode)
    _arm(request)
    return SweepResponse(status="armed", mode=mode)


def _arm(request: Request) -> None:
    dispatcher = request.app.state.editorial_control_dispatcher
    try:
        dispatcher.enqueue_autopilot_sweep(request_id=_request_id())
    except Exception as error:  # noqa: BLE001 - the mode is durable; arming is best effort
        raise HTTPException(
            status_code=503,
            detail=f"autopilot mode saved but the sweep could not be queued ({type(error).__name__})",
        ) from None
