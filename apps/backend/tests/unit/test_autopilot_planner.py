"""Autopilot planner (ADR 0012): the whole advance/wait policy, table-driven."""

import uuid

import pytest

from contentos.autopilot.enums import AutopilotMode
from contentos.autopilot.planner import (
    ACTION_ACCEPT_BRIEF,
    ACTION_ACCEPT_REVIEW,
    ACTION_ANALYZE_INTENT,
    ACTION_ASSEMBLE_PACKAGE,
    ACTION_BUILD_PACK,
    ACTION_COMMISSION,
    ACTION_COMPOSE_BRIEF,
    ACTION_GENERATE_DRAFT,
    ACTION_GENERATE_IDEAS,
    ACTION_GENERATE_IMAGE,
    ACTION_GENERATE_REVIEW,
    ACTION_PUBLISH,
    ACTION_REQUEST_REWORK,
    ACTION_RESOLVE_CHANGES,
    ACTION_RUN_QA,
    ACTION_SCHEDULE,
    ACTION_SELECT_IDEA,
    MAX_REWORK_CYCLES,
    Snapshot,
    plan,
)
from contentos.briefs.enums import BriefStatus
from contentos.evidence_packs.enums import EvidencePackSufficiency
from contentos.opportunities.enums import OpportunityDisposition
from contentos.qa.enums import QaOutcome
from contentos.reviews.enums import ReviewVerdict
from contentos.workflow.enums import WorkflowState

WI = uuid.uuid4()
OPP = uuid.uuid4()
IDEA = uuid.uuid4()
PACK = uuid.uuid4()
ANALYSIS = uuid.uuid4()
BRIEF = uuid.uuid4()
DRAFT = uuid.uuid4()
REVIEW = uuid.uuid4()
PACKAGE = uuid.uuid4()

SUPERVISED = AutopilotMode.SUPERVISED
AUTONOMOUS = AutopilotMode.AUTONOMOUS


def snap(state: WorkflowState, **overrides: object) -> Snapshot:
    base = dict(
        work_item_id=WI, state=state, opportunity_id=OPP, disposition=OpportunityDisposition.OPEN
    )
    base.update(overrides)
    return Snapshot(**base)  # type: ignore[arg-type]


def test_off_mode_never_acts() -> None:
    action = plan(snap(WorkflowState.EVIDENCE_BUILDING), AutopilotMode.OFF)
    assert action.kind == "none"


@pytest.mark.parametrize("mode", [SUPERVISED, AUTONOMOUS])
def test_in_flight_actions_are_never_repeated(mode: AutopilotMode) -> None:
    action = plan(
        snap(WorkflowState.EVIDENCE_BUILDING, in_flight=frozenset({ACTION_GENERATE_IDEAS})), mode
    )
    assert action.kind == "none"


class TestCommissioning:
    def test_gate_refused_waits_in_both_modes(self) -> None:
        for mode in (SUPERVISED, AUTONOMOUS):
            action = plan(snap(WorkflowState.IDEA_SCORING, commission_eligible=False), mode)
            assert action.is_wait and action.name == "commission_gate"

    def test_supervised_waits_autonomous_commissions(self) -> None:
        eligible = snap(WorkflowState.IDEA_SCORING, commission_eligible=True)
        assert plan(eligible, SUPERVISED).is_wait
        action = plan(eligible, AUTONOMOUS)
        assert action.kind == "command" and action.name == ACTION_COMMISSION
        assert action.payload == {"opportunity_id": str(OPP)}


class TestEvidenceBuilding:
    def test_production_steps_run_in_both_modes(self) -> None:
        for mode in (SUPERVISED, AUTONOMOUS):
            ideas = plan(snap(WorkflowState.EVIDENCE_BUILDING, idea_count=0), mode)
            assert ideas.kind == "enqueue" and ideas.name == ACTION_GENERATE_IDEAS
            assert ideas.payload["candidate_count"] == 3
            pack = plan(
                snap(
                    WorkflowState.EVIDENCE_BUILDING,
                    idea_count=3,
                    selected_idea_id=IDEA,
                    eligible_evidence_count=4,
                ),
                mode,
            )
            assert pack.kind == "enqueue" and pack.name == ACTION_BUILD_PACK
            assert pack.payload == {"opportunity_id": str(OPP), "idea_id": str(IDEA)}

    def test_idea_choice_is_the_supervised_gate(self) -> None:
        pending = snap(WorkflowState.EVIDENCE_BUILDING, idea_count=3, best_idea_id=IDEA)
        assert plan(pending, SUPERVISED).name == "idea_selection"
        chosen = plan(pending, AUTONOMOUS)
        assert chosen.kind == "command" and chosen.name == ACTION_SELECT_IDEA
        assert chosen.payload == {"idea_id": str(IDEA)}

    def test_no_evidence_and_weak_pack_wait_for_research(self) -> None:
        none = plan(
            snap(WorkflowState.EVIDENCE_BUILDING, idea_count=1, selected_idea_id=IDEA), AUTONOMOUS
        )
        assert none.is_wait and none.name == "no_evidence"
        weak = plan(
            snap(
                WorkflowState.EVIDENCE_BUILDING,
                idea_count=1,
                selected_idea_id=IDEA,
                eligible_evidence_count=2,
                latest_pack_id=PACK,
                latest_pack_sufficiency=EvidencePackSufficiency.INSUFFICIENT,
            ),
            AUTONOMOUS,
        )
        assert weak.is_wait and weak.name == "pack_insufficient"


