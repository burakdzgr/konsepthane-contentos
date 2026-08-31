"""Persistence-focused Source repository. Callers own transaction commits."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.sources.enums import SourceKind
from contentos.sources.models import Source, SourceLifecycleEvent


class SourceRepository:
    """Session-scoped persistence operations for the Source Registry."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, source_id: uuid.UUID) -> Source | None:
        return self._session.get(Source, source_id)

    def get_by_slug(self, slug: str) -> Source | None:
        statement = select(Source).where(Source.slug == slug)
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_identity(self, kind: SourceKind, base_url: str) -> Source | None:
        statement = select(Source).where(Source.kind == kind, Source.base_url == base_url)
        return self._session.execute(statement).scalar_one_or_none()

    def add(self, source: Source) -> Source:
        self._session.add(source)
        self._session.flush()
        return source

    def add_lifecycle_event(self, event: SourceLifecycleEvent) -> SourceLifecycleEvent:
        self._session.add(event)
        self._session.flush()
        return event

    def list_lifecycle_events(self, source_id: uuid.UUID) -> list[SourceLifecycleEvent]:
        statement = (
            select(SourceLifecycleEvent)
            .where(SourceLifecycleEvent.source_id == source_id)
            .order_by(SourceLifecycleEvent.id)
        )
        return list(self._session.execute(statement).scalars())
