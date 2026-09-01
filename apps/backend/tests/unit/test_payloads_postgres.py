"""Durable PostgreSQL raw-payload provider tests (SQLite-backed unit level)."""

import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from contentos.db.base import Base
from contentos.discovery.service import DiscoveryService
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.fetching.snapshots import FetchSnapshot
from contentos.normalization.enums import NormalizationStatus
from contentos.normalization.pipeline import NormalizationPipeline
from contentos.payloads.errors import (
    InvalidPayloadMetadataError,
    InvalidPayloadReferenceError,
    PayloadIntegrityError,
    PayloadNotFoundError,
    PayloadStoreConflictError,
    PayloadTooLargeError,
)
from contentos.payloads.models import RawPayloadRef
from contentos.payloads.postgres import (
    ABSOLUTE_MAX_PAYLOAD_BYTES,
    DEFAULT_MAX_PAYLOAD_BYTES,
    POSTGRES_PAYLOAD_REF_PREFIX,
    PostgresRawPayloadStore,
    RawPayloadBlob,
    reference_for_sha256,
    sha256_from_reference,
)
from contentos.payloads.store import read_verified_payload
from contentos.sources.enums import DiscoveryStrategy, SourceKind, TrustTier
from contentos.sources.service import SourceRegistryService

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
HTML_BODY = (
    "<html><head><title>İstanbul Rehberi</title></head>"
    "<body><p>İstanbul'da kutlama 🎉 başladı.</p></body></html>"
).encode()


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session
    engine.dispose()


def blob_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(RawPayloadBlob)) or 0


def create_snapshot(session: Session, body: bytes, raw_payload_ref: str) -> FetchSnapshot:
    suffix = str(uuid.uuid4())
    source = SourceRegistryService(session).register_source(
        slug=f"pg-payload-{suffix}",
        name=f"PG Payload {suffix}",
        kind=SourceKind.MANUAL,
        base_url=f"https://pg-payload-{suffix}.example.test/",
        trust_tier=TrustTier.GENERAL,
        discovery_strategy=DiscoveryStrategy.MANUAL,
    )
    discoveries = DiscoveryService(session)
    item = discoveries.discover_manual(
        source.id, f"https://pg-payload-{suffix}.example.test/article"
    )
    discoveries.accept_item(item.id)
    return FetchSnapshotService(session).record_fetch_result(
        item.id,
        FetchResult(
            requested_url=item.canonical_url,
            outcome=FetchOutcome.SUCCESS,
            retry=RetryClassification.NOT_APPLICABLE,
            robots_decision=RobotsDecision.ALLOWED,
            fetched_at=NOW,
            duration_ms=2.0,
            final_url=f"https://pg-payload-{suffix}.example.test/final",
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=body,
        ),
        raw_payload_ref=raw_payload_ref,
    )


class TestContentIdentity:
    def test_put_stores_exact_bytes_under_sha256_identity(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)

        stored = store.put(HTML_BODY)

        expected_hash = hashlib.sha256(HTML_BODY).hexdigest()
        assert stored.sha256 == expected_hash
        assert stored.size_bytes == len(HTML_BODY)
        assert stored.ref.value == f"{POSTGRES_PAYLOAD_REF_PREFIX}{expected_hash}"
        row = session.get(RawPayloadBlob, expected_hash)
        assert row is not None
        assert row.payload == HTML_BODY
        assert row.size_bytes == len(HTML_BODY)

    def test_same_bytes_share_a_reference_and_row(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)

        first = store.put(HTML_BODY)
        second = store.put(HTML_BODY)

        assert second == first
        assert blob_count(session) == 1

    def test_different_bytes_get_different_references(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)

        first = store.put(b"birinci")
        second = store.put(b"ikinci")

        assert first.ref != second.ref
        assert blob_count(session) == 2

    def test_empty_bytes_follow_the_existing_contract(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)

        stored = store.put(b"")

        assert stored.size_bytes == 0
        assert stored.sha256 == hashlib.sha256(b"").hexdigest()
        assert list(store.iter_bytes(stored.ref, max_bytes=10)) == []

    def test_non_bytes_payload_is_rejected(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)

        with pytest.raises(InvalidPayloadMetadataError):
            store.put("metin")  # type: ignore[arg-type]


