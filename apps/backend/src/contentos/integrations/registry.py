"""The registry: one place that knows every provider and its durable status.

`statuses(session)` never calls a vendor: it reads the persisted status
rows and computes `not_configured` / `access_required` live for providers
without credentials. `test(session, name)` performs the provider's ONE
cheap real call and persists the outcome. Worker tasks (scheduled
elsewhere) call `record_success` / `record_error` after their own calls.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar

import httpx
from sqlalchemy.orm import Session

from contentos.core.config import Settings
from contentos.integrations.base import IntegrationProvider, ProviderError, ProviderStatus
from contentos.integrations.budget import (
    BudgetedClient,
    DatabaseRequestBudget,
    MemoryRequestBudget,
    RequestBudget,
)
from contentos.integrations.cache import DatabaseResponseCache, MemoryResponseCache, ResponseCache
from contentos.integrations.enums import DISPLAY_NAMES, ProviderName, ProviderState
from contentos.integrations.google_analytics import GoogleAnalyticsProvider
from contentos.integrations.google_search_console import GoogleSearchConsoleProvider
from contentos.integrations.google_trends import GoogleTrendsProvider
from contentos.integrations.google_trends_bigquery import GoogleTrendsBigQueryProvider
from contentos.integrations.http import Clock, Sleep, utc_now
from contentos.integrations.models import IntegrationStatusRecord
from contentos.integrations.pinterest_trends import PinterestTrendsProvider
from contentos.integrations.semrush import SemrushProvider
from contentos.integrations.sessions import bind_session, make_session_scope
from contentos.integrations.support import FAILURE_DETAILS

SessionFactory = Callable[[], Session]
P = TypeVar("P", bound=IntegrationProvider)

UNVERIFIED_DETAIL = "Yapılandırıldı, henüz doğrulanmadı: Bağlantıyı Test Et."


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    requests_today: int
    daily_budget: int
    cache_hours: int


class UnknownProviderError(LookupError):
    pass


class IntegrationRegistry:
    def __init__(
        self,
        settings: Settings,
        session_factory: SessionFactory | None = None,
        *,
        http_client: httpx.Client | None = None,
        clock: Clock | None = None,
        sleep: Sleep | None = None,
        providers: list[IntegrationProvider] | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._clock: Clock = clock if clock is not None else utc_now
        cache: ResponseCache
        budget: RequestBudget
        if session_factory is not None:
            scope = make_session_scope(session_factory)
            cache = DatabaseResponseCache(scope)
            budget = DatabaseRequestBudget(scope)
        else:
            cache = MemoryResponseCache()
            budget = MemoryRequestBudget()
        if providers is None:

            def build(factory: Callable[..., P]) -> P:
                return factory(
                    settings,
                    http_client=http_client,
                    clock=self._clock,
                    sleep=sleep,
                    cache=cache,
                    budget=budget,
                )

            providers = [
                build(SemrushProvider),
                build(GoogleSearchConsoleProvider),
                build(GoogleAnalyticsProvider),
                build(GoogleTrendsProvider),
                build(GoogleTrendsBigQueryProvider),
                build(PinterestTrendsProvider),
            ]
        self._providers: dict[ProviderName, IntegrationProvider] = {
            provider.name: provider for provider in providers
        }

    def providers(self) -> list[IntegrationProvider]:
        return list(self._providers.values())

    def get(self, name: ProviderName | str) -> IntegrationProvider:
        try:
            key = ProviderName(name)
        except ValueError:
            raise UnknownProviderError(str(name)) from None
        provider = self._providers.get(key)
        if provider is None:
            raise UnknownProviderError(key.value)
        return provider

    def statuses(self, session: Session) -> list[ProviderStatus]:
        rows = {row.provider: row for row in session.query(IntegrationStatusRecord).all()}
        result: list[ProviderStatus] = []
        for provider in self._providers.values():
            row = rows.get(provider.name.value)
            last_success = row.last_success_at if row is not None else None
            if not provider.configured():
                # Live and cheap: an unconfigured provider never calls out.
                live = provider.test_connection()
                result.append(
                    ProviderStatus(
                        name=live.name,
                        state=live.state,
                        detail=live.detail,
                        checked_at=live.checked_at,
                        last_success_at=last_success,
                        last_error_class=None,
                    )
                )
                continue
            if row is None:
                result.append(
                    ProviderStatus(
                        name=provider.name,
                        state=ProviderState.DEGRADED,
                        detail=UNVERIFIED_DETAIL,
                        checked_at=self._clock(),
                        last_success_at=None,
                        last_error_class=None,
                    )
                )
                continue
            result.append(
                ProviderStatus(
                    name=provider.name,
                    state=row.state,
                    detail=row.detail,
                    checked_at=row.checked_at,
                    last_success_at=row.last_success_at,
                    last_error_class=row.last_error_class,
                )
            )
        return result

    def verified(self, session: Session, name: ProviderName) -> bool:
        return session.get(IntegrationStatusRecord, name.value) is not None

    def last_sync_at(self, session: Session, name: ProviderName) -> datetime | None:
        row = session.get(IntegrationStatusRecord, name.value)
        return row.last_sync_at if row is not None else None

    def usage(self, session: Session, name: ProviderName) -> ProviderUsage:
        provider = self.get(name)
        cost = _cost(provider)
        with bind_session(session):
            today = cost.requests_today() if cost is not None else 0
        return ProviderUsage(
            requests_today=today,
            daily_budget=cost.daily_budget if cost is not None else 0,
            cache_hours=int(cost.cache_ttl.total_seconds() // 3600) if cost is not None else 0,
        )

    def test(self, session: Session, name: ProviderName | str) -> ProviderStatus:
        """Run the provider's cheap real call and persist the outcome."""
        provider = self.get(name)
        with bind_session(session):
            status = provider.test_connection()
        if not provider.configured():
            return status
        self._upsert(session, status)
        return status

    def record_success(self, session: Session, name: ProviderName, *, synced: bool = True) -> None:
        now = self._clock()
        row = self._row(session, name)
        row.state = ProviderState.HEALTHY
        row.detail = "Son senkron başarılı."
        row.checked_at = now
        row.last_success_at = now
        row.last_error_class = None
        if synced:
            row.last_sync_at = now
        session.flush()

    def record_error(
        self,
        session: Session,
        name: ProviderName,
        error_class: str,
        *,
        kind: ProviderState = ProviderState.ERROR,
        detail: str | None = None,
    ) -> None:
        now = self._clock()
        row = self._row(session, name)
        row.state = kind
        row.detail = detail if detail is not None else FAILURE_DETAILS[kind]
        row.checked_at = now
        row.last_error_class = error_class[:64]
        session.flush()

    def record_provider_error(
        self, session: Session, name: ProviderName, error: ProviderError
    ) -> None:
        self.record_error(session, name, error.error_class, kind=error.kind)

    def _upsert(self, session: Session, status: ProviderStatus) -> None:
        row = self._row(session, status.name)
        row.state = status.state
        row.detail = status.detail
        row.checked_at = status.checked_at
        if status.state is ProviderState.HEALTHY:
            row.last_success_at = status.checked_at
            row.last_error_class = None
        else:
            row.last_error_class = status.last_error_class
        session.flush()

    def _row(self, session: Session, name: ProviderName) -> IntegrationStatusRecord:
        row = session.get(IntegrationStatusRecord, name.value)
        if row is None:
            row = IntegrationStatusRecord(
                provider=name.value,
                state=ProviderState.NOT_CONFIGURED,
                detail="",
                checked_at=self._clock(),
            )
            session.add(row)
        return row


def _cost(provider: IntegrationProvider) -> BudgetedClient | None:
    candidate = getattr(provider, "cost", None)
    return candidate if isinstance(candidate, BudgetedClient) else None


def display_name(name: ProviderName) -> str:
    return DISPLAY_NAMES[name]


def create_integration_registry(
    settings: Settings, session_factory: SessionFactory | None = None
) -> IntegrationRegistry:
    """Worker/API composition helper: durable cache + budget when a session
    factory is given; nothing touches the network at construction."""
    return IntegrationRegistry(settings, session_factory)
