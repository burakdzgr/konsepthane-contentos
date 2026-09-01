"""Narrow append/read-only idea persistence access. Callers own commit.

Idea versions and selection events are append-only: no update or delete
surface exists here, and PostgreSQL triggers enforce the same at the
database level.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.ideas.models import Idea, IdeaSelectionEvent
from contentos.opportunities.models import EditorialOpportunity


class IdeaRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def insert_idea(self, idea: Idea) -> Idea:
        self._session.add(idea)
        self._session.flush()
        return idea

    def insert_selection_event(self, event: IdeaSelectionEvent) -> IdeaSelectionEvent:
        self._session.add(event)
        self._session.flush()
        return event

    def get_idea(self, idea_id: uuid.UUID) -> Idea | None:
        return self._session.get(Idea, idea_id)

    def list_versions(self, logical_idea_id: uuid.UUID) -> list[Idea]:
        statement = (
            select(Idea).where(Idea.logical_idea_id == logical_idea_id).order_by(Idea.version)
        )
        return list(self._session.execute(statement).scalars())

    def max_version(self, logical_idea_id: uuid.UUID) -> int:
        current = self._session.scalar(
            select(func.max(Idea.version)).where(Idea.logical_idea_id == logical_idea_id)
        )
        return int(current or 0)

    def list_ideas(self, opportunity_id: uuid.UUID) -> list[Idea]:
        statement = (
            select(Idea)
            .where(Idea.opportunity_id == opportunity_id)
            .order_by(Idea.created_at, Idea.id)
        )
        return list(self._session.execute(statement).scalars())

    def list_selection_events(self, opportunity_id: uuid.UUID) -> list[IdeaSelectionEvent]:
        statement = (
            select(IdeaSelectionEvent)
            .where(IdeaSelectionEvent.opportunity_id == opportunity_id)
            .order_by(IdeaSelectionEvent.id)
        )
        return list(self._session.execute(statement).scalars())

    def get_latest_selection_event(self, opportunity_id: uuid.UUID) -> IdeaSelectionEvent | None:
        statement = (
            select(IdeaSelectionEvent)
            .where(IdeaSelectionEvent.opportunity_id == opportunity_id)
            .order_by(IdeaSelectionEvent.id.desc())
            .limit(1)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def lock_opportunity(self, opportunity_id: uuid.UUID) -> EditorialOpportunity | None:
        """Row-lock the owning opportunity to serialize version allocation
        and selection commands (no distributed lock; PostgreSQL is
        authoritative)."""
        statement = (
            select(EditorialOpportunity)
            .where(EditorialOpportunity.id == opportunity_id)
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()
