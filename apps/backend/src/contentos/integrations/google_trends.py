"""Google Trends adapter — official API access only (alpha / allow-listed).

There is no generally available official Google Trends API. This adapter
activates ONLY when `CONTENTOS_GOOGLE_TRENDS_API_KEY` is set (base URL
`CONTENTOS_GOOGLE_TRENDS_API_URL` overridable); otherwise the provider
reports `access_required`. trends.google.com is NEVER scraped. Values are
relative (0-100) — never absolute volumes.
"""

from datetime import date, datetime
from typing import Any

import httpx

from contentos.core.config import Settings
from contentos.integrations.base import ProviderError, ProviderStatus, sanitize_error_class
from contentos.integrations.budget import RequestBudget
from contentos.integrations.cache import JsonPayload, ResponseCache
from contentos.integrations.dto import TrendPoint, TrendSeries, TrendSummary, trend_direction
from contentos.integrations.enums import ProviderName, ProviderState
from contentos.integrations.http import Clock, Sleep
from contentos.integrations.support import TEST_TIMEOUT_SECONDS, ProviderSupport

DEFAULT_API_URL = "https://trends.googleapis.com/v1beta"
ACCESS_REQUIRED_DETAIL = "Google Trends API erişimi gerekli (resmi API alfa/izinli)"
MAX_TERMS = 5
TEST_TERM = "parti"


class GoogleTrendsProvider(ProviderSupport):
    name = ProviderName.GOOGLE_TRENDS

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
            ProviderName.GOOGLE_TRENDS,
            settings,
            daily_budget=settings.google_trends_daily_budget,
            cache_hours=settings.google_trends_cache_hours,
            http_client=http_client,
            clock=clock,
            sleep=sleep,
            cache=cache,
            budget=budget,
        )
        self._base_url = (settings.google_trends_api_url or DEFAULT_API_URL).rstrip("/")

    def configured(self) -> bool:
        return self._settings.google_trends_api_key is not None

    def test_connection(self) -> ProviderStatus:
        if not self.configured():
            return self.status(
                ProviderState.ACCESS_REQUIRED,
                f"{ACCESS_REQUIRED_DETAIL}: CONTENTOS_GOOGLE_TRENDS_API_KEY tanımlayın.",
            )
        try:
            payload = self.cost.uncached(
                lambda: self._fetch([TEST_TERM], "TR", timeout=TEST_TIMEOUT_SECONDS)
            )
        except ProviderError as error:
            if error.kind is ProviderState.ACCESS_REQUIRED:
                return self.status_from_error(
                    error, f"{ACCESS_REQUIRED_DETAIL}: anahtar reddedildi."
                )
            return self.status_from_error(error)
        series = _series(payload, ["parti"], "TR")
        if not series:
            return self.status(
                ProviderState.ERROR,
                "Google Trends beklenmedik bir yanıt döndürdü.",
                error_class=sanitize_error_class("google_trends", "malformed_body"),
            )
        return self.status(ProviderState.HEALTHY, "Bağlı. Göreli ilgi serileri okunabiliyor.")

    def interest_over_time(self, terms: list[str], geo: str = "TR") -> list[TrendSeries]:
        cleaned = [" ".join(term.split()) for term in terms if term.strip()][:MAX_TERMS]
        if not cleaned:
            return []
        region = geo.strip().upper() or "TR"
        payload = self.cost.cached(
            ("interest_over_time", region, cleaned),
            lambda: self._fetch(cleaned, region),
        )
        return _series(payload, cleaned, region)

    def summary(self, term: str, geo: str = "TR") -> TrendSummary:
        """rising|stable|falling|unknown from the last 12 vs previous 12 points."""
        region = geo.strip().upper() or "TR"
        series = self.interest_over_time([term], region)
        observed_at = self.now()
        if not series:
            return TrendSummary(
                term=term,
                geo=region,
                direction="unknown",
                seasonality_hint=None,
                observed_at=observed_at,
            )
        points = series[0].points
        values = [point.value for point in points]
        return TrendSummary(
            term=term,
            geo=region,
            direction=trend_direction(values),
            seasonality_hint=_seasonality_hint(points),
            observed_at=observed_at,
        )

    def _fetch(self, terms: list[str], geo: str, *, timeout: float | None = None) -> JsonPayload:
        key = self._settings.google_trends_api_key
        if key is None:
            raise ProviderError(
                ACCESS_REQUIRED_DETAIL,
                kind=ProviderState.ACCESS_REQUIRED,
                error_class=sanitize_error_class("google_trends", "access_required"),
            )
        response = self._http.request(
            "GET",
            f"{self._base_url}/interestOverTime",
            params={"terms": terms, "geo": geo},
            headers={"X-Goog-Api-Key": key.get_secret_value()},
            timeout_seconds=timeout,
        )
        decoded = self._http.json(response)
        if not isinstance(decoded, dict):
            raise ProviderError(
                "google trends returned a non-object body",
                kind=ProviderState.ERROR,
                error_class=sanitize_error_class("google_trends", "malformed_body"),
            )
        return {"series": _normalize_series(decoded)}


