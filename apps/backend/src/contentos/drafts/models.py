"""ContentDraft persistence models (immutable versioned draft artifacts).

One IMMUTABLE draft content version per row: after creation every content
field is frozen; ONLY `status` may move forward (`active` -> `superseded`,
with `superseded_by_draft_id` set once alongside it) through the guarded
service surface — a DB trigger enforces it. DELETE is forbidden.

Claim provenance is relational and append-only: `draft_claim_usages`
mirrors the body's per-block claim references 1:1, so the chain
Draft -> DraftClaimUsage -> BriefClaim -> BriefClaimEvidence ->
ResearchEvidence stays resolvable forever (ADR 0007 extended, never
replaced). No evidence link is duplicated at draft level by design.

A draft is a DRAFT: never approved content, never publication (ADR 0004
untouched), never article HTML — the body is the bounded
`writer-draft-body/1` structure.
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
# (acyclic: none of these import contentos.drafts).
from contentos.ai import models as _ai_models  # noqa: F401
from contentos.briefs import models as _brief_models  # noqa: F401
from contentos.db.base import Base
from contentos.db.types import JSON_DICT, string_enum
from contentos.drafts.enums import DraftActorOrigin, DraftOrigin, DraftStatus


class ContentDraft(Base):
    __tablename__ = "content_drafts"
    __table_args__ = (
        UniqueConstraint("work_item_id", "version", name="uq_content_drafts_version"),
        UniqueConstraint("generation_attempt_id", name="uq_content_drafts_attempt"),
        CheckConstraint("version > 0", name="ck_content_drafts_version_positive"),
        CheckConstraint(
            "(origin = 'operator') = (generation_attempt_id IS NULL)",
            name="ck_content_drafts_operator_attempt",
        ),
        CheckConstraint(
            "(origin = 'operator') = (manual_input_hash IS NOT NULL)",
            name="ck_content_drafts_manual_hash_origin",
        ),
        CheckConstraint("length(trim(locale)) > 0", name="ck_content_drafts_locale_nonempty"),
        CheckConstraint("length(trim(market)) = 2", name="ck_content_drafts_market_length"),
        CheckConstraint(
            "length(trim(engine_name)) > 0", name="ck_content_drafts_engine_name_nonempty"
        ),
        CheckConstraint(
            "length(trim(engine_version)) > 0",
            name="ck_content_drafts_engine_version_nonempty",
        ),
        CheckConstraint(
            "length(content_hash) = 64 AND content_hash = lower(content_hash)",
            name="ck_content_drafts_hash_format",
        ),
        CheckConstraint(
            "manual_input_hash IS NULL OR "
            "(length(manual_input_hash) = 64 AND manual_input_hash = lower(manual_input_hash))",
            name="ck_content_drafts_manual_hash_format",
        ),
        Index("ix_content_drafts_work_item", "work_item_id", "version"),
        Index("ix_content_drafts_brief", "content_brief_id"),
        # At most one ACTIVE draft per work item.
        Index(
            "uq_content_drafts_active",
            "work_item_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        # Manual-path idempotency: the same exact operator submission for the
        # same work item converges on the same durable draft.
        Index(
            "uq_content_drafts_manual_identity",
            "work_item_id",
            "manual_input_hash",
            unique=True,
            postgresql_where=text("origin = 'operator'"),
            sqlite_where=text("origin = 'operator'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("editorial_work_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    content_brief_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("content_briefs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    locale: Mapped[str] = mapped_column(String(length=20), nullable=False)
    market: Mapped[str] = mapped_column(String(length=2), nullable=False)
    origin: Mapped[DraftOrigin] = mapped_column(
        string_enum(DraftOrigin, "ck_content_drafts_origin", 16), nullable=False
    )
    generation_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(),
        ForeignKey("ai_generation_attempts.id", ondelete="RESTRICT"),
        nullable=True,
    )
    manual_input_hash: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    engine_name: Mapped[str] = mapped_column(String(length=100), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(length=50), nullable=False)
    title_proposal: Mapped[str | None] = mapped_column(Text(), nullable=True)
    body: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False)
    body_schema_version: Mapped[str] = mapped_column(String(length=50), nullable=False)
    uncertainty_coverage: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    validation_policy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    originality_policy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    originality_result: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    status: Mapped[DraftStatus] = mapped_column(
        string_enum(DraftStatus, "ck_content_drafts_status", 16), nullable=False
    )
    superseded_by_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("content_drafts.id", ondelete="RESTRICT"), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(length=64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DraftClaimUsage(Base):
    """One block-anchored use of one EXACT brief claim (append-only)."""

    __tablename__ = "draft_claim_usages"
    __table_args__ = (
        UniqueConstraint(
            "draft_id", "brief_claim_id", "block_id", name="uq_draft_claim_usages_anchor"
        ),
        CheckConstraint(
            "length(trim(section_key)) > 0", name="ck_draft_claim_usages_section_nonempty"
        ),
        CheckConstraint("length(trim(block_id)) > 0", name="ck_draft_claim_usages_block_nonempty"),
        Index("ix_draft_claim_usages_draft", "draft_id"),
        Index("ix_draft_claim_usages_claim", "brief_claim_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("content_drafts.id", ondelete="RESTRICT"), nullable=False
    )
    brief_claim_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("brief_claims.id", ondelete="RESTRICT"), nullable=False
    )
    section_key: Mapped[str] = mapped_column(String(length=50), nullable=False)
    block_id: Mapped[str] = mapped_column(String(length=64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DraftStatusEvent(Base):
    """Append-only audit of draft status changes (supersession)."""

    __tablename__ = "draft_status_events"
    __table_args__ = (
        CheckConstraint("length(trim(reason)) > 0", name="ck_draft_status_events_reason_nonempty"),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_draft_status_events_request_id_nonempty",
        ),
        Index("ix_draft_status_events_draft", "draft_id", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("content_drafts.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[DraftStatus] = mapped_column(
        string_enum(DraftStatus, "ck_draft_status_events_from", 16), nullable=False
    )
    to_status: Mapped[DraftStatus] = mapped_column(
        string_enum(DraftStatus, "ck_draft_status_events_to", 16), nullable=False
    )
    actor_origin: Mapped[DraftActorOrigin] = mapped_column(
        string_enum(DraftActorOrigin, "ck_draft_status_events_actor", 16), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    replacement_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("content_drafts.id", ondelete="RESTRICT"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
