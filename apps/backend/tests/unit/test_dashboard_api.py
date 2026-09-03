"""Dashboard read models and the audited intake pause controls."""

import pytest
from editorial_harness import (
    Context,
    Harness,
    seed_documents,
    seed_scored,
)
from sqlalchemy import select

from contentos.operations.enums import PauseScope
from contentos.operations.errors import IntakePausedError
from contentos.operations.models import OperationalPauseEvent
from contentos.operations.service import OperationsService
from contentos.workflow.enums import WorkflowState


@pytest.fixture()
def harness() -> Harness:
    return Harness()


class TestOperationsService:
    def test_pause_is_idempotent_and_audited_only_on_change(self, harness: Harness) -> None:
        with harness.session() as session:
            service = OperationsService(session)
            first = service.pause(PauseScope.WRITER, reason="bakım", actor_user_id=None)
            assert first.changed is True and first.is_paused is True
            second = service.pause(PauseScope.WRITER, reason="tekrar", actor_user_id=None)
            assert second.changed is False
            events = session.scalars(select(OperationalPauseEvent)).all()
            assert len(events) == 1
            assert events[0].action.value == "paused"
            assert events[0].reason == "bakım"

    def test_resume_of_never_paused_scope_records_nothing(self, harness: Harness) -> None:
        with harness.session() as session:
            service = OperationsService(session)
            change = service.resume(PauseScope.QA, reason="gerek yok", actor_user_id=None)
            assert change.changed is False
            assert session.scalars(select(OperationalPauseEvent)).first() is None

    def test_engine_pause_gates_every_scope(self, harness: Harness) -> None:
        with harness.session() as session:
            service = OperationsService(session)
            service.pause(PauseScope.ENGINE, reason="acil durdurma", actor_user_id=None)
            with pytest.raises(IntakePausedError) as engine_error:
                service.ensure_dispatch_allowed(PauseScope.WRITER)
            assert engine_error.value.scope is PauseScope.ENGINE
            service.resume(PauseScope.ENGINE, reason="devam", actor_user_id=None)
            service.ensure_dispatch_allowed(PauseScope.WRITER)

    def test_reason_is_required_and_bounded(self, harness: Harness) -> None:
        with harness.session() as session:
            service = OperationsService(session)
            with pytest.raises(ValueError):
                service.pause(PauseScope.QA, reason="   ", actor_user_id=None)
            with pytest.raises(ValueError):
                service.pause(PauseScope.QA, reason="x" * 501, actor_user_id=None)


class TestPauseControls:
    def test_pause_resume_roundtrip_with_audit_actor(self, harness: Harness) -> None:
        response = harness.post(
            "/internal/dashboard/controls/pause",
            {"scope": "writer", "reason": "model değişikliği hazırlığı"},
        )
        assert response.status_code == 200
        assert response.json() == {"status": "applied", "scope": "writer", "is_paused": True}

        repeat = harness.post(
            "/internal/dashboard/controls/pause",
            {"scope": "writer", "reason": "tekrar"},
        )
        assert repeat.json()["status"] == "unchanged"

        controls = harness.get("/internal/dashboard/controls")
        assert controls.status_code == 200
        body = controls.json()
        writer = next(p for p in body["pauses"] if p["scope"] == "writer")
        assert writer["is_paused"] is True
        assert writer["reason"] == "model değişikliği hazırlığı"
        assert len(body["recent_events"]) == 1
        # The audited actor is the authenticated operator, by display name.
        assert body["recent_events"][0]["actor_display_name"] is not None

        resumed = harness.post(
            "/internal/dashboard/controls/resume",
            {"scope": "writer", "reason": "hazırlık bitti"},
        )
        assert resumed.json() == {"status": "applied", "scope": "writer", "is_paused": False}

    def test_unknown_scope_is_rejected(self, harness: Harness) -> None:
        response = harness.post(
            "/internal/dashboard/controls/pause",
            {"scope": "reactor", "reason": "yok"},
        )
        assert response.status_code == 422


