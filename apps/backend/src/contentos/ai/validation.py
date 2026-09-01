"""Versioned structured-output schema binding and domain-validation hook.

Structured output ONLY: the provider payload is validated against an
explicit versioned Pydantic schema, then optionally against a caller-
supplied domain validator, before an attempt may be SUCCEEDED. Malformed or
invalid output is never coerced, never partially accepted, and never
becomes a domain artifact.

The domain validator is a plain typed callback so future engines (ideas,
search intent, briefs, evidence organization) can attach their own rules
WITHOUT contentos.ai importing any of those modules. It returns None when
the payload is domain-valid; any non-None return means the generation is a
VALIDATION_FAILED attempt (with the stable `domain_validation` class).
"""

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from contentos.ai.dto import MAX_IDENTIFIER_LENGTH, MAX_VERSION_LENGTH
from contentos.ai.errors import InvalidSchemaSpecError

# Stable persisted error-class vocabulary for validation outcomes.
SCHEMA_VALIDATION_ERROR_CLASS = "schema_validation"
DOMAIN_VALIDATION_ERROR_CLASS = "domain_validation"


@dataclass(frozen=True, slots=True)
class StructuredOutputSpec[PayloadT: BaseModel]:
    """One exact versioned output contract for one generation call."""

    schema_name: str
    schema_version: str
    model_type: type[PayloadT]
    domain_validator: Callable[[PayloadT], str | None] | None = None

    def __post_init__(self) -> None:
        for name, value, limit in (
            ("schema_name", self.schema_name, MAX_IDENTIFIER_LENGTH),
            ("schema_version", self.schema_version, MAX_VERSION_LENGTH),
        ):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise InvalidSchemaSpecError(f"{name} must be a non-blank trimmed string")
            if len(value) > limit:
                raise InvalidSchemaSpecError(f"{name} exceeds the {limit}-character limit")
        if not (isinstance(self.model_type, type) and issubclass(self.model_type, BaseModel)):
            raise InvalidSchemaSpecError("model_type must be a Pydantic BaseModel subclass")
