"""Editorial opportunity persistence models (references, never content)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
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
from contentos.db.types import JSON_DICT, JSON_LIST, string_enum
from contentos.opportunities.enums import (
    ComponentAvailability,
    OpportunityActor,
    OpportunityDisposition,
    ResearchInputRole,
    ScoreBand,
    ScoreComponent,
    ScoreEligibility,
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


class OpportunityScore(Base):
    """Append-only, explainable evaluation of one opportunity by one engine run."""

    __tablename__ = "opportunity_scores"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_id",
            "engine_name",
            "engine_version",
            "input_snapshot_hash",
            name="uq_opportunity_scores_identity",
        ),
        CheckConstraint(
            "length(trim(engine_name)) > 0",
            name="ck_opportunity_scores_engine_name_nonempty",
        ),
        CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_opportunity_scores_engine_version_nonempty",
        ),
        CheckConstraint(
            "length(input_snapshot_hash) = 64 AND input_snapshot_hash = lower(input_snapshot_hash)",
            name="ck_opportunity_scores_hash_format",
        ),
        CheckConstraint(
            "overall_value IS NULL OR (overall_value >= 0 AND overall_value <= 1)",
            name="ck_opportunity_scores_value_range",
        ),
        Index("ix_opportunity_scores_opportunity", "opportunity_id", "evaluated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    engine_name: Mapped[str] = mapped_column(String(100), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(100), nullable=False)
    overall_band: Mapped[ScoreBand] = mapped_column(
        string_enum(ScoreBand, "ck_opportunity_scores_overall_band", 16),
        nullable=False,
    )
    # Normalized 0..1 contribution scale, frozen for engine v1; the band is
    # the primary contract and the numeric value is never claimed precise.
    overall_value: Mapped[float | None] = mapped_column(Float(), nullable=True)
    eligibility: Mapped[ScoreEligibility] = mapped_column(
        string_enum(ScoreEligibility, "ck_opportunity_scores_eligibility", 24),
        nullable=False,
    )
    weights_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    threshold_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    missing_signals: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False, default=list)
    risk_flags: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False, default=list)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OpportunityScoreComponent(Base):
    """One relational, queryable component evaluation of one score."""

    __tablename__ = "opportunity_score_components"
    __table_args__ = (
        UniqueConstraint(
            "score_id",
            "component",
            name="uq_opportunity_score_components_component",
        ),
        # UNKNOWN != ZERO, enforced by the database itself.
        CheckConstraint(
            "(availability = 'known' AND value IS NOT NULL) OR "
            "(availability != 'known' AND value IS NULL)",
            name="ck_opportunity_score_components_value_presence",
        ),
        CheckConstraint(
            "value IS NULL OR (value >= 0 AND value <= 1)",
            name="ck_opportunity_score_components_value_range",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_opportunity_score_components_confidence_range",
        ),
        Index("ix_opportunity_score_components_score", "score_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    score_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("opportunity_scores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    component: Mapped[ScoreComponent] = mapped_column(
        string_enum(ScoreComponent, "ck_opportunity_score_components_component", 32),
        nullable=False,
    )
    availability: Mapped[ComponentAvailability] = mapped_column(
        string_enum(ComponentAvailability, "ck_opportunity_score_components_availability", 16),
        nullable=False,
    )
    value: Mapped[float | None] = mapped_column(Float(), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float(), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provenance_ref: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
