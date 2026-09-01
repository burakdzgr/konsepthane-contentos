"""Narrow persistence access for opportunities. Callers own commit."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.opportunities.models import (
    EditorialOpportunity,
    OpportunityResearchInput,
    OpportunityScore,
    OpportunityScoreComponent,
)


class OpportunityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def insert_opportunity(self, opportunity: EditorialOpportunity) -> EditorialOpportunity:
        self._session.add(opportunity)
        self._session.flush()
        return opportunity

    def insert_research_input(
        self, research_input: OpportunityResearchInput
    ) -> OpportunityResearchInput:
        self._session.add(research_input)
        self._session.flush()
        return research_input

    def get_by_id(self, opportunity_id: uuid.UUID) -> EditorialOpportunity | None:
        return self._session.get(EditorialOpportunity, opportunity_id)

    def get_by_work_item_id(self, work_item_id: uuid.UUID) -> EditorialOpportunity | None:
        statement = select(EditorialOpportunity).where(
            EditorialOpportunity.work_item_id == work_item_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_promotion_root(
        self, normalized_document_id: uuid.UUID
    ) -> EditorialOpportunity | None:
        statement = select(EditorialOpportunity).where(
            EditorialOpportunity.promotion_root_document_id == normalized_document_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_research_inputs(self, opportunity_id: uuid.UUID) -> list[OpportunityResearchInput]:
        statement = (
            select(OpportunityResearchInput)
            .where(OpportunityResearchInput.opportunity_id == opportunity_id)
            .order_by(OpportunityResearchInput.added_at, OpportunityResearchInput.id)
        )
        return list(self._session.execute(statement).scalars())

    # --- Scores (append/read only; no update or delete surface) -----------

    def insert_score(self, score: OpportunityScore) -> OpportunityScore:
        self._session.add(score)
        self._session.flush()
        return score

    def insert_score_component(
        self, component: OpportunityScoreComponent
    ) -> OpportunityScoreComponent:
        self._session.add(component)
        self._session.flush()
        return component

    def get_score_by_identity(
        self,
        opportunity_id: uuid.UUID,
        engine_name: str,
        engine_version: str,
        input_snapshot_hash: str,
    ) -> OpportunityScore | None:
        statement = select(OpportunityScore).where(
            OpportunityScore.opportunity_id == opportunity_id,
            OpportunityScore.engine_name == engine_name,
            OpportunityScore.engine_version == engine_version,
            OpportunityScore.input_snapshot_hash == input_snapshot_hash,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_effective_score(self, opportunity_id: uuid.UUID) -> OpportunityScore | None:
        """The latest/effective score: evaluated_at DESC, then id DESC."""
        statement = (
            select(OpportunityScore)
            .where(OpportunityScore.opportunity_id == opportunity_id)
            .order_by(OpportunityScore.evaluated_at.desc(), OpportunityScore.id.desc())
            .limit(1)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_scores(self, opportunity_id: uuid.UUID) -> list[OpportunityScore]:
        statement = (
            select(OpportunityScore)
            .where(OpportunityScore.opportunity_id == opportunity_id)
            .order_by(OpportunityScore.evaluated_at, OpportunityScore.id)
        )
        return list(self._session.execute(statement).scalars())

    def list_score_components(self, score_id: uuid.UUID) -> list[OpportunityScoreComponent]:
        statement = (
            select(OpportunityScoreComponent)
            .where(OpportunityScoreComponent.score_id == score_id)
            .order_by(OpportunityScoreComponent.component)
        )
        return list(self._session.execute(statement).scalars())
