"""SearchIntentAnalysis persistence model (immutable versions)."""

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

# Registered so every FK target resolves wherever this model is used
# (acyclic: none of these import search_intent).
from contentos.ai import models as _ai_models  # noqa: F401
from contentos.db.base import Base
from contentos.db.types import JSON_DICT, JSON_LIST, string_enum
from contentos.ideas import models as _idea_models  # noqa: F401
from contentos.search_intent.enums import CannibalizationStatus


class SearchIntentAnalysis(Base):
    """One IMMUTABLE first-class analysis version (design §8, option A).

    `idea_id` pins the EXACT selected idea version analyzed at analysis
    time — a later selection change never repoints an existing analysis.
    `known_signal_refs` freezes the exact SearchSignal observations
    consumed (observations, never truth); `missing_signals` is durable
    data, not a log — UNKNOWN is never coerced to zero. Deliberately no
    evidence-pack FK: the READY-pack gate belongs to orchestration
    (design §18), not to this artifact's contract.

    `input_snapshot` + `input_snapshot_hash` are the DB-backed semantic
    identity (canonical JSON SHA-256): same semantic inputs return the
    existing version; any change appends a new one.
    """

    __tablename__ = "search_intent_analyses"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "version", name="uq_search_intent_analyses_version"),
        UniqueConstraint(
            "opportunity_id",
            "engine_name",
            "engine_version",
            "input_snapshot_hash",
            name="uq_search_intent_analyses_identity",
        ),
        CheckConstraint("version > 0", name="ck_search_intent_analyses_version_positive"),
        CheckConstraint(
            "length(trim(primary_intent)) > 0",
            name="ck_search_intent_analyses_primary_intent_nonempty",
        ),
        CheckConstraint(
            "length(trim(target_audience)) > 0",
            name="ck_search_intent_analyses_audience_nonempty",
        ),
        CheckConstraint(
            "length(trim(page_purpose)) > 0",
            name="ck_search_intent_analyses_page_purpose_nonempty",
        ),
        CheckConstraint(
            "length(trim(likely_format)) > 0",
            name="ck_search_intent_analyses_likely_format_nonempty",
        ),
        CheckConstraint(
            "length(trim(locale)) > 0", name="ck_search_intent_analyses_locale_nonempty"
        ),
        CheckConstraint("length(trim(market)) = 2", name="ck_search_intent_analyses_market_length"),
        CheckConstraint(
            "length(trim(engine_name)) > 0",
            name="ck_search_intent_analyses_engine_name_nonempty",
        ),
        CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_search_intent_analyses_engine_version_nonempty",
        ),
        CheckConstraint(
            "length(input_snapshot_hash) = 64 AND input_snapshot_hash = lower(input_snapshot_hash)",
            name="ck_search_intent_analyses_hash_format",
        ),
        Index("ix_search_intent_analyses_opportunity", "opportunity_id", "version"),
        Index("ix_search_intent_analyses_idea", "idea_id"),
        Index("ix_search_intent_analyses_synthesis_attempt", "synthesis_attempt_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_opportunities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    idea_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("ideas.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    primary_intent: Mapped[str] = mapped_column(String(200), nullable=False)
    secondary_intents: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False, default=list)
    target_audience: Mapped[str] = mapped_column(String(500), nullable=False)
    query_concepts: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False, default=list)
    page_purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    likely_format: Mapped[str] = mapped_column(String(200), nullable=False)
    known_signal_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_LIST, nullable=False, default=list
    )
    missing_signals: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False, default=list)
    cannibalization_status: Mapped[CannibalizationStatus] = mapped_column(
        string_enum(CannibalizationStatus, "ck_search_intent_analyses_cannibalization", 24),
        nullable=False,
        default=CannibalizationStatus.NOT_CHECKED,
    )
    cannibalization_basis: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    related_references: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_LIST, nullable=False, default=list
    )
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    market: Mapped[str] = mapped_column(String(2), nullable=False)
    engine_name: Mapped[str] = mapped_column(String(100), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(50), nullable=False)
    synthesis_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(),
        ForeignKey("ai_generation_attempts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    input_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
