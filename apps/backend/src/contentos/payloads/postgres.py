"""Durable, immutable, content-addressed PostgreSQL raw-payload provider.

Implements the provider-neutral Task 10 ``RawPayloadStore`` and
``RawPayloadReader`` protocols over a single append-only BYTEA table. The
frozen reference format is ``postgres:sha256:<64 lowercase hex>``; identity is
the SHA-256 of the exact bytes and nothing else. Storage never inspects,
parses, decompresses, renders, or logs payload contents — exact bytes only.

The store flushes but never commits: callers own the transaction so a future
worker can persist a payload and its FetchSnapshot under one coordinated
boundary. Uniqueness races are absorbed with the project's SAVEPOINT pattern;
the caller's outer transaction stays usable.
"""

import hashlib
from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import CheckConstraint, LargeBinary, String, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.types import BigInteger, DateTime

from contentos.db.base import Base
from contentos.payloads.errors import (
    InvalidPayloadMetadataError,
    InvalidPayloadReferenceError,
    PayloadBackendError,
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
from contentos.payloads.store import DEFAULT_IN_MEMORY_CHUNK_BYTES

POSTGRES_PAYLOAD_REF_PREFIX = "postgres:sha256:"

# Matches the FetchPolicy default body cap; composition should pass the
# configured `settings.fetch_max_body_bytes` explicitly.
DEFAULT_MAX_PAYLOAD_BYTES = 5 * 1024 * 1024

# Stable DB-level upper bound: the settings validation range never allows a
# fetched body larger than this, independent of runtime configuration.
ABSOLUTE_MAX_PAYLOAD_BYTES = 52_428_800

DEFAULT_POSTGRES_CHUNK_BYTES = DEFAULT_IN_MEMORY_CHUNK_BYTES


class RawPayloadBlob(Base):
    """One immutable content-addressed raw payload; exact untrusted bytes."""

    __tablename__ = "raw_payload_blobs"
    __table_args__ = (
        CheckConstraint(
            "length(sha256) = 64 AND sha256 = lower(sha256)",
            name="ck_raw_payload_blobs_sha256_format",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_raw_payload_blobs_size_nonnegative"),
        CheckConstraint(
            f"size_bytes <= {ABSOLUTE_MAX_PAYLOAD_BYTES}",
            name="ck_raw_payload_blobs_size_bounded",
        ),
        CheckConstraint(
            "length(payload) = size_bytes",
            name="ck_raw_payload_blobs_size_consistency",
        ),
    )

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PostgresRawPayloadStore:
    """Session-scoped durable provider satisfying both payload protocols."""

    def __init__(
        self,
        session: Session,
        *,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        chunk_size: int = DEFAULT_POSTGRES_CHUNK_BYTES,
    ) -> None:
        self._session = session
        self._max_payload_bytes = validate_max_bytes(max_payload_bytes)
        if self._max_payload_bytes > ABSOLUTE_MAX_PAYLOAD_BYTES:
            raise InvalidPayloadMetadataError("max_payload_bytes exceeds the durable backend bound")
        self._chunk_size = validate_max_bytes(chunk_size)

    def put(
        self,
        payload: bytes,
        *,
        expected_sha256: str | None = None,
        expected_size_bytes: int | None = None,
    ) -> StoredPayload:
        """Validate, then durably store exact bytes once under their SHA-256."""
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
        if actual_size > self._max_payload_bytes:
            raise PayloadTooLargeError("payload exceeds the durable backend size bound")

        stored = StoredPayload(
            ref=reference_for_sha256(actual_hash), sha256=actual_hash, size_bytes=actual_size
        )
        existing = self._get_blob(actual_hash)
        if existing is not None:
            self._verify_existing(existing, payload)
            return stored
        try:
            with self._session.begin_nested():
                self._session.add(
                    RawPayloadBlob(sha256=actual_hash, size_bytes=actual_size, payload=payload)
                )
        except IntegrityError:
            # Concurrent identical put won the unique race; the database is
            # authoritative and the outer transaction remains usable.
            winner = self._get_blob(actual_hash)
            if winner is None:
                raise PayloadBackendError("payload backend rejected the write") from None
            self._verify_existing(winner, payload)
            return stored
        except SQLAlchemyError:
            raise PayloadBackendError("payload backend rejected the write") from None
        return stored

    def iter_bytes(
        self,
        ref: RawPayloadRef,
        *,
        max_bytes: int,
    ) -> Iterator[bytes]:
        """Yield exact stored bytes in bounded chunks under the mandatory limit."""
        if not isinstance(ref, RawPayloadRef):
            raise InvalidPayloadReferenceError("reader requires a RawPayloadRef")
        sha256 = sha256_from_reference(ref)
        limit = validate_max_bytes(max_bytes)

        blob = self._get_blob(sha256)
        if blob is None:
            raise PayloadNotFoundError("payload reference was not found")
        payload = blob.payload
        if len(payload) != blob.size_bytes:
            raise PayloadIntegrityError("stored payload metadata is inconsistent")

        yielded = 0
        for offset in range(0, len(payload), self._chunk_size):
            chunk = payload[offset : offset + self._chunk_size]
            yielded += len(chunk)
            if yielded > limit:
                raise PayloadTooLargeError("payload bytes exceeded max_bytes")
            yield chunk

    def _get_blob(self, sha256: str) -> RawPayloadBlob | None:
        try:
            return self._session.get(RawPayloadBlob, sha256)
        except SQLAlchemyError:
            raise PayloadBackendError("payload backend read failed") from None

    @staticmethod
    def _verify_existing(existing: RawPayloadBlob, payload: bytes) -> None:
        if existing.size_bytes != len(payload) or existing.payload != payload:
            raise PayloadStoreConflictError(
                "payload reference already identifies different immutable bytes"
            )


def reference_for_sha256(sha256: str) -> RawPayloadRef:
    """Build the frozen ``postgres:sha256:<hex>`` reference for a digest."""
    return RawPayloadRef(f"{POSTGRES_PAYLOAD_REF_PREFIX}{validate_sha256(sha256)}")


def sha256_from_reference(ref: RawPayloadRef) -> str:
    """Extract the digest from a PostgreSQL provider reference; typed rejection."""
    value = ref.value
    if not value.startswith(POSTGRES_PAYLOAD_REF_PREFIX):
        raise InvalidPayloadReferenceError(
            "reference does not belong to the postgres payload provider"
        )
    digest = value[len(POSTGRES_PAYLOAD_REF_PREFIX) :]
    try:
        return validate_sha256(digest)
    except InvalidPayloadMetadataError:
        raise InvalidPayloadReferenceError(
            "postgres payload reference digest is malformed"
        ) from None
