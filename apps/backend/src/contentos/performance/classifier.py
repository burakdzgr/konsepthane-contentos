"""Pure, table-driven performance classification.

`PerformanceClassifier.assess` compares the last `window_days` of Google
Search Console daily observations with the previous equal window and
returns ONE honest status. It never touches a session, a provider, or a
clock other than the `now` it is given, so every rule is unit-testable
from fixture rows.

Statuses (see docs/PERFORMANCE_LOOP.md):

- ``unknown``            no Search Console daily snapshot exists at all;
- ``insufficient_data``  fewer than ``min_days`` observed days or fewer
                         than ``min_impressions`` impressions in either
                         window — a new content is NEVER "declining";
- ``declining``          impressions or clicks dropped by ``decline_pct``
                         or more AND the average position got worse;
- ``rising``             impressions or clicks grew by ``rise_pct`` or
                         more AND the average position did not get worse;
- ``volatile``           the two halves of the current window differ by
                         ``volatility_pct`` or more in impressions;
- ``stable``             everything else.
"""

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from contentos.performance.enums import AssessmentStatus, PerformanceProvider

ENGINE_NAME = "performance-classifier"
ENGINE_VERSION = "1"


@dataclass(frozen=True, slots=True)
class PerformancePolicy:
    """Thresholds; the snapshot of these values is part of every basis."""

    min_impressions: int = 100
    min_days: int = 7
    decline_pct: float = 0.25
    rise_pct: float = 0.25
    volatility_pct: float = 0.5

    @classmethod
    def from_settings(cls, settings: Any) -> "PerformancePolicy":
        return cls(
            min_impressions=int(getattr(settings, "performance_min_impressions", 100)),
            min_days=int(getattr(settings, "performance_min_days", 7)),
            decline_pct=float(getattr(settings, "performance_decline_pct", 0.25)),
            rise_pct=float(getattr(settings, "performance_rise_pct", 0.25)),
            volatility_pct=float(getattr(settings, "performance_volatility_pct", 0.5)),
        )


