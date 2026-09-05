"""Persistence access for intelligence signals (no domain logic)."""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.orm import Session

from contentos.intelligence.enums import SignalFamily
from contentos.intelligence.models import IntelligenceSignal


@dataclass(frozen=True, slots=True)
class FamilyTally:
    family: SignalFamily
    signal_count: int
    occurrence_total: int
    distinct_sources: int
    last_observed_at: datetime | None


class IntelligenceSignalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_hash(self, observation_hash: str) -> IntelligenceSignal | None:
        return self._session.scalar(
            select(IntelligenceSignal).where(
                IntelligenceSignal.observation_hash == observation_hash
            )
        )

    def add(self, row: IntelligenceSignal) -> IntelligenceSignal:
        self._session.add(row)
        self._session.flush()
        return row

    def list_signals(
        self,
        *,
        family: SignalFamily | None = None,
        limit: int,
        document_ids: Iterable[uuid.UUID] | None = None,
        opportunity_id: uuid.UUID | None = None,
    ) -> list[IntelligenceSignal]:
        query = self._base_query(family)
        if document_ids is not None or opportunity_id is not None:
            clauses: list[ColumnElement[bool]] = []
            if document_ids is not None:
                ids = list(document_ids)
                if ids:
                    clauses.append(IntelligenceSignal.normalized_document_id.in_(ids))
            if opportunity_id is not None:
                clauses.append(IntelligenceSignal.opportunity_id == opportunity_id)
            if not clauses:
                return []
            query = query.where(or_(*clauses))
        return list(self._session.scalars(query.limit(limit)))

    def list_by_concept_tokens(
        self,
        tokens: Sequence[str],
        *,
        family: SignalFamily | None = None,
        limit: int,
    ) -> list[IntelligenceSignal]:
        """Candidate rows whose concept key contains any of ``tokens``;
        the caller applies the stricter overlap rule."""
        if not tokens:
            return []
        query = self._base_query(family).where(
            or_(*[IntelligenceSignal.concept_key.contains(token) for token in tokens])
        )
        return list(self._session.scalars(query.limit(limit)))

    def tally_by_family(
        self, *, document_ids: Iterable[uuid.UUID] | None = None
    ) -> list[FamilyTally]:
        """Per-family tallies; ``document_ids`` bounds them to the signals
        extracted from those normalized documents (an empty bound is empty)."""
        query = select(
            IntelligenceSignal.family,
            func.count(IntelligenceSignal.id),
            func.coalesce(func.sum(IntelligenceSignal.occurrence_count), 0),
            func.count(func.distinct(IntelligenceSignal.source_id)),
            func.max(IntelligenceSignal.last_observed_at),
        )
        if document_ids is not None:
            ids = list(document_ids)
            if not ids:
                return []
            query = query.where(IntelligenceSignal.normalized_document_id.in_(ids))
        rows = self._session.execute(query.group_by(IntelligenceSignal.family)).all()
        return [
            FamilyTally(
                family=SignalFamily(str(family)),
                signal_count=int(count),
                occurrence_total=int(occurrences),
                distinct_sources=int(sources),
                last_observed_at=last,
            )
            for family, count, occurrences, sources, last in rows
        ]

    @staticmethod
    def _base_query(family: SignalFamily | None) -> Select[tuple[IntelligenceSignal]]:
        query = select(IntelligenceSignal).order_by(
            IntelligenceSignal.last_observed_at.desc(),
            IntelligenceSignal.concept_key,
            IntelligenceSignal.id,
        )
        if family is not None:
            query = query.where(IntelligenceSignal.family == family)
        return query
