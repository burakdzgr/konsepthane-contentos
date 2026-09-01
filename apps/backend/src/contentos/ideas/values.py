"""Bounded validation for idea exclusions and planning dimensions.

`planning_dimensions` uses a versioned bounded schema (schema_version 1)
with an explicit dimension allowlist — never a generic unbounded JSON bag,
never vendor/provider data. `exclusions` is a bounded deduplicated ordered
list of strings.
"""

import math
from typing import Any

from contentos.ideas.errors import InvalidIdeaInputError, InvalidPlanningDimensionsError

PLANNING_DIMENSIONS_SCHEMA_VERSION = 1

MAX_EXCLUSIONS = 20
MAX_EXCLUSION_LENGTH = 300
MAX_DIMENSION_STRING_LENGTH = 200

# The accepted Konsepthane planning vocabulary (design §13.2): single bounded
# strings for scalar dimensions, bounded ordered string lists for the rest.
_STRING_DIMENSIONS = (
    "theme",
    "cake",
    "budget_band",
    "space",
    "preparation_time",
    "diy_level",
    "suitability",
)
_LIST_DIMENSIONS: dict[str, int] = {
    "color_palette": 12,
    "decorations": 30,
    "menu": 30,
    "shopping_list": 50,
    "practical_steps": 30,
}
ALLOWED_PLANNING_DIMENSIONS = frozenset(_STRING_DIMENSIONS) | frozenset(_LIST_DIMENSIONS)


def validate_exclusions(value: list[str] | None) -> list[str]:
    """Bounded, order-preserving, exact-duplicate-free exclusion list."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise InvalidIdeaInputError("exclusions must be a list of strings")
    if len(value) > MAX_EXCLUSIONS:
        raise InvalidIdeaInputError(f"exclusions exceed the limit of {MAX_EXCLUSIONS} entries")
    cleaned: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise InvalidIdeaInputError("every exclusion must be a non-empty string")
        normalized = " ".join(entry.split())
        if len(normalized) > MAX_EXCLUSION_LENGTH:
            raise InvalidIdeaInputError(
                f"an exclusion exceeds the {MAX_EXCLUSION_LENGTH}-character limit"
            )
        if normalized not in cleaned:
            cleaned.append(normalized)
    return cleaned


def validate_planning_dimensions(value: dict[str, Any] | None) -> dict[str, Any]:
    """Validate against the versioned bounded schema; returns the stored shape."""
    dimensions: dict[str, Any] = {}
    if value is not None:
        if not isinstance(value, dict):
            raise InvalidPlanningDimensionsError("planning_dimensions must be an object")
        for key, raw in value.items():
            if key not in ALLOWED_PLANNING_DIMENSIONS:
                raise InvalidPlanningDimensionsError(
                    f"unknown planning dimension {key!r}; allowed: "
                    f"{sorted(ALLOWED_PLANNING_DIMENSIONS)}"
                )
            if key in _LIST_DIMENSIONS:
                dimensions[key] = _validate_string_list(key, raw, _LIST_DIMENSIONS[key])
            else:
                dimensions[key] = _validate_string(key, raw)
    return {
        "schema_version": PLANNING_DIMENSIONS_SCHEMA_VERSION,
        "dimensions": dimensions,
    }


def _validate_string(name: str, raw: Any) -> str:
    if isinstance(raw, float) and not math.isfinite(raw):
        raise InvalidPlanningDimensionsError(f"{name} must not be NaN or Infinity")
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidPlanningDimensionsError(f"{name} must be a non-empty string")
    normalized = " ".join(raw.split())
    if len(normalized) > MAX_DIMENSION_STRING_LENGTH:
        raise InvalidPlanningDimensionsError(
            f"{name} exceeds the {MAX_DIMENSION_STRING_LENGTH}-character limit"
        )
    return normalized


def _validate_string_list(name: str, raw: Any, limit: int) -> list[str]:
    if not isinstance(raw, list):
        raise InvalidPlanningDimensionsError(f"{name} must be a list of strings")
    if len(raw) > limit:
        raise InvalidPlanningDimensionsError(f"{name} exceeds the limit of {limit} entries")
    return [_validate_string(name, entry) for entry in raw]
