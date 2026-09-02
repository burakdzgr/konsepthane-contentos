"""QA persistence models (immutable versioned reports + audited waivers).

One IMMUTABLE QA report per row, pinned to the EXACT package it
evaluated (draft, editorial review, brief): after creation every content
field is frozen; ONLY `status` may move forward (`active` ->
`superseded`, with `superseded_by_report_id` set once alongside it) — a
DB trigger enforces it. DELETE is forbidden.

Waivers are work-item-scoped append-only human decisions (audited, with
required reasons) consumed by gate runs; they are never edited and never
hidden. No AI attempts exist in QA — v1 is fully deterministic.
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
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

# Registered so every FK target resolves wherever these models are used
# (acyclic: none of these import contentos.qa).
from contentos.db.base import Base
from contentos.db.types import JSON_DICT, string_enum
from contentos.drafts import models as _draft_models  # noqa: F401
from contentos.qa.enums import QaActorOrigin, QaOutcome, QaReportStatus, WaivableGateKey
from contentos.reviews import models as _review_models  # noqa: F401


class QaReport(Base):
    __tablename__ = "qa_reports"
    __table_args__ = (
        UniqueConstraint("work_item_id", "version", name="uq_qa_reports_version"),
        CheckConstraint("version > 0", name="ck_qa_reports_version_positive"),
        CheckConstraint("length(trim(engine_name)) > 0", name="ck_qa_reports_engine_name_nonempty"),
        CheckConstraint(
            "length(trim(engine_version)) > 0", name="ck_qa_reports_engine_version_nonempty"
        ),
        CheckConstraint(
            "length(content_hash) = 64 AND content_hash = lower(content_hash)",
            name="ck_qa_reports_hash_format",
        ),
        Index("ix_qa_reports_work_item", "work_item_id", "version"),
        Index("ix_qa_reports_draft", "content_draft_id"),
        # At most one ACTIVE report per work item.
        Index(
            "uq_qa_reports_active",
            "work_item_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    content_draft_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("content_drafts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    editorial_review_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_reviews.id", ondelete="RESTRICT"),
        nullable=False,
    )
    content_brief_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("content_briefs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    outcome: Mapped[QaOutcome] = mapped_column(
        string_enum(QaOutcome, "ck_qa_reports_outcome", 32), nullable=False
    )
    gate_results: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    gate_policy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    engine_name: Mapped[str] = mapped_column(String(length=100), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(length=50), nullable=False)
    status: Mapped[QaReportStatus] = mapped_column(
        string_enum(QaReportStatus, "ck_qa_reports_status", 16), nullable=False
    )
    superseded_by_report_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("qa_reports.id", ondelete="RESTRICT"), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(length=64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QaGateWaiver(Base):
    """One audited human waiver of one waivable gate (append-only).

    Work-item-scoped: it survives report supersession and is consumed by
    every subsequent gate run; it stays permanently visible."""

    __tablename__ = "qa_gate_waivers"
    __table_args__ = (
        CheckConstraint("length(trim(reason)) > 0", name="ck_qa_gate_waivers_reason_nonempty"),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_qa_gate_waivers_request_id_nonempty",
        ),
        Index("ix_qa_gate_waivers_work_item", "work_item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    gate_key: Mapped[WaivableGateKey] = mapped_column(
        string_enum(WaivableGateKey, "ck_qa_gate_waivers_key", 24), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QaReportStatusEvent(Base):
    """Append-only audit of QA report status changes (supersession)."""

    __tablename__ = "qa_report_status_events"
    __table_args__ = (
        CheckConstraint(
            "length(trim(reason)) > 0", name="ck_qa_report_status_events_reason_nonempty"
        ),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_qa_report_status_events_request_id_nonempty",
        ),
        Index("ix_qa_report_status_events_report", "report_id", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("qa_reports.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[QaReportStatus] = mapped_column(
        string_enum(QaReportStatus, "ck_qa_report_status_events_from", 16), nullable=False
    )
    to_status: Mapped[QaReportStatus] = mapped_column(
        string_enum(QaReportStatus, "ck_qa_report_status_events_to", 16), nullable=False
    )
    actor_origin: Mapped[QaActorOrigin] = mapped_column(
        string_enum(QaActorOrigin, "ck_qa_report_status_events_actor", 16), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    replacement_report_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("qa_reports.id", ondelete="RESTRICT"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
