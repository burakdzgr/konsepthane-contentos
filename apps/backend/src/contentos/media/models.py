"""Media persistence models (immutable assets + guarded satisfactions).

`media_assets` rows are IMMUTABLE and content-addressed: the sha256 of
the bytes is UNIQUE, so identical content converges on one asset by
construction. Origin is provenance-checked: an `ai_generated` asset MUST
reference its generation attempt; a `human_upload` MUST NOT. Alt text
and a licensing note are REQUIRED — accessibility and licensing honesty
are not optional metadata.

`media_need_satisfactions` bind ONE brief media need (positionally:
content_brief_id + need_index) to ONE asset, recorded by a NAMED human
with a required reason. The ACTIVE-row pattern with the two-shape
guarded supersession trigger mirrors drafts/reviews/reports; history is
audited append-only in `media_satisfaction_events`.
"""

import uuid
from datetime import UTC, datetime

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
# (acyclic: none of these import contentos.media).
from contentos.ai import models as _ai_models  # noqa: F401
from contentos.auth import models as _auth_models  # noqa: F401
from contentos.briefs import models as _brief_models  # noqa: F401
from contentos.db.base import Base
from contentos.db.types import string_enum
from contentos.media.enums import MediaOrigin, SatisfactionStatus


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint("content_sha256", name="uq_media_assets_content"),
        UniqueConstraint("generation_attempt_id", name="uq_media_assets_attempt"),
        CheckConstraint(
            "(origin = 'ai_generated') = (generation_attempt_id IS NOT NULL)",
            name="ck_media_assets_origin_attempt",
        ),
        CheckConstraint(
            "length(content_sha256) = 64 AND content_sha256 = lower(content_sha256)",
            name="ck_media_assets_sha_format",
        ),
        CheckConstraint("byte_size > 0", name="ck_media_assets_bytes_positive"),
        CheckConstraint(
            "media_type IN ('image/png', 'image/jpeg', 'image/webp')",
            name="ck_media_assets_media_type",
        ),
        CheckConstraint("width IS NULL OR width > 0", name="ck_media_assets_width_positive"),
        CheckConstraint("height IS NULL OR height > 0", name="ck_media_assets_height_positive"),
        CheckConstraint("length(trim(alt_text)) > 0", name="ck_media_assets_alt_text_nonempty"),
        CheckConstraint("length(trim(license_note)) > 0", name="ck_media_assets_license_nonempty"),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_media_assets_request_id_nonempty",
        ),
        Index("ix_media_assets_creator", "created_by_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    origin: Mapped[MediaOrigin] = mapped_column(
        string_enum(MediaOrigin, "ck_media_assets_origin", 16), nullable=False
    )
    content_sha256: Mapped[str] = mapped_column(String(length=64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    media_type: Mapped[str] = mapped_column(String(length=50), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    height: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    title: Mapped[str | None] = mapped_column(Text(), nullable=True)
    alt_text: Mapped[str] = mapped_column(Text(), nullable=False)
    license_note: Mapped[str] = mapped_column(Text(), nullable=False)
    source_attribution: Mapped[str | None] = mapped_column(Text(), nullable=True)
    generation_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("ai_generation_attempts.id", ondelete="RESTRICT"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    request_id: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class MediaNeedSatisfaction(Base):
    __tablename__ = "media_need_satisfactions"
    __table_args__ = (
        CheckConstraint("need_index >= 0", name="ck_media_satisfactions_need_index"),
        CheckConstraint("length(trim(reason)) > 0", name="ck_media_satisfactions_reason_nonempty"),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_media_satisfactions_request_id_nonempty",
        ),
        Index("ix_media_satisfactions_work_item", "work_item_id"),
        Index("ix_media_satisfactions_asset", "media_asset_id"),
        # At most one ACTIVE satisfaction per exact need.
        Index(
            "uq_media_satisfactions_active",
            "work_item_id",
            "content_brief_id",
            "need_index",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("editorial_work_items.id", ondelete="RESTRICT"), nullable=False
    )
    content_brief_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("content_briefs.id", ondelete="RESTRICT"), nullable=False
    )
    need_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[SatisfactionStatus] = mapped_column(
        string_enum(SatisfactionStatus, "ck_media_satisfactions_status", 16), nullable=False
    )
    superseded_by_satisfaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("media_need_satisfactions.id", ondelete="RESTRICT"), nullable=True
    )
    satisfied_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    # Microsecond ORM-side timestamp so (created_at, id) ordering stays
    # deterministic where the DB default truncates to whole seconds.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )


class MediaSatisfactionEvent(Base):
    """Append-only audit of satisfaction status changes (supersession).
    Media decisions are human-only in this phase: the actor is always a
    named user, never SYSTEM."""

    __tablename__ = "media_satisfaction_events"
    __table_args__ = (
        CheckConstraint(
            "length(trim(reason)) > 0", name="ck_media_satisfaction_events_reason_nonempty"
        ),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_media_satisfaction_events_request_id_nonempty",
        ),
        Index("ix_media_satisfaction_events_satisfaction", "satisfaction_id", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    satisfaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("media_need_satisfactions.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[SatisfactionStatus] = mapped_column(
        string_enum(SatisfactionStatus, "ck_media_satisfaction_events_from", 16), nullable=False
    )
    to_status: Mapped[SatisfactionStatus] = mapped_column(
        string_enum(SatisfactionStatus, "ck_media_satisfaction_events_to", 16), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    replacement_satisfaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("media_need_satisfactions.id", ondelete="RESTRICT"), nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
