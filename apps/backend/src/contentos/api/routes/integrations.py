"""External intelligence providers: status board and connection tests.

GET  /internal/integrations              -> every provider's honest state,
                                            usage against its daily budget,
                                            freshness (last sync)
POST /internal/integrations/{name}/test  -> ONE cheap real call, persisted

Responses never carry secrets: only states, Turkish detail sentences,
bounded error classes and the NAMES of the environment variables to set.
"""

from datetime import datetime
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
