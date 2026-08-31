"""Synchronous provider protocols, verified reads, and a DEV/TEST provider."""

import hashlib
from collections.abc import Iterator
from typing import Protocol

from contentos.payloads.errors import (
    InvalidPayloadMetadataError,
    InvalidPayloadReferenceError,
    PayloadBackendError,
    PayloadError,
    PayloadIntegrityError,
    PayloadNotFoundError,
    PayloadStoreConflictError,
    PayloadTooLargeError,
)
from contentos.payloads.models import (
    RawPayloadRef,
    StoredPayload,
    validate_max_bytes,
    validate_sha256,
    validate_size,
)

DEFAULT_IN_MEMORY_CHUNK_BYTES = 64 * 1024


class RawPayloadStore(Protocol):
    """Write exact bytes once and return provider-neutral provenance."""

    def put(
        self,
        payload: bytes,
        *,
        expected_sha256: str | None = None,
        expected_size_bytes: int | None = None,
    ) -> StoredPayload: ...


class RawPayloadReader(Protocol):
    """Yield opaque payload bytes under a mandatory caller-supplied bound."""

    def iter_bytes(
        self,
        ref: RawPayloadRef,
        *,
        max_bytes: int,
    ) -> Iterator[bytes]: ...


def read_verified_payload(
    reader: RawPayloadReader,
    ref: str | RawPayloadRef,
    *,
    expected_sha256: str,
    expected_size_bytes: int,
    max_bytes: int,
) -> bytes:
    """Read bounded bytes and return them only after exact provenance verification."""
    payload_ref = ref if isinstance(ref, RawPayloadRef) else RawPayloadRef(ref)
    expected_hash = validate_sha256(expected_sha256)
    expected_size = validate_size("expected_size_bytes", expected_size_bytes)
    limit = validate_max_bytes(max_bytes)
    if expected_size > limit:
        raise PayloadTooLargeError("expected payload size exceeds max_bytes")

    chunks: list[bytes] = []
    digest = hashlib.sha256()
    actual_size = 0
    try:
        stream = reader.iter_bytes(payload_ref, max_bytes=limit)
        for chunk in stream:
            if not isinstance(chunk, bytes):
                raise PayloadBackendError("payload backend yielded a non-bytes chunk")
            actual_size += len(chunk)
            if actual_size > limit:
                raise PayloadTooLargeError("payload bytes exceeded max_bytes")
            if actual_size > expected_size:
                raise PayloadIntegrityError("payload size does not match expected provenance")
            digest.update(chunk)
            chunks.append(chunk)
    except PayloadError:
        raise
    except Exception:
        raise PayloadBackendError("payload backend read failed") from None

    if actual_size != expected_size:
        raise PayloadIntegrityError("payload size does not match expected provenance")
    if digest.hexdigest() != expected_hash:
        raise PayloadIntegrityError("payload SHA-256 does not match expected provenance")
    return b"".join(chunks)


class InMemoryRawPayloadStore:
    """Process-local, non-persistent DEV/TEST provider; never a production default."""

    def __init__(self, *, chunk_size: int = DEFAULT_IN_MEMORY_CHUNK_BYTES) -> None:
        self._chunk_size = validate_max_bytes(chunk_size)
        self._payloads: dict[RawPayloadRef, bytes] = {}

    @property
    def stored_payload_count(self) -> int:
        """Expose deterministic state only for test/development assertions."""
        return len(self._payloads)

    def put(
        self,
        payload: bytes,
        *,
        expected_sha256: str | None = None,
        expected_size_bytes: int | None = None,
    ) -> StoredPayload:
        """Validate before storing exact immutable bytes under a content-derived ref."""
        if not isinstance(payload, bytes):
            raise InvalidPayloadMetadataError("payload must be exact bytes")
        actual_hash = hashlib.sha256(payload).hexdigest()
        actual_size = len(payload)
        if expected_sha256 is not None and validate_sha256(expected_sha256) != actual_hash:
            raise PayloadIntegrityError("payload SHA-256 does not match expected provenance")
        if (
            expected_size_bytes is not None
            and validate_size("expected_size_bytes", expected_size_bytes) != actual_size
        ):
            raise PayloadIntegrityError("payload size does not match expected provenance")

        ref = self._reference_for_hash(actual_hash)
        existing = self._payloads.get(ref)
        if existing is not None and existing != payload:
            raise PayloadStoreConflictError(
                "payload reference already identifies different immutable bytes"
            )
        if existing is None:
            self._payloads[ref] = payload
        return StoredPayload(ref=ref, sha256=actual_hash, size_bytes=actual_size)

    def iter_bytes(
        self,
        ref: RawPayloadRef,
        *,
        max_bytes: int,
    ) -> Iterator[bytes]:
        """Yield exact stored bytes while independently enforcing the read limit."""
        if not isinstance(ref, RawPayloadRef):
            raise InvalidPayloadReferenceError("reader requires a RawPayloadRef")
        limit = validate_max_bytes(max_bytes)
        try:
            payload = self._payloads[ref]
        except KeyError:
            raise PayloadNotFoundError("payload reference was not found") from None

        actual_size = 0
        for offset in range(0, len(payload), self._chunk_size):
            chunk = payload[offset : offset + self._chunk_size]
            actual_size += len(chunk)
            if actual_size > limit:
                raise PayloadTooLargeError("payload bytes exceeded max_bytes")
            yield chunk

    def _reference_for_hash(self, sha256: str) -> RawPayloadRef:
        return RawPayloadRef(f"memory:sha256:{sha256}")
