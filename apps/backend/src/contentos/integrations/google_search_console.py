"""Google Search Console adapter (OUR real search performance).

Search Analytics API: `POST https://searchconsole.googleapis.com/webmasters
/v3/sites/{siteUrl}/searchAnalytics/query` with a service-account access
token. `test_connection` reads the site entry (one cheap call) which also
proves the account was granted access to the property.
"""

from datetime import date
from typing import Any
from urllib.parse import quote

import httpx

from contentos.core.config import Settings
from contentos.integrations.base import ProviderError, ProviderStatus, sanitize_error_class
from contentos.integrations.budget import RequestBudget
from contentos.integrations.cache import JsonPayload, ResponseCache
from contentos.integrations.dto import SearchAnalyticsRow
from contentos.integrations.enums import ProviderName, ProviderState
from contentos.integrations.google_auth import (
    ServiceAccountTokenSource,
    load_service_account,
)
from contentos.integrations.http import Clock, Sleep
from contentos.integrations.support import TEST_TIMEOUT_SECONDS, ProviderSupport

BASE_URL = "https://searchconsole.googleapis.com/webmasters/v3"
SCOPES = ("https://www.googleapis.com/auth/webmasters.readonly",)
ALLOWED_DIMENSIONS = ("date", "query", "page", "country", "device")
MAX_ROW_LIMIT = 25_000


class GoogleSearchConsoleProvider(ProviderSupport):
    name = ProviderName.GOOGLE_SEARCH_CONSOLE

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.Client | None = None,
        clock: Clock | None = None,
        sleep: Sleep | None = None,
        cache: ResponseCache | None = None,
        budget: RequestBudget | None = None,
    ) -> None:
        super().__init__(
            ProviderName.GOOGLE_SEARCH_CONSOLE,
            settings,
            daily_budget=settings.gsc_daily_budget,
            cache_hours=settings.gsc_cache_hours,
            http_client=http_client,
            clock=clock,
            sleep=sleep,
            cache=cache,
            budget=budget,
        )
        self._site_url = settings.gsc_site_url
        self._tokens: ServiceAccountTokenSource | None = None

    def configured(self) -> bool:
        return self._settings.google_service_account_json is not None and self._site_url is not None

    def test_connection(self) -> ProviderStatus:
        if not self.configured():
            return self.not_configured_status()
        try:
            body = self.cost.uncached(
                lambda: self._http.json(
                    self._http.request(
                        "GET",
                        f"{BASE_URL}/sites/{self._encoded_site()}",
                        headers=self._headers(),
                        timeout_seconds=TEST_TIMEOUT_SECONDS,
                    )
                )
            )
        except ProviderError as error:
            if error.error_class.endswith("_http_404"):
                return self.status(
                    ProviderState.ACCESS_REQUIRED,
                    "Servis hesabı bu Search Console mülkünü göremiyor: mülke "
                    "kullanıcı olarak ekleyin (Tam veya Kısıtlı yetki).",
                    error_class=error.error_class,
                )
            if error.kind is ProviderState.ACCESS_REQUIRED:
                return self.status_from_error(
                    error,
                    "Search Console erişimi reddedildi: servis hesabını mülke ekleyin "
                    "ve anahtar dosyasını kontrol edin.",
                )
            return self.status_from_error(error)
        level = body.get("permissionLevel") if isinstance(body, dict) else None
        if not isinstance(level, str):
            return self.status(
                ProviderState.ERROR,
                "Search Console beklenmedik bir yanıt döndürdü.",
                error_class=sanitize_error_class("google_search_console", "malformed_body"),
            )
        if level.lower().endswith("unverifieduser"):
            return self.status(
                ProviderState.ACCESS_REQUIRED,
                "Servis hesabı mülkte doğrulanmamış kullanıcı: yetki verin.",
                error_class=sanitize_error_class("google_search_console", "unverified"),
            )
        return self.status(ProviderState.HEALTHY, f"Bağlı. Mülk yetkisi: {level}.")

    def search_analytics(
        self,
        start: date,
        end: date,
        dimensions: list[str],
        page_filter: str | None = None,
        row_limit: int = 1000,
    ) -> list[SearchAnalyticsRow]:
        dims = [dim for dim in dimensions if dim in ALLOWED_DIMENSIONS]
        bounded = max(1, min(row_limit, MAX_ROW_LIMIT))
        body: dict[str, Any] = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": dims,
            "rowLimit": bounded,
        }
        if page_filter:
            body["dimensionFilterGroups"] = [
                {
                    "filters": [
                        {"dimension": "page", "operator": "equals", "expression": page_filter}
                    ]
                }
            ]
        payload = self.cost.cached(
            ("search_analytics", self._site_url, body),
            lambda: self._query(body),
        )
        rows = payload.get("rows")
        if not isinstance(rows, list):
            return []
        result: list[SearchAnalyticsRow] = []
        for row in rows:
            parsed = _row(row, dims)
            if parsed is not None:
                result.append(parsed)
        return result

    def _query(self, body: dict[str, Any]) -> JsonPayload:
        response = self._http.request(
            "POST",
            f"{BASE_URL}/sites/{self._encoded_site()}/searchAnalytics/query",
            headers=self._headers(),
            json_body=body,
        )
        decoded = self._http.json(response)
        if not isinstance(decoded, dict):
            raise ProviderError(
                "search console returned a non-object body",
                kind=ProviderState.ERROR,
                error_class=sanitize_error_class("google_search_console", "malformed_body"),
            )
        return {"rows": decoded.get("rows") or []}

    def _encoded_site(self) -> str:
        return quote(self._site_url or "", safe="")

    def _headers(self) -> dict[str, str]:
        if self._tokens is None:
            info = load_service_account(self._settings.google_service_account_json)
            self._tokens = ServiceAccountTokenSource(
                info, SCOPES, http=self._http, clock=self._clock
            )
        return {"Authorization": f"Bearer {self._tokens.access_token()}"}


def _row(raw: Any, dims: list[str]) -> SearchAnalyticsRow | None:
    if not isinstance(raw, dict):
        return None
    keys = raw.get("keys")
    values: dict[str, str] = {}
    if isinstance(keys, list):
        for dim, key in zip(dims, keys, strict=False):
            if isinstance(key, str):
                values[dim] = key
    parsed_date: date | None = None
    if "date" in values:
        try:
            parsed_date = date.fromisoformat(values["date"])
        except ValueError:
            parsed_date = None
    try:
        clicks = int(raw.get("clicks") or 0)
        impressions = int(raw.get("impressions") or 0)
        ctr = float(raw.get("ctr") or 0.0)
        position = float(raw.get("position") or 0.0)
    except (TypeError, ValueError):
        return None
    return SearchAnalyticsRow(
        date=parsed_date,
        query=values.get("query"),
        page=values.get("page"),
        country=values.get("country"),
        device=values.get("device"),
        clicks=clicks,
        impressions=impressions,
        ctr=ctr,
        position=position,
    )
