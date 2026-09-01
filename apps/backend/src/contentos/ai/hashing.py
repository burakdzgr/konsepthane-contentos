"""Deterministic canonical-JSON hashing for generation identities.

Never Python repr: stable UTF-8, sorted keys, compact separators, and
allow_nan=False so NaN/Infinity can never silently enter an identity.
Dictionary key order never matters; list order always does (order is
preserved wherever the caller supplied it, so a list must only be used
where order genuinely carries meaning).
"""

import hashlib
import json
from typing import Any

# Version of the canonical input identity. Future canonicalization changes
# must bump this so old hashes are never silently reused.
GENERATION_INPUT_SCHEMA_VERSION = 1

# Version of the canonical attempt identity (one provider invocation).
ATTEMPT_IDENTITY_SCHEMA_VERSION = 1


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_hex(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def generation_input_hash(
    *,
    input_refs: dict[str, Any],
    input_projection: dict[str, Any],
    generation_bounds: dict[str, int],
) -> str:
    """Canonical input identity: exact durable provenance + projection.

    Two generations whose visible projection is identical but whose exact
    artifact provenance (`input_refs`) differs MUST hash differently — that
    is the audit-honesty rule.
    """
    return sha256_hex(
        {
            "schema": GENERATION_INPUT_SCHEMA_VERSION,
            "input_refs": input_refs,
            "input_projection": input_projection,
            "generation_bounds": generation_bounds,
        }
    )


def attempt_identity_hash(
    *,
    purpose: str,
    input_hash: str,
    provider: str,
    model_name: str,
    model_version: str | None,
    schema_name: str,
    schema_version: str,
    template_name: str,
    template_version: str,
    retry_number: int,
) -> str:
    """NULL-safe canonical identity of ONE provider invocation.

    A genuinely unavailable model_version participates explicitly as JSON
    null (never a fabricated "unknown" string), and the hash is DB-unique,
    so nullable-column UNIQUE-tuple semantics can never permit duplicates.
    """
    return sha256_hex(
        {
            "schema": ATTEMPT_IDENTITY_SCHEMA_VERSION,
            "purpose": purpose,
            "input_hash": input_hash,
            "provider": provider,
            "model_name": model_name,
            "model_version": model_version,
            "schema_name": schema_name,
            "schema_version": schema_version,
            "template_name": template_name,
            "template_version": template_version,
            "retry_number": retry_number,
        }
    )
