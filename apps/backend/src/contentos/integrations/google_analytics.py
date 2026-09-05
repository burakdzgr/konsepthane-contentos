"""Google Analytics 4 Data API adapter (on-site behaviour of OUR pages).

`POST https://analyticsdata.googleapis.com/v1beta/properties/{id}:runReport`
with the same service account as Search Console (GA4 property Viewer).
Key events are reported ONLY for the names in `CONTENTOS_GA4_KEY_EVENTS`;
nothing is invented for events Konsepthane does not have.
"""

from datetime import date
from typing import Any

import httpx

from contentos.core.config import Settings
from contentos.integrations.base import ProviderError, ProviderStatus, sanitize_error_class
from contentos.integrations.budget import RequestBudget
from contentos.integrations.cache import JsonPayload, ResponseCache
from contentos.integrations.dto import AnalyticsRow
from contentos.integrations.enums import ProviderName, ProviderState
from contentos.integrations.google_auth import (
    ServiceAccountTokenSource,
    load_service_account,
)
from contentos.integrations.http import Clock, Sleep
from contentos.integrations.support import TEST_TIMEOUT_SECONDS, ProviderSupport

BASE_URL = "https://analyticsdata.googleapis.com/v1beta"
SCOPES = ("https://www.googleapis.com/auth/analytics.readonly",)
# Caller-facing metric names → GA4 API metric names.
METRIC_ALIASES: dict[str, str] = {
    "users": "activeUsers",
    "activeUsers": "activeUsers",
    "totalUsers": "totalUsers",
    "sessions": "sessions",
    "screenPageViews": "screenPageViews",
    "views": "screenPageViews",
    "engagementRate": "engagementRate",
    "keyEvents": "keyEvents",
}
ALLOWED_DIMENSIONS = ("date", "pagePath")
MAX_KEY_EVENTS = 10
MAX_ROWS = 10_000


