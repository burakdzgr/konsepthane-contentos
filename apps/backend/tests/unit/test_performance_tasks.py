"""Performance worker tasks with fake providers: success, not configured,
rate limited, timeout; the beat schedule; the beat entrypoint arguments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from editorial_harness import Harness
from performance_fixtures import NOW, TODAY, declining_points, seed_published, write_daily
from sqlalchemy import select

from contentos.core.config import Environment, LogLevel, Settings
from contentos.performance.enums import PerformanceProvider, RefreshStatus
from contentos.performance.models import ContentPerformanceSnapshot, RefreshOpportunity
from contentos.performance.service import PerformanceService
from contentos.queue.celery import create_celery_app
from contentos.worker.main import beat_arguments, create_worker_app
from contentos.worker.performance_tasks import (
    ASSESS_TASK,
    DETECT_REFRESH_TASK,
    PERFORMANCE_TASK_NAMES,
    REFRESH_MARKET_SIGNALS_TASK,
    SYNC_ALL_TASK,
    SYNC_ANALYTICS_TASK,
    SYNC_SEARCH_CONSOLE_TASK,
    classify_provider_error,
    performance_beat_schedule,
    register_performance_tasks,
)
from contentos.worker.runtime import WorkerRuntime


def settings(**overrides: Any) -> Settings:
    return Settings(
        environment=Environment.TEST,
        service_name="ContentOS Performance Task Test",
        application_version="1.0.0-test",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
        celery_task_always_eager=True,
        celery_broker_connection_retry_on_startup=False,
        redis_broker_url="redis://:task-secret@localhost:6379/0",
        **overrides,
    )


@dataclass(frozen=True, slots=True)
class Row:
    date: date | None = None
    query: str | None = None
    page: str | None = None
    country: str | None = None
    device: str | None = None
    clicks: int = 0
    impressions: int = 0
    ctr: float = 0.0
    position: float = 0.0


@dataclass(frozen=True, slots=True)
class AnalyticsRow:
    date: date | None
    page: str | None
    users: int | None
    sessions: int | None
    views: int | None
    engagement_rate: float | None
    key_events: int | None


class ProviderFailure(Exception):
    def __init__(self, kind: str, error_class: str) -> None:
        super().__init__("provider failed (message never persisted)")
        self.kind = kind
        self.error_class = error_class


class FakeSearchConsole:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[dict[str, Any]] = []

    def search_analytics(self, start, end, dimensions, page_filter=None, row_limit=1000):
        self.calls.append({"dims": dimensions, "page": page_filter, "limit": row_limit})
        if self.failure is not None:
            raise self.failure
        if dimensions == ["date"]:
            days = (end - start).days + 1
            return [
                Row(
                    date=start + timedelta(days=i),
                    clicks=3,
                    impressions=40,
                    ctr=0.075,
                    position=5.5,
                )
                for i in range(days)
            ]
        return [
            Row(query="balon temalı doğum günü", clicks=20, impressions=300, position=4.0),
            Row(query="evde parti", clicks=5, impressions=90, position=7.0),
        ]


class FakeAnalytics:
    def run_report(self, start, end, dimensions, metrics, page_filter=None):
        days = (end - start).days + 1
        return [
            AnalyticsRow(start + timedelta(days=i), page_filter, 10, 12, 15, 0.6, 1)
            for i in range(days)
        ]


class FakeSemrush:
    def keyword_overview(self, keywords, database=None):
        return [
            {"keyword": keyword, "search_volume": 880, "keyword_difficulty": 32.5}
            for keyword in keywords
        ]


class FakeTrends:
    def summary(self, term, geo):
        return {"term": term, "geo": geo, "direction": "rising", "provider": "google_trends"}


class FakePinterest:
    def keyword_trend(self, keyword, region):
        return {"keyword": keyword, "region": region, "growth_pct_wow": 12.0}


class FakeRegistry:
    """Mirrors the registry contract the tasks use: get/record_*."""

    def __init__(self, providers: dict[str, Any]) -> None:
        self._providers = providers
        self.statuses: list[tuple[str, str, str | None]] = []

    def get(self, name: str) -> Any:
        provider = self._providers.get(name)
        if isinstance(provider, Exception):
            raise provider
        if provider is None:
            raise ProviderFailure("not_configured", f"{name}_not_configured")
        return provider

    def record_error(self, session, name, error_class, *, kind, detail=None) -> None:
        self.statuses.append(
            (str(getattr(name, "value", name)), str(getattr(kind, "value", kind)), error_class)
        )

    def record_success(self, session, name, *, synced: bool = True) -> None:
        self.statuses.append((str(getattr(name, "value", name)), "healthy", None))


def worker_app(harness: Harness, registry: Any, **overrides: Any):
    resolved = settings(**overrides)
    runtime = WorkerRuntime(resolved, session_factory=harness.session_factory)
    app = create_celery_app(resolved)
    register_performance_tasks(app, runtime, registry_factory=lambda: registry)
    return app


def run(app, name: str) -> dict[str, Any]:
    return app.tasks[name].apply().get()


@pytest.fixture()
def harness() -> Harness:
    return Harness()


class TestSearchConsoleSync:
    def test_success_writes_daily_and_summary_snapshots_and_records_health(
        self, harness: Harness
    ) -> None:
        with harness.session() as session:
            content = seed_published(session, remote_ref="https://konsepthane.net/balon")
            seed_published(session, title="Adresi yok", remote_ref="konsepthane-pub-2")
            session.commit()
            content_id = content.id
        gsc = FakeSearchConsole()
        registry = FakeRegistry({"google_search_console": gsc})
        result = run(worker_app(harness, registry), SYNC_SEARCH_CONSOLE_TASK)
        assert result["state"] == "healthy"
        assert result["contents"] == 1
        assert result["skipped_without_url"] == 1
        assert result["snapshots"] == 29  # 28 daily + 1 summary
        assert gsc.calls[0]["page"] == "https://konsepthane.net/balon"
        assert registry.statuses == [("google_search_console", "healthy", None)]
        with harness.session() as session:
            rows = PerformanceService(session).snapshots_for(
                content_id, PerformanceProvider.GOOGLE_SEARCH_CONSOLE
            )
            summary = [row for row in rows if row.period_start != row.period_end]
            assert len(summary) == 1
            assert summary[0].metrics["top_queries"][0]["query"] == "balon temalı doğum günü"
            assert summary[0].metrics["impressions"] == 28 * 40
        # Redelivery on the same day converges: no duplicate rows.
        again = run(worker_app(harness, registry), SYNC_SEARCH_CONSOLE_TASK)
        assert again["snapshots"] == 0

    def test_not_configured_writes_nothing_and_persists_the_state(self, harness: Harness) -> None:
        with harness.session() as session:
            seed_published(session, remote_ref="https://konsepthane.net/balon")
            session.commit()
        registry = FakeRegistry({})
        result = run(worker_app(harness, registry), SYNC_SEARCH_CONSOLE_TASK)
        assert result["state"] == "not_configured"
        assert result["snapshots"] == 0
        assert registry.statuses == [
            ("google_search_console", "not_configured", "google_search_console_not_configured")
        ]
        with harness.session() as session:
            assert session.execute(select(ContentPerformanceSnapshot)).scalars().all() == []

    @pytest.mark.parametrize(
        ("failure", "expected_state", "expected_class"),
        [
            (ProviderFailure("rate_limited", "gsc_http_429"), "rate_limited", "gsc_http_429"),
            (ProviderFailure("access_required", "gsc_http_403"), "access_required", "gsc_http_403"),
            (TimeoutError("read timed out at https://secret"), "degraded", "TimeoutError"),
            (RuntimeError("boom"), "error", "RuntimeError"),
        ],
    )
    def test_provider_failures_are_bounded_and_never_crash(
        self, harness: Harness, failure: Exception, expected_state: str, expected_class: str
    ) -> None:
        with harness.session() as session:
            seed_published(session, remote_ref="https://konsepthane.net/balon")
            session.commit()
        registry = FakeRegistry({"google_search_console": FakeSearchConsole(failure)})
        result = run(worker_app(harness, registry), SYNC_SEARCH_CONSOLE_TASK)
        assert result["state"] == expected_state
        assert result["error_class"] == expected_class
        assert "secret" not in str(result)
        assert registry.statuses[-1] == ("google_search_console", expected_state, expected_class)

    def test_missing_integration_layer_is_an_honest_summary(self, harness: Harness) -> None:
        from contentos.worker.performance_tasks import IntegrationsUnavailableError

        def factory() -> Any:
            raise IntegrationsUnavailableError("ImportError")

        resolved = settings()
        runtime = WorkerRuntime(resolved, session_factory=harness.session_factory)
        app = create_celery_app(resolved)
        register_performance_tasks(app, runtime, registry_factory=factory)
        result = run(app, SYNC_SEARCH_CONSOLE_TASK)
        assert result["state"] == "not_configured"
        assert result["error_class"].startswith("integrations_unavailable")


class TestOtherSyncs:
    def test_analytics_and_market_signals(self, harness: Harness) -> None:
        with harness.session() as session:
            content = seed_published(session, remote_ref="https://konsepthane.net/balon")
            session.commit()
            content_id = content.id
        registry = FakeRegistry(
            {
                "google_search_console": FakeSearchConsole(),
                "google_analytics": FakeAnalytics(),
                "semrush": FakeSemrush(),
                "google_trends": FakeTrends(),
                "pinterest_trends": ProviderFailure("access_required", "pinterest_http_401"),
            }
        )
        app = worker_app(harness, registry)
        # Market signals need REAL queries first: nothing is asked before GSC.
        before = run(app, REFRESH_MARKET_SIGNALS_TASK)
        assert before["contents"] == 0 and before["snapshots"] == 0
        assert run(app, SYNC_SEARCH_CONSOLE_TASK)["state"] == "healthy"
        analytics = run(app, SYNC_ANALYTICS_TASK)
        assert analytics["state"] == "healthy" and analytics["snapshots"] == 29
        market = run(app, REFRESH_MARKET_SIGNALS_TASK)
        assert market["contents"] == 1
        assert market["providers"]["semrush"]["snapshots"] == 1
        assert market["providers"]["google_trends"]["snapshots"] == 1
        assert market["providers"]["pinterest_trends"]["state"] == "access_required"
        with harness.session() as session:
            service = PerformanceService(session)
            semrush = service.snapshots_for(content_id, PerformanceProvider.SEMRUSH)
            assert semrush[0].metrics["keywords"][0]["keyword"] == "balon temalı doğum günü"
            trends = service.snapshots_for(content_id, PerformanceProvider.GOOGLE_TRENDS)
            assert trends[0].metrics["terms"][0]["direction"] == "rising"
            assert service.snapshots_for(content_id, PerformanceProvider.PINTEREST_TRENDS) == []
        # Cache-aware: a second run on the same day asks nothing new.
        assert run(app, REFRESH_MARKET_SIGNALS_TASK)["snapshots"] == 0


class TestLearnTasks:
    def test_assess_detect_and_sync_all_run_end_to_end(self, harness: Harness) -> None:
        with harness.session() as session:
            content = seed_published(session)
            write_daily(session, content, declining_points())
            session.commit()
            content_id = content.id
        app = worker_app(harness, FakeRegistry({}))
        assert run(app, ASSESS_TASK)["assessments"] == 3
        assert run(app, DETECT_REFRESH_TASK)["proposed"] == 1
        with harness.session() as session:
            row = session.execute(select(RefreshOpportunity)).scalar_one()
            assert row.published_content_id == content_id
            assert row.status is RefreshStatus.PROPOSED
        summary = run(app, SYNC_ALL_TASK)
        assert set(summary) == {
            "search_console",
            "analytics",
            "market",
            "assess",
            "detect_refresh",
            "aggregate_history",
            "suggest_strategy",
        }
        assert summary["detect_refresh"]["proposed"] == 0

    def test_task_failures_are_bounded_summaries(self, harness: Harness) -> None:
        def factory() -> Any:
            raise RuntimeError("registry exploded")

        resolved = settings()
        runtime = WorkerRuntime(resolved, session_factory=harness.session_factory)
        app = create_celery_app(resolved)
        register_performance_tasks(app, runtime, registry_factory=factory)
        result = run(app, SYNC_ANALYTICS_TASK)
        assert result == {"status": "failed", "error_type": "RuntimeError"}


class TestScheduleAndRegistration:
    def test_worker_app_registers_every_performance_task(self) -> None:
        app = create_worker_app(settings())
        for name in PERFORMANCE_TASK_NAMES:
            assert name in app.tasks

    def test_beat_schedule_is_present_when_enabled_and_absent_when_disabled(self) -> None:
        enabled = create_celery_app(settings(performance_schedule_enabled=True))
        schedule = enabled.conf.beat_schedule
        assert {entry["task"] for entry in schedule.values()} == (
            set(PERFORMANCE_TASK_NAMES) - {SYNC_ALL_TASK}
        ) | {"contentos.trends.sync_google_trends_bigquery"}
        assert str(schedule["performance-sync-search-console"]["schedule"]).startswith("<crontab")
        disabled = create_celery_app(settings(performance_schedule_enabled=False))
        assert not disabled.conf.beat_schedule

    def test_schedule_hours_come_from_settings(self) -> None:
        schedule = performance_beat_schedule(
            settings(performance_sync_hour_utc=5, performance_market_interval_hours=12)
        )
        assert schedule["performance-sync-search-console"]["schedule"].hour == {5}
        assert schedule["performance-refresh-market-signals"]["schedule"] == timedelta(hours=12)

    def test_beat_arguments_add_a_writable_schedule_file(self) -> None:
        assert beat_arguments(["beat"]) == [
            "beat",
            "--schedule",
            "/tmp/celerybeat-schedule",
            "--loglevel=INFO",
        ]
        assert beat_arguments(["beat", "--schedule=/data/s", "--loglevel=DEBUG"]) == [
            "beat",
            "--schedule=/data/s",
            "--loglevel=DEBUG",
        ]

    def test_classification_uses_the_provider_error_contract(self) -> None:
        from contentos.integrations.base import ProviderError, ProviderNotConfiguredError
        from contentos.integrations.enums import ProviderName, ProviderState

        assert classify_provider_error(ProviderNotConfiguredError(ProviderName.SEMRUSH)) == (
            "not_configured",
            "semrush_not_configured",
        )
        rate = ProviderError("x", kind=ProviderState.RATE_LIMITED, error_class="semrush_http_429")
        assert classify_provider_error(rate) == ("rate_limited", "semrush_http_429")
        assert classify_provider_error(TimeoutError()) == ("degraded", "TimeoutError")

    def test_now_is_injectable_for_deterministic_windows(self, harness: Harness) -> None:
        from contentos.worker.performance_tasks import PerformanceSyncRunner

        with harness.session() as session:
            seed_published(session, remote_ref="https://konsepthane.net/balon")
            session.commit()
        gsc = FakeSearchConsole()
        runtime = WorkerRuntime(settings(), session_factory=harness.session_factory)
        runner = PerformanceSyncRunner(
            runtime, lambda: FakeRegistry({"google_search_console": gsc})
        )
        result = runner.sync_search_console(now=datetime.combine(TODAY, NOW.timetz()))
        assert result["snapshots"] == 29
