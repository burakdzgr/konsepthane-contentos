"""Intake-run API tests (real services, fake step dispatcher)."""

import uuid

import pytest
from editorial_harness import Harness
from sqlalchemy.orm import Session

from contentos.sources.enums import DiscoveryStrategy, SourceKind, TrustTier
from contentos.sources.service import SourceRegistryService


class FakeIntakeDispatcher:
    def __init__(self) -> None:
        self.steps: list[str] = []

    def enqueue_intake_step(self, run_id: str, *, request_id: str | None = None) -> None:
        self.steps.append(run_id)


@pytest.fixture()
def harness() -> Harness:
    built = Harness()
    built.app.state.intake_control_dispatcher = FakeIntakeDispatcher()
    return built


def seed_sitemap_source(session: Session) -> uuid.UUID:
    source = SourceRegistryService(session).register_source(
        slug=f"intake-{uuid.uuid4().hex[:8]}",
        name="Intake Kaynağı",
        kind=SourceKind.SITEMAP,
        base_url="https://intake.example.test/sitemap.xml",
        trust_tier=TrustTier.GENERAL,
        discovery_strategy=DiscoveryStrategy.SITEMAP,
    )
    session.commit()
    return source.id


def intake_dispatcher(harness: Harness) -> FakeIntakeDispatcher:
    dispatcher = harness.app.state.intake_control_dispatcher
    assert isinstance(dispatcher, FakeIntakeDispatcher)
    return dispatcher


class TestStartRun:
    def test_start_creates_run_and_publishes_one_step(self, harness: Harness) -> None:
        with harness.session() as session:
            source_id = seed_sitemap_source(session)
        response = harness.post(f"/internal/intake/sources/{source_id}/runs", {})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "started"
        assert intake_dispatcher(harness).steps == [body["run_id"]]

        detail = harness.get(f"/internal/intake/runs/{body['run_id']}")
        assert detail.status_code == 200
        run = detail.json()["run"]
        assert run["status"] == "running"
        assert run["policy"]["max_fetches_per_run"] >= 1
        stages = {stage["key"]: stage["state"] for stage in detail.json()["stages"]}
        assert stages["discovery"] == "active"
        events = detail.json()["events"]
        assert events[0]["kind"] == "run_started"

    def test_second_start_conflicts_while_live(self, harness: Harness) -> None:
        with harness.session() as session:
            source_id = seed_sitemap_source(session)
        first = harness.post(f"/internal/intake/sources/{source_id}/runs", {})
        assert first.status_code == 200
        second = harness.post(f"/internal/intake/sources/{source_id}/runs", {})
        assert second.status_code == 409
        assert "already exists" in second.json()["error"]["message"]

    def test_manual_source_is_rejected(self, harness: Harness) -> None:
        with harness.session() as session:
            source = SourceRegistryService(session).register_source(
                slug="manuel-intake",
                name="Manuel",
                kind=SourceKind.MANUAL,
                base_url="https://manuel.example.test/",
                trust_tier=TrustTier.GENERAL,
            )
            session.commit()
            source_id = source.id
        response = harness.post(f"/internal/intake/sources/{source_id}/runs", {})
        assert response.status_code == 422

    def test_research_operational_pause_blocks_new_runs(self, harness: Harness) -> None:
        with harness.session() as session:
            source_id = seed_sitemap_source(session)
        harness.post(
            "/internal/dashboard/controls/pause",
            {"scope": "research", "reason": "alım kapalı"},
        )
        response = harness.post(f"/internal/intake/sources/{source_id}/runs", {})
        assert response.status_code == 409
        assert "intake paused (research)" in response.json()["error"]["message"]
        assert intake_dispatcher(harness).steps == []


class TestRunControls:
    def start(self, harness: Harness) -> str:
        with harness.session() as session:
            source_id = seed_sitemap_source(session)
        response = harness.post(f"/internal/intake/sources/{source_id}/runs", {})
        assert response.status_code == 200
        return str(response.json()["run_id"])

    def test_pause_resume_stop_roundtrip(self, harness: Harness) -> None:
        run_id = self.start(harness)
        paused = harness.post(
            f"/internal/intake/runs/{run_id}/pause", {"reason": "operatör molası"}
        )
        assert paused.status_code == 200
        assert paused.json()["run_status"] == "paused"

        resumed = harness.post(f"/internal/intake/runs/{run_id}/resume", {"reason": "devam"})
        assert resumed.status_code == 200
        assert resumed.json()["run_status"] == "running"
        # start + resume both publish a step.
        assert intake_dispatcher(harness).steps == [run_id, run_id]

        stopped = harness.post(f"/internal/intake/runs/{run_id}/stop", {"reason": "yeter"})
        assert stopped.status_code == 200
        assert stopped.json()["run_status"] == "stopped"

        again = harness.post(f"/internal/intake/runs/{run_id}/pause", {"reason": "geç"})
        assert again.status_code == 409

    def test_events_endpoint_supports_incremental_polling(self, harness: Harness) -> None:
        run_id = self.start(harness)
        harness.post(f"/internal/intake/runs/{run_id}/pause", {"reason": "a"})
        first = harness.get(f"/internal/intake/runs/{run_id}/events")
        assert first.status_code == 200
        events = first.json()["events"]
        newest_first = [event["kind"] for event in events]
        assert newest_first[0] == "run_paused"
        oldest_id = min(event["id"] for event in events)
        incremental = harness.get(f"/internal/intake/runs/{run_id}/events?after_id={oldest_id}")
        assert [event["kind"] for event in incremental.json()["events"]] == ["run_paused"]

    def test_runs_listing_includes_source_identity(self, harness: Harness) -> None:
        run_id = self.start(harness)
        listing = harness.get("/internal/intake/runs")
        assert listing.status_code == 200
        runs = listing.json()["runs"]
        assert runs[0]["id"] == run_id
        assert runs[0]["source_name"] == "Intake Kaynağı"

    def test_unknown_run_is_404(self, harness: Harness) -> None:
        missing = uuid.uuid4()
        assert harness.get(f"/internal/intake/runs/{missing}").status_code == 404
        assert (
            harness.post(f"/internal/intake/runs/{missing}/pause", {"reason": "x"}).status_code
            == 404
        )
