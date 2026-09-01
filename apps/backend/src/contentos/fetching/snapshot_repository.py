"""Persistence-only FetchSnapshot repository. Callers own transactions."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.fetching.models import FetchOutcome
from contentos.fetching.snapshots import FetchSnapshot


class FetchSnapshotRepository:
    """Append and read immutable fetch-attempt history."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, snapshot: FetchSnapshot) -> FetchSnapshot:
        self._session.add(snapshot)
        self._session.flush()
        return snapshot

    def get_by_id(self, snapshot_id: uuid.UUID) -> FetchSnapshot | None:
        return self._session.get(FetchSnapshot, snapshot_id)

    def get_latest_successful_for_discovery_item(
        self, discovery_item_id: uuid.UUID
    ) -> FetchSnapshot | None:
        """Return the newest successful attempt without listing full history."""
        statement = (
            select(FetchSnapshot)
            .where(
                FetchSnapshot.discovery_item_id == discovery_item_id,
                FetchSnapshot.fetch_outcome == FetchOutcome.SUCCESS,
            )
            .order_by(
                FetchSnapshot.fetched_at.desc(),
                FetchSnapshot.created_at.desc(),
                FetchSnapshot.id.desc(),
            )
            .limit(1)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_discovery_item(self, discovery_item_id: uuid.UUID) -> list[FetchSnapshot]:
        statement = (
            select(FetchSnapshot)
            .where(FetchSnapshot.discovery_item_id == discovery_item_id)
            .order_by(
                FetchSnapshot.fetched_at,
                FetchSnapshot.created_at,
                FetchSnapshot.id,
            )
        )
        return list(self._session.execute(statement).scalars())
