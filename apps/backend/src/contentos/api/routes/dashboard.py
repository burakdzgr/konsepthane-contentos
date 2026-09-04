"""Read-only operational dashboard projections and the audited pause controls.

Reads are bounded projections of durable rows (plus a broker LLEN for
the queue depth); the ONLY mutations are the intake pause/resume
commands — audited, idempotent, named-actor, and gating exclusively NEW
dispatch at the control surface. Nothing here can transition workflow
state, cancel a running task, or touch editorial content, so no
existing invariant gains a bypass.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from contentos.api.read_models.dashboard import (
    DEFAULT_ACTIVITY_LIMIT,
    MAX_ACTIVITY_LIMIT,
    ActivityPage,
    AgentsPage,
    ControlsPage,
    DashboardSummary,
    PublicationQueuePage,
    load_activity,
    load_agents,
    load_controls,
    load_publication_queue,
    load_summary,
    measure_queue_depth,
)
from contentos.core.context import get_request_id, is_valid_request_id
from contentos.db.session import get_db_session
from contentos.operations.enums import PauseScope
from contentos.operations.service import MAX_REASON_LENGTH, OperationsService

router = APIRouter(prefix="/internal/dashboard")


class PauseCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: PauseScope
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)


class PauseCommandResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["applied", "unchanged"]
    scope: PauseScope
    is_paused: bool


def _current_user_id(request: Request) -> uuid.UUID | None:
    user = getattr(request.state, "current_user", None)
    return user.id if user is not None else None


def _current_request_id() -> str | None:
    candidate = get_request_id()
    return candidate if is_valid_request_id(candidate) else None


@router.get("/summary", response_model=DashboardSummary)
def dashboard_summary(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
) -> DashboardSummary:
    settings = request.app.state.settings
    depth = measure_queue_depth(
        request.app.state.redis_client_factory, settings.celery_default_queue
    )
    return load_summary(
        session,
        daily_budget=settings.ai_daily_attempt_budget,
        queue_depth=depth,
        text_provider_configured=settings.openai_text_provider_configured,
        image_provider_configured=settings.openai_image_provider_configured,
    )


@router.get("/agents", response_model=AgentsPage)
def dashboard_agents(
    session: Annotated[Session, Depends(get_db_session)],
) -> AgentsPage:
    return load_agents(session)


@router.get("/activity", response_model=ActivityPage)
def dashboard_activity(
    session: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=MAX_ACTIVITY_LIMIT)] = DEFAULT_ACTIVITY_LIMIT,
) -> ActivityPage:
    return load_activity(session, limit=limit)


@router.get("/publications", response_model=PublicationQueuePage)
def dashboard_publications(
    session: Annotated[Session, Depends(get_db_session)],
) -> PublicationQueuePage:
    return load_publication_queue(session)


@router.get("/controls", response_model=ControlsPage)
def dashboard_controls(
    session: Annotated[Session, Depends(get_db_session)],
) -> ControlsPage:
    return load_controls(session)


@router.post("/controls/pause", response_model=PauseCommandResponse)
def pause_intake(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    body: PauseCommand,
) -> PauseCommandResponse:
    """Stop accepting NEW work for the scope (audited, idempotent).

    Running tasks always finish; nothing is cancelled or transitioned."""
    try:
        change = OperationsService(session).pause(
            body.scope,
            reason=body.reason,
            actor_user_id=_current_user_id(request),
            request_id=_current_request_id(),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return PauseCommandResponse(
        status="applied" if change.changed else "unchanged",
        scope=change.scope,
        is_paused=change.is_paused,
    )


@router.post("/controls/resume", response_model=PauseCommandResponse)
def resume_intake(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    body: PauseCommand,
) -> PauseCommandResponse:
    """Resume accepting new work for the scope (audited, idempotent)."""
    try:
        change = OperationsService(session).resume(
            body.scope,
            reason=body.reason,
            actor_user_id=_current_user_id(request),
            request_id=_current_request_id(),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return PauseCommandResponse(
        status="applied" if change.changed else "unchanged",
        scope=change.scope,
        is_paused=change.is_paused,
    )
