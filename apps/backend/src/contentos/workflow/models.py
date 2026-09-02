"""Durable editorial workflow persistence models."""

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
)
from sqlalchemy.orm import Mapped, mapped_column

# Registered so the users FK target resolves wherever these models are used
# (acyclic: contentos.auth.models imports only the db base).
from contentos.auth import models as _auth_models  # noqa: F401
from contentos.core.context import REQUEST_ID_MAX_LENGTH
from contentos.db.base import Base
from contentos.db.types import JSON_DICT, string_enum
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState, WorkItemOrigin


class EditorialWorkItem(Base):
    """The durable editorial identity across all phases.

    Deliberately a spine, not a body: no Phase 2 lifecycle fields, no
    document/evidence/idea/brief content, no scores, and no queue state ever
    live here. `current_state` is a denormalized projection maintained only
    by WorkflowService together with a matching append-only event.
    """

    __tablename__ = "editorial_work_items"
    __table_args__ = (
        CheckConstraint(
            "length(trim(locale)) > 0",
            name="ck_editorial_work_items_locale_nonempty",
        ),
        CheckConstraint(
            "length(trim(market)) = 2",
            name="ck_editorial_work_items_market_length",
        ),
        CheckConstraint(
            "length(trim(title_working_label)) > 0",
            name="ck_editorial_work_items_label_nonempty",
        ),
        CheckConstraint(
            "current_state != 'blocked' OR "
            "(blocked_reason IS NOT NULL AND length(trim(blocked_reason)) > 0)",
            name="ck_editorial_work_items_blocked_reason",
        ),
        CheckConstraint(
            "current_state != 'rejected' OR "
            "(rejected_reason IS NOT NULL AND length(trim(rejected_reason)) > 0)",
            name="ck_editorial_work_items_rejected_reason",
        ),
        Index("ix_editorial_work_items_current_state", "current_state"),
        Index("ix_editorial_work_items_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    market: Mapped[str] = mapped_column(String(2), nullable=False)
    origin: Mapped[WorkItemOrigin] = mapped_column(
        string_enum(WorkItemOrigin, "ck_editorial_work_items_origin", 16),
        nullable=False,
    )
    current_state: Mapped[WorkflowState] = mapped_column(
        string_enum(WorkflowState, "ck_editorial_work_items_current_state", 24),
        nullable=False,
    )
    current_state_entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    title_working_label: Mapped[str] = mapped_column(String(200), nullable=False)
    blocked_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class EditorialWorkflowEvent(Base):
    """Append-only record of one workflow transition (or creation).

    `artifact_refs` is an immutable historical snapshot of caller-provided
    identifiers; this module never interprets them as foreign keys.
    """

    __tablename__ = "editorial_workflow_events"
    __table_args__ = (
        CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_editorial_workflow_events_reason_nonempty",
        ),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_editorial_workflow_events_request_id_nonempty",
        ),
        Index("ix_editorial_workflow_events_work_item", "work_item_id", "id"),
    )

    # Monotonic identity so append order is the audit order, independent of
    # timestamp precision (the SourceLifecycleEvent pattern).
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_state: Mapped[WorkflowState | None] = mapped_column(
        string_enum(WorkflowState, "ck_editorial_workflow_events_from_state", 24),
        nullable=True,
    )
    to_state: Mapped[WorkflowState] = mapped_column(
        string_enum(WorkflowState, "ck_editorial_workflow_events_to_state", 24),
        nullable=False,
    )
    actor_origin: Mapped[WorkflowActorOrigin] = mapped_column(
        string_enum(WorkflowActorOrigin, "ck_editorial_workflow_events_actor_origin", 16),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    artifact_refs: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(REQUEST_ID_MAX_LENGTH), nullable=True)
    # Phase 5 G3: the authenticated human behind an OPERATOR-actor
    # transition. Nullable — historical rows and service-internal
    # transitions honestly stay UNKNOWN.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
