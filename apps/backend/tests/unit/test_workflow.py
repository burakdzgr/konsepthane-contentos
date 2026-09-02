"""Editorial workflow foundation tests (real SQLite sessions, real services)."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from contentos.db.base import Base
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState, WorkItemOrigin
from contentos.workflow.errors import (
    InvalidWorkflowInputError,
    InvalidWorkflowTransitionError,
    WorkItemNotFoundError,
)
from contentos.workflow.models import EditorialWorkflowEvent, EditorialWorkItem
from contentos.workflow.repository import WorkflowRepository
from contentos.workflow.service import (
    INITIAL_STATE,
    STRUCTURAL_TRANSITIONS,
    WorkflowService,
)

PROMOTION_REFS = {
    "discovery_item_id": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    "normalized_document_id": "31111111-2222-4333-8444-555555555555",
    "duplicate_decision_id": "41111111-2222-4333-8444-555555555555",
}


@pytest.fixture()
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    # SQLite returns timezone-naive datetimes; PostgreSQL timestamptz is
    # always aware. Restore UTC awareness on load (test harness only) so
    # comparisons behave as in production (the established Task 16 shim).
    @event.listens_for(factory, "loaded_as_persistent")
    def _restore_utc_awareness(_session: Session, instance: Any) -> None:
        for key, value in list(instance.__dict__.items()):
            if isinstance(value, datetime) and value.tzinfo is None:
                instance.__dict__[key] = value.replace(tzinfo=UTC)

    return factory


@contextmanager
def open_session(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
    finally:
        session.close()


def create_item(
    session: Session,
    *,
    origin: WorkItemOrigin = WorkItemOrigin.RESEARCH_INTAKE,
    label: str = "Doğum günü konsepti",
    reason: str = "promoted from eligible Phase 2 research",
    request_id: str | None = "workflow-req-1",
) -> EditorialWorkItem:
    item = WorkflowService(session).create_work_item(
        origin=origin,
        title_working_label=label,
        reason=reason,
        actor_origin=WorkflowActorOrigin.SYSTEM,
        artifact_refs=PROMOTION_REFS,
        request_id=request_id,
    )
    session.commit()
    return item


class TestCreation:
    def test_creation_starts_at_idea_scoring_with_one_creation_event(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)

            assert item.current_state is WorkflowState.IDEA_SCORING
            assert item.origin is WorkItemOrigin.RESEARCH_INTAKE
            assert item.locale == "tr-TR"
            assert item.market == "TR"
            assert item.blocked_reason is None
            assert item.rejected_reason is None

            events = WorkflowRepository(session).list_events(item.id)
            assert len(events) == 1
            event = events[0]
            assert event.from_state is None
            assert event.to_state is WorkflowState.IDEA_SCORING
            assert event.actor_origin is WorkflowActorOrigin.SYSTEM
            assert event.reason == "promoted from eligible Phase 2 research"
            assert event.artifact_refs == PROMOTION_REFS
            assert event.request_id == "workflow-req-1"
            assert event.occurred_at == item.current_state_entered_at

    def test_creation_flushes_but_caller_owns_commit(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            WorkflowService(session).create_work_item(
                origin=WorkItemOrigin.OPERATOR,
                title_working_label="Kaydedilmeyen",
                reason="will be rolled back",
                actor_origin=WorkflowActorOrigin.OPERATOR,
            )
            session.rollback()

        with open_session(session_factory) as session:
            assert session.execute(select(EditorialWorkItem)).scalar_one_or_none() is None
            assert session.execute(select(EditorialWorkflowEvent)).scalar_one_or_none() is None

    def test_no_caller_arbitrary_initial_state_exists(self) -> None:
        import inspect

        signature = inspect.signature(WorkflowService.create_work_item)
        assert "initial_state" not in signature.parameters
        assert "current_state" not in signature.parameters
        assert INITIAL_STATE is WorkflowState.IDEA_SCORING

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("title_working_label", ""),
            ("title_working_label", "   "),
            ("title_working_label", "x" * 201),
            ("reason", ""),
            ("locale", "  "),
            ("market", "TUR"),
            ("market", "T"),
        ],
    )
    def test_creation_input_validation(
        self, session_factory: sessionmaker[Session], field: str, value: str
    ) -> None:
        kwargs = {
            "origin": WorkItemOrigin.OPERATOR,
            "title_working_label": "Geçerli Etiket",
            "reason": "valid reason",
            "actor_origin": WorkflowActorOrigin.OPERATOR,
        }
        kwargs[field] = value
        with open_session(session_factory) as session:
            with pytest.raises(InvalidWorkflowInputError):
                WorkflowService(session).create_work_item(**kwargs)  # type: ignore[arg-type]

    def test_artifact_refs_are_bounded(self, session_factory: sessionmaker[Session]) -> None:
        service_kwargs = {
            "origin": WorkItemOrigin.OPERATOR,
            "title_working_label": "Sınır Testi",
            "reason": "bounded refs",
            "actor_origin": WorkflowActorOrigin.OPERATOR,
        }
        oversized_value = {"body": "x" * 501}
        too_many = {f"k{i}": i for i in range(51)}
        too_deep = {"a": {"b": {"c": {"d": {"e": 1}}}}}
        not_object = ["a", "b"]
        with open_session(session_factory) as session:
            service = WorkflowService(session)
            for bad in (oversized_value, too_many, too_deep, not_object):
                with pytest.raises(InvalidWorkflowInputError):
                    service.create_work_item(artifact_refs=bad, **service_kwargs)  # type: ignore[arg-type]

    def test_invalid_request_id_rejected(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            with pytest.raises(InvalidWorkflowInputError):
                WorkflowService(session).create_work_item(
                    origin=WorkItemOrigin.OPERATOR,
                    title_working_label="Korelasyon",
                    reason="bad request id",
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    request_id="not valid!!",
                )


class TestTransitions:
    def test_allowed_transition_updates_projection_and_appends_event(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            updated = WorkflowService(session).transition(
                item.id,
                WorkflowState.EVIDENCE_BUILDING,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="opportunity commissioned",
                artifact_refs={"opportunity_id": "51111111-2222-4333-8444-555555555555"},
                request_id="workflow-req-2",
            )
            session.commit()

            assert updated.current_state is WorkflowState.EVIDENCE_BUILDING
            events = WorkflowRepository(session).list_events(item.id)
            assert [event.to_state for event in events] == [
                WorkflowState.IDEA_SCORING,
                WorkflowState.EVIDENCE_BUILDING,
            ]
            last = events[-1]
            assert last.from_state is WorkflowState.IDEA_SCORING
            assert last.actor_origin is WorkflowActorOrigin.OPERATOR
            assert last.reason == "opportunity commissioned"
            assert last.request_id == "workflow-req-2"
            assert last.occurred_at == updated.current_state_entered_at

    def test_invalid_transition_raises_and_mutates_nothing(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item_id = create_item(session).id
            with pytest.raises(InvalidWorkflowTransitionError):
                WorkflowService(session).transition(
                    item_id,
                    WorkflowState.BRIEFING,
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    reason="skipping states",
                )
            session.rollback()

        with open_session(session_factory) as session:
            fresh = WorkflowRepository(session).get_by_id(item_id)
            assert fresh is not None
            assert fresh.current_state is WorkflowState.IDEA_SCORING
            assert len(WorkflowRepository(session).list_events(item_id)) == 1

    def test_missing_item_raises_not_found(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            with pytest.raises(WorkItemNotFoundError):
                WorkflowService(session).transition(
                    uuid.uuid4(),
                    WorkflowState.EVIDENCE_BUILDING,
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    reason="ghost",
                )

    def test_same_state_transition_is_invalid_outside_measuring_loop(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            with pytest.raises(InvalidWorkflowTransitionError):
                WorkflowService(session).transition(
                    item.id,
                    WorkflowState.IDEA_SCORING,
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    reason="noop",
                )

    def test_stale_expected_transition_fails_against_actual_state(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """A raced second request validates against the real current state."""
        with open_session(session_factory) as session:
            item_id = create_item(session).id
            service = WorkflowService(session)
            service.transition(
                item_id,
                WorkflowState.EVIDENCE_BUILDING,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="first writer wins",
            )
            session.commit()

        with open_session(session_factory) as session:
            # The second caller believed the item was still in IDEA_SCORING
            # and repeats the exact same transition (duplicate delivery).
            # It must fail against the actual state instead of silently
            # appending an identical event.
            with pytest.raises(InvalidWorkflowTransitionError):
                WorkflowService(session).transition(
                    item_id,
                    WorkflowState.EVIDENCE_BUILDING,
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    reason="stale duplicate of the first request",
                )
            session.rollback()

        with open_session(session_factory) as session:
            events = WorkflowRepository(session).list_events(item_id)
            # No impossible history was appended.
            assert [event.to_state for event in events] == [
                WorkflowState.IDEA_SCORING,
                WorkflowState.EVIDENCE_BUILDING,
            ]

    def test_full_phase3_happy_path_is_structurally_allowed(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = WorkflowService(session)
            for target in (
                WorkflowState.EVIDENCE_BUILDING,
                WorkflowState.SEO_RESEARCH,
                WorkflowState.BRIEFING,
            ):
                service.transition(
                    item.id,
                    target,
                    actor_origin=WorkflowActorOrigin.SYSTEM,
                    reason=f"advance to {target.value}",
                )
            session.commit()
            assert item.current_state is WorkflowState.BRIEFING


class TestBlocked:
    def test_entering_blocked_sets_reason_and_resume_restores_prior_state(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = WorkflowService(session)
            service.transition(
                item.id,
                WorkflowState.EVIDENCE_BUILDING,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="commissioned",
            )
            service.transition(
                item.id,
                WorkflowState.BLOCKED,
                actor_origin=WorkflowActorOrigin.SYSTEM,
                reason="evidence insufficient: menü kanıtı eksik",
            )
            session.commit()
            assert item.blocked_reason == "evidence insufficient: menü kanıtı eksik"

            # Resume target is derived from durable history: only the prior
            # state (EVIDENCE_BUILDING) or REJECTED are allowed.
            with pytest.raises(InvalidWorkflowTransitionError):
                service.transition(
                    item.id,
                    WorkflowState.SEO_RESEARCH,
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    reason="skipping resume target",
                )
            session.rollback()

            service.transition(
                item.id,
                WorkflowState.EVIDENCE_BUILDING,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="block resolved: kanıt eklendi",
            )
            session.commit()

            assert item.current_state is WorkflowState.EVIDENCE_BUILDING
            # Current-row projection clears; the immutable event history
            # preserves the original block reason.
            assert item.blocked_reason is None
            events = WorkflowRepository(session).list_events(item.id)
            blocked_events = [event for event in events if event.to_state is WorkflowState.BLOCKED]
            assert len(blocked_events) == 1
            assert blocked_events[0].reason == "evidence insufficient: menü kanıtı eksik"

    def test_blocked_can_move_to_rejected(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = WorkflowService(session)
            service.transition(
                item.id,
                WorkflowState.BLOCKED,
                actor_origin=WorkflowActorOrigin.SYSTEM,
                reason="required signal unavailable",
            )
            service.transition(
                item.id,
                WorkflowState.REJECTED,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="not worth unblocking",
            )
            session.commit()

            assert item.current_state is WorkflowState.REJECTED
            assert item.rejected_reason == "not worth unblocking"
            assert item.blocked_reason is None


class TestRejected:
    def test_rejecting_sets_reason(self, session_factory: sessionmaker[Session]) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            WorkflowService(session).transition(
                item.id,
                WorkflowState.REJECTED,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="fırsat değersiz",
            )
            session.commit()
            assert item.current_state is WorkflowState.REJECTED
            assert item.rejected_reason == "fırsat değersiz"

    def test_rejected_only_reopens_to_researching(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = WorkflowService(session)
            service.transition(
                item.id,
                WorkflowState.REJECTED,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="ret",
            )
            session.commit()

            with pytest.raises(InvalidWorkflowTransitionError):
                service.transition(
                    item.id,
                    WorkflowState.IDEA_SCORING,
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    reason="cannot jump back",
                )
            session.rollback()

            service.transition(
                item.id,
                WorkflowState.RESEARCHING,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="explicitly reopened with new angle",
            )
            session.commit()
            assert item.current_state is WorkflowState.RESEARCHING
            assert item.rejected_reason is None


class TestMatrixAndHistory:
    def test_structural_matrix_matches_workflow_document(self) -> None:
        # Spot-pin the canonical rows most relevant to Phase 3 plus the
        # explicit MEASURING self-loop and terminal reopen paths.
        assert STRUCTURAL_TRANSITIONS[WorkflowState.IDEA_SCORING] == frozenset(
            {WorkflowState.EVIDENCE_BUILDING, WorkflowState.REJECTED, WorkflowState.BLOCKED}
        )
        assert STRUCTURAL_TRANSITIONS[WorkflowState.SEO_RESEARCH] == frozenset(
            {WorkflowState.BRIEFING, WorkflowState.BLOCKED}
        )
        assert STRUCTURAL_TRANSITIONS[WorkflowState.BRIEFING] == frozenset(
            {WorkflowState.DRAFTING, WorkflowState.CHANGES_REQUESTED}
        )
        assert WorkflowState.MEASURING in STRUCTURAL_TRANSITIONS[WorkflowState.MEASURING]
        assert STRUCTURAL_TRANSITIONS[WorkflowState.REJECTED] == frozenset(
            {WorkflowState.RESEARCHING}
        )
        assert STRUCTURAL_TRANSITIONS[WorkflowState.ARCHIVED] == frozenset(
            {WorkflowState.RESEARCHING}
        )
        # BLOCKED / CHANGES_REQUESTED exits are dynamic (history-derived),
        # so the static matrix deliberately has no rows for them.
        assert WorkflowState.BLOCKED not in STRUCTURAL_TRANSITIONS
        assert WorkflowState.CHANGES_REQUESTED not in STRUCTURAL_TRANSITIONS
        # Every referenced target is a canonical state.
        for targets in STRUCTURAL_TRANSITIONS.values():
            for target in targets:
                assert isinstance(target, WorkflowState)

    def test_history_is_deterministic_append_order(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = WorkflowService(session)
            service.transition(
                item.id,
                WorkflowState.EVIDENCE_BUILDING,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="one",
            )
            service.transition(
                item.id,
                WorkflowState.SEO_RESEARCH,
                actor_origin=WorkflowActorOrigin.SYSTEM,
                reason="two",
            )
            session.commit()

            events = WorkflowRepository(session).list_events(item.id)
            assert [event.id for event in events] == sorted(event.id for event in events)
            assert events[0].from_state is None
            assert [event.reason for event in events] == [
                "promoted from eligible Phase 2 research",
                "one",
                "two",
            ]
            # Each event chains from the previous event's to_state.
            for previous, current in zip(events, events[1:], strict=False):
                assert current.from_state is previous.to_state

    def test_repository_exposes_no_mutation_or_delete_surface(self) -> None:
        exposed = {name for name in dir(WorkflowRepository) if not name.startswith("_")}
        assert exposed == {
            "insert_work_item",
            "append_event",
            "get_by_id",
            "get_by_id_for_update",
            "list_events",
            "get_latest_entry_event",
        }


def advance_to_editing(session: Session, item_id: uuid.UUID) -> WorkflowService:
    service = WorkflowService(session)
    for target in (
        WorkflowState.EVIDENCE_BUILDING,
        WorkflowState.SEO_RESEARCH,
        WorkflowState.BRIEFING,
        WorkflowState.DRAFTING,
        WorkflowState.EDITING,
    ):
        service.transition(
            item_id,
            target,
            actor_origin=WorkflowActorOrigin.SYSTEM,
            reason=f"advance to {target.value}",
        )
    return service


class TestResponsibleStateRouting:
    """Named CHANGES_REQUESTED responsible-state routing (Phase 4 Task 6)."""

    def test_editing_rework_routes_to_recorded_responsible_state(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = advance_to_editing(session, item.id)
            service.transition(
                item.id,
                WorkflowState.CHANGES_REQUESTED,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="taslak yeniden yazılmalı: bütçe bölümü zayıf",
                artifact_refs={"content_draft_id": "61111111-2222-4333-8444-555555555555"},
                responsible_state=WorkflowState.DRAFTING,
            )
            session.commit()

            events = WorkflowRepository(session).list_events(item.id)
            entry = events[-1]
            assert entry.to_state is WorkflowState.CHANGES_REQUESTED
            # The responsible state is durably recorded in the validated
            # entry event, alongside the caller's own refs.
            assert entry.artifact_refs["responsible_state"] == "drafting"
            assert entry.artifact_refs["content_draft_id"] == (
                "61111111-2222-4333-8444-555555555555"
            )

            # Return-to-origin is now closed: the recorded responsible state
            # is the ONLY exit.
            with pytest.raises(InvalidWorkflowTransitionError):
                service.transition(
                    item.id,
                    WorkflowState.EDITING,
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    reason="origin is not the responsible state here",
                )
            session.rollback()

            service.transition(
                item.id,
                WorkflowState.DRAFTING,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="rework routed to the writer stage",
            )
            session.commit()
            assert item.current_state is WorkflowState.DRAFTING
            trail = [event.to_state for event in WorkflowRepository(session).list_events(item.id)]
            assert trail[-3:] == [
                WorkflowState.EDITING,
                WorkflowState.CHANGES_REQUESTED,
                WorkflowState.DRAFTING,
            ]

    def test_entry_without_responsible_state_keeps_return_to_origin(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = advance_to_editing(session, item.id)
            service.transition(
                item.id,
                WorkflowState.CHANGES_REQUESTED,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="küçük düzeltmeler istendi",
            )
            session.commit()

            with pytest.raises(InvalidWorkflowTransitionError):
                service.transition(
                    item.id,
                    WorkflowState.DRAFTING,
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    reason="no responsible state was recorded",
                )
            session.rollback()

            service.transition(
                item.id,
                WorkflowState.EDITING,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="düzeltmeler yapıldı",
            )
            session.commit()
            assert item.current_state is WorkflowState.EDITING

    def test_responsible_state_requires_changes_requested_target(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = advance_to_editing(session, item.id)
            with pytest.raises(InvalidWorkflowInputError):
                service.transition(
                    item.id,
                    WorkflowState.QA_REVIEW,
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    reason="responsible state outside changes_requested",
                    responsible_state=WorkflowState.DRAFTING,
                )

    def test_unpermitted_responsible_state_for_review_context(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = advance_to_editing(session, item.id)
            # From EDITING, only DRAFTING is in the fixed vocabulary.
            with pytest.raises(InvalidWorkflowTransitionError):
                service.transition(
                    item.id,
                    WorkflowState.CHANGES_REQUESTED,
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    reason="arbitrary target must be impossible",
                    responsible_state=WorkflowState.QA_REVIEW,
                )
            session.rollback()

        with open_session(session_factory) as session:
            item = create_item(session)
            service = WorkflowService(session)
            for target in (
                WorkflowState.EVIDENCE_BUILDING,
                WorkflowState.SEO_RESEARCH,
                WorkflowState.BRIEFING,
            ):
                service.transition(
                    item.id,
                    target,
                    actor_origin=WorkflowActorOrigin.SYSTEM,
                    reason=f"advance to {target.value}",
                )
            # BRIEFING enters CHANGES_REQUESTED structurally, but has NO
            # responsible-state vocabulary yet: naming one is rejected.
            with pytest.raises(InvalidWorkflowTransitionError):
                service.transition(
                    item.id,
                    WorkflowState.CHANGES_REQUESTED,
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    reason="no vocabulary for this context",
                    responsible_state=WorkflowState.DRAFTING,
                )

    def test_artifact_refs_cannot_forge_responsible_state(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = advance_to_editing(session, item.id)
            with pytest.raises(InvalidWorkflowInputError):
                service.transition(
                    item.id,
                    WorkflowState.CHANGES_REQUESTED,
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    reason="forged via raw refs",
                    artifact_refs={"responsible_state": "drafting"},
                )

    def test_unrecognized_recorded_responsible_state_fails_closed(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = advance_to_editing(session, item.id)
            service.transition(
                item.id,
                WorkflowState.CHANGES_REQUESTED,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="rework istendi",
                responsible_state=WorkflowState.DRAFTING,
            )
            session.commit()

            # Simulate a corrupt durable record (SQLite harness has no
            # append-only trigger); the service must fail closed, never
            # silently reroute.
            entry = WorkflowRepository(session).get_latest_entry_event(
                item.id, WorkflowState.CHANGES_REQUESTED
            )
            assert entry is not None
            entry.artifact_refs = {"responsible_state": "not-a-state"}
            session.flush()

            with pytest.raises(InvalidWorkflowTransitionError, match="unrecognized"):
                service.transition(
                    item.id,
                    WorkflowState.DRAFTING,
                    actor_origin=WorkflowActorOrigin.OPERATOR,
                    reason="cannot resolve the durable record",
                )

    def test_resolve_changes_requested_routes_to_recorded_state(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = advance_to_editing(session, item.id)
            service.transition(
                item.id,
                WorkflowState.CHANGES_REQUESTED,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="rework istendi",
                responsible_state=WorkflowState.DRAFTING,
            )
            session.commit()
            resolved = service.resolve_changes_requested(
                item.id, reason="yazara yönlendirildi", request_id="workflow-req-7"
            )
            session.commit()
            assert resolved.current_state is WorkflowState.DRAFTING
            last = WorkflowRepository(session).list_events(item.id)[-1]
            assert last.actor_origin is WorkflowActorOrigin.OPERATOR
            assert last.reason == "yazara yönlendirildi"

    def test_resolve_changes_requested_falls_back_to_origin(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = advance_to_editing(session, item.id)
            service.transition(
                item.id,
                WorkflowState.CHANGES_REQUESTED,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="küçük düzeltme",
            )
            session.commit()
            resolved = service.resolve_changes_requested(item.id, reason="düzeltildi")
            session.commit()
            assert resolved.current_state is WorkflowState.EDITING

    def test_resolve_changes_requested_requires_the_state(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            with pytest.raises(InvalidWorkflowTransitionError):
                WorkflowService(session).resolve_changes_requested(
                    item.id, reason="not in changes_requested"
                )

    def test_blocked_semantics_are_untouched_by_routing(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with open_session(session_factory) as session:
            item = create_item(session)
            service = advance_to_editing(session, item.id)
            # DRAFTING-adjacent BLOCKED entry/resume still resolves purely
            # from history (no responsible-state involvement).
            service.transition(
                item.id,
                WorkflowState.CHANGES_REQUESTED,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="rework",
                responsible_state=WorkflowState.DRAFTING,
            )
            service.transition(
                item.id,
                WorkflowState.DRAFTING,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                reason="routed",
            )
            service.transition(
                item.id,
                WorkflowState.BLOCKED,
                actor_origin=WorkflowActorOrigin.SYSTEM,
                reason="brief superseded while drafting",
            )
            session.commit()
            resumed = service.resolve_block(
                item.id, reason="brief re-pinned", request_id="workflow-req-9"
            )
            session.commit()
            assert resumed.current_state is WorkflowState.DRAFTING
