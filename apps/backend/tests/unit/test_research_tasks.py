"""Celery research-pipeline orchestration tests (eager mode, no broker)."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from celery import Celery
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contentos.core.config import Environment, LogLevel, Settings
from contentos.db.base import Base
from contentos.discovery.enums import DiscoveryLifecycleState
from contentos.discovery.models import DiscoveryItem
from contentos.discovery.service import DiscoveryService
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.duplicates.service import DuplicateDecisionService
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshots import FetchSnapshot
from contentos.normalization.enums import NormalizationStatus
from contentos.normalization.models import NormalizedDocument
from contentos.payloads.postgres import RawPayloadBlob
from contentos.queue.celery import create_celery_app
from contentos.research.models import ResearchEvidence
from contentos.sources.enums import DiscoveryStrategy, SourceKind, SourceLifecycleState, TrustTier
from contentos.sources.models import Source
from contentos.sources.service import SourceRegistryService
from contentos.worker.main import create_worker_app
from contentos.worker.research_tasks import (
    BASE_RETRY_SECONDS,
    DISCOVER_SOURCE_TASK,
    EVALUATE_DUPLICATE_TASK,
    EXTRACT_RESEARCH_EVIDENCE_TASK,
    FETCH_DISCOVERY_ITEM_TASK,
    MAX_RETRIES,
    MAX_RETRY_SECONDS,
    NORMALIZE_FETCH_TASK,
    RESEARCH_TASK_NAMES,
    CeleryPipelineDispatcher,
    InvalidPipelineInputError,
    _retry_countdown,
    register_research_pipeline_tasks,
)
from contentos.worker.runtime import WorkerRuntime

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

ARTICLE_HTML = (
    "<html><head><title>İstanbul Rehberi</title>"
    '<meta name="author" content="Ayşe Yılmaz">'
    '<meta property="article:published_time" content="2026-08-30T09:30:00+00:00">'
    "</head><body><p>İstanbul'da kutlama 🎉 başladı. Şehirde etkinlik programı "
    "gün boyu sürecek ve detaylar burada uzun uzun anlatılıyor.</p></body></html>"
).encode()

FEED_XML = (
    '<rss version="2.0"><channel><title>Örnek Kaynak</title>'
    "<item><title>Yeni Konu</title>"
    "<link>https://feed-site.example.test/haber/yeni-konu</link></item>"
    "</channel></rss>"
).encode()

SITEMAP_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    b"<url><loc>https://map-site.example.test/haber/harita-konu</loc></url>"
    b"</urlset>"
)


def eager_settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        service_name="ContentOS Pipeline Test",
        application_version="1.0.0-test",
        log_level=LogLevel.INFO,
        api_docs_enabled=False,
        celery_task_always_eager=True,
        celery_broker_connection_retry_on_startup=False,
    )


class FakeFetchClient:
    """Deterministic offline fetch client; sequenced responses per URL."""

    def __init__(self, responses: dict[str, list[FetchResult]]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def __enter__(self) -> "FakeFetchClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        queue = self._responses[url]
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    def enqueue(self, task_name: str, entity_id: str, *, request_id: str | None = None) -> None:
        self.calls.append((task_name, entity_id, request_id))


class FailingOnceDispatcher(RecordingDispatcher):
    def __init__(self) -> None:
        super().__init__()
        self.failures = 0

    def enqueue(self, task_name: str, entity_id: str, *, request_id: str | None = None) -> None:
        if not self.calls and self.failures == 0:
            self.failures += 1
            raise ConnectionError("broker publish failed")
        super().enqueue(task_name, entity_id, request_id=request_id)


def success_result(url: str, body: bytes, content_type: str) -> FetchResult:
    return FetchResult(
        requested_url=url,
        outcome=FetchOutcome.SUCCESS,
        retry=RetryClassification.NOT_APPLICABLE,
        robots_decision=RobotsDecision.ALLOWED,
        fetched_at=NOW,
        duration_ms=2.0,
        final_url=url,
        status_code=200,
        content_type=content_type,
        body=body,
    )


def failure_result(
    url: str,
    outcome: FetchOutcome = FetchOutcome.TIMEOUT,
    retry: RetryClassification = RetryClassification.RETRYABLE,
    retry_after_seconds: float | None = None,
) -> FetchResult:
    return FetchResult(
        requested_url=url,
        outcome=outcome,
        retry=retry,
        robots_decision=RobotsDecision.ALLOWED,
        fetched_at=NOW,
        duration_ms=2.0,
        failure_detail=outcome.value,
        retry_after_seconds=retry_after_seconds,
    )


def _postgres_faithful_sqlite_engine() -> Engine:
    """SQLite engine adjusted to mirror PostgreSQL transactional semantics.

    pysqlite's legacy mode implicitly commits around SAVEPOINT statements,
    which would silently break the project's begin_nested()/rollback contract
    in tests only; disabling driver transaction handling and emitting BEGIN
    explicitly is the SQLAlchemy-documented correction.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _disable_driver_transactions(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _emit_begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    return engine


class Harness:
    """One shared in-memory database plus an eager Celery pipeline app."""

    def __init__(self) -> None:
        self.engine = _postgres_faithful_sqlite_engine()
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

        # SQLite returns timezone-naive datetimes; PostgreSQL timestamptz is
        # always aware. Restore UTC awareness on load (harness sessions only)
        # so cross-session equality comparisons behave as in production.
        @event.listens_for(self.session_factory, "loaded_as_persistent")
        def _restore_utc_awareness(_session: Session, instance: Any) -> None:
            for key, value in list(instance.__dict__.items()):
                if isinstance(value, datetime) and value.tzinfo is None:
                    instance.__dict__[key] = value.replace(tzinfo=UTC)

        self.settings = eager_settings()
        self.fetch_client = FakeFetchClient({})
        self.runtime = WorkerRuntime(
            self.settings,
            session_factory=self.session_factory,
            fetch_client_factory=lambda: self.fetch_client,
        )

    def app(self, dispatcher: RecordingDispatcher | None = None) -> Celery:
        celery_app = create_celery_app(self.settings)
        register_research_pipeline_tasks(celery_app, self.runtime, dispatcher=dispatcher)
        return celery_app

    def session(self) -> Session:
        return self.session_factory()

    def make_source(
        self,
        slug: str,
        *,
        kind: SourceKind = SourceKind.MANUAL,
        strategy: DiscoveryStrategy | None = None,
        base_url: str,
    ) -> Source:
        with self.session() as session:
            source = SourceRegistryService(session).register_source(
                slug=slug,
                name=f"Kaynak {slug}",
                kind=kind,
                base_url=base_url,
                trust_tier=TrustTier.GENERAL,
                discovery_strategy=strategy,
            )
            session.commit()
            return source

    def make_accepted_item(self, source: Source, url: str) -> DiscoveryItem:
        with self.session() as session:
            service = DiscoveryService(session)
            item = service.discover_manual(source.id, url)
            service.accept_item(item.id)
            session.commit()
            return item

    def transition_source(self, source: Source, state: SourceLifecycleState) -> None:
        with self.session() as session:
            SourceRegistryService(session).transition_source_state(
                source.id, state, reason="test transition"
            )
            session.commit()

    def count(self, model: type[Any]) -> int:
        with self.session() as session:
            return session.scalar(select(func.count()).select_from(model)) or 0

    def get_item(self, item_id: uuid.UUID) -> DiscoveryItem:
        with self.session() as session:
            item = session.get(DiscoveryItem, item_id)
            assert item is not None
            return item


@pytest.fixture()
def harness() -> Iterator[Harness]:
    instance = Harness()
    yield instance
    instance.engine.dispose()


def run(app: Celery, task_name: str, argument: str) -> Any:
    """Execute a registered task eagerly, tolerating eager Retry propagation."""
    try:
        return app.tasks[task_name].apply(args=[argument])
    except BaseException:  # eager retry chains may re-raise through the stack
        return None


class TestRegistrationAndPolicy:
    def test_worker_app_registers_all_five_stable_task_names(self) -> None:
        app = create_worker_app(eager_settings())

        assert RESEARCH_TASK_NAMES == (
            "contentos.research.discover_source",
            "contentos.research.fetch_discovery_item",
            "contentos.research.normalize_fetch",
            "contentos.research.evaluate_duplicate",
            "contentos.research.extract_research_evidence",
        )
        for name in RESEARCH_TASK_NAMES:
            assert name in app.tasks
            assert app.tasks[name].acks_late is True
            assert app.tasks[name].reject_on_worker_lost is True
            assert app.tasks[name].max_retries == MAX_RETRIES

    def test_retry_policy_is_bounded_exponential_with_clamped_retry_after(self) -> None:
        assert MAX_RETRIES == 3
        assert _retry_countdown(0) == BASE_RETRY_SECONDS
        assert _retry_countdown(1) == BASE_RETRY_SECONDS * 2
        assert _retry_countdown(2) == BASE_RETRY_SECONDS * 4
        assert _retry_countdown(10) == MAX_RETRY_SECONDS
        assert _retry_countdown(0, retry_after_seconds=400.0) == 400.0
        assert _retry_countdown(0, retry_after_seconds=10.0) == BASE_RETRY_SECONDS
        assert _retry_countdown(0, retry_after_seconds=10_000.0) == MAX_RETRY_SECONDS
        assert _retry_countdown(0, retry_after_seconds=-5.0) == BASE_RETRY_SECONDS
        assert _retry_countdown(0, retry_after_seconds=float("nan")) == BASE_RETRY_SECONDS

    def test_invalid_uuid_argument_is_a_sanitized_terminal_failure(self, harness: Harness) -> None:
        app = harness.app(RecordingDispatcher())

        result = app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=["not-a-uuid"])

        assert isinstance(result.result, InvalidPipelineInputError)
        assert "not-a-uuid" not in str(result.result)

    def test_dispatcher_sends_headers_only_with_valid_request_id(self) -> None:
        recorded: list[dict[str, Any]] = []
        stub_task = SimpleNamespace(apply_async=lambda **kwargs: recorded.append(kwargs))
        app = SimpleNamespace(tasks={NORMALIZE_FETCH_TASK: stub_task})
        dispatcher = CeleryPipelineDispatcher(app)  # type: ignore[arg-type]

        dispatcher.enqueue(NORMALIZE_FETCH_TASK, "abc", request_id="req-1")
        dispatcher.enqueue(NORMALIZE_FETCH_TASK, "abc", request_id=None)

        assert recorded[0]["headers"] == {"request_id": "req-1"}
        assert recorded[1]["headers"] is None


