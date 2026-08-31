"""Contract tests for provider-neutral immutable raw-payload storage and reads."""

import hashlib
import urllib.request
from collections.abc import Iterator
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from contentos.core.config import Settings
from contentos.payloads.errors import (
    InvalidPayloadMetadataError,
    InvalidPayloadReferenceError,
    PayloadBackendError,
    PayloadIntegrityError,
    PayloadNotFoundError,
    PayloadStoreConflictError,
    PayloadTooLargeError,
)
from contentos.payloads.models import MAX_RAW_PAYLOAD_REF_LENGTH, RawPayloadRef, StoredPayload
from contentos.payloads.store import (
    InMemoryRawPayloadStore,
    RawPayloadReader,
    RawPayloadStore,
    read_verified_payload,
)


class ChunkReader:
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks
        self.seen_refs: list[RawPayloadRef] = []
        self.seen_limits: list[int] = []

    def iter_bytes(self, ref: RawPayloadRef, *, max_bytes: int) -> Iterator[bytes]:
        self.seen_refs.append(ref)
        self.seen_limits.append(max_bytes)
        yield from self.chunks


class ExplodingReader:
    def iter_bytes(self, ref: RawPayloadRef, *, max_bytes: int) -> Iterator[bytes]:
        del ref, max_bytes
        yield b"partial"
        raise OSError("implementation-specific disk detail")


class CollidingInMemoryStore(InMemoryRawPayloadStore):
    def _reference_for_hash(self, sha256: str) -> RawPayloadRef:
        del sha256
        return RawPayloadRef("memory:forced-collision")


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class TestOpaqueReference:
    @pytest.mark.parametrize("value", ["", " ", "\t", " leading", "trailing "])
    def test_empty_or_whitespace_reference_is_rejected(self, value: str) -> None:
        with pytest.raises(InvalidPayloadReferenceError):
            RawPayloadRef(value)

    def test_oversized_and_control_character_references_are_rejected(self) -> None:
        with pytest.raises(InvalidPayloadReferenceError):
            RawPayloadRef("x" * (MAX_RAW_PAYLOAD_REF_LENGTH + 1))
        with pytest.raises(InvalidPayloadReferenceError):
            RawPayloadRef("opaque\nreference")

    @pytest.mark.parametrize(
        "value",
        [
            "https://user:secret@example.test/object",
            "vendor://token@example.test/key",
        ],
    )
    def test_obvious_embedded_credentials_are_rejected(self, value: str) -> None:
        with pytest.raises(InvalidPayloadReferenceError):
            RawPayloadRef(value)

    @pytest.mark.parametrize(
        "value",
        [
            "opaque-reference",
            "provider-specific:key@identifier",
            "https://example.test/object",
            "memory:sha256:abc",
        ],
    )
    def test_generic_contract_requires_no_vendor_prefix(self, value: str) -> None:
        assert str(RawPayloadRef(value)) == value

    def test_reference_is_frozen(self) -> None:
        ref = RawPayloadRef("opaque-reference")
        with pytest.raises(FrozenInstanceError):
            ref.value = "changed"  # type: ignore[misc]


class TestStoredPayload:
    def test_result_contains_only_opaque_ref_hash_and_size(self) -> None:
        payload = b"exact bytes"
        result = StoredPayload(
            ref=RawPayloadRef("provider:opaque"),
            sha256=sha256(payload),
            size_bytes=len(payload),
        )

        assert {field.name for field in fields(result)} == {"ref", "sha256", "size_bytes"}
        assert result.sha256 == sha256(payload)
        assert result.size_bytes == len(payload)
        with pytest.raises(FrozenInstanceError):
            result.size_bytes = 0  # type: ignore[misc]

    @pytest.mark.parametrize(
        ("digest", "size"),
        [("A" * 64, 0), ("not-a-hash", 0), ("0" * 64, -1), ("0" * 64, True)],
    )
    def test_invalid_hash_or_size_is_rejected(self, digest: str, size: int) -> None:
        with pytest.raises(InvalidPayloadMetadataError):
            StoredPayload(RawPayloadRef("opaque"), digest, size)


