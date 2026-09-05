"""Performance loop API (Measure -> Learn -> Improve).

GET  /internal/performance/overview?window=7|28|90
GET  /internal/performance/contents/{work_item_id}
GET  /internal/performance/refresh-opportunities?status=
POST /internal/performance/refresh-opportunities/{id}/approve   (named, reasoned)
POST /internal/performance/refresh-opportunities/{id}/dismiss   (named, reasoned)
GET  /internal/performance/strategy-suggestions?status=
POST /internal/performance/strategy-suggestions/{id}/accept     (named, reasoned)
POST /internal/performance/strategy-suggestions/{id}/ignore     (named, reasoned)
POST /internal/performance/sync                                  ("Şimdi senkronize et")

Nothing here publishes. Approving a refresh only moves the work item onto
the canonical rework route; the next step stays with a human/autopilot.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from contentos.api.read_models.performance import (
    ContentPerformanceDetailView,
    PerformanceOverviewView,
    RefreshOpportunityView,
    StrategySuggestionView,
    list_refresh_views,
    list_suggestion_views,
    load_content_detail,
    load_overview,
    refresh_view,
    suggestion_view,
)
from contentos.api.security import require_operator
from contentos.auth.models import User
from contentos.core.context import get_request_id, is_valid_request_id
from contentos.db.session import get_db_session
from contentos.performance.enums import RefreshStatus, SuggestionStatus
from contentos.performance.refresh import (
    RefreshActorRequiredError,
    RefreshNotFoundError,
    RefreshOpportunityService,
    RefreshStateError,
    RefreshWorkflowStateError,
)
from contentos.performance.service import PerformanceService
from contentos.performance.suggestions import (
    StrategySuggestionService,
    SuggestionActorRequiredError,
    SuggestionNotFoundError,
    SuggestionStateError,
)
from contentos.workflow.errors import InvalidWorkflowTransitionError

router = APIRouter(prefix="/internal/performance")


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class SyncResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["queued"]
    backfilled_published: int
    tasks: list[str]


def _request_id() -> str | None:
    candidate = get_request_id()
    return candidate if is_valid_request_id(candidate) else None


def _provider_states(request: Request, session: Session) -> dict[str, str | None]:
    """Provider states as the integration layer persists them; a missing or
    failing layer is honestly "unknown" (None), never "healthy"."""
    try:
        from contentos.integrations.registry import create_integration_registry

        registry = create_integration_registry(request.app.state.settings)
        return {status.name.value: status.state.value for status in registry.statuses(session)}
    except Exception:  # noqa: BLE001 - a status read must never break the overview
        return {}


@router.get("/overview", response_model=PerformanceOverviewView)
def performance_overview(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    _operator: Annotated[User, Depends(require_operator)],
    window: Annotated[int, Query()] = 28,
) -> PerformanceOverviewView:
    if window not in (7, 28, 90):
        raise HTTPException(status_code=422, detail="window must be 7, 28 or 90")
    settings = request.app.state.settings
    return load_overview(
        session,
        window_days=window,
        provider_states=_provider_states(request, session),
        schedule_enabled=bool(getattr(settings, "performance_schedule_enabled", False)),
    )


@router.get("/contents/{work_item_id}", response_model=ContentPerformanceDetailView)
def content_performance(
    work_item_id: uuid.UUID,
    session: Annotated[Session, Depends(get_db_session)],
    _operator: Annotated[User, Depends(require_operator)],
) -> ContentPerformanceDetailView:
    detail = load_content_detail(session, work_item_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="no published content for this work item")
    return detail


@router.get("/refresh-opportunities", response_model=list[RefreshOpportunityView])
def refresh_opportunities(
    session: Annotated[Session, Depends(get_db_session)],
    _operator: Annotated[User, Depends(require_operator)],
    status: RefreshStatus | None = None,
) -> list[RefreshOpportunityView]:
    return list_refresh_views(session, status)


@router.post("/refresh-opportunities/{refresh_id}/approve", response_model=RefreshOpportunityView)
def approve_refresh(
    refresh_id: uuid.UUID,
    body: DecisionRequest,
    session: Annotated[Session, Depends(get_db_session)],
    operator: Annotated[User, Depends(require_operator)],
) -> RefreshOpportunityView:
    """Named approval: the work item enters the canonical rework route
    (MEASURING -> REFRESH_CANDIDATE). Nothing is published."""
    service = RefreshOpportunityService(session)
    try:
        row = service.approve(
            refresh_id, user=operator, reason=body.reason, request_id=_request_id()
        )
    except RefreshNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except RefreshActorRequiredError as error:
        raise HTTPException(status_code=403, detail=str(error)) from None
    except (RefreshStateError, RefreshWorkflowStateError, InvalidWorkflowTransitionError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    return refresh_view(row, session)


@router.post("/refresh-opportunities/{refresh_id}/dismiss", response_model=RefreshOpportunityView)
def dismiss_refresh(
    refresh_id: uuid.UUID,
    body: DecisionRequest,
    session: Annotated[Session, Depends(get_db_session)],
    operator: Annotated[User, Depends(require_operator)],
) -> RefreshOpportunityView:
    service = RefreshOpportunityService(session)
    try:
        row = service.dismiss(
            refresh_id, user=operator, reason=body.reason, request_id=_request_id()
        )
    except RefreshNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except RefreshActorRequiredError as error:
        raise HTTPException(status_code=403, detail=str(error)) from None
    except RefreshStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    return refresh_view(row, session)


@router.get("/strategy-suggestions", response_model=list[StrategySuggestionView])
def strategy_suggestions(
    session: Annotated[Session, Depends(get_db_session)],
    _operator: Annotated[User, Depends(require_operator)],
    status: SuggestionStatus | None = None,
) -> list[StrategySuggestionView]:
    return list_suggestion_views(session, status)


@router.post("/strategy-suggestions/{suggestion_id}/accept", response_model=StrategySuggestionView)
def accept_suggestion(
    suggestion_id: uuid.UUID,
    body: DecisionRequest,
    session: Annotated[Session, Depends(get_db_session)],
    operator: Annotated[User, Depends(require_operator)],
) -> StrategySuggestionView:
    service = StrategySuggestionService(session)
    try:
        row = service.accept(suggestion_id, user=operator, reason=body.reason)
    except SuggestionNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except SuggestionActorRequiredError as error:
        raise HTTPException(status_code=403, detail=str(error)) from None
    except (SuggestionStateError, ValueError, LookupError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    return suggestion_view(row, session)


@router.post("/strategy-suggestions/{suggestion_id}/ignore", response_model=StrategySuggestionView)
def ignore_suggestion(
    suggestion_id: uuid.UUID,
    body: DecisionRequest,
    session: Annotated[Session, Depends(get_db_session)],
    operator: Annotated[User, Depends(require_operator)],
) -> StrategySuggestionView:
    service = StrategySuggestionService(session)
    try:
        row = service.ignore(suggestion_id, user=operator, reason=body.reason)
    except SuggestionNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except SuggestionActorRequiredError as error:
        raise HTTPException(status_code=403, detail=str(error)) from None
    except SuggestionStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    return suggestion_view(row, session)


@router.post("/sync", response_model=SyncResponse)
def sync_now(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    _operator: Annotated[User, Depends(require_operator)],
) -> SyncResponse:
    """ "Şimdi senkronize et": register any successful publication that is
    not yet measured (DB-only, synchronous), then enqueue the whole
    performance chain (provider syncs -> assess -> detect -> aggregate ->
    suggest) through the producer seam."""
    backfilled = PerformanceService.backfill_published(session)
    session.commit()
    dispatcher = request.app.state.editorial_control_dispatcher
    try:
        tasks = dispatcher.enqueue_performance_sync(request_id=_request_id())
    except Exception as error:  # noqa: BLE001 - broker failures are bounded 503s
        raise HTTPException(
            status_code=503,
            detail=f"performance sync could not be queued ({type(error).__name__})",
        ) from None
    return SyncResponse(status="queued", backfilled_published=backfilled, tasks=list(tasks))
