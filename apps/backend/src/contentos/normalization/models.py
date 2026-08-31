"""Immutable NormalizedDocument persistence model."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
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
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.db.base import Base
from contentos.db.types import JSON_DICT, JSON_LIST, string_enum
from contentos.normalization.enums import NormalizationFailureCode, NormalizationStatus


def _utc_now() -> datetime:
    return datetime.now(UTC)


class NormalizedDocument(Base):
    """Append-only output of one extractor version over one FetchSnapshot."""

    __tablename__ = "normalized_documents"
    __table_args__ = (
        UniqueConstraint(
            "fetch_snapshot_id",
            "extractor_name",
            "extractor_version",
            name="uq_normalized_documents_snapshot_extractor",
        ),
        CheckConstraint(
            "(normalization_status = 'succeeded' "
            "AND clean_text IS NOT NULL AND length(trim(clean_text)) > 0 "
            "AND failure_code IS NULL AND failure_detail IS NULL "
            "AND content_fingerprint IS NOT NULL AND fingerprint_version IS NOT NULL) "
            "OR (normalization_status = 'failed' "
            "AND failure_code IS NOT NULL "
            "AND title IS NULL AND clean_text IS NULL AND language IS NULL "
            "AND author_name IS NULL AND external_published_at IS NULL "
            "AND content_fingerprint IS NULL AND fingerprint_version IS NULL)",
            name="ck_normalized_documents_status_consistency",
        ),
        CheckConstraint(
            "content_fingerprint IS NULL OR "
            "(length(content_fingerprint) = 64 "
            "AND content_fingerprint = lower(content_fingerprint))",
            name="ck_normalized_documents_fingerprint_format",
        ),
        CheckConstraint(
            "fingerprint_version IS NULL OR fingerprint_version > 0",
            name="ck_normalized_documents_fingerprint_version_positive",
        ),
        Index("ix_normalized_documents_status", "normalization_status"),
        Index("ix_normalized_documents_content_fingerprint", "content_fingerprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    fetch_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("fetch_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    extractor_name: Mapped[str] = mapped_column(String(100), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    normalization_status: Mapped[NormalizationStatus] = mapped_column(
        string_enum(
            NormalizationStatus,
            "ck_normalized_documents_normalization_status",
            16,
        ),
        nullable=False,
    )
    failure_code: Mapped[NormalizationFailureCode | None] = mapped_column(
        string_enum(
            NormalizationFailureCode,
            "ck_normalized_documents_failure_code",
            32,
        ),
        nullable=True,
    )
    failure_detail: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    clean_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    language: Mapped[str | None] = mapped_column(String(35), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    external_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    headings: Mapped[list[dict[str, Any]]] = mapped_column(JSON_LIST, nullable=False, default=list)
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSON_LIST, nullable=False, default=list)
    links: Mapped[list[dict[str, Any]]] = mapped_column(JSON_LIST, nullable=False, default=list)
    structured_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fingerprint_version: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    normalized_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
