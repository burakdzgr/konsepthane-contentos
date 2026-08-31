"""Immutable ResearchEvidence persistence model."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.db.base import Base
from contentos.db.types import JSON_DICT, string_enum
from contentos.research.enums import EvidenceType, ExtractionMethod, VerificationStatus
from contentos.research.validation import (
    EVIDENCE_KEY_VERSION,
    MAX_CONFIDENCE_BASIS_LENGTH,
    MAX_EXCERPT_LENGTH,
    MAX_EXTRACTOR_NAME_LENGTH,
    MAX_EXTRACTOR_VERSION_LENGTH,
    MAX_LICENSING_NOTES_LENGTH,
    MAX_SOURCE_LOCATOR_LENGTH,
    MAX_STATEMENT_LENGTH,
    RESEARCH_EVIDENCE_OFFSET_VERSION,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ResearchEvidence(Base):
    """One append-only statement with exact capture and source provenance."""

    __tablename__ = "research_evidence"
    __table_args__ = (
        UniqueConstraint(
            "normalized_document_id",
            "extractor_name",
            "extractor_version",
            "evidence_key",
            name="uq_research_evidence_document_extractor_key",
        ),
        CheckConstraint(
            "length(trim(statement)) > 0",
            name="ck_research_evidence_statement_nonempty",
        ),
        CheckConstraint(
            "length(trim(extractor_name)) > 0",
            name="ck_research_evidence_extractor_name_nonempty",
        ),
        CheckConstraint(
            "length(trim(extractor_version)) > 0",
            name="ck_research_evidence_extractor_version_nonempty",
        ),
        CheckConstraint(
            "length(trim(source_url)) > 0",
            name="ck_research_evidence_source_url_nonempty",
        ),
        CheckConstraint(
            "length(evidence_key) = 64 AND evidence_key = lower(evidence_key)",
            name="ck_research_evidence_key_format",
        ),
        CheckConstraint(
            f"evidence_key_version = {EVIDENCE_KEY_VERSION}",
            name="ck_research_evidence_key_version",
        ),
        CheckConstraint(
            "(excerpt IS NULL AND excerpt_start IS NULL AND excerpt_end IS NULL "
            "AND offset_version IS NULL AND source_locator IS NOT NULL) OR "
            f"(excerpt IS NOT NULL AND length(excerpt) > 0 "
            f"AND length(excerpt) <= {MAX_EXCERPT_LENGTH} "
            "AND excerpt_start IS NOT NULL AND excerpt_start >= 0 "
            "AND excerpt_end IS NOT NULL AND excerpt_end > excerpt_start "
            f"AND offset_version = {RESEARCH_EVIDENCE_OFFSET_VERSION})",
            name="ck_research_evidence_excerpt_consistency",
        ),
        CheckConstraint(
            "verification_status != 'verified' OR excerpt IS NOT NULL",
            name="ck_research_evidence_verified_has_excerpt",
        ),
        CheckConstraint(
            "evidence_type != 'quote' OR excerpt IS NOT NULL",
            name="ck_research_evidence_quote_has_excerpt",
        ),
        CheckConstraint(
            "source_locator IS NULL OR length(trim(source_locator)) > 0",
            name="ck_research_evidence_source_locator_nonempty",
        ),
        CheckConstraint(
            "(confidence IS NULL AND confidence_basis IS NULL) OR "
            "(confidence IS NOT NULL AND confidence >= 0 AND confidence <= 1 "
            "AND confidence_basis IS NOT NULL AND length(trim(confidence_basis)) > 0)",
            name="ck_research_evidence_confidence_consistency",
        ),
        Index("ix_research_evidence_verification_status", "verification_status"),
        Index("ix_research_evidence_evidence_type", "evidence_type"),
        Index("ix_research_evidence_source_id", "source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    normalized_document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(),
        ForeignKey("normalized_documents.id", ondelete="RESTRICT"),
        nullable=False,
    )
    fetch_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("fetch_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    source_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_type: Mapped[EvidenceType] = mapped_column(
        string_enum(EvidenceType, "ck_research_evidence_evidence_type", 24),
        nullable=False,
    )
    statement: Mapped[str] = mapped_column(String(MAX_STATEMENT_LENGTH), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(String(MAX_EXCERPT_LENGTH), nullable=True)
    excerpt_start: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    excerpt_end: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    offset_version: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    source_locator: Mapped[str | None] = mapped_column(
        String(MAX_SOURCE_LOCATOR_LENGTH), nullable=True
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        string_enum(VerificationStatus, "ck_research_evidence_verification_status", 16),
        nullable=False,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    confidence_basis: Mapped[str | None] = mapped_column(
        String(MAX_CONFIDENCE_BASIS_LENGTH), nullable=True
    )
    extractor_name: Mapped[str] = mapped_column(String(MAX_EXTRACTOR_NAME_LENGTH), nullable=False)
    extractor_version: Mapped[str] = mapped_column(
        String(MAX_EXTRACTOR_VERSION_LENGTH), nullable=False
    )
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        string_enum(ExtractionMethod, "ck_research_evidence_extraction_method", 16),
        nullable=False,
    )
    licensing_notes: Mapped[str | None] = mapped_column(
        String(MAX_LICENSING_NOTES_LENGTH), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DICT, nullable=False, default=dict
    )
    evidence_key: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_key_version: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=EVIDENCE_KEY_VERSION
    )
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
