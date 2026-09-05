"""Performance API through the real app harness."""

from datetime import timedelta

import pytest
from editorial_harness import Harness
from performance_fixtures import (
    NOW,
    TODAY,
    declining_points,
    rising_points,
    seed_published,
    write_daily,
    write_summary,
)
from sqlalchemy import select

from contentos.performance.classifier import PerformancePolicy
from contentos.performance.refresh import RefreshOpportunityService
from contentos.performance.service import PerformanceService
from contentos.performance.suggestions import StrategySuggestionService
from contentos.publishing.models import PublicationAttempt
from contentos.strategy.service import StrategyService
from contentos.workflow.models import EditorialWorkItem

POLICY = PerformancePolicy()
SECRETS = ("api-secret", "task-secret", "postgresql+psycopg", "redis://")


@pytest.fixture()
def harness() -> Harness:
    return Harness()


def _no_secret(text: str) -> None:
    for marker in SECRETS:
        assert marker not in text


def seed_declining(harness: Harness):
    with harness.session() as session:
        content = seed_published(session, remote_ref="https://konsepthane.net/balon")
        write_daily(session, content, declining_points())
        write_summary(
            session,
            content,
            start=TODAY - timedelta(days=55),
            end=TODAY - timedelta(days=28),
            top_queries=[
                {
                    "query": "balon temalı doğum günü",
                    "clicks": 30,
                    "impressions": 300,
                    "position": 3.5,
                }
            ],
            observed_at=NOW - timedelta(days=28),
        )
        write_summary(
            session,
            content,
            start=TODAY - timedelta(days=27),
            end=TODAY,
            top_queries=[
                {
                    "query": "balon temalı doğum günü",
                    "clicks": 10,
                    "impressions": 200,
                    "position": 9.5,
                }
            ],
        )
        PerformanceService(session).assess_all(now=NOW, policy=POLICY)
        [refresh] = RefreshOpportunityService(session).detect(now=NOW)
        session.commit()
        return content.work_item_id, refresh.id


class TestOverview:
    def test_empty_overview_is_honest(self, harness: Harness) -> None:
        response = harness.get("/internal/performance/overview?window=28")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["totals"]["published"] == 0
        assert body["window_days"] == 28
        assert {row["provider"] for row in body["freshness"]} == {
            "google_search_console",
            "google_analytics",
            "semrush",
            "google_trends",
            "pinterest_trends",
        }
        assert all(row["last_observed_at"] is None for row in body["freshness"])
        assert body["schedule_enabled"] is True
        _no_secret(response.text)

    def test_window_is_bounded(self, harness: Harness) -> None:
        assert harness.get("/internal/performance/overview?window=10").status_code == 422

    def test_overview_buckets_and_clusters(self, harness: Harness) -> None:
        with harness.session() as session:
            cluster = StrategyService(session).create_cluster(name="Doğum Günü", priority=80)
            rising = seed_published(session, remote_ref="konsepthane-pub-r", cluster_id=cluster.id)
            write_daily(session, rising, rising_points())
            fresh = seed_published(
                session,
                title="Yeni yayın",
                remote_ref="konsepthane-pub-n",
                published_at=NOW - timedelta(days=2),
            )
            PerformanceService(session).assess_all(now=NOW, policy=POLICY)
            session.commit()
            fresh_id = fresh.work_item_id
        response = harness.get("/internal/performance/overview?window=28")
        body = response.json()
        assert body["totals"]["published"] == 2
        assert body["totals"]["rising"] == 1
        assert body["totals"]["new"] == 1
        assert body["rising"][0]["cluster_name"] == "Doğum Günü"
        assert body["rising"][0]["canonical_url_missing"] is True
        assert body["rising"][0]["impressions"] == 40 * 28
        assert body["new"][0]["work_item_id"] == str(fresh_id)
        # No snapshot at all is an honest "unknown" verdict, never a zero.
        assert body["new"][0]["assessment"]["status"] == "unknown"
        assert body["new"][0]["impressions"] is None
        clusters = {row["cluster_name"]: row for row in body["clusters"]}
        assert clusters["Doğum Günü"]["rising"] == 1 and clusters["Doğum Günü"]["sufficient"]
        assert clusters["Küme atanmadı"]["sufficient"] is False


