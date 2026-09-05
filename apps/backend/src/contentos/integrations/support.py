"""Shared provider plumbing: HTTP + cost client construction, status helpers."""

from datetime import datetime, timedelta

import httpx

from contentos.core.config import Settings
from contentos.integrations.base import ProviderError, ProviderStatus
from contentos.integrations.budget import BudgetedClient, MemoryRequestBudget, RequestBudget
from contentos.integrations.cache import MemoryResponseCache, ResponseCache
from contentos.integrations.enums import DISPLAY_NAMES, REQUIRED_ENV, ProviderName, ProviderState
from contentos.integrations.http import Clock, ProviderHttp, Sleep, utc_now

# Operator-facing Turkish detail per failure kind (the bounded error class
# travels separately; vendor text never reaches the operator verbatim).
FAILURE_DETAILS: dict[ProviderState, str] = {
    ProviderState.ACCESS_REQUIRED: "API erişimi reddedildi: anahtar/yetki geçersiz veya eksik.",
    ProviderState.RATE_LIMITED: "Kota sınırına ulaşıldı; istekler geçici olarak durduruldu.",
    ProviderState.DEGRADED: "Sağlayıcı yanıt vermedi (zaman aşımı ya da sunucu hatası).",
    ProviderState.ERROR: "Beklenmedik sağlayıcı hatası.",
    ProviderState.NOT_CONFIGURED: "Yapılandırılmadı.",
    ProviderState.HEALTHY: "Bağlantı doğrulandı.",
}

# Test-connection calls must answer inside the admin's request window.
TEST_TIMEOUT_SECONDS = 4.0


def not_configured_detail(name: ProviderName) -> str:
    variables = " ve ".join(REQUIRED_ENV[name])
    return f"Yapılandırılmadı: {variables} tanımlayın ve servisleri yeniden başlatın."


class ProviderSupport:
    """Composition base every adapter builds on (not a provider itself)."""

    name: ProviderName

    def __init__(
        self,
        name: ProviderName,
        settings: Settings,
        *,
        daily_budget: int,
        cache_hours: int,
        http_client: httpx.Client | None = None,
        clock: Clock | None = None,
        sleep: Sleep | None = None,
        cache: ResponseCache | None = None,
        budget: RequestBudget | None = None,
    ) -> None:
        self.name = name
        self.display_name = DISPLAY_NAMES[name]
        self._settings = settings
        self._clock: Clock = clock if clock is not None else utc_now
        self._http = ProviderHttp(
            name.value,
            client=http_client,
            timeout_seconds=settings.integrations_http_timeout_seconds,
            sleep=sleep,
            clock=self._clock,
            user_agent=settings.fetch_user_agent,
        )
        self.cost = BudgetedClient(
            name,
            daily_budget=daily_budget,
            cache_ttl=timedelta(hours=cache_hours),
            cache=cache if cache is not None else MemoryResponseCache(),
            budget=budget if budget is not None else MemoryRequestBudget(),
            clock=self._clock,
        )

    def now(self) -> datetime:
        return self._clock()

    def status(
        self,
        state: ProviderState,
        detail: str,
        *,
        error_class: str | None = None,
        last_success_at: datetime | None = None,
    ) -> ProviderStatus:
        now = self._clock()
        return ProviderStatus(
            name=self.name,
            state=state,
            detail=detail,
            checked_at=now,
            last_success_at=now if state is ProviderState.HEALTHY else last_success_at,
            last_error_class=error_class,
        )

    def status_from_error(self, error: ProviderError, detail: str | None = None) -> ProviderStatus:
        return self.status(
            error.kind,
            detail if detail is not None else FAILURE_DETAILS[error.kind],
            error_class=error.error_class,
        )

    def not_configured_status(self) -> ProviderStatus:
        return self.status(ProviderState.NOT_CONFIGURED, not_configured_detail(self.name))
