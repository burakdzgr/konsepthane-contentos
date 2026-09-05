"""Table-driven tests for the pure performance classifier."""

from datetime import timedelta

import pytest
from performance_fixtures import (
    NOW,
    TODAY,
    FakeSnapshot,
    daily_series,
    declining_points,
    rising_points,
    weak_new_points,
)

from contentos.performance.classifier import (
    ENGINE_NAME,
    ENGINE_VERSION,
    PerformanceClassifier,
    PerformancePolicy,
    daily_points,
)
from contentos.performance.enums import AssessmentStatus, PerformanceProvider

POLICY = PerformancePolicy()


def assess(points, window=28, now=NOW, policy=POLICY):
    return PerformanceClassifier().assess(points, window, now, policy)


class TestVerdicts:
    def test_no_snapshots_is_unknown_never_zero(self) -> None:
        result = assess([])
        assert result.status is AssessmentStatus.UNKNOWN
        assert result.basis["reason"] == "no_search_console_snapshots"
        assert result.basis["sample"]["daily_points"] == 0
        assert result.engine_name == ENGINE_NAME and result.engine_version == ENGINE_VERSION

    def test_a_new_content_with_a_few_weak_days_is_insufficient_never_declining(self) -> None:
        result = assess(weak_new_points())
        assert result.status is AssessmentStatus.INSUFFICIENT_DATA
        assert result.basis["reason"] == "too_few_days_in_current_window"
        assert "deltas" not in result.basis

    def test_low_impressions_are_insufficient(self) -> None:
        points = daily_series(TODAY, 56, impressions=2, clicks=0, position=30.0)
        result = assess(points)
        assert result.status is AssessmentStatus.INSUFFICIENT_DATA
        assert result.basis["reason"] == "too_few_impressions_in_current_window"

    def test_missing_previous_window_is_insufficient(self) -> None:
        points = daily_series(TODAY, 30, impressions=40, clicks=4, position=5.0)
        result = assess(points)
        assert result.status is AssessmentStatus.INSUFFICIENT_DATA
        assert result.basis["reason"] == "too_few_days_in_previous_window"

    def test_enough_rising_history_is_rising(self) -> None:
        result = assess(rising_points())
        assert result.status is AssessmentStatus.RISING
        deltas = result.basis["deltas"]
        assert deltas["impressions_pct"] >= POLICY.rise_pct
        assert deltas["position_delta"] < 0
        assert result.basis["current"]["days"] == 28
        assert result.basis["previous"]["days"] == 28

    def test_declining_history_is_declining(self) -> None:
        result = assess(declining_points())
        assert result.status is AssessmentStatus.DECLINING
        deltas = result.basis["deltas"]
        assert deltas["impressions_pct"] <= -0.3
        assert deltas["clicks_pct"] <= -0.25
        assert result.basis["previous"]["position"] < result.basis["current"]["position"]
        assert deltas["position_delta"] > 0

    def test_a_drop_without_position_loss_is_not_declining(self) -> None:
        previous = daily_series(
            TODAY - timedelta(days=28), 28, impressions=30, clicks=6, position=5.0
        )
        current = daily_series(TODAY, 28, impressions=20, clicks=4, position=4.0)
        result = assess(previous + current)
        assert result.status is not AssessmentStatus.DECLINING

    def test_swinging_halves_are_volatile(self) -> None:
        previous = daily_series(
            TODAY - timedelta(days=28), 28, impressions=25, clicks=3, position=6.0
        )
        current = daily_series(TODAY, 28, impressions=[10] * 14 + [40] * 14, clicks=3, position=6.0)
        result = assess(previous + current)
        assert result.status is AssessmentStatus.VOLATILE
        assert result.basis["sub_periods"]["swing_pct"] >= POLICY.volatility_pct

    def test_flat_history_is_stable(self) -> None:
        points = daily_series(TODAY, 56, impressions=25, clicks=3, position=6.0)
        result = assess(points)
        assert result.status is AssessmentStatus.STABLE
        assert result.basis["deltas"]["impressions_pct"] == 0.0

    @pytest.mark.parametrize("window", [7, 28, 90])
    def test_every_window_is_supported(self, window: int) -> None:
        points = daily_series(TODAY, 2 * window, impressions=25, clicks=3, position=6.0)
        result = assess(points, window=window)
        assert result.window_days == window
        assert result.status is AssessmentStatus.STABLE


class TestMechanics:
    def test_thresholds_are_snapshotted_into_the_basis(self) -> None:
        policy = PerformancePolicy(min_impressions=10, decline_pct=0.1)
        result = assess(rising_points(), policy=policy)
        assert result.basis["thresholds"]["min_impressions"] == 10
        assert result.basis["thresholds"]["decline_pct"] == 0.1

    def test_window_anchors_on_the_latest_observed_day_not_on_now(self) -> None:
        points = rising_points(end=TODAY - timedelta(days=3))
        result = assess(points, now=NOW)
        assert result.basis["anchor_day"] == (TODAY - timedelta(days=3)).isoformat()
        assert result.status is AssessmentStatus.RISING

    def test_latest_observation_per_day_wins_and_other_providers_are_ignored(self) -> None:
        early = FakeSnapshot(
            TODAY, TODAY, {"impressions": 1, "clicks": 0, "position": 50.0}, observed_at=NOW
        )
        late = FakeSnapshot(
            TODAY,
            TODAY,
            {"impressions": 99, "clicks": 9, "position": 2.0},
            observed_at=NOW + timedelta(hours=1),
        )
        analytics = FakeSnapshot(
            TODAY, TODAY, {"users": 5}, provider=PerformanceProvider.GOOGLE_ANALYTICS
        )
        summary = FakeSnapshot(
            TODAY - timedelta(days=27), TODAY, {"impressions": 1000, "clicks": 100}
        )
        points = daily_points([early, late, analytics, summary])
        assert len(points) == 1
        assert points[0].impressions == 99

    def test_window_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            assess(rising_points(), window=0)

    def test_policy_from_settings_reads_the_configured_thresholds(self) -> None:
        from contentos.core.config import Settings

        settings = Settings(performance_min_impressions=250, performance_decline_pct=0.4)
        policy = PerformancePolicy.from_settings(settings)
        assert policy.min_impressions == 250
        assert policy.decline_pct == 0.4
        assert policy.min_days == 7
