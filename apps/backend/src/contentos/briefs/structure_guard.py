"""Deterministic structural copyright guard (design §9.2 — never AI).

Compares the brief's ORDERED required-section guidance against EACH
individual admitted input document's stored `NormalizedDocument.headings`.
A near-match to any single source fails brief acceptance. Article body
text is never compared and never stored — only bounded derived metrics
plus document references.

Thresholds are an explicit versioned operational policy persisted with the
result — never a hidden magic number. A document without usable headings
is NOT_CHECKABLE, and "could not check" is never recorded as a pass; when
no relevant source structure is checkable at all, the configured policy
fails acceptance closed (`not_checkable_blocks_acceptance`).
"""

import re
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from contentos.briefs.enums import StructureGuardOutcome
from contentos.briefs.errors import BriefInputError

STRUCTURE_GUARD_SCHEMA_VERSION = 1
STRUCTURE_SIMILARITY_METRIC = "ordered-heading-sequence-matcher-v1"

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class BriefStructurePolicy:
    """One complete versioned structure-guard policy."""

    name: str
    version: str
    similarity_failure_threshold: float
    min_checkable_headings: int
    not_checkable_blocks_acceptance: bool

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.version.strip():
            raise BriefInputError("structure policy needs a name and a version")
        if not 0.0 < self.similarity_failure_threshold <= 1.0:
            raise BriefInputError("similarity_failure_threshold must be within (0, 1]")
        if self.min_checkable_headings < 1:
            raise BriefInputError("min_checkable_headings must be at least 1")

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": STRUCTURE_GUARD_SCHEMA_VERSION,
            "policy_name": self.name,
            "policy_version": self.version,
            "similarity_failure_threshold": self.similarity_failure_threshold,
            "min_checkable_headings": self.min_checkable_headings,
            "not_checkable_blocks_acceptance": self.not_checkable_blocks_acceptance,
            "metric": STRUCTURE_SIMILARITY_METRIC,
            "note": (
                "initial operational policy; thresholds are operational choices, "
                "not universal editorial truth"
            ),
        }


DEFAULT_BRIEF_STRUCTURE_POLICY = BriefStructurePolicy(
    name="default",
    version="1",
    similarity_failure_threshold=0.8,
    min_checkable_headings=2,
    not_checkable_blocks_acceptance=True,
)


@dataclass(frozen=True, slots=True)
class SourceStructure:
    """One admitted input document's ordered heading structure."""

    normalized_document_id: uuid.UUID
    headings: list[str]


def evaluate_structure_guard(
    section_labels: list[str],
    sources: list[SourceStructure],
    policy: BriefStructurePolicy,
) -> dict[str, Any]:
    """Deterministic ordered-structure comparison against each source.

    Similarity is difflib.SequenceMatcher over the two ORDERED lists of
    whitespace-normalized casefolded labels (the established bounded
    normalization semantics) — no NLP, no body text, no AI.
    """
    normalized_sections = [_normalize(label) for label in section_labels]
    checked: list[dict[str, Any]] = []
    skipped: list[str] = []
    max_similarity = 0.0
    most_similar: uuid.UUID | None = None
    for source in sources:
        normalized_headings = [
            _normalize(heading) for heading in source.headings if heading and heading.strip()
        ]
        if len(normalized_headings) < policy.min_checkable_headings:
            skipped.append(str(source.normalized_document_id))
            continue
        similarity = round(
            SequenceMatcher(None, normalized_sections, normalized_headings, autojunk=False).ratio(),
            6,
        )
        checked.append(
            {
                "normalized_document_id": str(source.normalized_document_id),
                "heading_count": len(normalized_headings),
                "similarity": similarity,
            }
        )
        if similarity > max_similarity:
            max_similarity = similarity
            most_similar = source.normalized_document_id

    if not checked:
        outcome = StructureGuardOutcome.NOT_CHECKABLE
    elif max_similarity >= policy.similarity_failure_threshold:
        outcome = StructureGuardOutcome.FAILED
    else:
        outcome = StructureGuardOutcome.PASSED
    return {
        "schema_version": STRUCTURE_GUARD_SCHEMA_VERSION,
        "outcome": outcome.value,
        "section_count": len(normalized_sections),
        "checked_documents": sorted(checked, key=lambda e: e["normalized_document_id"]),
        "skipped_documents": sorted(skipped),
        "max_similarity": max_similarity if checked else None,
        "most_similar_document_id": str(most_similar) if most_similar is not None else None,
        "threshold": policy.similarity_failure_threshold,
        "metric": STRUCTURE_SIMILARITY_METRIC,
    }


def _normalize(value: str) -> str:
    return _WHITESPACE.sub(" ", value or "").strip().casefold()
