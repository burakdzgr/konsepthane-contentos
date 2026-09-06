"""Model-assisted evidence extraction over successful NormalizedDocuments.

The deterministic v1 extractor only yields metadata observations (author,
date); an evidence pack needs *facts*: statistics, instructions, source
assertions and quotes. This engine asks the provider-neutral AI boundary
for candidate statements, each with the verbatim span of the normalized
text it rests on, then validates every candidate deterministically:

- the excerpt must be an exact contiguous substring of ``clean_text``
  (the offsets are computed here, never trusted from the model);
- statements and excerpts stay inside the persistence bounds;
- only sources whose role permits research evidence and yields
  opportunities are read (community sources never, taxonomy/competitor
  product pages not either — they feed signals);
- rejected candidates are counted and dropped, never repaired.

Persisted rows carry ``extraction_method = model_assisted``, the exact
generation attempt id in ``metadata_json`` and ``verification_status =
verified`` ONLY because the excerpt is proven to be an exact span of the
source: "verified" means excerpt-grounded here, not fact-checked. The
attempt identity (StructuredGenerationService) makes a re-run over the
same document and retry number idempotent; the raw model output is never
persisted.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from contentos.ai.dto import GenerationRequest
from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.models import AiGenerationAttempt
from contentos.ai.protocol import StructuredGenerationProvider
from contentos.ai.service import StructuredGenerationService
from contentos.ai.validation import StructuredOutputSpec
from contentos.normalization.enums import NormalizationStatus
from contentos.normalization.models import NormalizedDocument
from contentos.research.enums import EvidenceType, ExtractionMethod, VerificationStatus
from contentos.research.model_schemas import (
    EVIDENCE_CANDIDATE_SCHEMA_NAME,
    EVIDENCE_CANDIDATE_SCHEMA_VERSION,
    MAX_MODEL_CANDIDATES,
    EvidenceCandidateBatchV1,
    EvidenceCandidateV1,
)
from contentos.research.models import ResearchEvidence
from contentos.research.repository import ResearchEvidenceRepository, ResearchProvenanceRepository
from contentos.research.service import ResearchEvidenceService
from contentos.research.validation import (
    MAX_EXCERPT_LENGTH,
    MAX_STATEMENT_LENGTH,
    InvalidEvidenceInputError,
    ResearchDocumentNotEligibleError,
    ResearchDocumentNotFoundError,
)
from contentos.sources.enums import role_yields_opportunities
from contentos.sources.service import SourceRegistryService

MODEL_EXTRACTOR_NAME = "model-evidence-extractor"
MODEL_EXTRACTOR_VERSION = "1"
EVIDENCE_TEMPLATE_NAME = "evidence-extraction"
EVIDENCE_TEMPLATE_VERSION = "1"
EXTRACTION_INPUT_REFS_SCHEMA = "evidence-extraction/1"
# Bounded projection of the normalized text handed to the provider, as
# consecutive segments (the AI boundary caps single strings at 5000 chars).
MAX_TEXT_CHARS = 9_000
TEXT_SEGMENT_CHARS = 3_000
MAX_OUTPUT_TOKENS = 4_000

_TYPE_MAP: dict[str, EvidenceType] = {
    "statistic": EvidenceType.STATISTIC,
    "instruction": EvidenceType.INSTRUCTION,
    "source_assertion": EvidenceType.SOURCE_ASSERTION,
    "quote": EvidenceType.QUOTE,
}

# Versioned by EVIDENCE_TEMPLATE_NAME/VERSION; substantive changes REQUIRE a
# version bump (the text is never hashed).
_TEMPLATE_V1 = """\
You extract RESEARCH EVIDENCE from ONE source text for Konsepthane, a Turkish
practical celebration/event-planning publication. You receive the source
title, its trust tier, locale and the normalized text as consecutive
segments (`text_segments`, in order; concatenated they are the text).

Return up to the requested number of candidates. Each candidate MUST:
- rest on ONE verbatim excerpt: a contiguous span copied EXACTLY from the
  supplied text (same characters, same spacing, no ellipsis, no paraphrase,
  no translation), at most 400 characters;
- carry a self-contained STATEMENT written in Turkish that says what the
  excerpt establishes (numbers, quantities, steps, materials, timings,
  claims the source makes);
- use the right type: "statistic" for numbers/quantities/prices/durations,
  "instruction" for concrete how-to steps or material lists, "quote" for a
  notable verbatim sentence worth citing, "source_assertion" for a claim
  the source makes as fact;
- give a one-line BASIS explaining why the excerpt supports the statement.

Each candidate MUST NOT:
- invent, round, combine or infer facts that are not in the excerpt;
- restate marketing slogans, opinions, or generic filler as facts;
- include personal data (names of private people, phone numbers, emails);
- overlap another candidate's excerpt.