class TestPauseEnforcement:
    def test_scope_pause_refuses_dispatch_and_publishes_nothing(self, harness: Harness) -> None:
        with harness.session() as session:
            document_ids = seed_documents(session)
        harness.post(
            "/internal/dashboard/controls/pause",
            {"scope": "opportunity", "reason": "değerlendirme molası"},
        )
        response = harness.post(
            f"/internal/editorial/research/{document_ids[0]}/promote",
            {},
        )
        assert response.status_code == 409
        assert "intake paused (opportunity)" in response.json()["error"]["message"]
        assert harness.dispatcher.calls == []

    def test_engine_pause_refuses_every_editorial_dispatch(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_scored(session, context)
        harness.post(
            "/internal/dashboard/controls/pause",
            {"scope": "engine", "reason": "acil durdurma"},
        )
        response = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/evaluate",
            {},
        )
        assert response.status_code == 409
        assert "intake paused (engine)" in response.json()["error"]["message"]
        assert harness.dispatcher.calls == []
        # Direct (non-queue) domain commands stay available: a pause gates
        # dispatch only, never the human's own recorded decisions.
        commission = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/commission",
            {"reason": "insan kararı çalışmaya devam eder"},
        )
        assert commission.status_code == 200

    def test_resume_restores_dispatch(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_scored(session, context)
        harness.post(
            "/internal/dashboard/controls/pause",
            {"scope": "engine", "reason": "kısa durdurma"},
        )
        harness.post(
            "/internal/dashboard/controls/resume",
            {"scope": "engine", "reason": "devam"},
        )
        response = harness.post(
            f"/internal/editorial/opportunities/{context.opportunity_id}/evaluate",
            {},
        )
        assert response.status_code == 200
        assert [call[0] for call in harness.dispatcher.calls] == ["evaluate_opportunity"]


class TestSummary:
    def test_summary_reports_real_counts_and_honest_unknowns(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_scored(session, context)
        response = harness.get("/internal/dashboard/summary")
        assert response.status_code == 200
        body = response.json()
        states = body["work_item_states"]
        assert set(states) == {state.value for state in WorkflowState}
        assert states["idea_scoring"] == 1
        assert body["published_today"] == 0
        assert body["research"]["active_sources"] >= 1
        # No broker exists in unit tests: the depth is honestly unknown.
        assert body["queue"]["depth"] is None
        assert body["ai"]["attempts_today"] == 0
        assert len(body["pauses"]) == len(PauseScope)

    def test_summary_reflects_pauses(self, harness: Harness) -> None:
        harness.post(
            "/internal/dashboard/controls/pause",
            {"scope": "publisher", "reason": "yayın penceresi kapalı"},
        )
        body = harness.get("/internal/dashboard/summary").json()
        publisher = next(p for p in body["pauses"] if p["scope"] == "publisher")
        assert publisher["is_paused"] is True


class TestAgents:
    def test_agents_expose_only_real_execution_units(self, harness: Harness) -> None:
        response = harness.get("/internal/dashboard/agents")
        assert response.status_code == 200
        body = response.json()
        keys = [agent["key"] for agent in body["agents"]]
        assert keys == [
            "research",
            "opportunity",
            "ideas",
            "evidence",
            "intent",
            "brief",
            "writer",
            "editor",
            "qa",
            "media",
            "publisher",
        ]
        writer = next(agent for agent in body["agents"] if agent["key"] == "writer")
        assert writer["kind"] == "ai"
        assert writer["purposes"] == ["writer_draft"]
        assert writer["attempts_today"] == 0
        assert writer["last_attempt"] is None
        assert body["engine_paused"] is False

    def test_agent_pause_and_metrics_reflect_durable_state(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_scored(session, context)
        harness.post(
            "/internal/dashboard/controls/pause",
            {"scope": "writer", "reason": "mola"},
        )
        body = harness.get("/internal/dashboard/agents").json()
        writer = next(agent for agent in body["agents"] if agent["key"] == "writer")
        assert writer["is_paused"] is True
        assert writer["pause_reason"] == "mola"
        opportunity = next(agent for agent in body["agents"] if agent["key"] == "opportunity")
        assert opportunity["metrics"].get("open", 0) >= 1


class TestActivityAndPublications:
    def test_activity_lists_workflow_events_with_titles(self, harness: Harness) -> None:
        with harness.session() as session:
            context = Context()
            seed_scored(session, context)
        response = harness.get("/internal/dashboard/activity?limit=10")
        assert response.status_code == 200
        entries = response.json()["entries"]
        assert len(entries) >= 1
        workflow_entries = [entry for entry in entries if entry["kind"] == "workflow"]
        assert workflow_entries, "seeded workflow transitions must appear"
        assert workflow_entries[0]["title"] is not None
        assert workflow_entries[0]["to_state"] is not None

    def test_activity_includes_pause_events(self, harness: Harness) -> None:
        harness.post(
            "/internal/dashboard/controls/pause",
            {"scope": "qa", "reason": "kapı bakımı"},
        )
        entries = harness.get("/internal/dashboard/activity").json()["entries"]
        pause_entries = [entry for entry in entries if entry["kind"] == "pause"]
        assert pause_entries and pause_entries[0]["scope"] == "qa"
        assert pause_entries[0]["action"] == "paused"

    def test_publication_queue_is_empty_not_invented(self, harness: Harness) -> None:
        response = harness.get("/internal/dashboard/publications")
        assert response.status_code == 200
        assert response.json()["rows"] == []

    def test_activity_limit_is_bounded(self, harness: Harness) -> None:
        assert harness.get("/internal/dashboard/activity?limit=0").status_code == 422
        assert harness.get("/internal/dashboard/activity?limit=101").status_code == 422


def test_dashboard_requires_authentication(harness: Harness) -> None:
    # A fresh unauthenticated client (no login side effects).
    harness.auth_token = "0" * 64  # syntactically plausible, never issued
    response = harness.get("/internal/dashboard/summary")
    assert response.status_code == 401
    body = response.json()
    assert "error" in body


def test_pause_scope_vocabulary_matches_operation_map() -> None:
    """Every dispatchable operation maps to a real scope and vice versa
    (the publisher/research scopes are covered by their routers)."""
    from contentos.api.routes.editorial_control import _OPERATION_PAUSE_SCOPES

    assert set(_OPERATION_PAUSE_SCOPES.values()) == {
        PauseScope.OPPORTUNITY,
        PauseScope.IDEAS,
        PauseScope.EVIDENCE,
        PauseScope.INTENT,
        PauseScope.BRIEF,
        PauseScope.WRITER,
        PauseScope.EDITOR,
        PauseScope.QA,
        PauseScope.MEDIA,
        PauseScope.PUBLISHER,
    }
