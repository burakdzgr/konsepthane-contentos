"""Persistence-focused DiscoveryItem repository. Callers own commits."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.discovery.models import DiscoveryItem


class DiscoveryItemRepository:
    """Session-scoped persistence operations for discovery items."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, item_id: uuid.UUID) -> DiscoveryItem | None:
        return self._session.get(DiscoveryItem, item_id)

    def get_by_id_for_update(self, item_id: uuid.UUID) -> DiscoveryItem | None:
        """Lock one item for a transaction-scoped state transition."""
        statement = select(DiscoveryItem).where(DiscoveryItem.id == item_id).with_for_update()
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_source_and_hash(self, source_id: uuid.UUID, url_hash: str) -> DiscoveryItem | None:
        statement = select(DiscoveryItem).where(
            DiscoveryItem.source_id == source_id, DiscoveryItem.url_hash == url_hash
        )
        return self._session.execute(statement).scalar_one_or_none()

    def add(self, item: DiscoveryItem) -> DiscoveryItem:
        self._session.add(item)
        self._session.flush()
        return item
