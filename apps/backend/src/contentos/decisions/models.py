"""Human decision persistence (append-only decision EVENTS).

Decisions are events, not stateful artifacts: no status, no supersession,
no edits — a changed mind is a NEW decision after the workflow loops
back. Every row pins the exact package (QA report, draft, editor review,
and the draft's content hash at decision time) and the named reviewer.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

# Registered so every FK target resolves wherever these models are used
# (acyclic: none of these import contentos.decisions).
from contentos.auth import models as _auth_models  # noqa: F401
from contentos.db.base import Base
from contentos.db.types import string_enum
from contentos.decisions.enums import DecisionKind
from contentos.qa import models as _qa_models  # noqa: F401
from contentos.reviews import models as _review_models  # noqa: F401


class HumanDecision(Base):
    __tablename__ = "human_decisions"
    __table_args__ = (
        CheckConstraint("length(trim(reason)) > 0", name="ck_human_decisions_reason_nonempty"),
        CheckConstraint(
            "length(content_hash) = 64 AND content_hash = lower(content_hash)",
            name="ck_human_decisions_hash_format",
        ),
        CheckConstraint(
            "(decision = 'approval_revoked') = (revokes_decision_id IS NOT NULL)",
            name="ck_human_decisions_revocation_reference",
        ),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_human_decisions_request_id_nonempty",
        ),
        Index("ix_human_decisions_work_item", "work_item_id", "created_at"),
        Index("ix_human_decisions_reviewer", "reviewer_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[DecisionKind] = mapped_column(
        string_enum(DecisionKind, "ck_human_decisions_decision", 24), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    qa_report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("qa_reports.id", ondelete="RESTRICT"), nullable=False
    )
    content_draft_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("content_drafts.id", ondelete="RESTRICT"), nullable=False
    )
    editorial_review_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("editorial_reviews.id", ondelete="RESTRICT"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(length=64), nullable=False)
    revokes_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("human_decisions.id", ondelete="RESTRICT"), nullable=True
    )
    request_id: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    # ORM inserts stamp a microsecond-precision timestamp so the decision
    # ordering (created_at, id) is deterministic even where the database
    # default (kept for raw inserts) truncates to whole seconds.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
