"""Narrow append/read access to search-signal history. Callers own commit.

No update/delete surface and no "effective/current signal" helper exist on
purpose: corrections append new observations, and later consumers choose and
pin exact signal IDs themselves.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.signals.enums import SearchSignalType
from contentos.signals.models import SearchSignal

DEFAULT_LIST_LIMIT = 100


class SearchSignalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, signal: SearchSignal) -> SearchSignal:
        self._session.add(signal)
        self._session.flush()
        return signal

    def get_by_id(self, signal_id: uuid.UUID) -> SearchSignal | None:
        return self._session.get(SearchSignal, signal_id)

    def get_by_observation_hash(self, observation_hash: str) -> SearchSignal | None:
        statement = select(SearchSignal).where(SearchSignal.observation_hash == observation_hash)
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_subject(
        self,
        subject: str,
        locale: str,
        market: str,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> list[SearchSignal]:
        """All observations for one subject, newest first, deterministically."""
        statement = (
            select(SearchSignal)
            .where(
                SearchSignal.subject == subject,
                SearchSignal.locale == locale,
                SearchSignal.market == market,
            )
            .order_by(
                SearchSignal.observed_at.desc(),
                SearchSignal.recorded_at.desc(),
                SearchSignal.id.desc(),
            )
            .limit(limit)
        )
        return list(self._session.execute(statement).scalars())

    def list_by_type(
        self, signal_type: SearchSignalType, *, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[SearchSignal]:
        statement = (
            select(SearchSignal)
            .where(SearchSignal.signal_type == signal_type)
            .order_by(
                SearchSignal.observed_at.desc(),
                SearchSignal.recorded_at.desc(),
                SearchSignal.id.desc(),
            )
            .limit(limit)
        )
        return list(self._session.execute(statement).scalars())