class TestDiscoverSource:
    def test_feed_source_discovers_and_leaves_items_discovered(self, harness: Harness) -> None:
        source = harness.make_source(
            "feed-kaynak",
            kind=SourceKind.RSS_FEED,
            base_url="https://feed-site.example.test/feed.xml",
        )
        harness.fetch_client = FakeFetchClient(
            {source.base_url: [success_result(source.base_url, FEED_XML, "application/rss+xml")]}
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)

        result = app.tasks[DISCOVER_SOURCE_TASK].apply(args=[str(source.id)]).get()

        assert result["status"] == "completed"
        assert result["admitted_new"] == 1
        assert dispatcher.calls == []  # admission boundary: nothing auto-fetched
        with harness.session() as session:
            items = list(session.execute(select(DiscoveryItem)).scalars())
        assert len(items) == 1
        assert items[0].lifecycle_state is DiscoveryLifecycleState.DISCOVERED

    def test_sitemap_source_discovers_and_leaves_items_discovered(self, harness: Harness) -> None:
        source = harness.make_source(
            "map-kaynak",
            kind=SourceKind.SITEMAP,
            base_url="https://map-site.example.test/sitemap.xml",
        )
        harness.fetch_client = FakeFetchClient(
            {source.base_url: [success_result(source.base_url, SITEMAP_XML, "application/xml")]}
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)

        result = app.tasks[DISCOVER_SOURCE_TASK].apply(args=[str(source.id)]).get()

        assert result["status"] == "completed"
        assert result["admitted_new"] == 1
        assert dispatcher.calls == []
        with harness.session() as session:
            item = session.execute(select(DiscoveryItem)).scalar_one()
            assert item.lifecycle_state is DiscoveryLifecycleState.DISCOVERED

    def test_manual_and_inactive_sources_never_touch_the_network(self, harness: Harness) -> None:
        manual = harness.make_source("manuel", base_url="https://manuel.example.test/")
        feed = harness.make_source(
            "durdurulmus",
            kind=SourceKind.RSS_FEED,
            base_url="https://paused.example.test/feed.xml",
        )
        harness.transition_source(feed, SourceLifecycleState.PAUSED)
        app = harness.app(RecordingDispatcher())

        manual_result = app.tasks[DISCOVER_SOURCE_TASK].apply(args=[str(manual.id)]).get()
        paused_result = app.tasks[DISCOVER_SOURCE_TASK].apply(args=[str(feed.id)]).get()

        assert manual_result == {
            "status": "skipped",
            "next_task": None,
            "source_id": str(manual.id),
            "reason": "manual_source",
        }
        assert paused_result["reason"] == "source_not_active"
        assert harness.fetch_client.calls == []

    def test_retryable_feed_failure_retries_with_bounds(self, harness: Harness) -> None:
        source = harness.make_source(
            "retry-feed",
            kind=SourceKind.RSS_FEED,
            base_url="https://retry-feed.example.test/feed.xml",
        )
        harness.fetch_client = FakeFetchClient(
            {source.base_url: [failure_result(source.base_url, FetchOutcome.TIMEOUT)]}
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        app = harness.app(RecordingDispatcher())

        run(app, DISCOVER_SOURCE_TASK, str(source.id))

        assert len(harness.fetch_client.calls) == MAX_RETRIES + 1

    def test_terminal_feed_failure_is_not_retried(self, harness: Harness) -> None:
        source = harness.make_source(
            "terminal-feed",
            kind=SourceKind.RSS_FEED,
            base_url="https://terminal-feed.example.test/feed.xml",
        )
        harness.fetch_client = FakeFetchClient(
            {
                source.base_url: [
                    failure_result(
                        source.base_url,
                        FetchOutcome.SSRF_BLOCKED,
                        RetryClassification.TERMINAL,
                    )
                ]
            }
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        app = harness.app(RecordingDispatcher())

        result = app.tasks[DISCOVER_SOURCE_TASK].apply(args=[str(source.id)])

        assert result.state == "FAILURE"
        assert len(harness.fetch_client.calls) == 1


def article_source_and_item(harness: Harness, slug: str) -> tuple[Source, DiscoveryItem, str]:
    url = f"https://{slug}.example.test/haber/konu"
    source = harness.make_source(slug, base_url=f"https://{slug}.example.test/")
    item = harness.make_accepted_item(source, url)
    return source, item, item.canonical_url


class TestFetchDiscoveryItem:
    def test_success_persists_payload_snapshot_and_dispatches_normalize(
        self, harness: Harness
    ) -> None:
        source, item, url = article_source_and_item(harness, "basari")
        harness.fetch_client = FakeFetchClient(
            {url: [success_result(url, ARTICLE_HTML, "text/html; charset=utf-8")]}
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)

        result = app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(item.id)]).get()

        assert result["status"] == "completed"
        assert result["next_task"] == NORMALIZE_FETCH_TASK
        assert harness.count(RawPayloadBlob) == 1
        assert harness.count(FetchSnapshot) == 1
        assert harness.get_item(item.id).lifecycle_state is DiscoveryLifecycleState.FETCHED
        assert len(dispatcher.calls) == 1
        assert dispatcher.calls[0][0] == NORMALIZE_FETCH_TASK
        assert dispatcher.calls[0][1] == result["fetch_snapshot_id"]

    def test_fetched_redelivery_reuses_snapshot_without_network(self, harness: Harness) -> None:
        source, item, url = article_source_and_item(harness, "tekrar")
        harness.fetch_client = FakeFetchClient(
            {url: [success_result(url, ARTICLE_HTML, "text/html; charset=utf-8")]}
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)

        first = app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(item.id)]).get()
        second = app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(item.id)]).get()

        assert second["status"] == "reused"
        assert second["fetch_snapshot_id"] == first["fetch_snapshot_id"]
        assert len(harness.fetch_client.calls) == 1
        assert harness.count(FetchSnapshot) == 1
        assert [call[0] for call in dispatcher.calls] == [
            NORMALIZE_FETCH_TASK,
            NORMALIZE_FETCH_TASK,
        ]

    def test_commit_survives_dispatch_failure_and_rerun_reuses_it(self, harness: Harness) -> None:
        source, item, url = article_source_and_item(harness, "yayinlama")
        harness.fetch_client = FakeFetchClient(
            {url: [success_result(url, ARTICLE_HTML, "text/html; charset=utf-8")]}
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        dispatcher = FailingOnceDispatcher()
        app = harness.app(dispatcher)

        run(app, FETCH_DISCOVERY_ITEM_TASK, str(item.id))

        # Commit happened before the failed enqueue: durable state survived
        # and the automatic dispatch retry reused it without a second fetch.
        assert harness.count(FetchSnapshot) == 1
        assert harness.get_item(item.id).lifecycle_state is DiscoveryLifecycleState.FETCHED
        assert len(harness.fetch_client.calls) == 1
        assert len(dispatcher.calls) == 1
        assert dispatcher.calls[0][0] == NORMALIZE_FETCH_TASK

    def test_failed_commit_prevents_downstream_dispatch(self, harness: Harness) -> None:
        source, item, url = article_source_and_item(harness, "cokme")
        harness.fetch_client = FakeFetchClient(
            {url: [success_result(url, ARTICLE_HTML, "text/html; charset=utf-8")]}
        )

        def failing_commit_factory() -> Session:
            session = harness.session_factory()

            def broken_commit() -> None:
                raise RuntimeError("commit failed")

            session.commit = broken_commit  # type: ignore[method-assign]
            return session

        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=failing_commit_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)

        result = app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(item.id)])

        assert result.state == "FAILURE"
        assert dispatcher.calls == []
        assert harness.count(FetchSnapshot) == 0
        assert harness.get_item(item.id).lifecycle_state is DiscoveryLifecycleState.ACCEPTED

    def test_retryable_failure_records_snapshots_requeues_and_exhausts(
        self, harness: Harness
    ) -> None:
        source, item, url = article_source_and_item(harness, "zamanasimi")
        harness.fetch_client = FakeFetchClient({url: [failure_result(url, FetchOutcome.TIMEOUT)]})
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)

        run(app, FETCH_DISCOVERY_ITEM_TASK, str(item.id))

        assert len(harness.fetch_client.calls) == MAX_RETRIES + 1
        assert harness.count(FetchSnapshot) == MAX_RETRIES + 1
        final_item = harness.get_item(item.id)
        assert final_item.lifecycle_state is DiscoveryLifecycleState.FETCH_FAILED
        assert final_item.metadata_json["last_requeue_reason"] == (
            "automatic retry of a retryable fetch failure"
        )
        assert dispatcher.calls == []

    def test_retryable_failure_then_success_recovers(self, harness: Harness) -> None:
        source, item, url = article_source_and_item(harness, "toparlanma")
        harness.fetch_client = FakeFetchClient(
            {
                url: [
                    failure_result(url, FetchOutcome.TIMEOUT),
                    success_result(url, ARTICLE_HTML, "text/html; charset=utf-8"),
                ]
            }
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)

        run(app, FETCH_DISCOVERY_ITEM_TASK, str(item.id))

        assert len(harness.fetch_client.calls) == 2
        assert harness.count(FetchSnapshot) == 2
        assert harness.get_item(item.id).lifecycle_state is DiscoveryLifecycleState.FETCHED
        assert [call[0] for call in dispatcher.calls] == [NORMALIZE_FETCH_TASK]

    def test_policy_terminal_failure_never_retries_or_dispatches(self, harness: Harness) -> None:
        source, item, url = article_source_and_item(harness, "politika")
        harness.fetch_client = FakeFetchClient(
            {url: [failure_result(url, FetchOutcome.SSRF_BLOCKED, RetryClassification.TERMINAL)]}
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)

        result = app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(item.id)]).get()

        assert result["status"] == "terminal"
        assert result["outcome"] == "ssrf_blocked"
        assert len(harness.fetch_client.calls) == 1
        assert harness.count(FetchSnapshot) == 1
        assert harness.get_item(item.id).lifecycle_state is DiscoveryLifecycleState.FETCH_FAILED
        assert dispatcher.calls == []

    def test_fetch_failed_redelivery_is_terminal_noop(self, harness: Harness) -> None:
        source, item, url = article_source_and_item(harness, "kalici")
        harness.fetch_client = FakeFetchClient(
            {
                url: [
                    failure_result(
                        url, FetchOutcome.ROBOTS_DISALLOWED, RetryClassification.TERMINAL
                    )
                ]
            }
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        app = harness.app(RecordingDispatcher())
        app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(item.id)]).get()

        redelivery = app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(item.id)]).get()

        assert redelivery["status"] == "terminal"
        assert redelivery["reason"] == "fetch_failed"
        assert len(harness.fetch_client.calls) == 1  # no resurrect, no new request

    def test_admission_boundary_and_source_gate_prevent_network(self, harness: Harness) -> None:
        source = harness.make_source("kapi", base_url="https://kapi.example.test/")
        with harness.session() as session:
            discovered = DiscoveryService(session).discover_manual(
                source.id, "https://kapi.example.test/haber/bekleyen"
            )
            session.commit()
        accepted_source, accepted_item, url = article_source_and_item(harness, "kapali")
        harness.transition_source(accepted_source, SourceLifecycleState.PAUSED)
        app = harness.app(RecordingDispatcher())

        discovered_result = (
            app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(discovered.id)]).get()
        )
        paused_result = (
            app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(accepted_item.id)]).get()
        )

        assert discovered_result["reason"] == "item_discovered"
        assert paused_result["reason"] == "source_not_active"
        assert harness.fetch_client.calls == []

    def test_request_id_header_is_propagated_downstream(self, harness: Harness) -> None:
        source, item, url = article_source_and_item(harness, "korelasyon")
        harness.fetch_client = FakeFetchClient(
            {url: [success_result(url, ARTICLE_HTML, "text/html; charset=utf-8")]}
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)

        app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(
            args=[str(item.id)], headers={"request_id": "pipeline-req-1"}
        ).get()

        assert dispatcher.calls[0][2] == "pipeline-req-1"


