"""Per-type validation of provider-neutral signal values (v1 schemas).

Each signal type has a small strict allowlist schema: values are bounded
JSON objects, never raw API responses, never SERP HTML, never secret request
metadata, and never provider-specific fields. A metric without an explicit
unit/basis is rejected rather than stored as an ambiguous naked number;
unknown metadata stays absent instead of being invented.

The returned dict is the canonical cleaned value used for persistence and
for the observation-identity hash.
"""

import math
from typing import Any

from contentos.signals.enums import SearchSignalType
from contentos.signals.errors import UnsupportedSignalValueError

MAX_SHORT_TEXT = 50
MAX_LABEL_TEXT = 200
MAX_BASIS_TEXT = 200
MAX_NOTE_TEXT = 2000
MAX_SERP_NOTE_TEXT = 1000
MAX_QUERY_SET_ENTRIES = 50
MAX_QUERY_TEXT = 200
MAX_SERP_FEATURES = 25


def validate_signal_value(signal_type: SearchSignalType, value: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical bounded value for one signal type; reject the rest."""
    if not isinstance(value, dict):
        raise UnsupportedSignalValueError("signal value must be a JSON object")
    if signal_type is SearchSignalType.SEARCH_VOLUME:
        return _search_volume(value)
    if signal_type is SearchSignalType.TREND:
        return _trend(value)
    if signal_type is SearchSignalType.SERP_OBSERVATION:
        return _serp_observation(value)
    if signal_type is SearchSignalType.QUERY_SET:
        return _query_set(value)
    if signal_type is SearchSignalType.MANUAL_INTENT_NOTE:
        return _manual_intent_note(value)
    raise UnsupportedSignalValueError(  # pragma: no cover - enum is closed
        f"unsupported signal type '{signal_type}'"
    )


def _search_volume(value: dict[str, Any]) -> dict[str, Any]:
    """A volume observation must never be an unexplained naked number."""
    _allow_keys(value, {"value", "unit", "basis", "period"})
    volume = _finite_number(value.get("value"), "value")
    if volume < 0:
        raise UnsupportedSignalValueError("search volume must not be negative")
    canonical: dict[str, Any] = {
        "value": volume,
        "unit": _required_text(value.get("unit"), "unit", MAX_SHORT_TEXT),
        "basis": _required_text(value.get("basis"), "basis", MAX_BASIS_TEXT),
    }
    period = _optional_text(value.get("period"), "period", MAX_SHORT_TEXT)
    if period is not None:
        canonical["period"] = period
    return canonical


def _trend(value: dict[str, Any]) -> dict[str, Any]:
    """A trend observation must make its scale and basis explicit."""
    _allow_keys(value, {"observation", "scale", "basis", "period"})
    observation = value.get("observation")
    if isinstance(observation, bool) or observation is None:
        raise UnsupportedSignalValueError("trend observation must be a number or text")
    if isinstance(observation, (int, float)):
        observation = _finite_number(observation, "observation")
    elif isinstance(observation, str):
        observation = _required_text(observation, "observation", MAX_LABEL_TEXT)
    else:
        raise UnsupportedSignalValueError("trend observation must be a number or text")
    canonical: dict[str, Any] = {
        "observation": observation,
        "scale": _required_text(value.get("scale"), "scale", MAX_LABEL_TEXT),
        "basis": _required_text(value.get("basis"), "basis", MAX_BASIS_TEXT),
    }
    period = _optional_text(value.get("period"), "period", MAX_SHORT_TEXT)
    if period is not None:
        canonical["period"] = period
    return canonical


def _serp_observation(value: dict[str, Any]) -> dict[str, Any]:
    """Bounded manually-observed SERP facts; never raw pages or scraping."""
    _allow_keys(value, {"features", "notes", "intent_pattern", "ranking_notes"})
    canonical: dict[str, Any] = {}
    features = value.get("features")
    if features is not None:
        if not isinstance(features, list) or not features:
            raise UnsupportedSignalValueError("features must be a non-empty list")
        if len(features) > MAX_SERP_FEATURES:
            raise UnsupportedSignalValueError("too many SERP features")
        canonical["features"] = [
            _required_text(feature, "feature", MAX_LABEL_TEXT) for feature in features
        ]
    notes = _optional_text(value.get("notes"), "notes", MAX_SERP_NOTE_TEXT)
    if notes is not None:
        canonical["notes"] = notes
    intent_pattern = _optional_text(value.get("intent_pattern"), "intent_pattern", MAX_LABEL_TEXT)
    if intent_pattern is not None:
        canonical["intent_pattern"] = intent_pattern
    ranking_notes = _optional_text(value.get("ranking_notes"), "ranking_notes", MAX_SERP_NOTE_TEXT)
    if ranking_notes is not None:
        canonical["ranking_notes"] = ranking_notes
    if not canonical:
        raise UnsupportedSignalValueError("a SERP observation needs at least one observed field")
    return canonical


def _query_set(value: dict[str, Any]) -> dict[str, Any]:
    """Operator-collected related queries; order is semantically meaningful.

    Blank entries are dropped, duplicates are removed deterministically
    keeping the FIRST occurrence, and the operator-supplied order is
    preserved (the identity hash is therefore order-sensitive on purpose).
    """
    _allow_keys(value, {"queries"})
    queries = value.get("queries")
    if not isinstance(queries, list):
        raise UnsupportedSignalValueError("queries must be a list")
    cleaned: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if not isinstance(query, str):
            raise UnsupportedSignalValueError("each query must be a string")
        stripped = " ".join(query.split())
        if not stripped:
            continue
        if len(stripped) > MAX_QUERY_TEXT:
            raise UnsupportedSignalValueError("a query exceeds the length limit")
        if stripped in seen:
            continue
        seen.add(stripped)
        cleaned.append(stripped)
    if not cleaned:
        raise UnsupportedSignalValueError("query set has no usable queries")
    if len(cleaned) > MAX_QUERY_SET_ENTRIES:
        raise UnsupportedSignalValueError("query set exceeds the entry limit")
    return {"queries": cleaned}


def _manual_intent_note(value: dict[str, Any]) -> dict[str, Any]:
    """Bounded operator research note — never factual evidence."""
    _allow_keys(value, {"note"})
    return {"note": _required_text(value.get("note"), "note", MAX_NOTE_TEXT)}


def _allow_keys(value: dict[str, Any], allowed: set[str]) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise UnsupportedSignalValueError(f"unsupported value keys: {', '.join(sorted(unknown))}")


def _finite_number(candidate: Any, name: str) -> float:
    if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
        raise UnsupportedSignalValueError(f"{name} must be a number")
    number = float(candidate)
    if not math.isfinite(number):
        raise UnsupportedSignalValueError(f"{name} must be finite")
    return number


def _required_text(candidate: Any, name: str, limit: int) -> str:
    if not isinstance(candidate, str) or not candidate.strip():
        raise UnsupportedSignalValueError(f"{name} must be non-empty text")
    cleaned = " ".join(candidate.split())
    if len(cleaned) > limit:
        raise UnsupportedSignalValueError(f"{name} exceeds the {limit}-character limit")
    return cleaned


def _optional_text(candidate: Any, name: str, limit: int) -> str | None:
    if candidate is None:
        return None
    return _required_text(candidate, name, limit)
