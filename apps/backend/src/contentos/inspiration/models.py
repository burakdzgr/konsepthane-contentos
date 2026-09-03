"""Append-only inspiration signals and evaluations with source provenance."""

import uuid
from datetime import datetime
from typing import Any

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
from contentos.db.types import JSON_DICT, JSON_LIST, string_enum
from contentos.inspiration.enums import (
    InspirationBand,
    OpportunityRecommendation,
    SearchOpportunityBand,
    SignalExtractionMethod,
    TrendState,
)


class InspirationSignal(Base):
    __tablename__ = "inspiration_signals"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_id",
            "normalized_document_id",
            "extractor_name",
            "extractor_version",
            "signal_key",
            name="uq_inspiration_signals_identity",
        ),
        CheckConstraint(
            "length(signal_key) = 64 AND signal_key = lower(signal_key)",
            name="ck_inspiration_signals_key_format",
        ),
        CheckConstraint("length(trim(title)) > 0", name="ck_inspiration_signals_title_nonempty"),
        Index("ix_inspiration_signals_opportunity", "opportunity_id", "created_at"),
        Index("ix_inspiration_signals_concept", "concept_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"), nullable=False
    )
    normalized_document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("normalized_documents.id", ondelete="RESTRICT"), nullable=False
    )
    signal_key: Mapped[str] = mapped_column(String(64), nullable=False)
    concept_key: Mapped[str] = mapped_column(String(240), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text(), nullable=True)
    extraction_method: Mapped[SignalExtractionMethod] = mapped_column(
        string_enum(SignalExtractionMethod, "ck_inspiration_signals_method", 20), nullable=False
    )
    extractor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(100), nullable=False)
    source_locator: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InspirationEvaluation(Base):
    __tablename__ = "inspiration_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_id",
            "engine_name",
            "engine_version",
            "input_snapshot_hash",
            name="uq_inspiration_evaluations_identity",
        ),
        CheckConstraint(
            "length(input_snapshot_hash) = 64 AND input_snapshot_hash = lower(input_snapshot_hash)",
            name="ck_inspiration_evaluations_hash_format",
        ),
        Index("ix_inspiration_evaluations_opportunity", "opportunity_id", "evaluated_at"),
        Index("ix_inspiration_evaluations_recommendation", "recommendation"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"), nullable=False
    )
    engine_name: Mapped[str] = mapped_column(String(100), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(100), nullable=False)
    inspiration_band: Mapped[InspirationBand] = mapped_column(
        string_enum(InspirationBand, "ck_inspiration_evaluations_band", 16), nullable=False
    )
    search_opportunity: Mapped[SearchOpportunityBand] = mapped_column(
        string_enum(SearchOpportunityBand, "ck_inspiration_evaluations_search", 16), nullable=False
    )
    trend_state: Mapped[TrendState] = mapped_column(
        string_enum(TrendState, "ck_inspiration_evaluations_trend", 16), nullable=False
    )
    recommendation: Mapped[OpportunityRecommendation] = mapped_column(
        string_enum(OpportunityRecommendation, "ck_inspiration_evaluations_recommendation", 20),
        nullable=False,
    )
    rationale: Mapped[str] = mapped_column(Text(), nullable=False)
    factors: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    strategy_context: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    missing_signals: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False, default=list)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
