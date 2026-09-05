"""Autopilot (ADR 0012): mode switch, trail, and the runner over real state."""

import uuid
from typing import Any

import pytest
from editorial_harness import TEST_OPERATOR_USERNAME, Context, Harness, seed_scored
from sqlalchemy import select

from contentos.auth.models import User
from contentos.autopilot.enums import AutopilotEventKind, AutopilotMode
from contentos.autopilot.planner import ACTION_COMMISSION, ACTION_GENERATE_IDEAS
from contentos.autopilot.runner import AutopilotRunner
from contentos.autopilot.service import AutopilotService, InvalidAutopilotInputError
from contentos.opportunities.enums import OpportunityDisposition
from contentos.opportunities.repository import OpportunityRepository
from contentos.workflow.enums import WorkflowState
from contentos.workflow.repository import WorkflowRepository


@pytest.fixture
def harness() -> Harness:
    return Harness()


def operator_id(harness: Harness) -> uuid.UUID:
    with harness.session() as session:
        user = session.scalar(select(User).where(User.username == TEST_OPERATOR_USERNAME))
        assert user is not None
        return user.id


class TestModeApi:
    def test_default_is_off_and_switching_is_a_named_recorded_decision(
        self, harness: Harness
    ) -> None:
        state = harness.get("/internal/autopilot").json()
        assert state["mode"] == "off"
        assert state["events"] == []

        response = harness.put(
            "/internal/autopilot/mode",
            json_body={"mode": "supervised", "reason": "ilk denetimli tur"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "supervised"
        assert body["actor_display_name"] == "Test Operator"
        assert body["events"][0]["kind"] == "mode_changed"
        assert body["events"][0]["detail"]["from"] == "off"
        # Switching on arms the worker sweep through the dispatcher seam.
        assert ("autopilot_sweep", {}, None) in [
            (name, payload, rid) for name, payload, rid in harness.dispatcher.calls
        ] or any(call[0] == "autopilot_sweep" for call in harness.dispatcher.calls)

        blank = harness.put(
            "/internal/autopilot/mode", json_body={"mode": "autonomous", "reason": "   "}
        )
        assert blank.status_code == 422

    def test_service_refuses_an_unnamed_switch_on(self, harness: Harness) -> None:
        with harness.session() as session:
            with pytest.raises(InvalidAutopilotInputError):
                AutopilotService(session).set_mode(
                    AutopilotMode.AUTONOMOUS, actor_user_id=None, reason="kimsesiz"
                )
            # OFF may be recorded without an actor (e.g. an emergency stop).
            state = AutopilotService(session).set_mode(
                AutopilotMode.OFF, actor_user_id=None, reason="dur"
            )
            assert state.mode is AutopilotMode.OFF


class TestRunner:
    def test_supervised_waits_autonomous_commissions_then_produces(self, harness: Harness) -> None:
        actor = operator_id(harness)
        with harness.session() as session:
            context = Context()
            seed_scored(session, context)  # OPEN + IDEA_SCORING + COMMISSIONABLE
        enqueued: list[tuple[str, dict[str, Any]]] = []

        def enqueue(task_name: str, payload: dict[str, Any]) -> None:
            enqueued.append((task_name, payload))

        # Supervised: the production decision stays with the human.
        with harness.session() as session:
            AutopilotService(session).set_mode(
                AutopilotMode.SUPERVISED, actor_user_id=actor, reason="denetimli"
            )
            outcome = AutopilotRunner(session, enqueue=enqueue).step(context.work_item_id)
            session.commit()
        assert outcome is not None and outcome.action.is_wait
        assert outcome.action.name == "commission_decision"
        assert enqueued == []

        # Autonomous: the gate passes, the autopilot commissions on behalf of
        # the named operator and marks the transition.
        with harness.session() as session:
            AutopilotService(session).set_mode(
                AutopilotMode.AUTONOMOUS, actor_user_id=actor, reason="otonom"
            )
            outcome = AutopilotRunner(session, enqueue=enqueue).step(context.work_item_id)
            session.commit()
        assert outcome is not None and outcome.performed
        assert outcome.action.name == ACTION_COMMISSION
        with harness.session() as session:
            opportunity = OpportunityRepository(session).get_by_id(context.opportunity_id)
            assert opportunity is not None
            assert opportunity.disposition is OpportunityDisposition.COMMISSIONED
            item = WorkflowRepository(session).get_by_id(context.work_item_id)
            assert item is not None and item.current_state is WorkflowState.EVIDENCE_BUILDING
            entry = WorkflowRepository(session).get_latest_entry_event(
                context.work_item_id, WorkflowState.EVIDENCE_BUILDING
            )
            assert entry is not None
            assert entry.artifact_refs["autopilot"] == "true"
            assert entry.actor_user_id == actor

        # Next step: no ideas yet -> the idea task is enqueued once, then the
        # in-flight guard keeps the sweep from enqueueing it again.
        with harness.session() as session:
            runner = AutopilotRunner(session, enqueue=enqueue)
            first = runner.step(context.work_item_id)
            session.commit()
            second = runner.step(context.work_item_id)
            session.commit()
        assert first is not None and first.performed
        assert first.action.name == ACTION_GENERATE_IDEAS
        assert enqueued == [
            (
                "contentos.editorial.generate_idea_candidates",
                {"opportunity_id": str(context.opportunity_id), "candidate_count": 3},
            )
        ]
        assert second is not None and second.action.kind == "none"

        # The trail shows the decision and the actions, newest first.
        trail = harness.get("/internal/autopilot").json()["events"]
        kinds = [(event["kind"], event["action"]) for event in trail]
        assert (AutopilotEventKind.ACTION.value, ACTION_GENERATE_IDEAS) in kinds
        assert (AutopilotEventKind.ACTION.value, ACTION_COMMISSION) in kinds
        assert (AutopilotEventKind.WAITING.value, "commission_decision") in kinds

    def test_off_mode_does_nothing_and_sweep_scope_lists_actionable_items(
        self, harness: Harness
    ) -> None:
        with harness.session() as session:
            context = Context()
            seed_scored(session, context)
            runner = AutopilotRunner(session)
            assert context.work_item_id in runner.actionable_work_item_ids()
            outcome = runner.step(context.work_item_id)
            assert outcome is not None and outcome.action.kind == "none"
            assert AutopilotService(session).recent_events() == []
