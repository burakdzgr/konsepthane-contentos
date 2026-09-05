"""Performance loop domain services over the in-memory harness."""

import uuid
from datetime import timedelta

import pytest
from editorial_harness import Harness
from performance_fixtures import (
    NOW,
    TODAY,
    declining_points,
    operator,
    rising_points,
    seed_published,
    weak_new_points,
    write_daily,
    write_summary,
)
from sqlalchemy import select

from contentos.intelligence.enums import SignalFamily
from contentos.intelligence.models import IntelligenceSignal
from contentos.performance.classifier import PerformancePolicy
from contentos.performance.enums import (
    AssessmentStatus,
    HistoricalBand,
    HistoricalOutcome,
    PerformanceProvider,
    RefreshStatus,
    SuggestionKind,
    SuggestionStatus,
)
from contentos.performance.history import HistoricalPerformanceService, historical_signal_for
from contentos.performance.models import PerformanceAssessment, PublishedContent
from contentos.performance.refresh import (
    RefreshActorRequiredError,
    RefreshOpportunityService,
    RefreshStateError,
)
from contentos.performance.service import (
    PerformanceService,
    canonical_url_from_ref,
    record_publication_fail_safe,
)
from contentos.performance.suggestions import (
    StrategySuggestionService,
    SuggestionActorRequiredError,
)
from contentos.publishing.models import PublicationAttempt
from contentos.strategy.models import TopicCluster
from contentos.strategy.service import StrategyService
from contentos.workflow.enums import WorkflowState
from contentos.workflow.models import EditorialWorkflowEvent, EditorialWorkItem

POLICY = PerformancePolicy()


@pytest.fixture()
def harness() -> Harness:
    return Harness()


class TestPublishedContents:
    def test_canonical_url_only_when_the_reference_is_an_absolute_url(self) -> None:
        assert canonical_url_from_ref("konsepthane-pub-42") is None
        assert canonical_url_from_ref("  ") is None
        assert (
            canonical_url_from_ref("https://konsepthane.net/yazi/balon")
            == "https://konsepthane.net/yazi/balon"
        )
        assert canonical_url_from_ref("https://x.y/a b") is None

    def test_record_published_is_idempotent_and_derives_strategy_context(
        self, harness: Harness
    ) -> None:
        with harness.session() as session:
            strategy = StrategyService(session)
            cluster = strategy.create_cluster(name="Doğum Günü Partileri", priority=80)
            strategy.create_keyword(
                phrase="balon temalı doğum günü", priority=90, topic_cluster_id=cluster.id
            )
            session.commit()
            content = seed_published(session, remote_ref="https://konsepthane.net/balon")
            session.commit()
            again = PerformanceService(session).record_published(
                work_item_id=content.work_item_id,
                publication_package_id=content.publication_package_id,
                publication_attempt_id=content.publication_attempt_id,
                remote_publication_ref="https://konsepthane.net/balon",
                published_at=NOW,
            )
            assert again.id == content.id
            assert content.canonical_url == "https://konsepthane.net/balon"
            assert content.topic_cluster_id == cluster.id
            assert len(session.execute(select(PublishedContent)).scalars().all()) == 1

    def test_bare_reference_leaves_the_url_unknown(self, harness: Harness) -> None:
        with harness.session() as session:
            content = seed_published(session, remote_ref="konsepthane-pub-7")
            assert content.canonical_url is None
            assert content.remote_publication_ref == "konsepthane-pub-7"

    def test_backfill_registers_successful_attempts_without_a_row(self, harness: Harness) -> None:
        with harness.session() as session:
            content = seed_published(session)
            session.delete(content)
            session.commit()
            assert PerformanceService.backfill_published(session) == 1
            assert PerformanceService.backfill_published(session) == 0
            row = session.execute(select(PublishedContent)).scalar_one()
            published_event = session.scalar(
                select(EditorialWorkflowEvent).where(
                    EditorialWorkflowEvent.work_item_id == row.work_item_id,
                    EditorialWorkflowEvent.to_state == WorkflowState.PUBLISHED,
                )
            )
            assert published_event is not None
            assert row.published_at == published_event.occurred_at

    def test_fail_safe_hook_never_raises(self, harness: Harness) -> None:
        with harness.session() as session:
            record_publication_fail_safe(
                session,
                work_item_id=uuid.uuid4(),
                publication_package_id=uuid.uuid4(),
                publication_attempt_id=None,
                remote_publication_ref="konsepthane-pub-x",
            )
            assert session.execute(select(PublishedContent)).scalars().all() == []
            record_publication_fail_safe(
                session,
                work_item_id=uuid.uuid4(),
                publication_package_id=uuid.uuid4(),
                publication_attempt_id=None,
                remote_publication_ref=None,
            )


