"""Autonomous intake: prefilter, run lifecycle, and the bounded step."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from test_sitemap_discovery import (
    SITEMAP_URL,
    FakeFetchClient,
    make_source,
    successful_fetch,
    urlset,
)

from contentos.db.base import Base
from contentos.discovery.enums import DiscoveryLifecycleState, DiscoveryRejectionReason
from contentos.discovery.models import DiscoveryItem
from contentos.discovery.service import DiscoveryService
from contentos.intake.enums import IntakeEventKind, IntakeRunStatus
from contentos.intake.errors import IntakeRunConflictError, IntakeSourceNotEligibleError
from contentos.intake.models import IntakeRunEvent
from contentos.intake.orchestrator import IntakeOrchestrator
from contentos.intake.prefilter import classify_url
from contentos.intake.service import IntakePolicy, IntakeRunService
from contentos.operations.enums import PauseScope
from contentos.operations.service import OperationsService
from contentos.sources.enums import SourceKind, SourceLifecycleState

POLICY = IntakePolicy(
    prefilter_batch_size=100,
    fetch_batch_size=2,
    max_fetches_per_run=4,
    daily_fetch_budget_per_source=100,
    max_promotions_per_run=5,
    step_interval_seconds=15,
)


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session
    engine.dispose()


def factory_for(client: FakeFetchClient) -> Any:
    @contextmanager
    def _factory() -> Iterator[FakeFetchClient]:
        yield client

    return _factory


def article_urls(count: int) -> list[str]:
    return [f"https://www.example.test/parti-fikri-{index}" for index in range(count)]


class TestPrefilter:
    @pytest.mark.parametrize(
        ("url", "rule"),
        [
            ("https://x.test/tag/frozen", "listing:tag"),
            ("https://x.test/category/dogum-gunu/", "listing:category"),
            ("https://x.test/author/kara", "listing:author"),
            ("https://x.test/page/4", "listing:page"),
            ("https://x.test/feed", "listing:feed"),
            ("https://x.test/shop/urun", "listing:shop"),
            ("https://x.test/hero.jpg", "asset_extension"),
            ("https://x.test/sitemap.xml", "asset_extension"),
            ("https://x.test/", "site_root"),
            ("https://x.test/about", "utility:about"),
            ("https://x.test/privacy-policy.html", "utility:privacy-policy"),
            ("https://x.test/2024/05", "date_archive"),
            ("ftp://x.test/dosya", "scheme"),
        ],
    )
    def test_rejects_non_article_urls_with_named_rules(self, url: str, rule: str) -> None:
        decision = classify_url(url)
        assert decision is not None
        assert decision.rule == rule

    @pytest.mark.parametrize(
        "url",
        [
            "https://x.test/frozen-birthday-party",
            "https://x.test/2024/05/frozen-birthday-party.html",
            "https://x.test/rehber/ev-partisi",
        ],
    )
    def test_accepts_article_urls(self, url: str) -> None:
        assert classify_url(url) is None


class TestRunLifecycle:
    def test_start_requires_active_automated_source(self, session: Session) -> None:
        source = make_source(session)
        source.lifecycle_state = SourceLifecycleState.PAUSED
        session.flush()
        with pytest.raises(IntakeSourceNotEligibleError):
            IntakeRunService(session).start_run(source.id, policy=POLICY, actor_user_id=None)

    def test_start_refuses_manual_sources(self, session: Session) -> None:
        from contentos.sources.enums import DiscoveryStrategy

        source = make_source(session, kind=SourceKind.MANUAL, strategy=DiscoveryStrategy.MANUAL)
        with pytest.raises(IntakeSourceNotEligibleError):
            IntakeRunService(session).start_run(source.id, policy=POLICY, actor_user_id=None)

    def test_one_live_run_per_source(self, session: Session) -> None:
        source = make_source(session)
        service = IntakeRunService(session)
        run = service.start_run(source.id, policy=POLICY, actor_user_id=None)
        with pytest.raises(IntakeRunConflictError):
            service.start_run(source.id, policy=POLICY, actor_user_id=None)
        service.pause_run(run.id, reason="mola", actor_user_id=None)
        with pytest.raises(IntakeRunConflictError):
            service.start_run(source.id, policy=POLICY, actor_user_id=None)
        service.stop_run(run.id, reason="bitti", actor_user_id=None)
        second = service.start_run(source.id, policy=POLICY, actor_user_id=None)
        assert second.id != run.id

    def test_lifecycle_events_are_recorded(self, session: Session) -> None:
        source = make_source(session)
        service = IntakeRunService(session)
        run = service.start_run(source.id, policy=POLICY, actor_user_id=None)
        service.pause_run(run.id, reason="mola", actor_user_id=None)
        service.resume_run(run.id, reason="devam", actor_user_id=None)
        kinds = [event.kind for event in reversed(service.events_for(run.id))]
        assert kinds == [
            IntakeEventKind.RUN_STARTED,
            IntakeEventKind.RUN_PAUSED,
            IntakeEventKind.RUN_RESUMED,
        ]


def seeded_run(session: Session, urls: list[str]) -> tuple[Any, Any, FakeFetchClient]:
    source = make_source(session)
    client = FakeFetchClient(
        {SITEMAP_URL: successful_fetch(SITEMAP_URL, urlset(*[(url, None) for url in urls]))}
    )
    run = IntakeRunService(session).start_run(source.id, policy=POLICY, actor_user_id=None)
    return source, run, client


class TestOrchestrator:
    def test_discovery_then_prefilter_then_bounded_fetch(self, session: Session) -> None:
        urls = article_urls(3) + [
            "https://www.example.test/tag/frozen",
            "https://www.example.test/logo.png",
        ]
        source, run, client = seeded_run(session, urls)
        orchestrator = IntakeOrchestrator(session, fetch_client_factory=factory_for(client))

        outcome = orchestrator.advance(run.id)
        assert outcome.action == "reschedule"
        assert run.discovery_completed_at is not None
        assert run.discovered_new == 5

        outcome = orchestrator.advance(run.id)
        assert outcome.action == "reschedule"
        assert run.prefilter_completed_at is not None
        assert run.prefilter_accepted == 3
        assert run.prefilter_rejected == 2
        rejected = session.scalars(
            select(DiscoveryItem).where(
                DiscoveryItem.lifecycle_state == DiscoveryLifecycleState.REJECTED
            )
        ).all()
        assert {item.rejection_reason for item in rejected} == {
            DiscoveryRejectionReason.OUT_OF_SCOPE
        }
        assert all((item.rejection_note or "").startswith("intake prefilter:") for item in rejected)

        outcome = orchestrator.advance(run.id)
        assert outcome.action == "waiting"
        assert len(outcome.fetch_dispatches) == 2  # batch size bound
        assert run.fetch_dispatched == 2

    def test_step_is_idempotent_while_fetches_are_in_flight(self, session: Session) -> None:
        source, run, client = seeded_run(session, article_urls(3))
        orchestrator = IntakeOrchestrator(session, fetch_client_factory=factory_for(client))
        orchestrator.advance(run.id)  # discovery
        orchestrator.advance(run.id)  # prefilter
        first = orchestrator.advance(run.id)
        assert len(first.fetch_dispatches) == 2
        # A duplicate step while the batch is in flight dispatches NOTHING new.
        repeat = orchestrator.advance(run.id)
        assert repeat.action == "waiting"
        assert repeat.fetch_dispatches == ()
        assert run.fetch_dispatched == 2

    def test_fetch_outcomes_roll_forward_and_run_completes(self, session: Session) -> None:
        source, run, client = seeded_run(session, article_urls(2))
        orchestrator = IntakeOrchestrator(session, fetch_client_factory=factory_for(client))
        orchestrator.advance(run.id)
        orchestrator.advance(run.id)
        dispatched = orchestrator.advance(run.id)
        discovery = DiscoveryService(session)
        for raw_id in dispatched.fetch_dispatches:
            discovery.mark_fetched(uuid.UUID(raw_id))
        outcome = orchestrator.advance(run.id)
        # No promotable documents exist (no normalization ran): completed.
        assert outcome.action == "done"
        assert run.status is IntakeRunStatus.COMPLETED
        assert run.fetched == 2
        kinds = {event.kind for event in IntakeRunService(session).events_for(run.id, limit=50)}
        assert IntakeEventKind.FETCH_COMPLETED in kinds
        assert IntakeEventKind.RUN_COMPLETED in kinds

    def test_run_cap_bounds_total_fetches(self, session: Session) -> None:
        source, run, client = seeded_run(session, article_urls(9))
        orchestrator = IntakeOrchestrator(session, fetch_client_factory=factory_for(client))
        orchestrator.advance(run.id)
        orchestrator.advance(run.id)
        discovery = DiscoveryService(session)
        total = 0
        for _ in range(5):
            outcome = orchestrator.advance(run.id)
            total += len(outcome.fetch_dispatches)
            for raw_id in outcome.fetch_dispatches:
                discovery.mark_fetched(uuid.UUID(raw_id))
            if outcome.action == "done":
                break
        assert total == POLICY.max_fetches_per_run
        assert run.status is IntakeRunStatus.COMPLETED
        assert IntakeRunService(session).has_event(run.id, IntakeEventKind.FETCH_CAP_REACHED)
        # Remainder stays durable for a later run.
        remaining = int(
            session.scalar(
                select(func.count())
                .select_from(DiscoveryItem)
                .where(DiscoveryItem.lifecycle_state == DiscoveryLifecycleState.ACCEPTED)
            )
            or 0
        )
        assert remaining == 9 - POLICY.max_fetches_per_run

    def test_operational_research_pause_pauses_the_run(self, session: Session) -> None:
        source, run, client = seeded_run(session, article_urls(2))
        OperationsService(session).pause(PauseScope.RESEARCH, reason="bakım", actor_user_id=None)
        orchestrator = IntakeOrchestrator(session, fetch_client_factory=factory_for(client))
        outcome = orchestrator.advance(run.id)
        assert outcome.action == "halted"
        assert run.status is IntakeRunStatus.PAUSED
        assert IntakeRunService(session).has_event(run.id, IntakeEventKind.OPERATIONAL_PAUSE)

    def test_paused_run_does_nothing(self, session: Session) -> None:
        source, run, client = seeded_run(session, article_urls(2))
        IntakeRunService(session).pause_run(run.id, reason="mola", actor_user_id=None)
        orchestrator = IntakeOrchestrator(session, fetch_client_factory=factory_for(client))
        outcome = orchestrator.advance(run.id)
        assert outcome.action == "halted"
        assert run.discovery_completed_at is None

    def test_daily_budget_bounds_dispatch(self, session: Session) -> None:
        tight = IntakePolicy(
            prefilter_batch_size=100,
            fetch_batch_size=5,
            max_fetches_per_run=10,
            daily_fetch_budget_per_source=1,
            max_promotions_per_run=5,
            step_interval_seconds=15,
        )
        source = make_source(session)
        client = FakeFetchClient(
            {
                SITEMAP_URL: successful_fetch(
                    SITEMAP_URL, urlset(*[(url, None) for url in article_urls(3)])
                )
            }
        )
        run = IntakeRunService(session).start_run(source.id, policy=tight, actor_user_id=None)
        orchestrator = IntakeOrchestrator(session, fetch_client_factory=factory_for(client))
        orchestrator.advance(run.id, tight)
        orchestrator.advance(run.id, tight)
        first = orchestrator.advance(run.id, tight)
        assert len(first.fetch_dispatches) == 1  # daily budget bound
        DiscoveryService(session).mark_fetched(uuid.UUID(first.fetch_dispatches[0]))
        outcome = orchestrator.advance(run.id, tight)
        assert IntakeRunService(session).has_event(run.id, IntakeEventKind.FETCH_BUDGET_EXHAUSTED)
        assert outcome.action == "done"


class TestPromotePhase:
    def test_promotes_eligible_documents_and_counts_opportunities(self, session: Session) -> None:
        import hashlib
        from datetime import UTC, datetime

        from contentos.duplicates.enums import DuplicateDecisionOutcome
        from contentos.duplicates.models import DuplicateDecision
        from contentos.fetching.models import (
            FetchOutcome,
            FetchResult,
            RetryClassification,
            RobotsDecision,
        )
        from contentos.fetching.snapshot_service import FetchSnapshotService
        from contentos.normalization.service import NormalizationService

        now = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
        source, run, client = seeded_run(session, article_urls(1))
        orchestrator = IntakeOrchestrator(session, fetch_client_factory=factory_for(client))
        orchestrator.advance(run.id)  # discovery
        orchestrator.advance(run.id)  # prefilter
        dispatched = orchestrator.advance(run.id)
        item_id = uuid.UUID(dispatched.fetch_dispatches[0])
        item = session.get(DiscoveryItem, item_id)
        assert item is not None

        body = b"<html>parti fikri govdesi</html>"
        snapshot = FetchSnapshotService(session).record_fetch_result(
            item.id,
            FetchResult(
                requested_url=item.canonical_url,
                outcome=FetchOutcome.SUCCESS,
                retry=RetryClassification.NOT_APPLICABLE,
                robots_decision=RobotsDecision.ALLOWED,
                fetched_at=now,
                duration_ms=2.0,
                final_url=item.canonical_url,
                status_code=200,
                content_type="text/html; charset=utf-8",
                body=body,
            ),
            raw_payload_ref=f"memory:sha256:{hashlib.sha256(body).hexdigest()}",
        )
        document = NormalizationService(session).record_success(
            snapshot.id,
            extractor_name="html-basic",
            extractor_version="1",
            clean_text="parti fikri için uzun ve özgün araştırma metni.",
            title="Parti Fikri",
            headings=[],
        )
        session.add(
            DuplicateDecision(
                normalized_document_id=document.id,
                engine_name="duplicate-engine",
                engine_version="1",
                decision=DuplicateDecisionOutcome.UNIQUE,
                signals={},
                thresholds={},
                matches=[],
                rationale_codes=[],
                evaluated_at=now,
            )
        )
        session.flush()
        if session.get(DiscoveryItem, item_id).lifecycle_state is not (
            DiscoveryLifecycleState.FETCHED
        ):
            DiscoveryService(session).mark_fetched(item_id)

        outcome = orchestrator.advance(run.id)
        assert outcome.promote_dispatches == (str(document.id),)
        assert run.promotions_dispatched == 1
        # Re-advancing does not re-dispatch the same document.
        repeat = orchestrator.advance(run.id)
        assert repeat.promote_dispatches == ()

        # Simulate the promote task having run through the real service.
        from contentos.opportunities.service import ResearchPromotionService

        ResearchPromotionService(session).promote_research(document.id)
        session.flush()
        final = orchestrator.advance(run.id)
        assert run.opportunities_created == 1
        assert final.action == "done"
        assert run.status is IntakeRunStatus.COMPLETED
        completed = next(
            event
            for event in IntakeRunService(session).events_for(run.id, limit=50)
            if event.kind is IntakeEventKind.RUN_COMPLETED
        )
        assert completed.detail["opportunities_created"] == 1


def test_intake_step_task_name_matches_producer() -> None:
    from contentos.worker.intake_tasks import INTAKE_STEP_TASK as worker_name
    from contentos.worker.producer import INTAKE_STEP_TASK as producer_name

    assert worker_name == producer_name


def test_events_pagination_by_after_id(session: Session) -> None:
    source = make_source(session)
    service = IntakeRunService(session)
    run = service.start_run(source.id, policy=POLICY, actor_user_id=None)
    service.pause_run(run.id, reason="a", actor_user_id=None)
    service.resume_run(run.id, reason="b", actor_user_id=None)
    all_events = service.events_for(run.id, limit=10)
    oldest_id = min(event.id for event in all_events)
    newer = service.events_for(run.id, after_id=oldest_id, limit=10)
    assert [event.kind for event in newer] == [
        IntakeEventKind.RUN_PAUSED,
        IntakeEventKind.RUN_RESUMED,
    ]
    assert isinstance(all_events[0], IntakeRunEvent)