class SnapshotLike(Protocol):
    """The shape the classifier reads (ORM rows and test fakes alike)."""

    @property
    def provider(self) -> Any: ...

    @property
    def period_start(self) -> date: ...

    @property
    def period_end(self) -> date: ...

    @property
    def observed_at(self) -> datetime: ...

    @property
    def metrics(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class DailyPoint:
    day: date
    impressions: int
    clicks: int
    position: float | None
    ctr: float | None


@dataclass(frozen=True, slots=True)
class WindowStats:
    start: date
    end: date
    days: int
    impressions: int
    clicks: int
    position: float | None
    ctr: float | None

    def projection(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "days": self.days,
            "impressions": self.impressions,
            "clicks": self.clicks,
            "position": self.position,
            "ctr": self.ctr,
        }


@dataclass(frozen=True, slots=True)
class Assessment:
    status: AssessmentStatus
    window_days: int
    basis: dict[str, Any]
    engine_name: str = ENGINE_NAME
    engine_version: str = ENGINE_VERSION


def _provider_value(value: Any) -> str:
    return value.value if isinstance(value, PerformanceProvider) else str(value)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def daily_points(snapshots: Iterable[SnapshotLike]) -> list[DailyPoint]:
    """Search Console DAILY rows only, the latest observation per day wins."""
    latest: dict[date, SnapshotLike] = {}
    for snapshot in snapshots:
        if _provider_value(snapshot.provider) != PerformanceProvider.GOOGLE_SEARCH_CONSOLE.value:
            continue
        if snapshot.period_start != snapshot.period_end:
            continue
        current = latest.get(snapshot.period_start)
        if current is None or snapshot.observed_at > current.observed_at:
            latest[snapshot.period_start] = snapshot
    points: list[DailyPoint] = []
    for day in sorted(latest):
        metrics = latest[day].metrics
        impressions = _number(metrics.get("impressions"))
        clicks = _number(metrics.get("clicks"))
        points.append(
            DailyPoint(
                day=day,
                impressions=int(impressions) if impressions is not None else 0,
                clicks=int(clicks) if clicks is not None else 0,
                position=_number(metrics.get("position")),
                ctr=_number(metrics.get("ctr")),
            )
        )
    return points


def window_stats(points: Iterable[DailyPoint], start: date, end: date) -> WindowStats:
    """Aggregate the points inside [start, end]; position is impression-weighted."""
    inside = [point for point in points if start <= point.day <= end]
    impressions = sum(point.impressions for point in inside)
    clicks = sum(point.clicks for point in inside)
    weighted = [
        (point.position, point.impressions) for point in inside if point.position is not None
    ]
    position: float | None = None
    if weighted:
        weight_total = sum(weight for _, weight in weighted)
        if weight_total > 0:
            position = sum(value * weight for value, weight in weighted) / weight_total
        else:
            position = sum(value for value, _ in weighted) / len(weighted)
    ctr = (clicks / impressions) if impressions > 0 else None
    return WindowStats(
        start=start,
        end=end,
        days=len(inside),
        impressions=impressions,
        clicks=clicks,
        position=round(position, 2) if position is not None else None,
        ctr=round(ctr, 4) if ctr is not None else None,
    )


def _pct_change(current: int, previous: int) -> float | None:
    if previous <= 0:
        return None
    return round((current - previous) / previous, 4)


class PerformanceClassifier:
    """Pure function object; `assess` is deterministic for the same inputs."""

    def assess(
        self,
        snapshots: Iterable[SnapshotLike],
        window_days: int,
        now: datetime,
        policy: PerformancePolicy,
    ) -> Assessment:
        if window_days <= 0:
            raise ValueError("window_days must be positive")
        thresholds = asdict(policy)
        points = daily_points(snapshots)
        if not points:
            return Assessment(
                status=AssessmentStatus.UNKNOWN,
                window_days=window_days,
                basis={
                    "reason": "no_search_console_snapshots",
                    "sample": {"daily_points": 0},
                    "thresholds": thresholds,
                },
            )
        # Search Console data lags by a few days: anchor the window on the
        # latest observed day, never on a day nobody has data for yet.
        anchor = min(now.date(), points[-1].day)
        current = window_stats(points, anchor - timedelta(days=window_days - 1), anchor)
        previous = window_stats(
            points,
            anchor - timedelta(days=2 * window_days - 1),
            anchor - timedelta(days=window_days),
        )
        required_days = min(policy.min_days, window_days)
        basis: dict[str, Any] = {
            "anchor_day": anchor.isoformat(),
            "current": current.projection(),
            "previous": previous.projection(),
            "sample": {"daily_points": len(points)},
            "thresholds": thresholds,
        }
        insufficient_reason = _insufficient_reason(current, previous, required_days, policy)
        if insufficient_reason is not None:
            basis["reason"] = insufficient_reason
            return Assessment(AssessmentStatus.INSUFFICIENT_DATA, window_days, basis)

        impressions_pct = _pct_change(current.impressions, previous.impressions)
        clicks_pct = _pct_change(current.clicks, previous.clicks)
        position_delta = (
            round(current.position - previous.position, 2)
            if current.position is not None and previous.position is not None
            else None
        )
        midpoint = current.start + timedelta(days=(window_days // 2) - 1)
        first_half = window_stats(points, current.start, midpoint)
        second_half = window_stats(points, midpoint + timedelta(days=1), current.end)
        largest_half = max(first_half.impressions, second_half.impressions)
        swing = (
            round(abs(second_half.impressions - first_half.impressions) / largest_half, 4)
            if largest_half > 0
            else 0.0
        )
        basis["deltas"] = {
            "impressions_pct": impressions_pct,
            "clicks_pct": clicks_pct,
            "position_delta": position_delta,
        }
        basis["sub_periods"] = {
            "first_half_impressions": first_half.impressions,
            "second_half_impressions": second_half.impressions,
            "swing_pct": swing,
        }

        dropped = _at_most(impressions_pct, -policy.decline_pct) or _at_most(
            clicks_pct, -policy.decline_pct
        )
        grew = _at_least(impressions_pct, policy.rise_pct) or _at_least(clicks_pct, policy.rise_pct)
        if dropped and position_delta is not None and position_delta > 0:
            return Assessment(AssessmentStatus.DECLINING, window_days, basis)
        if grew and (position_delta is None or position_delta <= 0):
            return Assessment(AssessmentStatus.RISING, window_days, basis)
        if swing >= policy.volatility_pct:
            return Assessment(AssessmentStatus.VOLATILE, window_days, basis)
        return Assessment(AssessmentStatus.STABLE, window_days, basis)


def _insufficient_reason(
    current: WindowStats, previous: WindowStats, required_days: int, policy: PerformancePolicy
) -> str | None:
    if current.days < required_days:
        return "too_few_days_in_current_window"
    if current.impressions < policy.min_impressions:
        return "too_few_impressions_in_current_window"
    if previous.days < required_days:
        return "too_few_days_in_previous_window"
    if previous.impressions < policy.min_impressions:
        return "too_few_impressions_in_previous_window"
    return None


def _at_most(value: float | None, bound: float) -> bool:
    return value is not None and value <= bound


def _at_least(value: float | None, bound: float) -> bool:
    return value is not None and value >= bound
