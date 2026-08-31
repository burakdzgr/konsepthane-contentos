"""Immutable comparison inputs, metrics, results, and frozen v1 thresholds."""

import re
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher

from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.normalization.enums import NormalizationStatus

TITLE_SIMILARITY_METRIC = "unicode-sequence-matcher-v1"
LEXICAL_SIMILARITY_METRIC = "unicode-token-jaccard-v1"

_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[\w\u0300-\u036f]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class DuplicateThresholds:
    """Complete frozen policy snapshot for one deterministic engine version."""

    max_candidate_documents: int = 200
    max_lexical_text_chars: int = 100_000
    max_tokens: int = 10_000
    max_stored_matches: int = 10
    max_rationale_codes: int = 20
    duplicate_title_similarity: float = 0.92
    duplicate_lexical_similarity: float = 0.85
    related_title_similarity: float = 0.65
    related_lexical_similarity: float = 0.45
    related_title_lexical_floor: float = 0.25


V1_THRESHOLDS = DuplicateThresholds()


@dataclass(frozen=True, slots=True)
class ComparisonDocument:
    """Bounded local provenance and content needed for one comparison."""

    normalized_document_id: uuid.UUID
    fetch_snapshot_id: uuid.UUID
    discovery_item_id: uuid.UUID
    normalization_status: NormalizationStatus
    canonical_url: str
    final_url: str | None
    raw_body_sha256: str | None
    content_fingerprint: str | None
    title: str | None
    clean_text: str | None


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    """Safe bounded provenance and scores for one material local match."""

    normalized_document_id: uuid.UUID
    fetch_snapshot_id: uuid.UUID
    discovery_item_id: uuid.UUID
    exact_canonical_url: bool
    exact_final_url: bool
    exact_raw_body: bool
    exact_content_fingerprint: bool
    title_similarity: float
    lexical_similarity: float
    rationale_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DuplicateSignals:
    """Aggregate signal telemetry persisted for every decision."""

    candidate_count: int
    exact_canonical_url_matches: int
    exact_final_url_matches: int
    exact_raw_body_matches: int
    exact_content_fingerprint_matches: int
    highest_title_similarity: float
    highest_lexical_similarity: float
    title_similarity_metric: str = TITLE_SIMILARITY_METRIC
    lexical_similarity_metric: str = LEXICAL_SIMILARITY_METRIC


@dataclass(frozen=True, slots=True)
class DuplicateEvaluation:
    """Immutable engine output; persistence remains a separate service concern."""

    decision: DuplicateDecisionOutcome
    signals: DuplicateSignals
    thresholds: DuplicateThresholds
    matches: tuple[DuplicateMatch, ...]
    rationale_codes: tuple[str, ...]


def title_similarity(left: str | None, right: str | None) -> float:
    """Return deterministic Unicode-aware title similarity in the 0..1 range."""
    normalized_left = _normalize_text(left)
    normalized_right = _normalize_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return round(
        SequenceMatcher(None, normalized_left, normalized_right, autojunk=False).ratio(),
        6,
    )


def lexical_similarity(
    left: str | None,
    right: str | None,
    *,
    max_chars: int,
    max_tokens: int,
) -> float:
    """Return bounded token-set Jaccard similarity without stemming or transliteration."""
    left_tokens = _token_set(left, max_chars=max_chars, max_tokens=max_tokens)
    right_tokens = _token_set(right, max_chars=max_chars, max_tokens=max_tokens)
    if not left_tokens or not right_tokens:
        return 0.0
    return round(len(left_tokens & right_tokens) / len(left_tokens | right_tokens), 6)


def _normalize_text(value: str | None) -> str:
    return _WHITESPACE.sub(" ", value or "").strip().casefold()


def _token_set(value: str | None, *, max_chars: int, max_tokens: int) -> set[str]:
    normalized = _normalize_text((value or "")[:max_chars])
    return set(_TOKEN.findall(normalized)[:max_tokens])
