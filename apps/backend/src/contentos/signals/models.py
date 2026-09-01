"""Search-signal persistence model (append-only observation history)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.db.base import Base
from contentos.db.types import JSON_DICT, string_enum
from contentos.signals.enums import SearchSignalType


class SearchSignal(Base):
    """One provider-neutral search observation.

    Deliberately has no Opportunity FK: a signal may be referenced by many
    future consumers, which pin exact signal IDs in their own input
    snapshots. There is no "current truth" row — observations coexist.
    """

    __tablename__ = "search_signals"
    __table_args__ = (
        CheckConstraint(
            "length(trim(subject)) > 0",
            name="ck_search_signals_subject_nonempty",
        ),
        CheckConstraint(
            "length(trim(locale)) > 0",
            name="ck_search_signals_locale_nonempty",
        ),
        CheckConstraint(
            "length(trim(market)) = 2",
            name="ck_search_signals_market_length",
        ),
        CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_search_signals_provider_nonempty",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_search_signals_confidence_range",
        ),
        CheckConstraint(
            "length(observation_hash) = 64 AND observation_hash = lower(observation_hash)",
            name="ck_search_signals_hash_format",
        ),
        # Exact-observation idempotency identity (persistence concern only).
        Index(
            "uq_search_signals_observation_hash",
            "observation_hash",
            unique=True,
        ),
        Index(
            "ix_search_signals_subject",
            "subject",
            "locale",
            "market",
            "observed_at",
        ),
        Index("ix_search_signals_type", "signal_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    signal_type: Mapped[SearchSignalType] = mapped_column(
        string_enum(SearchSignalType, "ck_search_signals_signal_type", 24),
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    market: Mapped[str] = mapped_column(String(2), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float(), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
