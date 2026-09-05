"""Pinterest Trends adapter — official Pinterest API v5 only.

`GET https://api.pinterest.com/v5/trends/keywords/{region}/top/{trend_type}`
with `Authorization: Bearer <access token>` (app scope `trends:read`).
Without a token the provider reports `access_required`. pinterest.com is
NEVER scraped; growth percentages are relative signals, not volumes.
"""

from datetime import date
from typing import Any

import httpx

from contentos.core.config import Settings
from contentos.integrations.base import ProviderError, ProviderStatus, sanitize_error_class
from contentos.integrations.budget import RequestBudget
from contentos.integrations.cache import JsonPayload, ResponseCache
from contentos.integrations.dto import PinterestKeywordTrend, TrendPoint
from contentos.integrations.enums import ProviderName, ProviderState
from contentos.integrations.http import Clock, Sleep
from contentos.integrations.support import TEST_TIMEOUT_SECONDS, ProviderSupport

BASE_URL = "https://api.pinterest.com/v5"
TREND_TYPES = ("growing", "monthly", "yearly", "seasonal")
MAX_LIMIT = 50
ACCESS_REQUIRED_DETAIL = (
    "Pinterest API erişimi gerekli: trends:read kapsamlı bir erişim belirteci için "
    "CONTENTOS_PINTEREST_ACCESS_TOKEN tanımlayın."
)


class PinterestTrendsProvider(ProviderSupport):
    name = ProviderName.PINTEREST_TRENDS

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
            ProviderName.PINTEREST_TRENDS,
            settings,
            daily_budget=settings.pinterest_daily_budget,
            cache_hours=settings.pinterest_cache_hours,
            http_client=http_client,
            clock=clock,
            sleep=sleep,
            cache=cache,
            budget=budget,
        )
        self._region = settings.pinterest_region.strip().upper() or "TR"

    def configured(self) -> bool:
        return self._settings.pinterest_access_token is not None

    def test_connection(self) -> ProviderStatus:
        if not self.configured():
            return self.status(ProviderState.ACCESS_REQUIRED, ACCESS_REQUIRED_DETAIL)
        try:
            payload = self.cost.uncached(
                lambda: self._fetch(self._region, "growing", 1, None, timeout=TEST_TIMEOUT_SECONDS)
            )
        except ProviderError as error:
            if error.kind is ProviderState.ACCESS_REQUIRED:
                return self.status_from_error(
                    error,
                    "Pinterest erişimi reddedildi: belirtecin süresi dolmuş ya da "
                    "trends:read kapsamı eksik olabilir.",
                )
            return self.status_from_error(error)
        if "trends" not in payload:
            return self.status(
                ProviderState.ERROR,
                "Pinterest beklenmedik bir yanıt döndürdü.",
                error_class=sanitize_error_class("pinterest_trends", "malformed_body"),
            )
        return self.status(ProviderState.HEALTHY, f"Bağlı. Bölge: {self._region}.")

    def top_trends(
        self, region: str = "TR", trend_type: str = "growing", limit: int = 50
    ) -> list[PinterestKeywordTrend]:
        kind = trend_type if trend_type in TREND_TYPES else "growing"
        area = region.strip().upper() or self._region
        bounded = max(1, min(limit, MAX_LIMIT))
        payload = self.cost.cached(
            ("top_trends", area, kind, bounded),
            lambda: self._fetch(area, kind, bounded, None),
        )
        return _trends(payload, area, self.now())[:bounded]

    def keyword_trend(self, keyword: str, region: str = "TR") -> PinterestKeywordTrend | None:
        cleaned = " ".join(keyword.split())
        if not cleaned:
            return None
        area = region.strip().upper() or self._region
        payload = self.cost.cached(
            ("keyword_trend", area, cleaned.casefold()),
            lambda: self._fetch(area, "monthly", MAX_LIMIT, cleaned),
        )
        for trend in _trends(payload, area, self.now()):
            if trend.keyword.casefold() == cleaned.casefold():
                return trend
        return None

    def _fetch(
        self,
        region: str,
        trend_type: str,
        limit: int,
        include_keyword: str | None,
        *,
        timeout: float | None = None,
    ) -> JsonPayload:
        token = self._settings.pinterest_access_token
        if token is None:
            raise ProviderError(
                ACCESS_REQUIRED_DETAIL,
                kind=ProviderState.ACCESS_REQUIRED,
                error_class=sanitize_error_class("pinterest_trends", "access_required"),
            )
        params: dict[str, Any] = {"limit": limit}
        if include_keyword:
            params["include_keywords"] = [include_keyword]
        response = self._http.request(
            "GET",
            f"{BASE_URL}/trends/keywords/{region}/top/{trend_type}",
            params=params,
            headers={"Authorization": f"Bearer {token.get_secret_value()}"},
            timeout_seconds=timeout,
        )
        decoded = self._http.json(response)
        if not isinstance(decoded, dict) or not isinstance(decoded.get("trends"), list):
            raise ProviderError(
                "pinterest returned an unexpected body",
                kind=ProviderState.ERROR,
                error_class=sanitize_error_class("pinterest_trends", "malformed_body"),
            )
        return {"trends": decoded["trends"]}


def _trends(payload: JsonPayload, region: str, observed_at: Any) -> list[PinterestKeywordTrend]:
    raw = payload.get("trends")
    if not isinstance(raw, list):
        return []
    result: list[PinterestKeywordTrend] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        keyword = item.get("keyword")
        if not isinstance(keyword, str) or not keyword.strip():
            continue
        result.append(
            PinterestKeywordTrend(
                keyword=keyword.strip(),
                region=region,
                weekly_points=_points(item.get("time_series")),
                growth_pct_wow=_float(item.get("pct_growth_wow")),
                growth_pct_yoy=_float(item.get("pct_growth_yoy")),
                observed_at=observed_at,
            )
        )
    return result


def _points(raw: Any) -> list[TrendPoint]:
    if not isinstance(raw, dict):
        return []
    dates = raw.get("date")
    values = raw.get("index")
    if not isinstance(dates, list) or not isinstance(values, list):
        return []
    points: list[TrendPoint] = []
    for stamp, value in zip(dates, values, strict=False):
        if not isinstance(stamp, str) or isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        try:
            period = date.fromisoformat(stamp[:10])
        except ValueError:
            continue
        points.append(TrendPoint(period=period, value=float(value)))
    return points


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number else None
