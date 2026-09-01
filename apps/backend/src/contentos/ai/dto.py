"""Provider-neutral typed DTOs crossing the generation boundary.

Nothing here may ever hold SQLAlchemy objects, sessions, HTTP/SDK response
objects, secret headers, or provider exception objects.
"""

import math
from dataclasses import dataclass, field
from typing import Any

from contentos.ai.enums import GenerationPurpose
from contentos.ai.errors import (
    InvalidGenerationRequestError,
    InvalidProviderIdentityError,
    InvalidUsageError,
)

AiIdentifierError = InvalidGenerationRequestError | InvalidProviderIdentityError

MAX_IDENTIFIER_LENGTH = 100
MAX_MODEL_NAME_LENGTH = 200
MAX_VERSION_LENGTH = 50
MAX_FINISH_REASON_LENGTH = 100
MAX_GENERATION_BOUND_KEYS = 20
MAX_CURRENCY_LENGTH = 3
MAX_INSTRUCTIONS_LENGTH = 20_000

# Bounds for input_refs (immutable provenance metadata: ids/versions only).
MAX_REF_KEYS = 50
MAX_REF_DEPTH = 3
MAX_REF_LIST_ITEMS = 100
MAX_REF_STRING_LENGTH = 200

# Bounds for the in-memory input projection (never persisted in full).
MAX_PROJECTION_KEYS = 100
MAX_PROJECTION_DEPTH = 5
MAX_PROJECTION_LIST_ITEMS = 200
MAX_PROJECTION_STRING_LENGTH = 5000


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    """Stable recorded provider identity.

    `model_version` is None when a stable version identity is genuinely
    unavailable — never a fabricated placeholder.
    """

    provider: str
    model_name: str
    model_version: str | None

    def __post_init__(self) -> None:
        _require_identifier(
            "provider", self.provider, MAX_IDENTIFIER_LENGTH, InvalidProviderIdentityError
        )
        _require_identifier(
            "model_name", self.model_name, MAX_MODEL_NAME_LENGTH, InvalidProviderIdentityError
        )
        if self.model_version is not None:
            _require_identifier(
                "model_version",
                self.model_version,
                MAX_VERSION_LENGTH,
                InvalidProviderIdentityError,
            )