If the text contains no usable evidence, return an empty candidate list.
"""


@dataclass(frozen=True, slots=True)
class ModelExtractionResult:
    """What one extraction did; every count is a fact, never a guess."""

    attempt: AiGenerationAttempt | None
    status: GenerationStatus | None
    created: list[ResearchEvidence] = field(default_factory=list)
    existing: list[ResearchEvidence] = field(default_factory=list)
    rejected: int = 0
    attempt_created: bool = False
    skipped_reason: str | None = None

    @property
    def evidence(self) -> list[ResearchEvidence]:
        return [*self.created, *self.existing]


class ModelEvidenceExtractor:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._provenance = ResearchProvenanceRepository(session)
        self._evidence = ResearchEvidenceService(session)
        self._repository = ResearchEvidenceRepository(session)
        self._generation = StructuredGenerationService(session)

    def extract(
        self,
        normalized_document_id: uuid.UUID,
        *,
        provider: StructuredGenerationProvider,
        retry_number: int = 0,
        max_candidates: int = MAX_MODEL_CANDIDATES,
        now: datetime | None = None,
    ) -> ModelExtractionResult:
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
                "model evidence extraction requires a successful fingerprinted document"
            )
        provenance = self._provenance.get_provenance(normalized_document_id)
        if provenance is None or provenance.snapshot.final_url is None:
            raise ResearchDocumentNotEligibleError(
                "normalized document has no complete fetch/discovery/source provenance"
            )
        source = provenance.source
        if not SourceRegistryService.evidence_allowed(source):
            return ModelExtractionResult(
                attempt=None, status=None, skipped_reason="community_source"
            )
        if not role_yields_opportunities(source.primary_role):
            return ModelExtractionResult(
                attempt=None, status=None, skipped_reason="signal_only_source"
            )
        bounded = max(1, min(int(max_candidates), MAX_MODEL_CANDIDATES))

        request = self._build_request(
            document,
            source_label=source.slug,
            source=source,
            locale=provenance.discovery_item.locale,
            max_candidates=bounded,
            retry_number=retry_number,
        )
        spec: StructuredOutputSpec[EvidenceCandidateBatchV1] = StructuredOutputSpec(
            schema_name=EVIDENCE_CANDIDATE_SCHEMA_NAME,
            schema_version=EVIDENCE_CANDIDATE_SCHEMA_VERSION,
            model_type=EvidenceCandidateBatchV1,
        )
        execution = self._generation.execute(request, spec, provider)
        if execution.status is not GenerationStatus.SUCCEEDED:
            return ModelExtractionResult(
                attempt=execution.attempt,
                status=execution.status,
                attempt_created=execution.created,
            )
        if not execution.created:
            # Reused SUCCEEDED attempt: the rows it materialized are the answer.
            existing = self._rows_for_attempt(document.id, execution.attempt.id)
            return ModelExtractionResult(
                attempt=execution.attempt,
                status=execution.status,
                existing=existing,
                attempt_created=False,
            )
        assert execution.payload is not None
        created, existing, rejected = self._materialize(
            document, execution.attempt, execution.payload, now=now
        )
        return ModelExtractionResult(
            attempt=execution.attempt,
            status=execution.status,
            created=created,
            existing=existing,
            rejected=rejected,
            attempt_created=True,
        )

    # --- internal -------------------------------------------------------------

    def _build_request(
        self,
        document: NormalizedDocument,
        *,
        source_label: str,
        source: Any,
        locale: str | None,
        max_candidates: int,
        retry_number: int,
    ) -> GenerationRequest:
        text = document.clean_text or ""
        truncated = len(text) > MAX_TEXT_CHARS
        projected = text[:MAX_TEXT_CHARS]
        segments = text_segments(projected)
        input_refs = {
            "schema": EXTRACTION_INPUT_REFS_SCHEMA,
            "normalized_document_id": str(document.id),
            "fetch_snapshot_id": str(document.fetch_snapshot_id),
            "source_id": str(source.id),
            "content_fingerprint": document.content_fingerprint,
            "extractor_name": MODEL_EXTRACTOR_NAME,
            "extractor_version": MODEL_EXTRACTOR_VERSION,
            "max_candidates": max_candidates,
        }
        input_projection = {
            "title": document.title,
            "locale": locale,
            "source": {"label": source_label, "trust_tier": source.trust_tier.value},
            "text_segments": segments,
            "text_truncated": truncated,
            "max_candidates": max_candidates,
        }
        return GenerationRequest(
            purpose=GenerationPurpose.EVIDENCE_EXTRACTION,
            schema_name=EVIDENCE_CANDIDATE_SCHEMA_NAME,
            schema_version=EVIDENCE_CANDIDATE_SCHEMA_VERSION,
            template_name=EVIDENCE_TEMPLATE_NAME,
            template_version=EVIDENCE_TEMPLATE_VERSION,
            input_refs=input_refs,
            input_projection=input_projection,
            generation_bounds={
                "max_candidates": max_candidates,
                "max_output_tokens": MAX_OUTPUT_TOKENS,
            },
            retry_number=retry_number,
            instructions=_TEMPLATE_V1,
        )

    def _rows_for_attempt(
        self, document_id: uuid.UUID, attempt_id: uuid.UUID
    ) -> list[ResearchEvidence]:
        return [
            row
            for row in self._repository.list_for_normalized_document(document_id)
            if row.extractor_name == MODEL_EXTRACTOR_NAME
            and row.metadata_json.get("generation_attempt_id") == str(attempt_id)
        ]

    def _materialize(
        self,
        document: NormalizedDocument,
        attempt: AiGenerationAttempt,
        batch: EvidenceCandidateBatchV1,
        *,
        now: datetime | None,
    ) -> tuple[list[ResearchEvidence], list[ResearchEvidence], int]:
        clean_text = document.clean_text or ""
        moment = now if now is not None else datetime.now(UTC)
        created: list[ResearchEvidence] = []
        existing: list[ResearchEvidence] = []
        rejected = 0
        used_spans: list[tuple[int, int]] = []
        seen_ids: set[uuid.UUID] = set()
        for index, candidate in enumerate(batch.candidates):
            span = locate_excerpt(clean_text, candidate.excerpt)
            if span is None or _overlaps(span, used_spans):
                rejected += 1
                continue
            start, end = span
            excerpt = clean_text[start:end]
            statement = " ".join(candidate.statement.split())
            if not statement or len(statement) > MAX_STATEMENT_LENGTH:
                rejected += 1
                continue
            try:
                row = self._evidence.record_evidence(
                    document.id,
                    evidence_type=_TYPE_MAP[candidate.evidence_type],
                    statement=statement,
                    extraction_method=ExtractionMethod.MODEL_ASSISTED,
                    extractor_name=MODEL_EXTRACTOR_NAME,
                    extractor_version=MODEL_EXTRACTOR_VERSION,
                    excerpt=excerpt,
                    excerpt_start=start,
                    excerpt_end=end,
                    verification_status=VerificationStatus.VERIFIED,
                    metadata={
                        "generation_attempt_id": str(attempt.id),
                        "candidate_index": index,
                        "basis": " ".join(candidate.basis.split())[:300],
                        "provider": attempt.provider,
                        "model_name": attempt.model_name,
                    },
                    extracted_at=moment,
                )
            except InvalidEvidenceInputError:
                rejected += 1
                continue
            if row.id in seen_ids:
                continue
            seen_ids.add(row.id)
            used_spans.append(span)
            # `record_evidence` hands back the already-persisted row for a
            # repeated identity; a fresh row carries this run's attempt id.
            if row.metadata_json.get("generation_attempt_id") == str(attempt.id):
                created.append(row)
            else:
                existing.append(row)
        return created, existing, rejected


def text_segments(text: str, size: int = TEXT_SEGMENT_CHARS) -> list[str]:
    """Consecutive, order-preserving slices of the projected text; joined
    they reproduce it exactly (excerpts may span a boundary — the model
    sees the whole text, the validator checks the whole text)."""
    if not text:
        return []
    return [text[index : index + size] for index in range(0, len(text), size)]


def locate_excerpt(clean_text: str, excerpt: str) -> tuple[int, int] | None:
    """Exact zero-based, end-exclusive span of `excerpt` inside `clean_text`.

    The model's excerpt is trusted only when it is a verbatim contiguous
    substring (after trimming surrounding whitespace). A candidate whose
    excerpt cannot be located exactly is dropped; nothing is "repaired".
    """
    candidate = excerpt.strip()
    if not candidate or len(candidate) > MAX_EXCERPT_LENGTH:
        return None
    start = clean_text.find(candidate)
    if start < 0:
        return None
    return start, start + len(candidate)


def _overlaps(span: tuple[int, int], used: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < other_end and other_start < end for other_start, other_end in used)


def candidate_types() -> tuple[str, ...]:
    return tuple(_TYPE_MAP)


__all__ = [
    "EVIDENCE_TEMPLATE_NAME",
    "EVIDENCE_TEMPLATE_VERSION",
    "MAX_TEXT_CHARS",
    "MODEL_EXTRACTOR_NAME",
    "MODEL_EXTRACTOR_VERSION",
    "EvidenceCandidateV1",
    "ModelEvidenceExtractor",
    "ModelExtractionResult",
    "candidate_types",
    "locate_excerpt",
    "text_segments",
]