class TestInMemoryWrites:
    def test_protocols_are_satisfied_without_a_production_registration(self) -> None:
        provider = InMemoryRawPayloadStore()
        writer: RawPayloadStore = provider
        reader: RawPayloadReader = provider

        assert writer is provider
        assert reader is provider
        assert "DEV/TEST" in (provider.__class__.__doc__ or "")

    def test_put_computes_exact_byte_hash_size_and_content_address(self) -> None:
        payload = b"\x00binary\xffpayload"

        stored = InMemoryRawPayloadStore().put(payload)

        assert stored.sha256 == sha256(payload)
        assert stored.size_bytes == len(payload)
        assert stored.ref == RawPayloadRef(f"memory:sha256:{sha256(payload)}")

    def test_empty_payload_remains_a_valid_exact_object(self) -> None:
        provider = InMemoryRawPayloadStore()
        stored = provider.put(b"")

        assert stored.sha256 == sha256(b"")
        assert stored.size_bytes == 0
        assert (
            read_verified_payload(
                provider,
                stored.ref,
                expected_sha256=stored.sha256,
                expected_size_bytes=0,
                max_bytes=1,
            )
            == b""
        )

    def test_matching_expected_hash_and_size_succeed(self) -> None:
        payload = "İstanbul".encode()

        stored = InMemoryRawPayloadStore().put(
            payload,
            expected_sha256=sha256(payload),
            expected_size_bytes=len(payload),
        )

        assert stored.sha256 == sha256(payload)
        assert stored.size_bytes == len(payload)

    @pytest.mark.parametrize("mismatch", ["hash", "size"])
    def test_write_mismatch_fails_before_storing(self, mismatch: str) -> None:
        provider = InMemoryRawPayloadStore()
        payload = b"immutable"
        kwargs: dict[str, object] = {
            "expected_sha256": sha256(payload),
            "expected_size_bytes": len(payload),
        }
        if mismatch == "hash":
            kwargs["expected_sha256"] = sha256(b"different")
        else:
            kwargs["expected_size_bytes"] = len(payload) + 1

        with pytest.raises(PayloadIntegrityError):
            provider.put(payload, **kwargs)

        assert provider.stored_payload_count == 0

    def test_identical_duplicate_is_idempotent(self) -> None:
        provider = InMemoryRawPayloadStore()

        first = provider.put(b"same")
        second = provider.put(b"same")

        assert second == first
        assert provider.stored_payload_count == 1

    def test_conflicting_bytes_cannot_overwrite_the_same_reference(self) -> None:
        provider = CollidingInMemoryStore()
        first = provider.put(b"first")

        with pytest.raises(PayloadStoreConflictError):
            provider.put(b"second")

        assert provider.stored_payload_count == 1
        assert list(provider.iter_bytes(first.ref, max_bytes=100)) == [b"first"]

    def test_provider_has_no_update_delete_or_unbounded_read_api(self) -> None:
        provider = InMemoryRawPayloadStore()

        assert not hasattr(provider, "update")
        assert not hasattr(provider, "delete")
        assert not hasattr(provider, "read_all")


class TestBoundedReads:
    def test_valid_reference_yields_exact_configured_chunks(self) -> None:
        provider = InMemoryRawPayloadStore(chunk_size=2)
        stored = provider.put(b"abcdef")

        assert list(provider.iter_bytes(stored.ref, max_bytes=6)) == [b"ab", b"cd", b"ef"]

    def test_missing_reference_is_typed(self) -> None:
        with pytest.raises(PayloadNotFoundError):
            list(
                InMemoryRawPayloadStore().iter_bytes(RawPayloadRef("memory:missing"), max_bytes=100)
            )

    def test_provider_enforces_limit_from_actual_bytes(self) -> None:
        provider = InMemoryRawPayloadStore(chunk_size=2)
        stored = provider.put(b"abcdef")

        with pytest.raises(PayloadTooLargeError):
            list(provider.iter_bytes(stored.ref, max_bytes=5))

    @pytest.mark.parametrize("invalid_limit", [0, -1, True])
    def test_unbounded_or_invalid_limit_is_impossible(self, invalid_limit: int) -> None:
        provider = InMemoryRawPayloadStore()
        stored = provider.put(b"payload")

        with pytest.raises(InvalidPayloadMetadataError):
            list(provider.iter_bytes(stored.ref, max_bytes=invalid_limit))

    def test_existing_fetch_limit_can_be_used_without_a_second_setting(self) -> None:
        payload = b"bounded"
        provider = InMemoryRawPayloadStore()
        stored = provider.put(payload)

        result = read_verified_payload(
            provider,
            stored.ref,
            expected_sha256=stored.sha256,
            expected_size_bytes=stored.size_bytes,
            max_bytes=Settings().fetch_max_body_bytes,
        )

        assert result == payload