class TestSnapshotsAndAssessments:
    def test_snapshots_are_append_only_and_idempotent_per_day(self, harness: Harness) -> None:
        with harness.session() as session:
            content = seed_published(session)
            service = PerformanceService(session)
            first, created = service.record_snapshot(
                content.id,
                PerformanceProvider.GOOGLE_SEARCH_CONSOLE,
                period_start=TODAY,
                period_end=TODAY,
                metrics={"impressions": 10, "clicks": 1, "position": 5.0},
                observed_at=NOW,
            )
            second, created_again = service.record_snapshot(
                content.id,
                PerformanceProvider.GOOGLE_SEARCH_CONSOLE,
                period_start=TODAY,
                period_end=TODAY,
                metrics={"impressions": 999},
                observed_at=NOW + timedelta(hours=3),
            )
            assert created is True and created_again is False
            assert second.id == first.id and first.metrics["impressions"] == 10
            assert service.freshness()["google_search_console"] == NOW
            assert service.freshness()["google_analytics"] is None

    def test_assess_all_writes_every_window_once_per_verdict(self, harness: Harness) -> None:
        with harness.session() as session:
            content = seed_published(session)
            write_daily(session, content, rising_points())
            service = PerformanceService(session)
            written = service.assess_all(now=NOW, policy=POLICY)
            assert {row.window_days for row in written} == {7, 28, 90}
            latest = service.latest_assessments(content.id)
            assert latest[28].status is AssessmentStatus.RISING
            assert latest[90].status is AssessmentStatus.INSUFFICIENT_DATA
            assert service.assess_all(now=NOW, policy=POLICY) == []
            assert len(session.execute(select(PerformanceAssessment)).scalars().all()) == 3

    def test_new_weak_content_is_insufficient_not_declining(self, harness: Harness) -> None:
        with harness.session() as session:
            content = seed_published(session, published_at=NOW - timedelta(days=4))
            write_daily(session, content, weak_new_points())
            service = PerformanceService(session)
            service.assess_all(now=NOW, policy=POLICY)
            statuses = {row.status for row in service.latest_assessments(content.id).values()}
            assert statuses == {AssessmentStatus.INSUFFICIENT_DATA}
            overview = service.cluster_overview(28, now=NOW)
            assert overview[0].new == 1 and overview[0].insufficient == 1
            assert overview[0].sufficient is False


class TestHistoricalSignal:
    def test_rising_history_becomes_a_strong_priority_signal(self, harness: Harness) -> None:
        with harness.session() as session:
            cluster = StrategyService(session).create_cluster(name="1 Yaş Doğum Günü", priority=80)
            for index in range(3):
                content = seed_published(
                    session,
                    title=f"Soft animal temalı 1 yaş {index}",
                    remote_ref=f"konsepthane-pub-{index}",
                    cluster_id=cluster.id,
                    theme_key="soft animal",
                    content_format="planning_guide",
                )
                write_daily(session, content, rising_points(window=90))
            PerformanceService(session).assess_all(now=NOW, policy=POLICY)
            signals = HistoricalPerformanceService(session).aggregate(now=NOW)
            session.commit()
            assert signals
            assert all(row.family is SignalFamily.HISTORICAL_PERFORMANCE for row in signals)
            signal = historical_signal_for(
                session,
                cluster_id=cluster.id,
                audience_id=None,
                theme_key="soft animal",
                content_format="planning_guide",
            )
            assert signal.band is HistoricalBand.STRONG
            assert signal.outcome is HistoricalOutcome.POSITIVE
            assert signal.basis["real_metric_count"] == 3
            assert signal.basis["priority_only"] is True
            # The cluster grain answers when the exact context is unknown.
            broader = historical_signal_for(
                session,
                cluster_id=cluster.id,
                audience_id=None,
                theme_key="başka tema",
                content_format=None,
            )
            assert broader.basis["grain"] == "cluster"
            # Re-aggregation updates in place, never duplicates.
            HistoricalPerformanceService(session).aggregate(now=NOW + timedelta(days=1))
            rows = session.execute(select(IntelligenceSignal)).scalars().all()
            assert len({row.observation_hash for row in rows}) == len(rows)
            assert all(row.occurrence_count == 2 for row in rows)

    def test_absent_history_is_unknown(self, harness: Harness) -> None:
        with harness.session() as session:
            signal = historical_signal_for(
                session,
                cluster_id=uuid.uuid4(),
                audience_id=None,
                theme_key=None,
                content_format=None,
            )
            assert signal.band is HistoricalBand.UNKNOWN
            assert signal.outcome is None
            assert signal.projection()["priority_only"] is True

    def test_insufficient_data_never_becomes_history(self, harness: Harness) -> None:
        with harness.session() as session:
            content = seed_published(session, theme_key="yeni tema")
            write_daily(session, content, weak_new_points())
            PerformanceService(session).assess_all(now=NOW, policy=POLICY)
            assert HistoricalPerformanceService(session).aggregate(now=NOW) == []


