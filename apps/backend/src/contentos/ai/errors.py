"""Typed transport-neutral AI-boundary errors.

Contract errors (invalid request/spec/identity) are raised BEFORE any
provider invocation and persist nothing. Expected generation outcomes
(validation failure, provider failure, timeout, cancellation) are never
raised to callers — they become durable attempt rows returned in the typed
execution result.
"""

from contentos.ai.enums import ProviderFailureKind


class AiBoundaryError(Exception):
    """Base class for AI-boundary failures."""


class InvalidGenerationRequestError(AiBoundaryError):
    """A GenerationRequest field violates the bounded domain contract."""


class InvalidSchemaSpecError(AiBoundaryError):
    """The output-schema spec is invalid or disagrees with the request."""


class InvalidProviderIdentityError(AiBoundaryError):
    """A provider declared an unusable identity (blank/oversized fields)."""


class InvalidUsageError(AiBoundaryError):
    """Provider usage metadata violates the bounded contract."""


class GenerationConflictError(AiBoundaryError):
    """Concurrent attempt persistence conflicted and could not be recovered."""


class ProviderFailureError(AiBoundaryError):
    """Provider-neutral execution failure raised by adapters.

    `error_class` must already be bounded and sanitized: no API keys, no
    URLs with secrets, no raw provider bodies, no stack traces.
    """

    def __init__(self, kind: ProviderFailureKind, error_class: str) -> None:
        super().__init__(f"provider failure: {kind.value} ({error_class})")
        self.kind = kind
        self.error_class = error_class