class TestVerifiedRead:
    @pytest.mark.parametrize(
        "chunks",
        [(b"exact payload",), (b"e", b"x", b"a", b"c", b"t", b" ", b"payload")],
    )
    def test_exact_hash_and_size_pass_for_large_or_tiny_chunks(
        self, chunks: tuple[bytes, ...]
    ) -> None:
        payload = b"".join(chunks)
        reader = ChunkReader(*chunks)

        result = read_verified_payload(
            reader,
            "any-provider:opaque",
            expected_sha256=sha256(payload),
            expected_size_bytes=len(payload),
            max_bytes=len(payload),
        )

        assert result == payload
        assert reader.seen_refs == [RawPayloadRef("any-provider:opaque")]
        assert reader.seen_limits == [len(payload)]

    def test_one_huge_chunk_cannot_bypass_limit(self) -> None:
        with pytest.raises(PayloadTooLargeError):
            read_verified_payload(
                ChunkReader(b"123456"),
                "opaque",
                expected_sha256=sha256(b"12345"),
                expected_size_bytes=5,
                max_bytes=5,
            )

    def test_many_tiny_chunks_cannot_bypass_limit(self) -> None:
        with pytest.raises(PayloadTooLargeError):
            read_verified_payload(
                ChunkReader(*(b"x" for _ in range(6))),
                "opaque",
                expected_sha256=sha256(b"xxxxx"),
                expected_size_bytes=5,
                max_bytes=5,
            )

    def test_hash_mismatch_fails_without_returning_bytes(self) -> None:
        payload = b"same-size"
        with pytest.raises(PayloadIntegrityError, match="SHA-256"):
            read_verified_payload(
                ChunkReader(payload),
                "opaque",
                expected_sha256=sha256(b"different"),
                expected_size_bytes=len(payload),
                max_bytes=100,
            )

    @pytest.mark.parametrize(
        ("actual", "expected"),
        [(b"abc", b"abcd"), (b"abcde", b"abcd")],
    )
    def test_truncated_or_extra_bytes_fail_size_verification(
        self, actual: bytes, expected: bytes
    ) -> None:
        with pytest.raises(PayloadIntegrityError, match="size"):
            read_verified_payload(
                ChunkReader(actual),
                "opaque",
                expected_sha256=sha256(expected),
                expected_size_bytes=len(expected),
                max_bytes=100,
            )

    @pytest.mark.parametrize("payload", ["Türkçe Iİıi".encode(), b"\x00\xff\x10\x80"])
    def test_text_and_binary_payloads_remain_byte_exact(self, payload: bytes) -> None:
        provider = InMemoryRawPayloadStore(chunk_size=1)
        stored = provider.put(payload)

        assert (
            read_verified_payload(
                provider,
                stored.ref,
                expected_sha256=stored.sha256,
                expected_size_bytes=stored.size_bytes,
                max_bytes=max(1, stored.size_bytes),
            )
            == payload
        )

    def test_expected_size_above_limit_fails_before_provider_read(self) -> None:
        reader = ChunkReader(b"not read")

        with pytest.raises(PayloadTooLargeError):
            read_verified_payload(
                reader,
                "opaque",
                expected_sha256=sha256(b"not read"),
                expected_size_bytes=8,
                max_bytes=7,
            )

        assert reader.seen_refs == []

    def test_backend_exception_is_mapped_without_raw_detail(self) -> None:
        with pytest.raises(PayloadBackendError) as captured:
            read_verified_payload(
                ExplodingReader(),
                "opaque",
                expected_sha256=sha256(b"partial"),
                expected_size_bytes=7,
                max_bytes=100,
            )

        assert "disk detail" not in str(captured.value)
        assert captured.value.__cause__ is None

    def test_non_bytes_backend_chunk_is_mapped_to_stable_error(self) -> None:
        reader = ChunkReader(b"valid")
        reader.chunks = ("not bytes",)  # type: ignore[assignment]

        with pytest.raises(PayloadBackendError):
            read_verified_payload(
                reader,
                "opaque",
                expected_sha256=sha256(b"valid"),
                expected_size_bytes=5,
                max_bytes=100,
            )


def test_opaque_reference_never_triggers_network_or_filesystem_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("generic payload code attempted external access")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    payload = b"provider supplied bytes"

    assert (
        read_verified_payload(
            ChunkReader(payload),
            "https://example.test/not-fetched",
            expected_sha256=sha256(payload),
            expected_size_bytes=len(payload),
            max_bytes=100,
        )
        == payload
    )