class TestExpectedMetadataValidation:
    def test_matching_expectations_are_accepted(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)

        stored = store.put(
            HTML_BODY,
            expected_sha256=hashlib.sha256(HTML_BODY).hexdigest(),
            expected_size_bytes=len(HTML_BODY),
        )

        assert stored.size_bytes == len(HTML_BODY)

    def test_wrong_expected_hash_is_rejected_before_persistence(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)

        with pytest.raises(PayloadIntegrityError):
            store.put(HTML_BODY, expected_sha256="0" * 64)
        assert blob_count(session) == 0

    def test_wrong_expected_size_is_rejected_before_persistence(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)

        with pytest.raises(PayloadIntegrityError):
            store.put(HTML_BODY, expected_size_bytes=1)
        assert blob_count(session) == 0

    def test_oversized_payload_is_refused(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session, max_payload_bytes=16)

        with pytest.raises(PayloadTooLargeError):
            store.put(b"x" * 17)
        assert blob_count(session) == 0

    def test_store_bound_cannot_exceed_the_absolute_backend_bound(self, session: Session) -> None:
        assert DEFAULT_MAX_PAYLOAD_BYTES <= ABSOLUTE_MAX_PAYLOAD_BYTES
        with pytest.raises(InvalidPayloadMetadataError):
            PostgresRawPayloadStore(session, max_payload_bytes=ABSOLUTE_MAX_PAYLOAD_BYTES + 1)


