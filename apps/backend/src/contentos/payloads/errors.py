"""Stable errors exposed by every raw-payload provider."""


class PayloadError(Exception):
    """Base class for provider-neutral raw-payload failures."""


class InvalidPayloadReferenceError(PayloadError):
    """An opaque payload reference violates the generic safety contract."""


class InvalidPayloadMetadataError(PayloadError):
    """Expected hash, size, limit, or payload input is invalid."""


class PayloadNotFoundError(PayloadError):
    """The provider has no immutable object for the supplied reference."""


class PayloadTooLargeError(PayloadError):
    """Actual bytes exceeded the caller's mandatory retrieval bound."""


class PayloadIntegrityError(PayloadError):
    """Actual bytes do not match their expected SHA-256 or size provenance."""


class PayloadStoreConflictError(PayloadError):
    """A reference already identifies different immutable bytes."""


class PayloadBackendError(PayloadError):
    """A provider failed without exposing its implementation-specific error."""