def _declining_content(session, **kwargs):
    content = seed_published(session, **kwargs)
    write_daily(session, content, declining_points())
    write_summary(
        session,
        content,
        start=TODAY - timedelta(days=55),
        end=TODAY - timedelta(days=28),
        top_queries=[
            {"query": "balon temalı doğum günü", "clicks": 30, "impressions": 300, "position": 3.5},
            {"query": "evde parti süsleme", "clicks": 12, "impressions": 120, "position": 4.0},
        ],
        observed_at=NOW - timedelta(days=28),
    )
    write_summary(
        session,
        content,
        start=TODAY - timedelta(days=27),
        end=TODAY,
        top_queries=[
            {"query": "balon temalı doğum günü", "clicks": 10, "impressions": 200, "position": 9.5}
        ],
        impressions=300,
        clicks=15,
        position=9.5,
    )
    PerformanceService(session).assess_all(now=NOW, policy=POLICY)
    return content


class TestRefreshOpportunities:
    def test_declining_history_proposes_one_refresh_with_a_diagnosis(
        self, harness: Harness
    ) -> None:
        with harness.session() as session:
            content = _declining_content(session)
            service = RefreshOpportunityService(session)
            proposed = service.detect(now=NOW)
            assert len(proposed) == 1
            row = proposed[0]
            assert row.status is RefreshStatus.PROPOSED
            diagnosis = row.diagnosis
            assert diagnosis["window_days"] == 28
            assert diagnosis["position_movement"]["delta"] > 0
            assert diagnosis["query_changes"]["available"] is True
            assert diagnosis["query_changes"]["lost_queries"] == ["evde parti süsleme"]
            assert diagnosis["query_changes"]["position_drops"][0]["query"] == (
                "balon temalı doğum günü"
            )
            assert diagnosis["content_age_days"] == 60
            assert diagnosis["new_signals"] == []
            assert diagnosis["strategy_fit"]["available"] is True
            assert "pozisyon" in row.recommendation.lower()
            assert "yayın kararı ayrıdır" in row.recommendation
            # Idempotent: the same declining verdict never proposes twice.
            assert service.detect(now=NOW + timedelta(hours=1)) == []
            assert content.id == row.published_content_id

    def test_approval_requires_a_named_user_and_never_publishes(self, harness: Harness) -> None:
        with harness.session() as session:
            content = _declining_content(session)
            service = RefreshOpportunityService(session)
            [row] = service.detect(now=NOW)
            with pytest.raises(RefreshActorRequiredError):
                service.approve(row.id, user=None, reason="deneme")
            with pytest.raises(RefreshStateError):
                service.approve(row.id, user=operator(session), reason="   ")
            approved = service.approve(row.id, user=operator(session), reason="rakip içerik güncel")
            session.commit()
            assert approved.status is RefreshStatus.APPROVED
            assert approved.decided_by_user_id == operator(session).id
            item = session.get(EditorialWorkItem, content.work_item_id)
            assert item is not None
            assert item.current_state is WorkflowState.REFRESH_CANDIDATE
            events = (
                session.execute(
                    select(EditorialWorkflowEvent)
                    .where(EditorialWorkflowEvent.work_item_id == content.work_item_id)
                    .order_by(EditorialWorkflowEvent.id)
                )
                .scalars()
                .all()
            )
            assert [event.to_state for event in events[-2:]] == [
                WorkflowState.MEASURING,
                WorkflowState.REFRESH_CANDIDATE,
            ]
            assert events[-1].actor_user_id == operator(session).id
            assert events[-1].artifact_refs["refresh_opportunity_id"] == str(row.id)
            # No new publication attempt, the original provenance is untouched.
            attempts = session.execute(select(PublicationAttempt)).scalars().all()
            assert len(attempts) == 1 and attempts[0].status == "succeeded"
            with pytest.raises(RefreshStateError):
                service.dismiss(row.id, user=operator(session), reason="tekrar")

    def test_dismiss_records_the_decision_and_keeps_the_state(self, harness: Harness) -> None:
        with harness.session() as session:
            content = _declining_content(session)
            service = RefreshOpportunityService(session)
            [row] = service.detect(now=NOW)
            dismissed = service.dismiss(row.id, user=operator(session), reason="mevsimsel düşüş")
            assert dismissed.status is RefreshStatus.DISMISSED
            assert dismissed.decision_reason == "mevsimsel düşüş"
            item = session.get(EditorialWorkItem, content.work_item_id)
            assert item is not None and item.current_state is WorkflowState.PUBLISHED
            assert service.open_for(content.id) is None
            assert service.detect(now=NOW) == []