class TestReader:
    def test_round_trip_returns_exact_bytes_in_bounded_chunks(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session, chunk_size=7)
        stored = store.put(HTML_BODY)

        chunks = list(store.iter_bytes(stored.ref, max_bytes=len(HTML_BODY)))

        assert all(len(chunk) <= 7 for chunk in chunks)
        assert len(chunks) > 1
        assert b"".join(chunks) == HTML_BODY

    def test_read_verified_payload_round_trip(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)
        stored = store.put(HTML_BODY)

        payload = read_verified_payload(
            store,
            stored.ref,
            expected_sha256=stored.sha256,
            expected_size_bytes=stored.size_bytes,
            max_bytes=len(HTML_BODY),
        )

        assert payload == HTML_BODY

    def test_max_bytes_is_enforced(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)
        stored = store.put(HTML_BODY)

        with pytest.raises(PayloadTooLargeError):
            list(store.iter_bytes(stored.ref, max_bytes=len(HTML_BODY) - 1))

    def test_missing_reference_is_typed(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)
        missing = reference_for_sha256("a" * 64)

        with pytest.raises(PayloadNotFoundError):
            list(store.iter_bytes(missing, max_bytes=10))

    @pytest.mark.parametrize(
        "bad_reference",
        [
            f"memory:sha256:{'a' * 64}",
            f"postgres:md5:{'a' * 64}",
            "postgres:sha256:XYZ",
            f"postgres:sha256:{'A' * 64}",
            f"s3:sha256:{'a' * 64}",
            "postgres:sha256:" + "a" * 63,
        ],
    )
    def test_foreign_or_malformed_references_are_rejected(
        self, session: Session, bad_reference: str
    ) -> None:
        store = PostgresRawPayloadStore(session)

        with pytest.raises(InvalidPayloadReferenceError):
            list(store.iter_bytes(RawPayloadRef(bad_reference), max_bytes=10))

    def test_plain_ref_object_required(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)

        with pytest.raises(InvalidPayloadReferenceError):
            list(store.iter_bytes("postgres:sha256:" + "a" * 64, max_bytes=10))  # type: ignore[arg-type]

    def test_inconsistent_stored_row_is_safely_rejected(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = PostgresRawPayloadStore(session)
        stored = store.put(HTML_BODY)
        corrupted = RawPayloadBlob(
            sha256=stored.sha256, size_bytes=stored.size_bytes + 5, payload=HTML_BODY
        )
        monkeypatch.setattr(PostgresRawPayloadStore, "_get_blob", lambda _self, _sha: corrupted)

        with pytest.raises(PayloadIntegrityError):
            list(store.iter_bytes(stored.ref, max_bytes=len(HTML_BODY)))


class TestIdempotencyAndConflicts:
    def test_unique_race_returns_the_winner_and_keeps_transaction_usable(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = PostgresRawPayloadStore(session)
        winner = store.put(HTML_BODY)
        session.commit()

        real_get = PostgresRawPayloadStore._get_blob
        calls = {"count": 0}

        def racy_get(self: PostgresRawPayloadStore, sha256: str) -> RawPayloadBlob | None:
            calls["count"] += 1
            if calls["count"] == 1:
                return None
            return real_get(self, sha256)

        monkeypatch.setattr(PostgresRawPayloadStore, "_get_blob", racy_get)
        result = store.put(HTML_BODY)
        monkeypatch.undo()

        assert result == winner
        assert blob_count(session) == 1
        after_race = store.put(b"sonraki")
        assert after_race.size_bytes == len(b"sonraki")
        assert blob_count(session) == 2

    def test_conflicting_existing_bytes_raise_typed_conflict(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = PostgresRawPayloadStore(session)
        stored = store.put(HTML_BODY)
        impostor = RawPayloadBlob(
            sha256=stored.sha256, size_bytes=len(b"different"), payload=b"different"
        )
        monkeypatch.setattr(PostgresRawPayloadStore, "_get_blob", lambda _self, _sha: impostor)

        with pytest.raises(PayloadStoreConflictError):
            store.put(HTML_BODY)


class TestImmutability:
    def test_store_exposes_no_mutation_api(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)

        assert not hasattr(store, "update")
        assert not hasattr(store, "delete")
        assert not hasattr(store, "overwrite")
        assert not hasattr(store, "commit")


class TestIntegration:
    def test_body_to_store_to_fetch_snapshot_round_trip(self, session: Session) -> None:
        store = PostgresRawPayloadStore(session)
        stored = store.put(HTML_BODY)

        snapshot = create_snapshot(session, HTML_BODY, stored.ref.value)
        session.commit()

        assert snapshot.raw_payload_ref == stored.ref.value
        assert snapshot.body_sha256 == stored.sha256
        assert snapshot.body_size_bytes == stored.size_bytes
        payload = read_verified_payload(
            store,
            snapshot.raw_payload_ref,
            expected_sha256=snapshot.body_sha256,
            expected_size_bytes=snapshot.body_size_bytes,
            max_bytes=len(HTML_BODY),
        )
        assert payload == HTML_BODY

    def test_normalization_pipeline_succeeds_through_the_postgres_reader(
        self, session: Session
    ) -> None:
        store = PostgresRawPayloadStore(session)
        stored = store.put(HTML_BODY)
        snapshot = create_snapshot(session, HTML_BODY, stored.ref.value)

        pipeline = NormalizationPipeline(
            session, store, max_payload_bytes=DEFAULT_MAX_PAYLOAD_BYTES
        )
        document = pipeline.normalize_snapshot(snapshot.id)

        assert document.normalization_status is NormalizationStatus.SUCCEEDED
        assert document.clean_text is not None
        assert "İstanbul'da kutlama 🎉 başladı." in document.clean_text
        assert document.fetch_snapshot_id == snapshot.id


class TestReferenceHelpers:
    def test_reference_round_trip(self) -> None:
        digest = hashlib.sha256(b"veri").hexdigest()

        ref = reference_for_sha256(digest)

        assert ref.value == f"postgres:sha256:{digest}"
        assert sha256_from_reference(ref) == digest

    def test_reference_format_is_frozen(self) -> None:
        assert POSTGRES_PAYLOAD_REF_PREFIX == "postgres:sha256:"
