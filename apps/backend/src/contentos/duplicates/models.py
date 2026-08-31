"""Immutable append-only DuplicateDecision persistence model."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.db.base import Base
from contentos.db.types import JSON_DICT, JSON_LIST, string_enum
from contentos.duplicates.enums import DuplicateDecisionOutcome


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DuplicateDecision(Base):
    """One immutable engine-version evaluation of one normalized document."""

    __tablename__ = "duplicate_decisions"
    __table_args__ = (
        UniqueConstraint(
            "normalized_document_id",
            "engine_name",
            "engine_version",
            name="uq_duplicate_decisions_document_engine",
        ),
        CheckConstraint(
            "length(trim(engine_name)) > 0",
            name="ck_duplicate_decisions_engine_name_nonempty",
        ),
        CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_duplicate_decisions_engine_version_nonempty",
        ),
        Index("ix_duplicate_decisions_decision", "decision"),
        Index("ix_duplicate_decisions_evaluated_at", "evaluated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    normalized_document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("normalized_documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    engine_name: Mapped[str] = mapped_column(String(100), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(100), nullable=False)
    decision: Mapped[DuplicateDecisionOutcome] = mapped_column(
        string_enum(
            DuplicateDecisionOutcome,
            "ck_duplicate_decisions_decision",
            16,
        ),
        nullable=False,
    )
    signals: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    matches: Mapped[list[dict[str, Any]]] = mapped_column(JSON_LIST, nullable=False, default=list)
    rationale_codes: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False, default=list)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
