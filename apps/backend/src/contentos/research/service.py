"""Validated caller-committed recording of immutable research evidence."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from contentos.normalization.enums import NormalizationStatus
from contentos.research.enums import EvidenceType, ExtractionMethod, VerificationStatus
from contentos.research.models import ResearchEvidence
from contentos.research.repository import (
    ResearchEvidenceRepository,
    ResearchProvenanceRepository,
)
from contentos.research.validation import (
    EVIDENCE_KEY_VERSION,
    MAX_EXTRACTOR_NAME_LENGTH,
    MAX_EXTRACTOR_VERSION_LENGTH,
    MAX_LICENSING_NOTES_LENGTH,
    MAX_STATEMENT_LENGTH,
    InvalidEvidenceInputError,
    ResearchDocumentNotEligibleError,
    ResearchDocumentNotFoundError,
    ResearchEvidenceConflictError,
    ResearchEvidencePersistenceError,
    ResearchProvenanceMissingError,
    compute_evidence_key,
    validate_bounded_text,
    validate_confidence,
    validate_excerpt,
    validate_metadata,
    validate_optional_text,
    validate_source_locator,
)
from contentos.sources.service import SourceRegistryService

DEFAULT_EXTRACTOR_NAME = "deterministic-evidence"
DEFAULT_EXTRACTOR_VERSION = "1"

_SEMANTIC_FIELDS = (
    "normalized_document_id",
    "fetch_snapshot_id",
    "source_id",
    "source_url",
    "fetched_at",
    "evidence_type",
    "statement",
    "excerpt",
    "excerpt_start",
    "excerpt_end",
    "offset_version",
    "source_locator",
    "verification_status",
    "confidence",
    "confidence_basis",
    "extractor_name",
    "extractor_version",
    "extraction_method",
    "licensing_notes",
    "metadata_json",
    "evidence_key",
    "evidence_key_version",
)


class ResearchEvidenceService:
    """Record exact excerpt-backed or safely located structured evidence."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._evidence = ResearchEvidenceRepository(session)
        self._provenance = ResearchProvenanceRepository(session)

    def record_evidence(
        self,
        normalized_document_id: uuid.UUID,
        *,
        evidence_type: EvidenceType,
        statement: str,
        extraction_method: ExtractionMethod,
        extractor_name: str = DEFAULT_EXTRACTOR_NAME,
        extractor_version: str = DEFAULT_EXTRACTOR_VERSION,
        excerpt: str | None = None,
        excerpt_start: int | None = None,
        excerpt_end: int | None = None,
        source_locator: str | None = None,
        verification_status: VerificationStatus = VerificationStatus.UNVERIFIED,
        confidence: Decimal | int | float | str | None = None,
        confidence_basis: str | None = None,
        licensing_notes: str | None = None,
        metadata: dict[str, Any] | None = None,
        extracted_at: datetime | None = None,
    ) -> ResearchEvidence:
        """Validate and flush one evidence row; the caller owns commit."""
        if not isinstance(evidence_type, EvidenceType):
            raise InvalidEvidenceInputError("evidence_type must be an approved value")
        if not isinstance(extraction_method, ExtractionMethod):
            raise InvalidEvidenceInputError("extraction_method must be an approved value")
        if not isinstance(verification_status, VerificationStatus):
            raise InvalidEvidenceInputError("verification_status must be an approved value")

        document = self._provenance.get_document(normalized_document_id)
        if document is None:
            raise ResearchDocumentNotFoundError(
                f"no normalized document with id {normalized_document_id}"
            )
        if (
            document.normalization_status is not NormalizationStatus.SUCCEEDED
            or not document.clean_text
            or not document.content_fingerprint
        ):
            raise ResearchDocumentNotEligibleError(
                "evidence requires a successful fingerprinted normalized document"
            )
        provenance = self._provenance.get_provenance(normalized_document_id)
        if provenance is None:
            raise ResearchProvenanceMissingError(
                "normalized document has no complete fetch/discovery/source provenance"
            )
        if provenance.snapshot.final_url is None:
            raise ResearchProvenanceMissingError("successful provenance has no final source URL")
        if not SourceRegistryService.evidence_allowed(provenance.source):
            # Community sources yield PII-free needs, never facts (see
            # docs/INTAKE_ORCHESTRATION.md, "Source purpose").
            raise ResearchDocumentNotEligibleError(
                "community sources never produce research evidence "
                f"(source role '{provenance.source.primary_role.value}')"
            )

        clean_statement = validate_bounded_text("statement", statement, MAX_STATEMENT_LENGTH)
        clean_extractor_name = validate_bounded_text(
            "extractor_name", extractor_name, MAX_EXTRACTOR_NAME_LENGTH
        )
        clean_extractor_version = validate_bounded_text(
            "extractor_version", extractor_version, MAX_EXTRACTOR_VERSION_LENGTH
        )
        offset_version = validate_excerpt(document.clean_text, excerpt, excerpt_start, excerpt_end)
        clean_locator = validate_source_locator(source_locator, required=excerpt is None)
        if evidence_type is EvidenceType.QUOTE and excerpt is None:
            raise InvalidEvidenceInputError("quote evidence requires an exact bounded excerpt")
        if verification_status is VerificationStatus.VERIFIED and excerpt is None:
            raise InvalidEvidenceInputError(
                "verified means exact excerpt grounding and requires an excerpt"
            )
        clean_confidence, clean_confidence_basis = validate_confidence(confidence, confidence_basis)
        clean_licensing_notes = validate_optional_text(
            "licensing_notes", licensing_notes, MAX_LICENSING_NOTES_LENGTH
        )
        clean_metadata = validate_metadata(metadata)
        evidence_key = compute_evidence_key(
            evidence_type, clean_statement, excerpt_start, excerpt_end
        )
        timestamp = extracted_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise InvalidEvidenceInputError("extracted_at must be timezone-aware")

        candidate = ResearchEvidence(
            normalized_document_id=document.id,
            fetch_snapshot_id=provenance.snapshot.id,
            source_id=provenance.source.id,
            source_url=provenance.snapshot.final_url,
            fetched_at=provenance.snapshot.fetched_at,
            evidence_type=evidence_type,
            statement=clean_statement,
            excerpt=excerpt,
            excerpt_start=excerpt_start,
            excerpt_end=excerpt_end,
            offset_version=offset_version,
            source_locator=clean_locator,
            verification_status=verification_status,
            confidence=clean_confidence,
            confidence_basis=clean_confidence_basis,
            extractor_name=clean_extractor_name,
            extractor_version=clean_extractor_version,
            extraction_method=extraction_method,
            licensing_notes=clean_licensing_notes,
            metadata_json=clean_metadata,
            evidence_key=evidence_key,
            evidence_key_version=EVIDENCE_KEY_VERSION,
            extracted_at=timestamp,
        )
        return self._record(candidate)

    def _record(self, candidate: ResearchEvidence) -> ResearchEvidence:
        existing = self._evidence.get_by_identity(
            candidate.normalized_document_id,
            candidate.extractor_name,
            candidate.extractor_version,
            candidate.evidence_key,
        )
        if existing is not None:
            return _resolve_existing(existing, candidate)
        try:
            with self._session.begin_nested():
                return self._evidence.add(candidate)
        except IntegrityError:
            winner = self._evidence.get_by_identity(
                candidate.normalized_document_id,
                candidate.extractor_name,
                candidate.extractor_version,
                candidate.evidence_key,
            )
            if winner is not None:
                return _resolve_existing(winner, candidate)
            raise ResearchEvidencePersistenceError("database rejected research evidence") from None
        except SQLAlchemyError:
            raise ResearchEvidencePersistenceError("database rejected research evidence") from None


def _resolve_existing(existing: ResearchEvidence, candidate: ResearchEvidence) -> ResearchEvidence:
    if all(getattr(existing, field) == getattr(candidate, field) for field in _SEMANTIC_FIELDS):
        return existing
    raise ResearchEvidenceConflictError(
        "evidence identity already exists with different immutable content"
    )
