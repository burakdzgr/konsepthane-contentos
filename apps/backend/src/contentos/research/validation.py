"""Deterministic, provider-neutral validation for research evidence."""

import hashlib
import json
import math
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any

from contentos.research.enums import EvidenceType

RESEARCH_EVIDENCE_OFFSET_VERSION = 1
EVIDENCE_KEY_VERSION = 1
MAX_STATEMENT_LENGTH = 2_000
MAX_EXCERPT_LENGTH = 750
MAX_EXTRACTOR_NAME_LENGTH = 100
MAX_EXTRACTOR_VERSION_LENGTH = 100
MAX_SOURCE_LOCATOR_LENGTH = 500
MAX_LICENSING_NOTES_LENGTH = 1_000
MAX_CONFIDENCE_BASIS_LENGTH = 500
MAX_METADATA_DEPTH = 6
MAX_METADATA_ITEMS = 200
MAX_METADATA_STRING_LENGTH = 2_000

_SOURCE_LOCATOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*(?:[.:][A-Za-z_][A-Za-z0-9_-]*)*$")


class ResearchEvidenceError(Exception):
    """Base class for stable research-evidence failures."""


class ResearchDocumentNotFoundError(ResearchEvidenceError):
    """The requested normalized document does not exist."""


class ResearchDocumentNotEligibleError(ResearchEvidenceError):
    """The normalized document is not a complete successful result."""


class InvalidExcerptBoundsError(ResearchEvidenceError):
    """Excerpt offsets do not satisfy the frozen code-point contract."""


class ExcerptMismatchError(ResearchEvidenceError):
    """The exact clean-text slice differs from the supplied excerpt."""


class InvalidEvidenceInputError(ResearchEvidenceError):
    """Evidence content or extraction metadata violates the durable contract."""


class ResearchEvidenceConflictError(ResearchEvidenceError):
    """An evidence identity already exists with different immutable content."""


class ResearchProvenanceMissingError(ResearchEvidenceError):
    """The normalized document does not have a complete governed source chain."""


class ResearchEvidencePersistenceError(ResearchEvidenceError):
    """The database rejected an evidence recording operation."""


def validate_bounded_text(name: str, value: str, limit: int) -> str:
    """Trim and require one non-empty bounded text value."""
    if not isinstance(value, str):
        raise InvalidEvidenceInputError(f"{name} must be text")
    cleaned = value.strip()
    if not cleaned:
        raise InvalidEvidenceInputError(f"{name} must not be empty")
    if len(cleaned) > limit:
        raise InvalidEvidenceInputError(f"{name} exceeds the persistence limit")
    return cleaned


def validate_optional_text(name: str, value: str | None, limit: int) -> str | None:
    """Validate an optional operator-provided note without inferring its meaning."""
    if value is None:
        return None
    return validate_bounded_text(name, value, limit)


def validate_excerpt(
    clean_text: str,
    excerpt: str | None,
    excerpt_start: int | None,
    excerpt_end: int | None,
) -> int | None:
    """Prove an exact zero-based, end-exclusive Python code-point slice."""
    values_present = (excerpt is not None, excerpt_start is not None, excerpt_end is not None)
    if not any(values_present):
        return None
    if not all(values_present):
        raise InvalidExcerptBoundsError("excerpt and both offsets must be provided together")
    assert excerpt is not None and excerpt_start is not None and excerpt_end is not None
    if isinstance(excerpt_start, bool) or isinstance(excerpt_end, bool):
        raise InvalidExcerptBoundsError("excerpt offsets must be integers")
    if not isinstance(excerpt_start, int) or not isinstance(excerpt_end, int):
        raise InvalidExcerptBoundsError("excerpt offsets must be integers")
    if excerpt_start < 0 or excerpt_end <= excerpt_start or excerpt_end > len(clean_text):
        raise InvalidExcerptBoundsError("excerpt offsets are outside the normalized text")
    if not excerpt:
        raise InvalidExcerptBoundsError("excerpt must not be empty")
    if len(excerpt) > MAX_EXCERPT_LENGTH:
        raise InvalidEvidenceInputError("excerpt exceeds the copyright-safe persistence limit")
    if clean_text[excerpt_start:excerpt_end] != excerpt:
        raise ExcerptMismatchError("excerpt does not exactly match the normalized text span")
    return RESEARCH_EVIDENCE_OFFSET_VERSION