class TestContentDetail:
    def test_unknown_work_item_is_404(self, harness: Harness) -> None:
        import uuid

        assert harness.get(f"/internal/performance/contents/{uuid.uuid4()}").status_code == 404

    def test_detail_carries_series_assessments_and_the_open_refresh(self, harness: Harness) -> None:
        work_item_id, refresh_id = seed_declining(harness)
        response = harness.get(f"/internal/performance/contents/{work_item_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["content"]["canonical_url"] == "https://konsepthane.net/balon"
        assert body["content"]["has_open_refresh"] is True
        statuses = {row["window_days"]: row["status"] for row in body["assessments"]}
        assert statuses[28] == "declining"
        assert statuses[90] == "insufficient_data"
        assert len(body["search_console_daily"]) == 56
        assert len(body["search_console_summary"]) == 2
        assert body["top_queries"][0]["query"] == "balon temalı doğum günü"
        assert body["analytics"] == [] and body["semrush"] == []
        assert body["refresh"]["id"] == str(refresh_id)
        assert body["refresh"]["status"] == "proposed"
        assert body["historical_signal"]["band"] == "unknown"
        _no_secret(response.text)


class TestRefreshDecisions:
    def test_list_approve_and_never_publish(self, harness: Harness) -> None:
        work_item_id, refresh_id = seed_declining(harness)
        listed = harness.get("/internal/performance/refresh-opportunities?status=proposed")
        assert listed.status_code == 200
        assert [row["id"] for row in listed.json()] == [str(refresh_id)]
        assert listed.json()[0]["window_days"] == 28

        bad = harness.post(
            f"/internal/performance/refresh-opportunities/{refresh_id}/approve", {"reason": ""}
        )
        assert bad.status_code == 422

        approved = harness.post(
            f"/internal/performance/refresh-opportunities/{refresh_id}/approve",
            {"reason": "sorgular kaybedildi; yeniden araştır"},
        )
        assert approved.status_code == 200, approved.text
        body = approved.json()
        assert body["status"] == "approved"
        assert body["decided_by_display_name"] == "Test Operator"
        assert body["current_state"] == "refresh_candidate"
        with harness.session() as session:
            item = session.get(EditorialWorkItem, work_item_id)
            assert item is not None and item.current_state.value == "refresh_candidate"
            assert len(session.execute(select(PublicationAttempt)).scalars().all()) == 1
        assert harness.dispatcher.calls == []  # approval enqueues no publish job

        twice = harness.post(
            f"/internal/performance/refresh-opportunities/{refresh_id}/approve",
            {"reason": "tekrar"},
        )
        assert twice.status_code == 409
        assert (
            harness.get("/internal/performance/refresh-opportunities?status=proposed").json() == []
        )

    def test_dismiss(self, harness: Harness) -> None:
        _, refresh_id = seed_declining(harness)
        response = harness.post(
            f"/internal/performance/refresh-opportunities/{refresh_id}/dismiss",
            {"reason": "mevsimsel"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "dismissed"
        import uuid

        missing = harness.post(
            f"/internal/performance/refresh-opportunities/{uuid.uuid4()}/dismiss",
            {"reason": "x"},
        )
        assert missing.status_code == 404


class TestStrategySuggestions:
    def _seed(self, harness: Harness) -> list[str]:
        with harness.session() as session:
            cluster = StrategyService(session).create_cluster(name="Soft Animal", priority=60)
            for index in range(3):
                content = seed_published(
                    session,
                    title=f"Soft animal {index}",
                    remote_ref=f"konsepthane-pub-{index}",
                    cluster_id=cluster.id,
                )
                write_daily(session, content, rising_points(window=90))
            PerformanceService(session).assess_all(now=NOW, policy=POLICY)
            rows = StrategySuggestionService(session).generate(now=NOW)
            session.commit()
            return [str(row.id) for row in rows]

    def test_list_accept_and_ignore(self, harness: Harness) -> None:
        [suggestion_id] = self._seed(harness)
        listed = harness.get("/internal/performance/strategy-suggestions?status=proposed")
        assert listed.status_code == 200
        assert listed.json()[0]["kind"] == "cluster_focus"
        assert "Soft Animal" in listed.json()[0]["title"]
        accepted = harness.post(
            f"/internal/performance/strategy-suggestions/{suggestion_id}/accept",
            {"reason": "odak artsın"},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "accepted"
        assert accepted.json()["basis"]["applied"]["priority"] == 70
        ignored = harness.post(
            f"/internal/performance/strategy-suggestions/{suggestion_id}/ignore",
            {"reason": "zaten karar verildi"},
        )
        assert ignored.status_code == 409
        dashboard = harness.get("/internal/dashboard/summary")
        assert dashboard.status_code == 200
        assert dashboard.json()["attention"]["strategy_suggestions"] == 0
        assert dashboard.json()["attention"]["refresh_decisions"] == 0


class TestSync:
    def test_sync_backfills_and_enqueues_through_the_seam(self, harness: Harness) -> None:
        with harness.session() as session:
            content = seed_published(session)
            session.delete(content)
            session.commit()
        response = harness.post(
            "/internal/performance/sync", headers={"X-Request-ID": "req-performance-1"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "queued"
        assert body["backfilled_published"] == 1
        assert body["tasks"] == ["contentos.performance.sync_all"]
        assert harness.dispatcher.calls == [("performance_sync", {}, "req-performance-1")]
        _no_secret(response.text)

    def test_broker_failure_is_a_bounded_503(self, harness: Harness) -> None:
        from editorial_harness import FailingEditorialDispatcher

        failing = Harness(dispatcher=FailingEditorialDispatcher())
        response = failing.post("/internal/performance/sync")
        assert response.status_code == 503
        assert "redis" not in response.text.lower()
        assert "secret" not in response.text.lower()

    def test_dashboard_attention_counts_pending_decisions(self, harness: Harness) -> None:
        seed_declining(harness)
        dashboard = harness.get("/internal/dashboard/summary")
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["attention"]["refresh_decisions"] == 1
