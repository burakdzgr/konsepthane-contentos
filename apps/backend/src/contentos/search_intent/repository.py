"""Narrow append/read-only analysis persistence access. Callers own commit."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.opportunities.models import EditorialOpportunity
from contentos.search_intent.models import SearchIntentAnalysis


class SearchIntentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, analysis: SearchIntentAnalysis) -> SearchIntentAnalysis:
        self._session.add(analysis)
        self._session.flush()
        return analysis

    def get_by_id(self, analysis_id: uuid.UUID) -> SearchIntentAnalysis | None:
        return self._session.get(SearchIntentAnalysis, analysis_id)

    def get_by_identity(
        self,
        opportunity_id: uuid.UUID,
        engine_name: str,
        engine_version: str,
        input_snapshot_hash: str,
    ) -> SearchIntentAnalysis | None:
        statement = select(SearchIntentAnalysis).where(
            SearchIntentAnalysis.opportunity_id == opportunity_id,
            SearchIntentAnalysis.engine_name == engine_name,
            SearchIntentAnalysis.engine_version == engine_version,
            SearchIntentAnalysis.input_snapshot_hash == input_snapshot_hash,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_synthesis_attempt(
        self, synthesis_attempt_id: uuid.UUID
    ) -> SearchIntentAnalysis | None:
        statement = select(SearchIntentAnalysis).where(
            SearchIntentAnalysis.synthesis_attempt_id == synthesis_attempt_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_by_opportunity(self, opportunity_id: uuid.UUID) -> list[SearchIntentAnalysis]:
        statement = (
            select(SearchIntentAnalysis)
            .where(SearchIntentAnalysis.opportunity_id == opportunity_id)
            .order_by(SearchIntentAnalysis.version)
        )
        return list(self._session.execute(statement).scalars())

    def list_by_idea(self, idea_id: uuid.UUID) -> list[SearchIntentAnalysis]:
        statement = (
            select(SearchIntentAnalysis)
            .where(SearchIntentAnalysis.idea_id == idea_id)
            .order_by(SearchIntentAnalysis.created_at, SearchIntentAnalysis.id)
        )
        return list(self._session.execute(statement).scalars())

    def next_version(self, opportunity_id: uuid.UUID) -> int:
        current = self._session.scalar(
            select(func.max(SearchIntentAnalysis.version)).where(
                SearchIntentAnalysis.opportunity_id == opportunity_id
            )
        )
        return int(current or 0) + 1

    def lock_opportunity(self, opportunity_id: uuid.UUID) -> EditorialOpportunity | None:
        """Row-lock the owning opportunity to serialize version allocation."""
        statement = (
            select(EditorialOpportunity)
            .where(EditorialOpportunity.id == opportunity_id)
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()