def _normalize_series(decoded: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept `{"series":[{"term","points":[{"date","value"}]}]}` or the
    timeline shape `{"timelineData":[{"time"|"date", "value":[...]}]}`."""
    series = decoded.get("series")
    if isinstance(series, list):
        return [item for item in series if isinstance(item, dict)]
    timeline = decoded.get("timelineData")
    if isinstance(timeline, list):
        terms = decoded.get("terms")
        names = [t for t in terms if isinstance(t, str)] if isinstance(terms, list) else []
        buckets: dict[int, list[dict[str, Any]]] = {}
        for entry in timeline:
            if not isinstance(entry, dict):
                continue
            stamp = entry.get("date") or entry.get("time")
            values = entry.get("value")
            if not isinstance(values, list):
                continue
            for index, value in enumerate(values):
                buckets.setdefault(index, []).append({"date": stamp, "value": value})
        return [
            {"term": names[index] if index < len(names) else "", "points": points}
            for index, points in sorted(buckets.items())
        ]
    return []


def _series(payload: JsonPayload, terms: list[str], geo: str) -> list[TrendSeries]:
    raw = payload.get("series")
    if not isinstance(raw, list):
        return []
    result: list[TrendSeries] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        term = item.get("term")
        name = (
            term if isinstance(term, str) and term else (terms[index] if index < len(terms) else "")
        )
        points: list[TrendPoint] = []
        raw_points = item.get("points")
        if isinstance(raw_points, list):
            for point in raw_points:
                parsed = _point(point)
                if parsed is not None:
                    points.append(parsed)
        if name:
            result.append(TrendSeries(term=name, geo=geo, points=points))
    return result


def _point(raw: Any) -> TrendPoint | None:
    if not isinstance(raw, dict):
        return None
    stamp = raw.get("date") or raw.get("period") or raw.get("time")
    value = raw.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    period: date | None = None
    if isinstance(stamp, str):
        try:
            period = date.fromisoformat(stamp[:10])
        except ValueError:
            if stamp.isdigit():
                period = datetime.fromtimestamp(int(stamp)).date()
    elif isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
        period = datetime.fromtimestamp(int(stamp)).date()
    if period is None:
        return None
    return TrendPoint(period=period, value=float(value))


def _seasonality_hint(points: list[TrendPoint]) -> str | None:
    """Name the peak month when one month clearly dominates a year+ of data."""
    if len(points) < 52:
        return None
    by_month: dict[int, list[float]] = {}
    for point in points:
        by_month.setdefault(point.period.month, []).append(point.value)
    if len(by_month) < 12:
        return None
    means = {month: sum(values) / len(values) for month, values in by_month.items()}
    overall = sum(means.values()) / len(means)
    if overall <= 0:
        return None
    peak_month, peak_value = max(means.items(), key=lambda item: item[1])
    if peak_value >= overall * 1.5:
        return f"peak_month_{peak_month:02d}"
    return None