def committed_success_snapshot(
    harness: Harness,
    slug: str,
    body: bytes,
    content_type: str = "text/html; charset=utf-8",
) -> FetchSnapshot:
    from contentos.fetching.snapshot_service import FetchSnapshotService

    source, item, url = article_source_and_item(harness, slug)
    with harness.session() as session:
        store = harness.runtime.create_payload_store(session)
        stored = store.put(body)
        snapshot = FetchSnapshotService(session).record_fetch_result(
            item.id,
            success_result(url, body, content_type),
            raw_payload_ref=stored.ref.value,
        )
        session.commit()
        return snapshot


class TestNormalizeEvaluateExtract:
    def test_normalize_success_dispatches_duplicate_evaluation(self, harness: Harness) -> None:
        snapshot = committed_success_snapshot(harness, "normalize", ARTICLE_HTML)
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)

        result = app.tasks[NORMALIZE_FETCH_TASK].apply(args=[str(snapshot.id)]).get()

        assert result["status"] == "completed"
        assert result["next_task"] == EVALUATE_DUPLICATE_TASK
        assert harness.count(NormalizedDocument) == 1
        assert dispatcher.calls[0][0] == EVALUATE_DUPLICATE_TASK

    def test_normalize_rerun_is_idempotent_and_redispatches(self, harness: Harness) -> None:
        snapshot = committed_success_snapshot(harness, "yenidennormalize", ARTICLE_HTML)
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)

        first = app.tasks[NORMALIZE_FETCH_TASK].apply(args=[str(snapshot.id)]).get()
        second = app.tasks[NORMALIZE_FETCH_TASK].apply(args=[str(snapshot.id)]).get()

        assert first["normalized_document_id"] == second["normalized_document_id"]
        assert harness.count(NormalizedDocument) == 1
        assert len(dispatcher.calls) == 2

    def test_normalization_failure_does_not_dispatch_downstream(self, harness: Harness) -> None:
        snapshot = committed_success_snapshot(
            harness, "desteklenmeyen", b"%PDF-1.7 fake", content_type="application/pdf"
        )
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)

        result = app.tasks[NORMALIZE_FETCH_TASK].apply(args=[str(snapshot.id)]).get()

        assert result["result"] == "normalization_failed"
        assert result["next_task"] is None
        assert dispatcher.calls == []
        with harness.session() as session:
            document = session.execute(select(NormalizedDocument)).scalar_one()
            assert document.normalization_status is NormalizationStatus.FAILED

    def test_missing_snapshot_is_terminal(self, harness: Harness) -> None:
        app = harness.app(RecordingDispatcher())

        result = app.tasks[NORMALIZE_FETCH_TASK].apply(args=[str(uuid.uuid4())])

        assert result.state == "FAILURE"

    @pytest.mark.parametrize(
        ("outcome", "expects_evidence"),
        [
            (DuplicateDecisionOutcome.UNIQUE, True),
            (DuplicateDecisionOutcome.RELATED, True),
            (DuplicateDecisionOutcome.UPDATE_EXISTING, True),
            (DuplicateDecisionOutcome.DUPLICATE, False),
            (DuplicateDecisionOutcome.REJECT, False),
        ],
    )
    def test_duplicate_outcome_gate(
        self,
        harness: Harness,
        monkeypatch: pytest.MonkeyPatch,
        outcome: DuplicateDecisionOutcome,
        expects_evidence: bool,
    ) -> None:
        document_id = uuid.uuid4()
        stub_decision = SimpleNamespace(decision=outcome, id=uuid.uuid4())
        monkeypatch.setattr(
            DuplicateDecisionService,
            "evaluate_and_record",
            lambda self, did: stub_decision,
        )
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)

        result = app.tasks[EVALUATE_DUPLICATE_TASK].apply(args=[str(document_id)]).get()

        assert result["decision"] == outcome.value
        if expects_evidence:
            assert dispatcher.calls[0][0] == EXTRACT_RESEARCH_EVIDENCE_TASK
            assert result["next_task"] == EXTRACT_RESEARCH_EVIDENCE_TASK
        else:
            assert dispatcher.calls == []
            assert result["next_task"] is None

    def test_evidence_task_is_idempotent_terminal_stage(self, harness: Harness) -> None:
        snapshot = committed_success_snapshot(harness, "kanit", ARTICLE_HTML)
        dispatcher = RecordingDispatcher()
        app = harness.app(dispatcher)
        normalize = app.tasks[NORMALIZE_FETCH_TASK].apply(args=[str(snapshot.id)]).get()
        document_id = normalize["normalized_document_id"]
        calls_before_evidence = list(dispatcher.calls)

        first = app.tasks[EXTRACT_RESEARCH_EVIDENCE_TASK].apply(args=[document_id]).get()
        second = app.tasks[EXTRACT_RESEARCH_EVIDENCE_TASK].apply(args=[document_id]).get()

        assert first["evidence_created"] == 2  # author + publication date
        assert second["evidence_created"] == 0
        assert second["evidence_existing"] == 2
        assert first["next_task"] is None
        assert harness.count(ResearchEvidence) == 2
        assert dispatcher.calls == calls_before_evidence  # terminal stage adds none