@dataclass(frozen=True, slots=True)
class GenerationUsage:
    """Bounded provider-neutral usage metadata.

    Only genuinely supplied fields are set; nothing is fabricated. Cost is
    an optional future Cost/Budget hook: amount and currency must appear
    together and are recorded, never invented.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: float | None = None
    cost_amount: float | None = None
    cost_currency: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
            ("total_tokens", self.total_tokens),
        ):
            if value is not None and (not isinstance(value, int) or value < 0):
                raise InvalidUsageError(f"{name} must be a non-negative integer")
        if self.latency_ms is not None:
            if not isinstance(self.latency_ms, int | float) or isinstance(self.latency_ms, bool):
                raise InvalidUsageError("latency_ms must be a number")
            if not math.isfinite(self.latency_ms) or self.latency_ms < 0:
                raise InvalidUsageError("latency_ms must be finite and non-negative")
        if (self.cost_amount is None) != (self.cost_currency is None):
            raise InvalidUsageError("cost amount and currency must appear together")
        if self.cost_amount is not None:
            if not isinstance(self.cost_amount, int | float) or isinstance(self.cost_amount, bool):
                raise InvalidUsageError("cost_amount must be a number")
            if not math.isfinite(self.cost_amount) or self.cost_amount < 0:
                raise InvalidUsageError("cost_amount must be finite and non-negative")
        if self.cost_currency is not None and (
            len(self.cost_currency) != MAX_CURRENCY_LENGTH or not self.cost_currency.isupper()
        ):
            raise InvalidUsageError("cost_currency must be a three-letter uppercase code")

    def to_persisted(self) -> dict[str, Any]:
        """Only the genuinely present fields; absent stays absent."""
        persisted: dict[str, Any] = {}
        for name in (
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "latency_ms",
            "cost_amount",
            "cost_currency",
        ):
            value = getattr(self, name)
            if value is not None:
                persisted[name] = value
        return persisted


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    """One provider-neutral structured-generation request.

    `input_projection` is the bounded in-memory input handed to the
    provider; it is NEVER persisted in full. The attempt row persists only
    `input_refs` (exact durable artifact provenance) plus the deterministic
    canonical input hash, so results stay reconstructable from durable
    referenced inputs.

    `instructions` is the rendered versioned template text handed to the
    provider in memory only: it is never persisted (the attempt stores
    template name+version instead) and never part of the input hash —
    substantive instruction changes REQUIRE a template version bump, which
    changes the attempt identity.
    """

    purpose: GenerationPurpose
    schema_name: str
    schema_version: str
    template_name: str
    template_version: str
    input_refs: dict[str, Any] = field(default_factory=dict)
    input_projection: dict[str, Any] = field(default_factory=dict)
    generation_bounds: dict[str, int] = field(default_factory=dict)
    retry_number: int = 0
    instructions: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.purpose, GenerationPurpose):
            raise InvalidGenerationRequestError("purpose must be a GenerationPurpose value")
        _require_identifier("schema_name", self.schema_name, MAX_IDENTIFIER_LENGTH)
        _require_identifier("schema_version", self.schema_version, MAX_VERSION_LENGTH)
        _require_identifier("template_name", self.template_name, MAX_IDENTIFIER_LENGTH)
        _require_identifier("template_version", self.template_version, MAX_VERSION_LENGTH)
        if not isinstance(self.retry_number, int) or isinstance(self.retry_number, bool):
            raise InvalidGenerationRequestError("retry_number must be an integer")
        if self.retry_number < 0:
            raise InvalidGenerationRequestError("retry_number must be zero or positive")
        _validate_bounded_json(
            "input_refs",
            self.input_refs,
            max_keys=MAX_REF_KEYS,
            max_depth=MAX_REF_DEPTH,
            max_list_items=MAX_REF_LIST_ITEMS,
            max_string_length=MAX_REF_STRING_LENGTH,
        )
        _validate_bounded_json(
            "input_projection",
            self.input_projection,
            max_keys=MAX_PROJECTION_KEYS,
            max_depth=MAX_PROJECTION_DEPTH,
            max_list_items=MAX_PROJECTION_LIST_ITEMS,
            max_string_length=MAX_PROJECTION_STRING_LENGTH,
        )
        if not isinstance(self.generation_bounds, dict):
            raise InvalidGenerationRequestError("generation_bounds must be an object")
        if len(self.generation_bounds) > MAX_GENERATION_BOUND_KEYS:
            raise InvalidGenerationRequestError("generation_bounds has too many keys")
        for key, value in self.generation_bounds.items():
            if not isinstance(key, str) or not key.strip():
                raise InvalidGenerationRequestError("generation_bounds keys must be non-empty")
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise InvalidGenerationRequestError(
                    "generation_bounds values must be positive integers"
                )
        if not isinstance(self.instructions, str):
            raise InvalidGenerationRequestError("instructions must be a string")
        if len(self.instructions) > MAX_INSTRUCTIONS_LENGTH:
            raise InvalidGenerationRequestError(
                f"instructions exceed the {MAX_INSTRUCTIONS_LENGTH}-character limit"
            )


@dataclass(frozen=True, slots=True)
class ProviderOutputSchema:
    """Provider-neutral output-schema descriptor crossing the boundary.

    Carries only neutral data (name, version, a plain JSON Schema object,
    strictness) so adapters can request provider-side strict structured
    output as defense layer 1 — the service's own Pydantic validation
    remains defense layer 2 and always runs.
    """

    name: str
    version: str
    json_schema: dict[str, Any]
    strict: bool = True

    def __post_init__(self) -> None:
        _require_identifier("schema name", self.name, MAX_IDENTIFIER_LENGTH)
        _require_identifier("schema version", self.version, MAX_VERSION_LENGTH)
        if not isinstance(self.json_schema, dict) or not self.json_schema:
            raise InvalidGenerationRequestError("json_schema must be a non-empty object")


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Provider output crossing the boundary: JSON-compatible payload only.

    No SDK response object, no raw HTTP response, no secret headers, no
    provider request/exception objects.
    """

    payload: dict[str, Any]
    provider: str
    model_name: str
    model_version: str | None
    finish_reason: str | None = None
    usage: GenerationUsage | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.payload, dict):
            raise InvalidGenerationRequestError("provider payload must be a JSON object")
        if self.finish_reason is not None and (
            not self.finish_reason.strip() or len(self.finish_reason) > MAX_FINISH_REASON_LENGTH
        ):
            raise InvalidGenerationRequestError("finish_reason must be non-empty and bounded")


def _require_identifier(
    name: str,
    value: str,
    limit: int,
    error: type[AiIdentifierError] = InvalidGenerationRequestError,
) -> None:
    """Conservative identifier validation: no blank, no surrounding
    whitespace, bounded length. Never trims meaningfully different
    identities into one."""
    if not isinstance(value, str) or not value.strip():
        raise error(f"{name} must not be blank")
    if value != value.strip():
        raise error(f"{name} must not carry surrounding whitespace")
    if len(value) > limit:
        raise error(f"{name} exceeds the {limit}-character limit")


def _validate_bounded_json(
    name: str,
    value: Any,
    *,
    max_keys: int,
    max_depth: int,
    max_list_items: int,
    max_string_length: int,
    _depth: int = 1,
) -> None:
    if _depth > max_depth:
        raise InvalidGenerationRequestError(f"{name} exceeds the nesting-depth limit")
    if isinstance(value, dict):
        if len(value) > max_keys:
            raise InvalidGenerationRequestError(f"{name} has too many keys")
        for key, entry in value.items():
            if not isinstance(key, str) or not key.strip():
                raise InvalidGenerationRequestError(f"{name} keys must be non-empty strings")
            _validate_bounded_json(
                name,
                entry,
                max_keys=max_keys,
                max_depth=max_depth,
                max_list_items=max_list_items,
                max_string_length=max_string_length,
                _depth=_depth + 1,
            )
        return
    if isinstance(value, list):
        if len(value) > max_list_items:
            raise InvalidGenerationRequestError(f"{name} has too many list items")
        for entry in value:
            _validate_bounded_json(
                name,
                entry,
                max_keys=max_keys,
                max_depth=max_depth,
                max_list_items=max_list_items,
                max_string_length=max_string_length,
                _depth=_depth + 1,
            )
        return
    if isinstance(value, str):
        if len(value) > max_string_length:
            raise InvalidGenerationRequestError(f"{name} contains an oversized string")
        return
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidGenerationRequestError(f"{name} must not contain NaN or Infinity")
        return
    raise InvalidGenerationRequestError(f"{name} contains an unsupported value type")
