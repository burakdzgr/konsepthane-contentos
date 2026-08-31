"""Deterministic v1 evidence extractor over successful NormalizedDocuments.

The first executable producer of ResearchEvidence. It converts a small
allowlist of already-normalized metadata facts into excerpt-less OBSERVATION
evidence through ResearchEvidenceService — never by writing models directly.

Frozen v1 decisions:

- Identity is the existing ``deterministic-evidence`` / ``1`` contract;
  behavior changes require a version bump.
- Statements are deterministic Turkish templates (the project is
  Turkey-first and existing evidence fixtures are Turkish); no generative
  variation of any kind.
- v1 emits NO exact-excerpt candidates (``MAX_EXACT_EXCERPT_CANDIDATES = 0``):
  no metadata fact has a structurally certain clean-text span, and weak
  evidence must not be invented to raise counts. All v1 evidence is
  excerpt-less, UNVERIFIED, MACHINE, with a bounded source_locator and no
  confidence score.
- Author priority: ``normalized.author_name`` (the normalization pipeline's
  already-resolved result), then ``structured_metadata.article:author``, then
  the first JSON-LD ``author`` string. Exactly one author evidence at most.
- Publication-date priority: ``normalized.external_published_at``, then
  ``structured_metadata.article:published_time``, then the first JSON-LD
  ``datePublished`` string. Exactly one date evidence at most.
- Malformed metadata values are skipped with warnings; they never fail the
  whole document. A same-identity row with different immutable content raises
  the existing typed conflict — that is an integrity signal, not a skip.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from contentos.normalization.enums import NormalizationStatus
from contentos.normalization.models import NormalizedDocument
from contentos.research.enums import EvidenceType, ExtractionMethod, VerificationStatus
from contentos.research.models import ResearchEvidence
from contentos.research.repository import (
    ResearchEvidenceRepository,
    ResearchProvenanceRepository,
)
from contentos.research.service import (
    DEFAULT_EXTRACTOR_NAME,
    DEFAULT_EXTRACTOR_VERSION,
    ResearchEvidenceService,
)
from contentos.research.validation import (
    InvalidEvidenceInputError,
    ResearchDocumentNotEligibleError,
    ResearchDocumentNotFoundError,
    compute_evidence_key,
)

# Extractor limits; all are at or below the Task 13 persistence limits.
MAX_EVIDENCE_CANDIDATES_PER_DOCUMENT = 10
MAX_METADATA_VALUE_LENGTH = 300
MAX_JSON_LD_SUMMARIES_INSPECTED = 5
MAX_EXACT_EXCERPT_CANDIDATES = 0  # v1 deliberately produces metadata evidence only

AUTHOR_STATEMENT_TEMPLATE = "Kaynak, içeriğin yazarını '{value}' olarak belirtiyor."
DATE_STATEMENT_TEMPLATE = "Kaynak, yayın tarihini {value} olarak belirtiyor."
DATE_TEXT_STATEMENT_TEMPLATE = "Kaynak, yayın tarihini '{value}' olarak belirtiyor."

_AUTHOR_RULE = "author_attribution"
_DATE_RULE = "publication_date"


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    """One deterministic in-memory candidate; never persisted directly."""

    evidence_type: EvidenceType
    statement: str
    source_locator: str
    rule: str
    excerpt: str | None = None
    excerpt_start: int | None = None
    excerpt_end: int | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED


@dataclass(frozen=True, slots=True)
class DeterministicEvidenceExtractionResult:
    """Immutable outcome of one extraction run; runs are not persisted."""

    normalized_document_id: uuid.UUID
    candidates_seen: int
    created: tuple[ResearchEvidence, ...]
    existing: tuple[ResearchEvidence, ...]
    skipped_invalid: int
    warnings: tuple[str, ...]


@dataclass(slots=True)
class _Collector:
    """Mutable extraction bookkeeping shared by the candidate helpers."""

    warnings: list[str] = field(default_factory=list)
    skipped_invalid: int = 0

    def skip(self, message: str) -> None:
        self.warnings.append(message)
        self.skipped_invalid += 1


class DeterministicEvidenceExtractor:
    """Executable boundary from NormalizedDocument to immutable evidence rows.

    Flushes only; the caller owns the transaction. Idempotency is entirely the
    Task 13 evidence-key contract — a rerun returns the existing rows.
    """

    def __init__(self, session: Session) -> None:
        self._service = ResearchEvidenceService(session)
        self._evidence = ResearchEvidenceRepository(session)
        self._documents = ResearchProvenanceRepository(session)

    def extract_and_record(
        self, normalized_document_id: uuid.UUID
    ) -> DeterministicEvidenceExtractionResult:
        document = self._documents.get_document(normalized_document_id)
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
                "deterministic extraction requires a successful fingerprinted document"
            )

        collector = _Collector()
        candidates = _generate_candidates(document, collector)
        candidates_seen = len(candidates)
        if candidates_seen > MAX_EVIDENCE_CANDIDATES_PER_DOCUMENT:
            dropped = candidates_seen - MAX_EVIDENCE_CANDIDATES_PER_DOCUMENT
            collector.warnings.append(f"candidate limit exceeded; dropped {dropped} candidates")
            candidates = candidates[:MAX_EVIDENCE_CANDIDATES_PER_DOCUMENT]

        created: list[ResearchEvidence] = []
        existing: list[ResearchEvidence] = []
        for candidate in candidates:
            evidence_key = compute_evidence_key(
                candidate.evidence_type,
                candidate.statement,
                candidate.excerpt_start,
                candidate.excerpt_end,
            )
            already_stored = self._evidence.get_by_identity(
                document.id,
                DEFAULT_EXTRACTOR_NAME,
                DEFAULT_EXTRACTOR_VERSION,
                evidence_key,
            )
            try:
                row = self._service.record_evidence(
                    document.id,
                    evidence_type=candidate.evidence_type,
                    statement=candidate.statement,
                    extraction_method=ExtractionMethod.MACHINE,
                    extractor_name=DEFAULT_EXTRACTOR_NAME,
                    extractor_version=DEFAULT_EXTRACTOR_VERSION,
                    excerpt=candidate.excerpt,
                    excerpt_start=candidate.excerpt_start,
                    excerpt_end=candidate.excerpt_end,
                    source_locator=candidate.source_locator,
                    verification_status=candidate.verification_status,
                    metadata={"rule": candidate.rule},
                )
            except InvalidEvidenceInputError as error:
                collector.skip(f"candidate '{candidate.rule}' rejected: {error}")
                continue
            if already_stored is not None:
                existing.append(row)
            else:
                created.append(row)

        return DeterministicEvidenceExtractionResult(
            normalized_document_id=document.id,
            candidates_seen=candidates_seen,
            created=tuple(created),
            existing=tuple(existing),
            skipped_invalid=collector.skipped_invalid,
            warnings=tuple(collector.warnings),
        )


def _generate_candidates(
    document: NormalizedDocument, collector: _Collector
) -> list[EvidenceCandidate]:
    """Produce the bounded, deduplicated v1 candidate list."""
    candidates: list[EvidenceCandidate] = []
    author = _author_candidate(document, collector)
    if author is not None:
        candidates.append(author)
    date = _date_candidate(document, collector)
    if date is not None:
        candidates.append(date)
    return candidates


def _author_candidate(
    document: NormalizedDocument, collector: _Collector
) -> EvidenceCandidate | None:
    value = document.author_name
    locator = "normalized.author_name"
    if value is None:
        value, locator = _metadata_author(document, collector)
    if value is None:
        return None
    return EvidenceCandidate(
        evidence_type=EvidenceType.OBSERVATION,
        statement=AUTHOR_STATEMENT_TEMPLATE.format(value=value),
        source_locator=locator,
        rule=_AUTHOR_RULE,
    )


def _date_candidate(
    document: NormalizedDocument, collector: _Collector
) -> EvidenceCandidate | None:
    if document.external_published_at is not None:
        return EvidenceCandidate(
            evidence_type=EvidenceType.OBSERVATION,
            statement=DATE_STATEMENT_TEMPLATE.format(
                value=document.external_published_at.isoformat()
            ),
            source_locator="normalized.external_published_at",
            rule=_DATE_RULE,
        )
    value, locator = _metadata_date(document, collector)
    if value is None:
        return None
    return EvidenceCandidate(
        evidence_type=EvidenceType.OBSERVATION,
        statement=DATE_TEXT_STATEMENT_TEMPLATE.format(value=value),
        source_locator=locator,
        rule=_DATE_RULE,
    )


def _metadata_author(document: NormalizedDocument, collector: _Collector) -> tuple[str | None, str]:
    article = _metadata_container(document, "article", collector)
    if article is not None:
        value = _clean_metadata_value("article:author", article.get("article:author"), collector)
        if value is not None:
            return value, "structured_metadata.article:author"
    value = _json_ld_value(document, "author", collector)
    if value is not None:
        return value, "structured_metadata.json_ld.author"
    return None, ""


def _metadata_date(document: NormalizedDocument, collector: _Collector) -> tuple[str | None, str]:
    article = _metadata_container(document, "article", collector)
    if article is not None:
        value = _clean_metadata_value(
            "article:published_time", article.get("article:published_time"), collector
        )
        if value is not None:
            return value, "structured_metadata.article:published_time"
    value = _json_ld_value(document, "datePublished", collector)
    if value is not None:
        return value, "structured_metadata.json_ld.datePublished"
    return None, ""


def _metadata_container(
    document: NormalizedDocument, key: str, collector: _Collector
) -> dict[str, Any] | None:
    structured = document.structured_metadata
    if not isinstance(structured, dict):
        collector.skip("structured_metadata is not an object; value skipped")
        return None
    container = structured.get(key)
    if container is None:
        return None
    if not isinstance(container, dict):
        collector.skip(f"structured_metadata.{key} is not an object; value skipped")
        return None
    return container


def _json_ld_value(document: NormalizedDocument, key: str, collector: _Collector) -> str | None:
    structured = document.structured_metadata
    if not isinstance(structured, dict):
        return None
    summaries = structured.get("json_ld")
    if summaries is None:
        return None
    if not isinstance(summaries, list):
        collector.skip("structured_metadata.json_ld is not a list; value skipped")
        return None
    for summary in summaries[:MAX_JSON_LD_SUMMARIES_INSPECTED]:
        if not isinstance(summary, dict):
            continue
        value = _clean_metadata_value(f"json_ld.{key}", summary.get(key), collector)
        if value is not None:
            return value
    return None


def _clean_metadata_value(name: str, raw: object, collector: _Collector) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        collector.skip(f"metadata value '{name}' is not text; value skipped")
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_METADATA_VALUE_LENGTH:
        collector.skip(f"metadata value '{name}' exceeds the extractor bound; value skipped")
        return None
    return cleaned
