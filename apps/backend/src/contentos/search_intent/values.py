"""Typed bounded inputs for search-intent composition.

The accepted design freezes no universal SEO taxonomy, so semantic intent
fields are bounded validated editorial text — not an invented permanent
enum. Deterministic composition receives them through the explicit typed
`IntentComposition` DTO (never an arbitrary dict); the optional AI path
proposes ONLY the same semantic fields through its strict schema.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from contentos.search_intent.enums import CannibalizationStatus
from contentos.search_intent.errors import (
    InvalidAnalysisInputError,
    InvalidCannibalizationError,
)

MAX_INTENT_LENGTH = 200
MAX_SECONDARY_INTENTS = 10
MAX_QUERY_CONCEPTS = 30
MAX_QUERY_CONCEPT_LENGTH = 200
MAX_PAGE_PURPOSE_LENGTH = 500
MAX_LIKELY_FORMAT_LENGTH = 200
MAX_CHECKED_REFERENCES = 50
MAX_RELATED_REFERENCES = 30
MAX_BASIS_REASON_LENGTH = 500

CANNIBALIZATION_BASIS_SCHEMA_VERSION = 1

# Internal reference kinds an analysis may point at. Deliberately
# allowlisted ContentOS-internal identities — never arbitrary URLs/JSON.
ALLOWED_REFERENCE_KINDS = ("opportunity", "work_item", "idea", "analysis")


@dataclass(frozen=True, slots=True)
class IntentComposition:
    """Deterministic semantic intent fields, explicitly supplied.

    No hidden heuristic pretends to infer semantic search intent from
    sparse signals: where the semantic fields cannot be proven
    automatically, the operator/caller states them through this typed DTO.
    """

    primary_intent: str
    page_purpose: str
    likely_format: str
    secondary_intents: tuple[str, ...] = ()
    query_concepts: tuple[str, ...] = ()

    def cleaned(self) -> dict[str, Any]:
        return {
            "primary_intent": _required_text(
                "primary_intent", self.primary_intent, MAX_INTENT_LENGTH
            ),
            "page_purpose": _required_text(
                "page_purpose", self.page_purpose, MAX_PAGE_PURPOSE_LENGTH
            ),
            "likely_format": _required_text(
                "likely_format", self.likely_format, MAX_LIKELY_FORMAT_LENGTH
            ),
            "secondary_intents": validate_semantic_list(
                "secondary_intents",
                list(self.secondary_intents),
                max_items=MAX_SECONDARY_INTENTS,
                max_length=MAX_INTENT_LENGTH,
            ),
            "query_concepts": validate_semantic_list(
                "query_concepts",
                list(self.query_concepts),
                max_items=MAX_QUERY_CONCEPTS,
                max_length=MAX_QUERY_CONCEPT_LENGTH,
            ),
        }


@dataclass(frozen=True, slots=True)
class InternalReference:
    """One exact allowlisted ContentOS-internal reference."""

    kind: str
    reference_id: uuid.UUID

    def to_persisted(self) -> dict[str, str]:
        return {"kind": self.kind, "id": str(self.reference_id)}


@dataclass(frozen=True, slots=True)
class CannibalizationInput:
    """The recorded overlap-check truth for one analysis.

    KNOWN_CONFLICT is refused today: no published-inventory basis exists.
    NO_KNOWN_CONFLICT / POTENTIAL_CONFLICT require the exact internal
    references actually examined — a vague conflict state is never stored.
    """

    status: CannibalizationStatus = CannibalizationStatus.NOT_CHECKED
    checked_references: tuple[InternalReference, ...] = ()
    reason: str | None = None


NOT_CHECKED_INPUT = CannibalizationInput()


def build_cannibalization_basis(cannibalization: CannibalizationInput) -> dict[str, Any]:
    """The bounded versioned basis; the missing published-inventory scope
    stays visible in every shape."""
    if cannibalization.status is CannibalizationStatus.KNOWN_CONFLICT:
        raise InvalidCannibalizationError(
            "KNOWN_CONFLICT cannot be recorded: no published-inventory read "
            "contract exists (accepted future vocabulary only)"
        )
    if cannibalization.status is CannibalizationStatus.NOT_CHECKED:
        if cannibalization.checked_references or cannibalization.reason:
            raise InvalidCannibalizationError(
                "NOT_CHECKED cannot carry checked references or a reason"
            )
        return {
            "schema_version": CANNIBALIZATION_BASIS_SCHEMA_VERSION,
            "checked": False,
            "scope": None,
            "checked_references": [],
            "published_inventory": "unavailable_not_checked",
        }
    if not cannibalization.checked_references:
        raise InvalidCannibalizationError(
            f"{cannibalization.status.value} requires the exact internal "
            "references actually examined"
        )
    if len(cannibalization.checked_references) > MAX_CHECKED_REFERENCES:
        raise InvalidCannibalizationError("too many checked references")
    references = [
        _validated_reference(reference).to_persisted()
        for reference in cannibalization.checked_references
    ]
    basis: dict[str, Any] = {
        "schema_version": CANNIBALIZATION_BASIS_SCHEMA_VERSION,
        "checked": True,
        "scope": "contentos_internal",
        "checked_references": references,
        "published_inventory": "unavailable_not_checked",
    }
    if cannibalization.reason is not None:
        basis["reason"] = _required_text("reason", cannibalization.reason, MAX_BASIS_REASON_LENGTH)
    return basis


def validate_related_references(
    references: list[InternalReference] | None,
) -> list[dict[str, str]]:
    if not references:
        return []
    if len(references) > MAX_RELATED_REFERENCES:
        raise InvalidAnalysisInputError("too many related references")
    persisted: list[dict[str, str]] = []
    for reference in references:
        entry = _validated_reference(reference).to_persisted()
        if entry in persisted:
            raise InvalidAnalysisInputError("duplicate related reference")
        persisted.append(entry)
    return persisted


def validate_semantic_list(
    name: str, values: list[str], *, max_items: int, max_length: int
) -> list[str]:
    """Bounded, order-preserving, exact-duplicate-rejecting semantic text."""
    if len(values) > max_items:
        raise InvalidAnalysisInputError(f"{name} exceeds the limit of {max_items} entries")
    cleaned: list[str] = []
    for value in values:
        entry = _required_text(name, value, max_length)
        if entry in cleaned:
            raise InvalidAnalysisInputError(f"{name} contains duplicate entries")
        cleaned.append(entry)
    return cleaned


def _validated_reference(reference: InternalReference) -> InternalReference:
    if reference.kind not in ALLOWED_REFERENCE_KINDS:
        raise InvalidAnalysisInputError(
            f"unknown internal reference kind {reference.kind!r}; allowed: "
            f"{list(ALLOWED_REFERENCE_KINDS)}"
        )
    if not isinstance(reference.reference_id, uuid.UUID):
        raise InvalidAnalysisInputError("internal reference ids must be UUIDs")
    return reference


def _required_text(name: str, value: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidAnalysisInputError(f"{name} must not be empty")
    cleaned = " ".join(value.split())
    if len(cleaned) > limit:
        raise InvalidAnalysisInputError(f"{name} exceeds the {limit}-character limit")
    return cleaned
