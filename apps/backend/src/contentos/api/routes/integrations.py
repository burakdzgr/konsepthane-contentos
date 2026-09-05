"""External intelligence providers: status board and connection tests.

GET  /internal/integrations              -> every provider's honest state,
                                            usage against its daily budget,
                                            freshness (last sync)
POST /internal/integrations/{name}/test  -> ONE cheap real call, persisted

Responses never carry secrets: only states, Turkish detail sentences,
bounded error classes and the NAMES of the environment variables to set.
"""

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from contentos.api.security import require_operator
from contentos.auth.models import User
from contentos.db.session import get_db_session
from contentos.integrations.base import ProviderStatus
from contentos.integrations.enums import (
    DISPLAY_NAMES,
    OPTIONAL_ENV,
    PURPOSES,
    REQUIRED_ENV,
    ProviderName,
    ProviderState,
)
from contentos.integrations.http import utc_now
from contentos.integrations.registry import IntegrationRegistry, UnknownProviderError
from contentos.intelligence.trend_discovery import (
    DiscoverySnapshot,
    TrendTermSummary,
    discovery_snapshot,
)

router = APIRouter(prefix="/internal/integrations")


class IntegrationView(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: ProviderName
    display_name: str
    purpose: str
    configured: bool
    verified: bool
    state: ProviderState
    detail: str
    checked_at: datetime
    last_success_at: datetime | None
    last_error_class: str | None
    freshness: datetime | None
    daily_budget: int
    requests_today: int
    cache_hours: int
    required_env: list[str]
    optional_env: list[str]


class IntegrationsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    generated_at: datetime
    providers: list[IntegrationView]


def get_integration_registry(request: Request) -> IntegrationRegistry:
    """Lazily composed per app; tests replace it on app.state."""
    existing = getattr(request.app.state, "integration_registry", None)
    if isinstance(existing, IntegrationRegistry):
        return existing
    registry = IntegrationRegistry(request.app.state.settings, request.app.state.db_session_factory)
    request.app.state.integration_registry = registry
    return registry


def _view(
    session: Session, registry: IntegrationRegistry, status: ProviderStatus
) -> IntegrationView:
    provider = registry.get(status.name)
    usage = registry.usage(session, status.name)
    return IntegrationView(
        name=status.name,
        display_name=DISPLAY_NAMES[status.name],
        purpose=PURPOSES[status.name],
        configured=provider.configured(),
        verified=registry.verified(session, status.name),
        state=status.state,
        detail=status.detail,
        checked_at=status.checked_at,
        last_success_at=status.last_success_at,
        last_error_class=status.last_error_class,
        freshness=registry.last_sync_at(session, status.name),
        daily_budget=usage.daily_budget,
        requests_today=usage.requests_today,
        cache_hours=usage.cache_hours,
        required_env=list(REQUIRED_ENV[status.name]),
        optional_env=list(OPTIONAL_ENV[status.name]),
    )


@router.get("", response_model=IntegrationsResponse)
def list_integrations(
    session: Annotated[Session, Depends(get_db_session)],
    registry: Annotated[IntegrationRegistry, Depends(get_integration_registry)],
    _operator: Annotated[User, Depends(require_operator)],
) -> IntegrationsResponse:
    statuses = registry.statuses(session)
    return IntegrationsResponse(
        generated_at=utc_now(),
        providers=[_view(session, registry, status) for status in statuses],
    )


@router.post("/{name}/test", response_model=IntegrationView)
def test_integration(
    name: str,
    session: Annotated[Session, Depends(get_db_session)],
    registry: Annotated[IntegrationRegistry, Depends(get_integration_registry)],
    _operator: Annotated[User, Depends(require_operator)],
) -> IntegrationView:
    try:
        status = registry.test(session, name)
    except UnknownProviderError:
        raise HTTPException(status_code=404, detail="unknown integration provider") from None
    session.commit()
    return _view(session, registry, status)


# --- Google Trends public dataset discovery (BigQuery) ----------------------------
#
# GET  /internal/integrations/google_trends_bigquery/discovery -> the latest
#      synced Türkiye top / rising sets and which terms ContentOS deems
#      relevant (DB-only; never calls BigQuery)
# POST /internal/integrations/google_trends_bigquery/sync      -> enqueue the
#      daily sync now through the producer seam ("Şimdi senkronize et")


class TrendTermView(BaseModel):
    model_config = ConfigDict(frozen=True)

    term: str
    trend_type: str
    rank: int | None
    percent_gain: float | None
    latest_score: float | None
    region_count: int | None
    refresh_date: date
    matched: bool
    match_kind: str | None
    strategy_keywords: list[str]
    domain_terms: list[str]
    first_refresh_date: date | None
    occurrence_count: int | None


class TrendDiscoveryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: ProviderName
    country: str
    synced: bool
    refresh_date: date | None
    last_sync_at: datetime | None
    total_terms: int
    matched_count: int
    unique_terms_ever: int
    top: list[TrendTermView]
    rising: list[TrendTermView]
    matched: list[TrendTermView]
    generated_at: datetime


class TrendSyncResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    tasks: list[str]


def _term_view(item: TrendTermSummary) -> TrendTermView:
    return TrendTermView(
        term=item.term,
        trend_type=item.trend_type,
        rank=item.rank,
        percent_gain=item.percent_gain,
        latest_score=item.latest_score,
        region_count=item.region_count,
        refresh_date=item.refresh_date,
        matched=item.matched,
        match_kind=item.match_kind,
        strategy_keywords=list(item.strategy_keywords),
        domain_terms=list(item.domain_terms),
        first_refresh_date=item.first_refresh_date,
        occurrence_count=item.occurrence_count,
    )


def _discovery_response(
    snapshot: DiscoverySnapshot, last_sync_at: datetime | None
) -> TrendDiscoveryResponse:
    return TrendDiscoveryResponse(
        provider=ProviderName.GOOGLE_TRENDS_BIGQUERY,
        country=snapshot.country,
        synced=snapshot.synced,
        refresh_date=snapshot.refresh_date,
        last_sync_at=last_sync_at,
        total_terms=snapshot.total_terms,
        matched_count=len(snapshot.matched),
        unique_terms_ever=snapshot.unique_terms_ever,
        top=[_term_view(item) for item in snapshot.top],
        rising=[_term_view(item) for item in snapshot.rising],
        matched=[_term_view(item) for item in snapshot.matched],
        generated_at=utc_now(),
    )


@router.get("/google_trends_bigquery/discovery", response_model=TrendDiscoveryResponse)
def trend_discovery(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    registry: Annotated[IntegrationRegistry, Depends(get_integration_registry)],
    _operator: Annotated[User, Depends(require_operator)],
) -> TrendDiscoveryResponse:
    country = str(getattr(request.app.state.settings, "google_trends_bigquery_country", "TR"))
    snapshot = discovery_snapshot(session, country=country)
    return _discovery_response(
        snapshot, registry.last_sync_at(session, ProviderName.GOOGLE_TRENDS_BIGQUERY)
    )


@router.post("/google_trends_bigquery/sync", response_model=TrendSyncResponse)
def trend_discovery_sync(
    request: Request,
    _operator: Annotated[User, Depends(require_operator)],
) -> TrendSyncResponse:
    dispatcher = request.app.state.editorial_control_dispatcher
    request_id = request.headers.get("X-Request-ID") or f"trend-{uuid.uuid4()}"
    try:
        tasks = dispatcher.enqueue_trend_discovery_sync(request_id=request_id)
    except Exception as error:  # noqa: BLE001 - broker failures are bounded 503s
        raise HTTPException(
            status_code=503,
            detail=f"trend discovery sync could not be queued ({type(error).__name__})",
        ) from None
    return TrendSyncResponse(status="queued", tasks=list(tasks))
