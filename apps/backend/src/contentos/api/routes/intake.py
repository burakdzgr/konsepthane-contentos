"""Intake-run control and observation endpoints (operator-guarded).

Starting a run creates the durable record and publishes exactly one
step job; the worker-side orchestrator owns everything after that.
Pause/resume/stop are audited run-lifecycle controls — no endpoint here
can transition editorial workflow state or bypass a domain service.
"""

import uuid
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from contentos.api.read_models.intake import (
    MAX_EVENT_ROWS,
    IntakeEventsPage,
    IntakeRunDetail,
    IntakeRunsPage,
    load_run_detail,
    load_run_events,
    load_runs,
)
from contentos.core.context import get_request_id, is_valid_request_id
from contentos.db.session import get_db_session
from contentos.intake.enums import IntakeRunStatus
from contentos.intake.errors import (
    IntakeRunConflictError,
    IntakeRunNotFoundError,
    IntakeRunStateError,
    IntakeSourceNotEligibleError,
)
from contentos.intake.service import IntakePolicy, IntakeRunService
from contentos.operations.enums import PauseScope
from contentos.operations.errors import IntakePausedError
from contentos.operations.service import OperationsService

_logger = structlog.get_logger("contentos.api.intake")

router = APIRouter(prefix="/internal/intake")

QUEUE_FAILURE_MESSAGE = "queueing the intake step failed; the run was not started"


class RunControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


class RunStartedResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["started"]
    run_id: uuid.UUID


class RunControlResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["updated"]
    run_id: uuid.UUID
    run_status: IntakeRunStatus


def _dispatcher(request: Request) -> Any:
    return request.app.state.intake_control_dispatcher


def _current_request_id() -> str | None:
    candidate = get_request_id()
    return candidate if is_valid_request_id(candidate) else None


def _current_user_id(request: Request) -> uuid.UUID | None:
    user = getattr(request.state, "current_user", None)
    return user.id if user is not None else None


@router.post("/sources/{source_id}/runs", response_model=RunStartedResponse)
def start_intake_run(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    source_id: uuid.UUID,
) -> RunStartedResponse:
    try:
        OperationsService(session).ensure_dispatch_allowed(PauseScope.RESEARCH)
    except IntakePausedError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    service = IntakeRunService(session)
    try:
        run = service.start_run(
            source_id,
            policy=IntakePolicy.from_settings(request.app.state.settings),
            actor_user_id=_current_user_id(request),
            request_id=_current_request_id(),
        )
    except IntakeSourceNotEligibleError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except IntakeRunConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    try:
        _dispatcher(request).enqueue_intake_step(str(run.id), request_id=_current_request_id())
    except Exception as error:
        # The run row exists but nothing is processing it: surface an
        # honest 503; resume re-publishes the step.
        _logger.warning(
            "intake_step_enqueue_failed",
            run_id=str(run.id),
            error_type=type(error).__name__,
        )
        raise HTTPException(status_code=503, detail=QUEUE_FAILURE_MESSAGE) from None
    return RunStartedResponse(status="started", run_id=run.id)


@router.get("/runs", response_model=IntakeRunsPage)
def list_intake_runs(
    session: Annotated[Session, Depends(get_db_session)],
    source_id: uuid.UUID | None = None,
) -> IntakeRunsPage:
    return load_runs(session, source_id=source_id)


@router.get("/runs/{run_id}", response_model=IntakeRunDetail)
def get_intake_run(
    session: Annotated[Session, Depends(get_db_session)],
    run_id: uuid.UUID,
) -> IntakeRunDetail:
    detail = load_run_detail(session, run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"no intake run with id {run_id}")
    return detail


@router.get("/runs/{run_id}/events", response_model=IntakeEventsPage)
def get_intake_run_events(
    session: Annotated[Session, Depends(get_db_session)],
    run_id: uuid.UUID,
    after_id: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_EVENT_ROWS)] = 80,
) -> IntakeEventsPage:
    try:
        IntakeRunService(session).require_run(run_id)
    except IntakeRunNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    return load_run_events(session, run_id, after_id=after_id, limit=limit)


def _control(
    request: Request,
    session: Session,
    run_id: uuid.UUID,
    body: RunControlRequest,
    action: Literal["pause", "resume", "stop"],
) -> RunControlResponse:
    service = IntakeRunService(session)
    actor = _current_user_id(request)
    try:
        if action == "pause":
            run = service.pause_run(run_id, reason=body.reason, actor_user_id=actor)
        elif action == "resume":
            run = service.resume_run(run_id, reason=body.reason, actor_user_id=actor)
        else:
            run = service.stop_run(run_id, reason=body.reason, actor_user_id=actor)
    except IntakeRunNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except IntakeRunStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    if action == "resume":
        try:
            _dispatcher(request).enqueue_intake_step(str(run.id), request_id=_current_request_id())
        except Exception as error:
            _logger.warning(
                "intake_step_enqueue_failed",
                run_id=str(run.id),
                error_type=type(error).__name__,
            )
            raise HTTPException(status_code=503, detail=QUEUE_FAILURE_MESSAGE) from None
    return RunControlResponse(status="updated", run_id=run.id, run_status=run.status)


@router.post("/runs/{run_id}/pause", response_model=RunControlResponse)
def pause_intake_run(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    run_id: uuid.UUID,
    body: RunControlRequest,
) -> RunControlResponse:
    return _control(request, session, run_id, body, "pause")


@router.post("/runs/{run_id}/resume", response_model=RunControlResponse)
def resume_intake_run(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    run_id: uuid.UUID,
    body: RunControlRequest,
) -> RunControlResponse:
    return _control(request, session, run_id, body, "resume")


@router.post("/runs/{run_id}/stop", response_model=RunControlResponse)
def stop_intake_run(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    run_id: uuid.UUID,
    body: RunControlRequest,
) -> RunControlResponse:
    return _control(request, session, run_id, body, "stop")
