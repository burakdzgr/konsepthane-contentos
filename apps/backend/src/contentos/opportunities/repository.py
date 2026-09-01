"""Narrow persistence access for opportunities. Callers own commit."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.opportunities.models import EditorialOpportunity, OpportunityResearchInput


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
