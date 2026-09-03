"""Durable intake runs and their append-only operational event feed.

An `IntakeRun` is the operator-visible "what happened after I pressed
start" record: bounded policy snapshot, live counters, and status. Its
events reconstruct the run timeline after any restart, refresh, or
logout. Counters are conveniences recomputed from durable pipeline
state by the orchestrator — the pipeline rows stay authoritative.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.db.base import Base
from contentos.db.types import JSON_DICT, string_enum
from contentos.intake.enums import IntakeEventKind, IntakeRunStatus, IntakeStage

REQUEST_ID_MAX_LENGTH = 128


class IntakeRun(Base):
    __tablename__ = "intake_runs"
    __table_args__ = (
        CheckConstraint(
            "failure_note IS NULL OR length(trim(failure_note)) > 0",
            name="ck_intake_runs_failure_note_nonempty",
        ),
        # One live run per source: RUNNING/PAUSED rows are exclusive.
        Index(
            "uq_intake_runs_live_per_source",
            "source_id",
            unique=True,
            postgresql_where=text("status IN ('running', 'paused')"),
            sqlite_where=text("status IN ('running', 'paused')"),
        ),
        Index("ix_intake_runs_source", "source_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[IntakeRunStatus] = mapped_column(
        string_enum(IntakeRunStatus, "ck_intake_runs_status", 16), nullable=False
    )
    started_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    request_id: Mapped[str | None] = mapped_column(String(REQUEST_ID_MAX_LENGTH), nullable=True)
    # The bounded policy this run was started under (immutable snapshot).
    policy: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    # Live counters (recomputed from durable pipeline rows each step).
    discovered_new: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    rediscovered: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    prefilter_accepted: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    prefilter_rejected: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    fetch_dispatched: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    fetched: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    fetch_failed: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    promotions_dispatched: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    opportunities_created: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    discovery_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    prefilter_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class IntakeRunEvent(Base):
    """Append-only operational events; the run timeline's source of truth."""

    __tablename__ = "intake_run_events"
    __table_args__ = (Index("ix_intake_run_events_run", "run_id", "id"),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("intake_runs.id", ondelete="RESTRICT"), nullable=False
    )
    stage: Mapped[IntakeStage] = mapped_column(
        string_enum(IntakeStage, "ck_intake_run_events_stage", 16), nullable=False
    )
    kind: Mapped[IntakeEventKind] = mapped_column(
        string_enum(IntakeEventKind, "ck_intake_run_events_kind", 32), nullable=False
    )
    # Bounded structured facts only (counts, coded reasons, entity ids) —
    # never raw exception text, URLs beyond the pipeline's own rows, or
    # anything secret.
    detail: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
