"""Typed provider observations. Missing vendor data stays None (UNKNOWN),
never 0; every DTO names its provider so provenance survives persistence."""

from dataclasses import dataclass, field
from datetime import date, datetime

TREND_DIRECTIONS = ("rising", "stable", "falling", "unknown")


@dataclass(frozen=True, slots=True)
class KeywordMetrics:
    keyword: str
    database: str
    search_volume: int | None
    keyword_difficulty: float | None
    cpc: float | None
    competition: float | None
    intent: str | None
    observed_at: datetime
    provider: str = "semrush"


@dataclass(frozen=True, slots=True)
class RelatedKeyword:
    keyword: str
    search_volume: int | None
    keyword_difficulty: float | None


@dataclass(frozen=True, slots=True)
class SearchAnalyticsRow:
    date: date | None
    query: str | None
    page: str | None
    country: str | None
    device: str | None
    clicks: int
    impressions: int
    ctr: float
    position: float


@dataclass(frozen=True, slots=True)
class AnalyticsRow:
    date: date | None
    page: str | None
    users: int | None
    sessions: int | None
    views: int | None
    engagement_rate: float | None
    key_events: int | None


@dataclass(frozen=True, slots=True)
class TrendPoint:
    period: date
    value: float


@dataclass(frozen=True, slots=True)
class TrendSeries:
    term: str
    geo: str
    points: list[TrendPoint] = field(default_factory=list)
    relative: bool = True
    provider: str = "google_trends"


@dataclass(frozen=True, slots=True)
class TrendSummary:
    term: str
    geo: str
    direction: str  # rising | stable | falling | unknown
    seasonality_hint: str | None
    observed_at: datetime
    provider: str = "google_trends"


@dataclass(frozen=True, slots=True)
class PinterestKeywordTrend:
    keyword: str
    region: str
    weekly_points: list[TrendPoint]
    growth_pct_wow: float | None
    growth_pct_yoy: float | None
    observed_at: datetime
    provider: str = "pinterest_trends"


def trend_direction(values: list[float], *, window: int = 12) -> str:
    """rising|stable|falling from the last `window` points vs the previous
    `window`; `unknown` when fewer than two full windows exist. Relative
    values only — the caller never feeds absolute volumes here."""
    if len(values) < 2 * window:
        return "unknown"
    recent = values[-window:]
    previous = values[-2 * window : -window]
    recent_mean = sum(recent) / window
    previous_mean = sum(previous) / window
    if previous_mean <= 0:
        return "rising" if recent_mean > 0 else "unknown"
    change = (recent_mean - previous_mean) / previous_mean
    if change >= 0.15:
        return "rising"
    if change <= -0.15:
        return "falling"
    return "stable"
