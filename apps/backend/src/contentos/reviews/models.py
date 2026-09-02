"""EditorialReview persistence models (immutable versioned review artifacts).

One IMMUTABLE review per row, pinned to the EXACT ContentDraft version it
reviewed: after creation every content field is frozen; ONLY `status` may
move forward (`active` -> `superseded`, with `superseded_by_review_id` set
once alongside it) through the guarded service surface — a DB trigger
enforces it. DELETE is forbidden.

Findings are relational and append-only: policy signals anchored to draft
block ids and brief claim ids. They are NEVER Evidence and never enter the
ADR 0007 provenance chain as facts.
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
# (acyclic: none of these import contentos.reviews).
from contentos.ai import models as _ai_models  # noqa: F401
from contentos.briefs import models as _brief_models  # noqa: F401
from contentos.db.base import Base
from contentos.db.types import JSON_DICT, string_enum
from contentos.drafts import models as _draft_models  # noqa: F401
from contentos.reviews.enums import (
    FindingDimension,
    FindingOrigin,
    FindingSeverity,
    ReviewActorOrigin,
    ReviewStatus,
    ReviewVerdict,
)


class EditorialReview(Base):
    __tablename__ = "editorial_reviews"
    __table_args__ = (
        UniqueConstraint("work_item_id", "version", name="uq_editorial_reviews_version"),
        UniqueConstraint("generation_attempt_id", name="uq_editorial_reviews_attempt"),
        CheckConstraint("version > 0", name="ck_editorial_reviews_version_positive"),
        CheckConstraint(
            "length(trim(engine_name)) > 0", name="ck_editorial_reviews_engine_name_nonempty"
        ),
        CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_editorial_reviews_engine_version_nonempty",
        ),
        CheckConstraint(
            "length(content_hash) = 64 AND content_hash = lower(content_hash)",
            name="ck_editorial_reviews_hash_format",
        ),
        Index("ix_editorial_reviews_work_item", "work_item_id", "version"),
        Index("ix_editorial_reviews_draft", "content_draft_id"),
        # At most one ACTIVE review per work item.
        Index(
            "uq_editorial_reviews_active",
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
    content_brief_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("content_briefs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    verdict: Mapped[ReviewVerdict] = mapped_column(
        string_enum(ReviewVerdict, "ck_editorial_reviews_verdict", 16), nullable=False
    )
    generation_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(),
        ForeignKey("ai_generation_attempts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    engine_name: Mapped[str] = mapped_column(String(length=100), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(length=50), nullable=False)
    integrity_gate_result: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    verdict_policy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    review_scope: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    status: Mapped[ReviewStatus] = mapped_column(
        string_enum(ReviewStatus, "ck_editorial_reviews_status", 16), nullable=False
    )
    superseded_by_review_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("editorial_reviews.id", ondelete="RESTRICT"), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(length=64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EditorialReviewFinding(Base):
    """One typed finding of one review (append-only policy signal)."""

    __tablename__ = "editorial_review_findings"
    __table_args__ = (
        UniqueConstraint("review_id", "finding_key", name="uq_editorial_review_findings_key"),
        CheckConstraint(
            "length(trim(finding_key)) > 0", name="ck_editorial_review_findings_key_nonempty"
        ),
        CheckConstraint(
            "length(trim(description)) > 0",
            name="ck_editorial_review_findings_description_nonempty",
        ),
        CheckConstraint(
            "block_id IS NULL OR length(trim(block_id)) > 0",
            name="ck_editorial_review_findings_block_nonempty",
        ),
        Index("ix_editorial_review_findings_review", "review_id"),
        Index("ix_editorial_review_findings_claim", "brief_claim_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    review_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("editorial_reviews.id", ondelete="RESTRICT"), nullable=False
    )
    finding_key: Mapped[str] = mapped_column(String(length=64), nullable=False)
    dimension: Mapped[FindingDimension] = mapped_column(
        string_enum(FindingDimension, "ck_editorial_review_findings_dimension", 24),
        nullable=False,
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        string_enum(FindingSeverity, "ck_editorial_review_findings_severity", 16),
        nullable=False,
    )
    origin: Mapped[FindingOrigin] = mapped_column(
        string_enum(FindingOrigin, "ck_editorial_review_findings_origin", 16),
        nullable=False,
    )
    block_id: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    brief_claim_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("brief_claims.id", ondelete="RESTRICT"), nullable=True
    )
    description: Mapped[str] = mapped_column(Text(), nullable=False)
    recommendation: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EditorialReviewStatusEvent(Base):
    """Append-only audit of review status changes (supersession)."""

    __tablename__ = "editorial_review_status_events"
    __table_args__ = (
        CheckConstraint(
            "length(trim(reason)) > 0", name="ck_editorial_review_status_events_reason_nonempty"
        ),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_editorial_review_status_events_request_id_nonempty",
        ),
        Index("ix_editorial_review_status_events_review", "review_id", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    review_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("editorial_reviews.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[ReviewStatus] = mapped_column(
        string_enum(ReviewStatus, "ck_editorial_review_status_events_from", 16), nullable=False
    )
    to_status: Mapped[ReviewStatus] = mapped_column(
        string_enum(ReviewStatus, "ck_editorial_review_status_events_to", 16), nullable=False
    )
    actor_origin: Mapped[ReviewActorOrigin] = mapped_column(
        string_enum(ReviewActorOrigin, "ck_editorial_review_status_events_actor", 16),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    replacement_review_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("editorial_reviews.id", ondelete="RESTRICT"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