class TestStrategySuggestions:
    def _rising_cluster(self, session, count: int) -> TopicCluster:
        cluster = StrategyService(session).create_cluster(name="Soft Animal 1 Yaş", priority=70)
        for index in range(count):
            content = seed_published(
                session,
                title=f"Soft animal {index}",
                remote_ref=f"konsepthane-pub-{index}",
                cluster_id=cluster.id,
            )
            write_daily(session, content, rising_points(window=90))
            write_summary(
                session,
                content,
                start=TODAY - timedelta(days=27),
                end=TODAY,
                top_queries=[
                    {
                        "query": "woodland doğum günü",
                        "clicks": 20,
                        "impressions": 200,
                        "position": 4.0,
                    }
                ],
            )
        PerformanceService(session).assess_all(now=NOW, policy=POLICY)
        return cluster

    def test_three_rising_publications_yield_bounded_suggestions(self, harness: Harness) -> None:
        with harness.session() as session:
            cluster = self._rising_cluster(session, 3)
            service = StrategySuggestionService(session)
            written = service.generate(now=NOW)
            kinds = {row.kind for row in written}
            assert kinds == {SuggestionKind.CLUSTER_FOCUS, SuggestionKind.KEYWORD_ADD}
            focus = next(row for row in written if row.kind is SuggestionKind.CLUSTER_FOCUS)
            assert "Soft Animal 1 Yaş" in focus.title
            assert "yükseliyor" in focus.rationale
            assert focus.basis["cluster_id"] == str(cluster.id)
            assert focus.basis["metrics"]["rising"] == 3
            keyword = next(row for row in written if row.kind is SuggestionKind.KEYWORD_ADD)
            assert "woodland doğum günü" in keyword.title
            # Deduplicated by (kind, normalized title).
            assert service.generate(now=NOW + timedelta(days=1)) == []

    def test_fewer_than_three_publications_never_suggest(self, harness: Harness) -> None:
        with harness.session() as session:
            self._rising_cluster(session, 2)
            assert StrategySuggestionService(session).generate(now=NOW) == []

    def test_accept_applies_one_bounded_change_and_ignore_records(self, harness: Harness) -> None:
        with harness.session() as session:
            cluster = self._rising_cluster(session, 3)
            service = StrategySuggestionService(session)
            written = service.generate(now=NOW)
            focus = next(row for row in written if row.kind is SuggestionKind.CLUSTER_FOCUS)
            keyword = next(row for row in written if row.kind is SuggestionKind.KEYWORD_ADD)
            with pytest.raises(SuggestionActorRequiredError):
                service.accept(focus.id, user=None, reason="x")
            accepted = service.accept(focus.id, user=operator(session), reason="odak artsın")
            assert accepted.status is SuggestionStatus.ACCEPTED
            assert accepted.basis["applied"]["priority"] == 80
            assert session.get(TopicCluster, cluster.id).priority == 80
            ignored = service.ignore(keyword.id, user=operator(session), reason="şimdilik geç")
            assert ignored.status is SuggestionStatus.IGNORED
            phrases = [row.phrase for row in StrategyService(session).list_keywords()]
            assert "woodland doğum günü" not in phrases
            assert service.pending_count() == 0
            # A fresh keyword suggestion, once accepted, creates the strategic keyword.
            fresh = service.generate(now=NOW)
            assert fresh == []
            new_hash_row = next(iter(service.list_suggestions(SuggestionStatus.IGNORED)))
            new_hash_row.status = (
                SuggestionStatus.PROPOSED
            )  # test knob: re-open the same suggestion
            new_hash_row.decided_at = None
            session.flush()
            added = service.accept(new_hash_row.id, user=operator(session), reason="hedef olsun")
            assert added.basis["applied"]["kind"] == "keyword_created"
            phrases = [row.phrase for row in StrategyService(session).list_keywords()]
            assert "woodland doğum günü" in phrases