class GoogleAnalyticsProvider(ProviderSupport):
    name = ProviderName.GOOGLE_ANALYTICS

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
            ProviderName.GOOGLE_ANALYTICS,
            settings,
            daily_budget=settings.ga4_daily_budget,
            cache_hours=settings.ga4_cache_hours,
            http_client=http_client,
            clock=clock,
            sleep=sleep,
            cache=cache,
            budget=budget,
        )
        self._property = (settings.ga4_property_id or "").removeprefix("properties/")
        self._key_events = tuple(
            name.strip() for name in (settings.ga4_key_events or "").split(",") if name.strip()
        )[:MAX_KEY_EVENTS]
        self._tokens: ServiceAccountTokenSource | None = None

    def configured(self) -> bool:
        return self._settings.google_service_account_json is not None and bool(self._property)

    @property
    def key_events(self) -> tuple[str, ...]:
        return self._key_events

    def test_connection(self) -> ProviderStatus:
        if not self.configured():
            return self.not_configured_status()
        try:
            body = self.cost.uncached(
                lambda: self._http.json(
                    self._http.request(
                        "GET",
                        f"{BASE_URL}/properties/{self._property}/metadata",
                        headers=self._headers(),
                        timeout_seconds=TEST_TIMEOUT_SECONDS,
                    )
                )
            )
        except ProviderError as error:
            if error.kind is ProviderState.ACCESS_REQUIRED or error.error_class.endswith(
                "_http_404"
            ):
                return self.status(
                    ProviderState.ACCESS_REQUIRED,
                    "GA4 erişimi reddedildi: servis hesabına mülkte Görüntüleyici "
                    "rolü verin ve mülk kimliğini kontrol edin.",
                    error_class=error.error_class,
                )
            return self.status_from_error(error)
        if not isinstance(body, dict) or "metrics" not in body:
            return self.status(
                ProviderState.ERROR,
                "GA4 beklenmedik bir yanıt döndürdü.",
                error_class=sanitize_error_class("google_analytics", "malformed_body"),
            )
        events = (
            f" Anahtar olaylar: {', '.join(self._key_events)}."
            if self._key_events
            else " Anahtar olay tanımlı değil."
        )
        return self.status(ProviderState.HEALTHY, f"Bağlı. Mülk {self._property}.{events}")

    def run_report(
        self,
        start: date,
        end: date,
        dimensions: list[str],
        metrics: list[str],
        page_filter: str | None = None,
    ) -> list[AnalyticsRow]:
        dims = [dim for dim in dimensions if dim in ALLOWED_DIMENSIONS]
        api_metrics: list[str] = []
        for metric in metrics:
            mapped = METRIC_ALIASES.get(metric)
            if mapped is None:
                continue
            if mapped == "keyEvents":
                # Only configured key events; an unconfigured request stays UNKNOWN.
                api_metrics.extend(f"keyEvents:{name}" for name in self._key_events)
                continue
            if mapped not in api_metrics:
                api_metrics.append(mapped)
        if not api_metrics:
            return []
        body: dict[str, Any] = {
            "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
            "dimensions": [{"name": dim} for dim in dims],
            "metrics": [{"name": name} for name in api_metrics],
            "limit": MAX_ROWS,
        }
        if page_filter:
            body["dimensionFilter"] = {
                "filter": {
                    "fieldName": "pagePath",
                    "stringFilter": {"matchType": "EXACT", "value": page_filter},
                }
            }
        payload = self.cost.cached(
            ("run_report", self._property, body),
            lambda: self._run(body),
        )
        return _rows(payload)

    def _run(self, body: dict[str, Any]) -> JsonPayload:
        response = self._http.request(
            "POST",
            f"{BASE_URL}/properties/{self._property}:runReport",
            headers=self._headers(),
            json_body=body,
        )
        decoded = self._http.json(response)
        if not isinstance(decoded, dict):
            raise ProviderError(
                "ga4 returned a non-object body",
                kind=ProviderState.ERROR,
                error_class=sanitize_error_class("google_analytics", "malformed_body"),
            )
        return {
            "dimensionHeaders": decoded.get("dimensionHeaders") or [],
            "metricHeaders": decoded.get("metricHeaders") or [],
            "rows": decoded.get("rows") or [],
        }

    def _headers(self) -> dict[str, str]:
        if self._tokens is None:
            info = load_service_account(self._settings.google_service_account_json)
            self._tokens = ServiceAccountTokenSource(
                info, SCOPES, http=self._http, clock=self._clock
            )
        return {"Authorization": f"Bearer {self._tokens.access_token()}"}


def _header_names(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else None
        names.append(name if isinstance(name, str) else "")
    return names


def _rows(payload: JsonPayload) -> list[AnalyticsRow]:
    dim_names = _header_names(payload.get("dimensionHeaders"))
    metric_names = _header_names(payload.get("metricHeaders"))
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []
    result: list[AnalyticsRow] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        dims = _values(raw.get("dimensionValues"))
        mets = _values(raw.get("metricValues"))
        dim_map = dict(zip(dim_names, dims, strict=False))
        met_map = dict(zip(metric_names, mets, strict=False))
        parsed_date: date | None = None
        if "date" in dim_map:
            try:
                parsed_date = date.fromisoformat(
                    f"{dim_map['date'][:4]}-{dim_map['date'][4:6]}-{dim_map['date'][6:8]}"
                )
            except ValueError:
                parsed_date = None
        key_event_values = [
            _int(value) for name, value in met_map.items() if name.startswith("keyEvents")
        ]
        known_key_events = [value for value in key_event_values if value is not None]
        result.append(
            AnalyticsRow(
                date=parsed_date,
                page=dim_map.get("pagePath"),
                users=_int(met_map.get("activeUsers", met_map.get("totalUsers"))),
                sessions=_int(met_map.get("sessions")),
                views=_int(met_map.get("screenPageViews")),
                engagement_rate=_float(met_map.get("engagementRate")),
                key_events=sum(known_key_events) if known_key_events else None,
            )
        )
    return result


def _values(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for item in raw:
        value = item.get("value") if isinstance(item, dict) else None
        values.append(value if isinstance(value, str) else "")
    return values


def _int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if number == number else None