class TestFullPipeline:
    def test_synthetic_end_to_end_chain_and_redelivery(self, harness: Harness) -> None:
        source, item, url = article_source_and_item(harness, "boruhatti")
        harness.fetch_client = FakeFetchClient(
            {url: [success_result(url, ARTICLE_HTML, "text/html; charset=utf-8")]}
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        app = harness.app()  # real dispatcher: eager mode chains inline

        result = app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(item.id)]).get()

        assert result["status"] == "completed"
        assert harness.count(RawPayloadBlob) == 1
        assert harness.count(FetchSnapshot) == 1
        assert harness.count(NormalizedDocument) == 1
        assert harness.count(DuplicateDecision) == 1
        assert harness.count(ResearchEvidence) == 2
        with harness.session() as session:
            document = session.execute(select(NormalizedDocument)).scalar_one()
            decision = session.execute(select(DuplicateDecision)).scalar_one()
            evidence = list(session.execute(select(ResearchEvidence)).scalars())
            snapshot = session.execute(select(FetchSnapshot)).scalar_one()
            assert document.normalization_status is NormalizationStatus.SUCCEEDED
            assert decision.normalized_document_id == document.id
            assert decision.decision is DuplicateDecisionOutcome.UNIQUE
            for row in evidence:
                assert row.normalized_document_id == document.id
                assert row.fetch_snapshot_id == snapshot.id
                assert row.source_id == source.id

        redelivery = app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(item.id)]).get()

        assert redelivery["status"] == "reused"
        assert len(harness.fetch_client.calls) == 1  # no second HTTP request
        assert harness.count(RawPayloadBlob) == 1
        assert harness.count(FetchSnapshot) == 1
        assert harness.count(NormalizedDocument) == 1
        assert harness.count(DuplicateDecision) == 1
        assert harness.count(ResearchEvidence) == 2

    def test_duplicate_content_stops_before_evidence(self, harness: Harness) -> None:
        first_source, first_item, first_url = article_source_and_item(harness, "birinci")
        second_source, second_item, second_url = article_source_and_item(harness, "ikinci")
        harness.fetch_client = FakeFetchClient(
            {
                first_url: [success_result(first_url, ARTICLE_HTML, "text/html; charset=utf-8")],
                second_url: [success_result(second_url, ARTICLE_HTML, "text/html; charset=utf-8")],
            }
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=harness.session_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        app = harness.app()

        app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(first_item.id)]).get()
        app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(second_item.id)]).get()

        with harness.session() as session:
            decisions = list(session.execute(select(DuplicateDecision)).scalars())
            documents = list(session.execute(select(NormalizedDocument)).scalars())
        assert len(decisions) == 2
        outcomes = {decision.decision for decision in decisions}
        assert DuplicateDecisionOutcome.DUPLICATE in outcomes
        duplicate_document_ids = {
            decision.normalized_document_id
            for decision in decisions
            if decision.decision is DuplicateDecisionOutcome.DUPLICATE
        }
        with harness.session() as session:
            evidence = list(session.execute(select(ResearchEvidence)).scalars())
        assert len(evidence) == 2  # only the first (unique) document produced evidence
        assert all(row.normalized_document_id not in duplicate_document_ids for row in evidence)
        assert len(documents) == 2


class TestSessionSafety:
    def test_sessions_are_always_closed(self, harness: Harness) -> None:
        closes: list[bool] = []
        real_factory = harness.session_factory

        def tracking_factory() -> Session:
            session = real_factory()
            original_close = session.close

            def tracked_close() -> None:
                closes.append(True)
                original_close()

            session.close = tracked_close  # type: ignore[method-assign]
            return session

        source, item, url = article_source_and_item(harness, "oturum")
        harness.fetch_client = FakeFetchClient(
            {url: [success_result(url, ARTICLE_HTML, "text/html; charset=utf-8")]}
        )
        harness.runtime = WorkerRuntime(
            harness.settings,
            session_factory=tracking_factory,
            fetch_client_factory=lambda: harness.fetch_client,
        )
        app = harness.app(RecordingDispatcher())

        app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(item.id)]).get()
        # A failing task (missing item) must still roll back and close.
        app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=[str(uuid.uuid4())])
        # An invalid UUID fails before any session is created.
        app.tasks[FETCH_DISCOVERY_ITEM_TASK].apply(args=["not-a-uuid"])

        assert len(closes) == 2
