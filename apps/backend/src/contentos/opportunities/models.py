"""Editorial opportunity persistence models (references, never content)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.db.base import Base
from contentos.db.types import string_enum
from contentos.opportunities.enums import (
    OpportunityActor,
    OpportunityDisposition,
    ResearchInputRole,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EditorialOpportunity(Base):
    """The relational opportunity anchor: 1:1 with its EditorialWorkItem.

    `promotion_root_document_id` is the DATABASE-BACKED promotion identity
    (accepted design §10.3: one work item per promoted document root). It is
    deliberately separate from research-input roles, so the same document may
    still be attached as supporting/context research to a different
    opportunity without ever creating a second promotion.
    """

    __tablename__ = "editorial_opportunities"
    __table_args__ = (
        UniqueConstraint("work_item_id", name="uq_editorial_opportunities_work_item"),
        UniqueConstraint(
            "promotion_root_document_id",
            name="uq_editorial_opportunities_promotion_root",
        ),
        CheckConstraint(
            "length(trim(topic_summary)) > 0",
            name="ck_editorial_opportunities_topic_nonempty",
        ),
        CheckConstraint(
            "(disposition = 'open' AND disposition_reason IS NULL "
            "AND disposition_at IS NULL AND disposition_by IS NULL) OR "
            "(disposition != 'open' AND disposition_reason IS NOT NULL "
            "AND length(trim(disposition_reason)) > 0 "
            "AND disposition_at IS NOT NULL AND disposition_by IS NOT NULL)",
            name="ck_editorial_opportunities_disposition_consistency",
        ),
        Index("ix_editorial_opportunities_disposition", "disposition"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    promotion_root_document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("normalized_documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    topic_summary: Mapped[str] = mapped_column(Text(), nullable=False)
    update_of_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    disposition: Mapped[OpportunityDisposition] = mapped_column(
        string_enum(OpportunityDisposition, "ck_editorial_opportunities_disposition", 16),
        nullable=False,
        default=OpportunityDisposition.OPEN,
    )
    disposition_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    disposition_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disposition_by: Mapped[OpportunityActor | None] = mapped_column(
        string_enum(OpportunityActor, "ck_editorial_opportunities_disposition_by", 16),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class OpportunityResearchInput(Base):
    """One referenced Phase 2 research signal attached to an opportunity."""

    __tablename__ = "opportunity_research_inputs"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_id",
            "normalized_document_id",
            name="uq_opportunity_research_inputs_document",
        ),
        Index("ix_opportunity_research_inputs_document", "normalized_document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    normalized_document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("normalized_documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    duplicate_decision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("duplicate_decisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[ResearchInputRole] = mapped_column(
        string_enum(ResearchInputRole, "ck_opportunity_research_inputs_role", 16),
        nullable=False,
    )
    added_by: Mapped[OpportunityActor] = mapped_column(
        string_enum(OpportunityActor, "ck_opportunity_research_inputs_added_by", 16),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
