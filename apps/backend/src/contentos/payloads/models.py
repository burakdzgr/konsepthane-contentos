"""Immutable value objects for opaque payload identity and byte provenance."""

import re
from dataclasses import dataclass

from contentos.payloads.errors import (
    InvalidPayloadMetadataError,
    InvalidPayloadReferenceError,
)

MAX_RAW_PAYLOAD_REF_LENGTH = 2_000
SHA256_HEX_LENGTH = 64

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RawPayloadRef:
    """Opaque provider-owned identifier; never interpreted as a URL or path."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise InvalidPayloadReferenceError("payload reference must be text")
        if not self.value or not self.value.strip():
            raise InvalidPayloadReferenceError("payload reference must not be empty")
        if self.value != self.value.strip():
            raise InvalidPayloadReferenceError(
                "payload reference must not contain surrounding whitespace"
            )
        if len(self.value) > MAX_RAW_PAYLOAD_REF_LENGTH:
            raise InvalidPayloadReferenceError("payload reference exceeds the length limit")
        if any(character.isspace() or ord(character) < 32 for character in self.value):
            raise InvalidPayloadReferenceError(
                "payload reference must not contain whitespace or control characters"
            )
        if _contains_embedded_credentials(self.value):
            raise InvalidPayloadReferenceError(
                "payload reference must not contain embedded credentials"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class StoredPayload:
    """Provider-neutral immutable result of storing exact bytes."""

    ref: RawPayloadRef
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.ref, RawPayloadRef):
            raise InvalidPayloadReferenceError("stored payload ref must be a RawPayloadRef")
        validate_sha256(self.sha256)
        validate_size("size_bytes", self.size_bytes)


def validate_sha256(value: str) -> str:
    """Return a validated lowercase SHA-256 hex digest."""
    if not isinstance(value, str) or _SHA256_HEX.fullmatch(value) is None:
        raise InvalidPayloadMetadataError(
            "payload SHA-256 must be 64 lowercase hexadecimal characters"
        )
    return value


def validate_size(name: str, value: int) -> int:
    """Return a non-negative integer size, excluding bool values."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidPayloadMetadataError(f"{name} must be a non-negative integer")
    return value


def validate_max_bytes(value: int) -> int:
    """Return a strictly positive mandatory retrieval bound."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidPayloadMetadataError("max_bytes must be a positive integer")
    return value


def _contains_embedded_credentials(value: str) -> bool:
    marker = value.find("://")
    if marker < 0:
        return False
    authority = value[marker + 3 :]
    for separator in ("/", "?", "#"):
        authority = authority.split(separator, 1)[0]
    return "@" in authority
