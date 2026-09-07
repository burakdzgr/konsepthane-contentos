import uuid
from datetime import UTC, date, datetime

import pytest
from editorial_harness import Context, Harness, seed_scored
from sqlalchemy import select

from contentos.autopilot.daily import DailyPreparationService, local_day
from contentos.autopilot.models import DailyPreparation
from contentos.core.config import Settings
from contentos.opportunities.enums import ScoreEligibility
from contentos.sources.enums import DiscoveryStrategy, SourceKind
from contentos.sources.models import Source
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.models import EditorialWorkflowEvent


@pytest.fixture
def harness() -> Harness:
    return Harness()


def setup(
    harness: Harness, *, eligibility: ScoreEligibility = ScoreEligibility.COMMISSIONABLE
) -> Context:
    context = Context()
    with harness.session() as session:
        seed_scored(session, context, eligibility)
    return context


def configure(harness: Harness, target: int = 1) -> None:
    with harness.session() as session:
        sources = [str(value) for value in session.scalars(select(Source.id))]
    response = harness.put(
        "/internal/autopilot/daily-plan",
        json_body={
            "target": target,
            "source_ids": sources,
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text


def test_settings_are_durable_and_audited(harness: Harness) -> None:
    setup(harness)
    configure(harness, 10)
    result = harness.get("/internal/autopilot/daily-plan").json()
    assert result["target"] == 10
    assert result["mode"] == "autonomous"
    assert result["completed"] == 0
    assert all(source["selected"] for source in result["sources"])
    assert harness.get("/internal/autopilot").json()["actor_user_id"]


@pytest.mark.parametrize("target,sources", [(0, []), (51, []), (10, []), (10, [str(uuid.uuid4())])])
def test_invalid_plan_does_not_enable_bot(
    harness: Harness, target: int, sources: list[str]
) -> None:
    response = harness.put(
        "/internal/autopilot/daily-plan",
        json_body={
            "target": target,
            "source_ids": sources,
            "enabled": True,
        },
    )
    assert response.status_code == 422
    assert harness.get("/internal/autopilot").json()["mode"] == "off"


def test_reservation_is_not_completion_and_carries_over(harness: Harness) -> None:
    first, second = setup(harness), setup(harness)
    configure(harness)
    with harness.session() as session:
        service = DailyPreparationService(session)
        candidates = [first.work_item_id, second.work_item_id]
        assert service.reserve(candidates, today=date(2026, 9, 6)) == [first.work_item_id]
        session.commit()
    with harness.session() as session:
        service = DailyPreparationService(session)
        assert service.reserve(candidates, today=date(2026, 9, 7)) == [first.work_item_id]
        assert service.view()["completed"] == 0
        assert len(list(session.scalars(select(DailyPreparation)))) == 1


def test_weak_opportunity_does_not_consume_target(harness: Harness) -> None:
    weak = setup(harness, eligibility=ScoreEligibility.NOT_COMMISSIONABLE)
    good = setup(harness)
    configure(harness)
    with harness.session() as session:
        assert DailyPreparationService(session).reserve([weak.work_item_id, good.work_item_id]) == [
            good.work_item_id
        ]


def test_unselected_source_is_not_admitted(harness: Harness) -> None:
    first = setup(harness)
    configure(harness)
    second = setup(harness)
    with harness.session() as session:
        assert DailyPreparationService(session).reserve(
            [second.work_item_id, first.work_item_id]
        ) == [first.work_item_id]


def test_day_boundary_is_turkey_not_utc() -> None:
    assert local_day(datetime(2026, 9, 6, 21, 1, tzinfo=UTC)) == date(2026, 9, 7)


def test_daily_research_is_not_restarted_by_repeated_sweeps(harness: Harness) -> None:
    setup(harness)
    configure(harness)
    with harness.session() as session:
        source = session.scalars(select(Source)).first()
        assert source is not None
        source.kind = SourceKind.SITEMAP
        source.discovery_strategy = DiscoveryStrategy.SITEMAP
        session.flush()
        service = DailyPreparationService(session)
        assert len(service.start_daily_research(Settings())) == 1
        assert service.start_daily_research(Settings()) == []
        session.commit()
    with harness.session() as session:
        assert DailyPreparationService(session).start_daily_research(Settings()) == []


def test_only_real_review_transition_counts_once(harness: Harness) -> None:
    first, second = setup(harness), setup(harness)
    configure(harness)
    with harness.session() as session:
        service = DailyPreparationService(session)
        service.reserve([first.work_item_id], today=date(2026, 9, 6))
        # Fixture represents the durable transition emitted by the QA service;
        # a Celery success/attempt row alone deliberately has no effect.
        session.add(
            EditorialWorkflowEvent(
                work_item_id=first.work_item_id,
                from_state=WorkflowState.QA_REVIEW,
                to_state=WorkflowState.AWAITING_HUMAN_REVIEW,
                actor_origin=WorkflowActorOrigin.SYSTEM,
                reason="QA passed fixture",
                occurred_at=datetime(2026, 9, 6, 21, 1, tzinfo=UTC),
                artifact_refs={},
            )
        )
        session.flush()
        service.reconcile()
        service.reconcile()
        row = session.get(DailyPreparation, first.work_item_id)
        assert row is not None and row.completed_on == date(2026, 9, 7)
        assert service.reserve([second.work_item_id], today=date(2026, 9, 7)) == []
        assert service.reserve([second.work_item_id], today=date(2026, 9, 8)) == [
            second.work_item_id
        ]
