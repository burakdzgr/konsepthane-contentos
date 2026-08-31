"""Immutable persistence model for one governed fetch attempt."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.db.base import Base
from contentos.db.types import JSON_DICT, JSON_LIST, string_enum
from contentos.fetching.models import FetchOutcome, RetryClassification, RobotsDecision


class FetchSnapshot(Base):
    """Append-only metadata for an exact FetchResult and external raw payload."""

    __tablename__ = "fetch_snapshots"
    __table_args__ = (
        CheckConstraint("duration_ms >= 0", name="ck_fetch_snapshots_duration_nonnegative"),
        CheckConstraint(
            "body_size_bytes IS NULL OR body_size_bytes >= 0",
            name="ck_fetch_snapshots_body_size_nonnegative",
        ),
        Index(
            "ix_fetch_snapshots_discovery_fetched_at",
            "discovery_item_id",
            "fetched_at",
        ),
        Index("ix_fetch_snapshots_fetch_outcome", "fetch_outcome"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    discovery_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("discovery_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    requested_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    final_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    body_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    body_size_bytes: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    raw_payload_ref: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    selected_headers: Mapped[dict[str, str]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    duration_ms: Mapped[float] = mapped_column(Float(), nullable=False)
    redirect_chain: Mapped[list[str]] = mapped_column(JSON_LIST, nullable=False, default=list)
    fetch_outcome: Mapped[FetchOutcome] = mapped_column(
        string_enum(FetchOutcome, "ck_fetch_snapshots_fetch_outcome", 32),
        nullable=False,
    )
    retry_classification: Mapped[RetryClassification] = mapped_column(
        string_enum(
            RetryClassification,
            "ck_fetch_snapshots_retry_classification",
            16,
        ),
        nullable=False,
    )
    failure_detail: Mapped[str | None] = mapped_column(Text(), nullable=True)
    robots_decision: Mapped[RobotsDecision] = mapped_column(
        string_enum(RobotsDecision, "ck_fetch_snapshots_robots_decision", 16),
        nullable=False,
    )
    retry_after_seconds: Mapped[float | None] = mapped_column(Float(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