def validate_source_locator(value: str | None, *, required: bool) -> str | None:
    """Accept only a bounded dotted/colon-delimited data path, never JSONPath code."""
    locator = validate_optional_text("source_locator", value, MAX_SOURCE_LOCATOR_LENGTH)
    if required and locator is None:
        raise InvalidEvidenceInputError(
            "excerpt-less evidence requires a deterministic source_locator"
        )
    if locator is not None and _SOURCE_LOCATOR.fullmatch(locator) is None:
        raise InvalidEvidenceInputError("source_locator must be a safe deterministic path")
    return locator


def validate_confidence(
    confidence: Decimal | int | float | str | None,
    confidence_basis: str | None,
) -> tuple[Decimal | None, str | None]:
    """Validate optional explicit confidence; exact extraction never invents a score."""
    basis = validate_optional_text(
        "confidence_basis", confidence_basis, MAX_CONFIDENCE_BASIS_LENGTH
    )
    if confidence is None:
        if basis is not None:
            raise InvalidEvidenceInputError("confidence_basis requires confidence")
        return None, None
    if isinstance(confidence, bool):
        raise InvalidEvidenceInputError("confidence must be a decimal from 0 to 1")
    try:
        decimal_value = Decimal(str(confidence))
    except (InvalidOperation, ValueError):
        raise InvalidEvidenceInputError("confidence must be a decimal from 0 to 1") from None
    if not decimal_value.is_finite() or not Decimal(0) <= decimal_value <= Decimal(1):
        raise InvalidEvidenceInputError("confidence must be a finite decimal from 0 to 1")
    exponent = decimal_value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -4:
        raise InvalidEvidenceInputError("confidence supports at most four decimal places")
    if basis is None:
        raise InvalidEvidenceInputError("confidence requires a recorded basis")
    return decimal_value, basis


def validate_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and detach a bounded JSON object."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidEvidenceInputError("metadata must be a JSON object")
    item_count = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal item_count
        if depth > MAX_METADATA_DEPTH:
            raise InvalidEvidenceInputError("metadata exceeds the JSON depth limit")
        if isinstance(node, dict):
            item_count += len(node)
            for key, child in node.items():
                if not isinstance(key, str) or len(key) > MAX_METADATA_STRING_LENGTH:
                    raise InvalidEvidenceInputError("metadata contains an invalid JSON key")
                walk(child, depth + 1)
        elif isinstance(node, list):
            item_count += len(node)
            for child in node:
                walk(child, depth + 1)
        elif isinstance(node, str):
            if len(node) > MAX_METADATA_STRING_LENGTH:
                raise InvalidEvidenceInputError("metadata contains oversized text")
        elif isinstance(node, float):
            if not math.isfinite(node):
                raise InvalidEvidenceInputError("metadata contains a non-finite number")
        elif node is not None and not isinstance(node, (bool, int)):
            raise InvalidEvidenceInputError("metadata contains a non-JSON value")
        if item_count > MAX_METADATA_ITEMS:
            raise InvalidEvidenceInputError("metadata exceeds the JSON item limit")

    walk(value, 1)
    return deepcopy(value)


def evidence_key_payload(
    evidence_type: EvidenceType,
    statement: str,
    excerpt_start: int | None,
    excerpt_end: int | None,
) -> bytes:
    """Return the frozen v1 canonical JSON tuple encoded as exact UTF-8."""
    return json.dumps(
        [evidence_type.value, statement, excerpt_start, excerpt_end],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def compute_evidence_key(
    evidence_type: EvidenceType,
    statement: str,
    excerpt_start: int | None,
    excerpt_end: int | None,
) -> str:
    """SHA-256 lowercase hex of the frozen v1 canonical evidence tuple."""
    return hashlib.sha256(
        evidence_key_payload(evidence_type, statement, excerpt_start, excerpt_end)
    ).hexdigest()