class TestMiddleStages:
    def test_intent_brief_draft_review_production(self) -> None:
        intent = plan(
            snap(WorkflowState.SEO_RESEARCH, selected_idea_id=IDEA, latest_pack_id=PACK), SUPERVISED
        )
        assert intent.name == ACTION_ANALYZE_INTENT and intent.payload["evidence_pack_id"] == str(
            PACK
        )
        brief = plan(
            snap(
                WorkflowState.BRIEFING,
                selected_idea_id=IDEA,
                latest_pack_id=PACK,
                intent_analysis_id=ANALYSIS,
            ),
            SUPERVISED,
        )
        assert brief.name == ACTION_COMPOSE_BRIEF and brief.payload["work_item_id"] == str(WI)
        draft = plan(snap(WorkflowState.DRAFTING, latest_brief_id=BRIEF), SUPERVISED)
        assert draft.name == ACTION_GENERATE_DRAFT and draft.payload == {
            "content_brief_id": str(BRIEF)
        }
        review = plan(snap(WorkflowState.EDITING, active_draft_id=DRAFT), SUPERVISED)
        assert review.name == ACTION_GENERATE_REVIEW

    def test_brief_acceptance_gate(self) -> None:
        drafted = snap(
            WorkflowState.BRIEFING, latest_brief_id=BRIEF, latest_brief_status=BriefStatus.DRAFT
        )
        assert plan(drafted, SUPERVISED).name == "brief_acceptance"
        assert plan(drafted, AUTONOMOUS).name == ACTION_ACCEPT_BRIEF

    def test_review_pass_and_bounded_rework(self) -> None:
        passed = snap(
            WorkflowState.EDITING,
            active_draft_id=DRAFT,
            active_review_id=REVIEW,
            active_review_verdict=ReviewVerdict.PASS,
        )
        assert plan(passed, SUPERVISED).name == "review_acceptance"
        assert plan(passed, AUTONOMOUS).name == ACTION_ACCEPT_REVIEW
        revise = snap(
            WorkflowState.EDITING,
            active_draft_id=DRAFT,
            active_review_id=REVIEW,
            active_review_verdict=ReviewVerdict.REVISE,
        )
        assert plan(revise, SUPERVISED).name == "review_revise"
        assert plan(revise, AUTONOMOUS).name == ACTION_REQUEST_REWORK
        exhausted = plan(
            snap(
                WorkflowState.EDITING,
                active_draft_id=DRAFT,
                active_review_id=REVIEW,
                active_review_verdict=ReviewVerdict.REVISE,
                rework_cycles=MAX_REWORK_CYCLES,
            ),
            AUTONOMOUS,
        )
        assert exhausted.is_wait and exhausted.name == "rework_limit"
        assert (
            plan(snap(WorkflowState.CHANGES_REQUESTED), AUTONOMOUS).name == ACTION_RESOLVE_CHANGES
        )
        assert plan(snap(WorkflowState.CHANGES_REQUESTED), SUPERVISED).is_wait


class TestQaAndPublication:
    def test_qa_runs_then_media_then_human(self) -> None:
        assert plan(snap(WorkflowState.QA_REVIEW), SUPERVISED).name == ACTION_RUN_QA
        not_ready = snap(
            WorkflowState.QA_REVIEW,
            active_qa_outcome=QaOutcome.NOT_READY,
            open_media_needs=(0, 1),
        )
        image = plan(not_ready, AUTONOMOUS)
        assert image.name == ACTION_GENERATE_IMAGE and image.payload["need_index"] == 0
        assert plan(not_ready, SUPERVISED).is_wait
        ready = plan(
            snap(WorkflowState.QA_REVIEW, active_qa_outcome=QaOutcome.READY_FOR_HUMAN_REVIEW),
            AUTONOMOUS,
        )
        assert ready.kind == "none"

    def test_final_approval_always_waits_for_a_human(self) -> None:
        for mode in (SUPERVISED, AUTONOMOUS):
            action = plan(snap(WorkflowState.AWAITING_HUMAN_REVIEW), mode)
            assert action.is_wait and action.name == "final_approval"

    def test_after_approval_autonomous_assembles_schedules_publishes(self) -> None:
        approved = snap(WorkflowState.APPROVED)
        assert plan(approved, SUPERVISED).is_wait
        assert plan(approved, AUTONOMOUS).name == ACTION_ASSEMBLE_PACKAGE
        packaged = plan(snap(WorkflowState.APPROVED, latest_package_id=PACKAGE), AUTONOMOUS)
        assert packaged.name == ACTION_SCHEDULE and packaged.payload == {
            "publication_package_id": str(PACKAGE)
        }
        assert plan(snap(WorkflowState.SCHEDULED), AUTONOMOUS).name == ACTION_PUBLISH
        assert plan(snap(WorkflowState.SCHEDULED), SUPERVISED).is_wait


def test_terminal_and_blocked_states() -> None:
    assert plan(snap(WorkflowState.BLOCKED), AUTONOMOUS).name == "blocked"
    assert plan(snap(WorkflowState.PUBLISHED), AUTONOMOUS).kind == "none"
    assert plan(snap(WorkflowState.REJECTED), AUTONOMOUS).kind == "none"
