"""Durable, idempotent intelligence-signal persistence model."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.db.base import Base
from contentos.db.types import JSON_DICT, string_enum
from contentos.intelligence.enums import SignalFamily

MAX_SUBJECT_LENGTH = 300
MAX_CONCEPT_KEY_LENGTH = 240
MAX_PROVIDER_LENGTH = 100
MAX_VALUE_KEYS = 40
MAX_VALUE_TEXT_LENGTH = 300


class IntelligenceSignal(Base):
    """One PII-free, bounded signal observed from a source document.

    Identity is ``observation_hash`` = sha256 of
    ``family|concept_key|provider|source_id|normalized_document_id`` so that
    re-extraction updates ``occurrence_count`` / ``last_observed_at`` instead
    of duplicating rows. ``value`` never carries raw source text longer than
    ``MAX_VALUE_TEXT_LENGTH`` characters.
    """

    __tablename__ = "intelligence_signals"
    __table_args__ = (
        UniqueConstraint("observation_hash", name="uq_intelligence_signals_observation_hash"),
        CheckConstraint(
            "length(trim(subject)) > 0", name="ck_intelligence_signals_subject_nonempty"
        ),
        CheckConstraint(
            "length(trim(concept_key)) > 0", name="ck_intelligence_signals_concept_nonempty"
        ),
        CheckConstraint(
            "length(trim(provider)) > 0", name="ck_intelligence_signals_provider_nonempty"
        ),
        CheckConstraint("occurrence_count >= 1", name="ck_intelligence_signals_occurrence_min"),
        CheckConstraint(
            "length(observation_hash) = 64 AND observation_hash = lower(observation_hash)",
            name="ck_intelligence_signals_hash_format",
        ),
        Index("ix_intelligence_signals_family_concept", "family", "concept_key"),
        Index("ix_intelligence_signals_opportunity", "opportunity_id"),
        Index("ix_intelligence_signals_source_family", "source_id", "family"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    family: Mapped[SignalFamily] = mapped_column(
        string_enum(SignalFamily, "ck_intelligence_signals_family", 32), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(MAX_SUBJECT_LENGTH), nullable=False)
    concept_key: Mapped[str] = mapped_column(String(MAX_CONCEPT_KEY_LENGTH), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False, default="tr-TR")
    market: Mapped[str] = mapped_column(String(2), nullable=False, default="TR")
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("sources.id", ondelete="RESTRICT"), nullable=True
    )
    normalized_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("normalized_documents.id", ondelete="RESTRICT"), nullable=True
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(MAX_PROVIDER_LENGTH), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    occurrence_count: Mapped[int] = mapped_column(Integer(), nullable=False, default=1)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
