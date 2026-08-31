"""Contract tests for immutable FetchSnapshot recording."""

import hashlib
import uuid
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from contentos.db.base import Base
from contentos.discovery.enums import (
    DiscoveryLifecycleState,
    DiscoveryRejectionReason,
)
from contentos.discovery.models import DiscoveryItem
from contentos.discovery.service import DiscoveryService, InvalidDiscoveryTransitionError
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_repository import FetchSnapshotRepository
from contentos.fetching.snapshot_service import (
    FetchSnapshotItemNotEligibleError,
    FetchSnapshotItemNotFoundError,
    FetchSnapshotPersistenceError,
    FetchSnapshotService,
    InvalidFetchSnapshotInputError,
    MissingRawPayloadReferenceError,
)
from contentos.fetching.snapshots import FetchSnapshot
from contentos.sources.enums import DiscoveryStrategy, SourceKind, TrustTier
from contentos.sources.service import SourceRegistryService

FETCHED_AT = datetime(2026, 8, 31, 13, 45, tzinfo=UTC)
PAYLOAD_REF = "object://immutable/content/sha256/example"


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session
    engine.dispose()


def make_item(
    session: Session,
    *,
    url: str = "https://articles.example.test/story",
    accepted: bool = True,
) -> DiscoveryItem:
    source = SourceRegistryService(session).register_source(
        slug="manual-research",
        name="Manual research",
        kind=SourceKind.MANUAL,
        base_url="https://articles.example.test/",
        trust_tier=TrustTier.GENERAL,
        discovery_strategy=DiscoveryStrategy.MANUAL,
    )
    service = DiscoveryService(session)
    item = service.discover_manual(source.id, url)
    if accepted:
        service.accept_item(item.id)
    return item


def successful_result(body: bytes = b"exact raw payload") -> FetchResult:
    return FetchResult(
        requested_url="https://articles.example.test/story?utm_source=discovery",
        outcome=FetchOutcome.SUCCESS,
        retry=RetryClassification.NOT_APPLICABLE,
        robots_decision=RobotsDecision.ALLOWED,
        fetched_at=FETCHED_AT,
        duration_ms=18.25,
        final_url="https://articles.example.test/story",
        status_code=200,
        content_type="text/html",
        body=body,
        headers={
            "Content-Type": "text/html; charset=utf-8",
            "etag": '"safe-etag"',
            "set-cookie": "must-not-persist=secret",
            "authorization": "must-not-persist",
        },
        redirect_chain=(
            "https://articles.example.test/story?utm_source=discovery",
            "https://articles.example.test/story",
        ),
    )


def failed_result(
    outcome: FetchOutcome = FetchOutcome.TIMEOUT,
    *,
    retry: RetryClassification = RetryClassification.RETRYABLE,
    robots: RobotsDecision = RobotsDecision.ALLOWED,
    failure_detail: str = "read_timeout",
    status_code: int | None = None,
    retry_after_seconds: float | None = 30.0,
) -> FetchResult:
    return FetchResult(
        requested_url="https://articles.example.test/story",
        outcome=outcome,
        retry=retry,
        robots_decision=robots,
        fetched_at=FETCHED_AT,
        duration_ms=5.5,
        final_url="https://articles.example.test/story",
        status_code=status_code,
        content_type="text/html" if status_code is not None else None,
        headers={"cache-control": "no-cache", "set-cookie": "never"},
        redirect_chain=("https://articles.example.test/story",),
        failure_detail=failure_detail,
        retry_after_seconds=retry_after_seconds,
    )


def snapshot_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(FetchSnapshot)) or 0


class TestModelAndRepositoryContract:
    def test_model_has_exact_immutable_payload_metadata_shape(self) -> None:
        columns = set(FetchSnapshot.__table__.columns.keys())

        assert columns == {
            "id",
            "discovery_item_id",
            "requested_url",
            "final_url",
            "status_code",
            "content_type",
            "fetched_at",
            "body_sha256",
            "body_size_bytes",
            "raw_payload_ref",
            "selected_headers",
            "duration_ms",
            "redirect_chain",
            "fetch_outcome",
            "retry_classification",
            "failure_detail",
            "robots_decision",
            "retry_after_seconds",
            "created_at",
        }
        assert "updated_at" not in columns
        assert "raw_body" not in columns

    def test_repository_exposes_append_and_read_only(self, session: Session) -> None:
        repository = FetchSnapshotRepository(session)

        assert callable(repository.add)
        assert callable(repository.get_by_id)
        assert callable(repository.list_for_discovery_item)
        assert not hasattr(repository, "update")
        assert not hasattr(repository, "delete")

    def test_repository_lists_attempts_in_deterministic_chronological_order(
        self, session: Session
    ) -> None:
        item = make_item(session)
        repository = FetchSnapshotRepository(session)
        later = FetchSnapshot(
            discovery_item_id=item.id,
            requested_url=item.canonical_url,
            fetched_at=FETCHED_AT + timedelta(minutes=1),
            selected_headers={},
            duration_ms=1.0,
            redirect_chain=[],
            fetch_outcome=FetchOutcome.TIMEOUT,
            retry_classification=RetryClassification.RETRYABLE,
            robots_decision=RobotsDecision.ALLOWED,
        )
        earlier = FetchSnapshot(
            discovery_item_id=item.id,
            requested_url=item.canonical_url,
            fetched_at=FETCHED_AT,
            selected_headers={},
            duration_ms=1.0,
            redirect_chain=[],
            fetch_outcome=FetchOutcome.NETWORK_ERROR,
            retry_classification=RetryClassification.RETRYABLE,
            robots_decision=RobotsDecision.ALLOWED,
        )
        repository.add(later)
        repository.add(earlier)

        assert repository.list_for_discovery_item(item.id) == [earlier, later]
        assert repository.get_by_id(earlier.id) is earlier


class TestSuccessfulRecording:
    def test_success_persists_exact_result_metadata_and_marks_item_fetched(
        self, session: Session
    ) -> None:
        item = make_item(session)
        result = successful_result()

        snapshot = FetchSnapshotService(session).record_fetch_result(
            item.id, result, raw_payload_ref=PAYLOAD_REF
        )

        assert snapshot.discovery_item_id == item.id
        assert snapshot.requested_url == result.requested_url
        assert snapshot.final_url == result.final_url
        assert snapshot.status_code == 200
        assert snapshot.content_type == "text/html"
        assert snapshot.fetched_at == FETCHED_AT
        assert snapshot.body_sha256 == hashlib.sha256(result.body or b"").hexdigest()
        assert snapshot.body_size_bytes == len(result.body or b"")
        assert snapshot.raw_payload_ref == PAYLOAD_REF
        assert snapshot.selected_headers == {
            "content-type": "text/html; charset=utf-8",
            "etag": '"safe-etag"',
        }
        assert snapshot.duration_ms == 18.25
        assert snapshot.redirect_chain == list(result.redirect_chain)
        assert snapshot.fetch_outcome is FetchOutcome.SUCCESS
        assert snapshot.retry_classification is RetryClassification.NOT_APPLICABLE
        assert snapshot.robots_decision is RobotsDecision.ALLOWED
        assert snapshot.retry_after_seconds is None
        assert snapshot.failure_detail is None
        assert snapshot.created_at is not None
        assert item.lifecycle_state is DiscoveryLifecycleState.FETCHED

    def test_body_hash_is_exact_and_different_bytes_have_different_hashes(
        self, session: Session
    ) -> None:
        first_item = make_item(session, url="https://articles.example.test/first")
        second_item = make_item(session, url="https://articles.example.test/second")
        service = FetchSnapshotService(session)

        first = service.record_fetch_result(
            first_item.id,
            successful_result(b"payload-a\x00"),
            raw_payload_ref="blob://payload-a",
        )
        second = service.record_fetch_result(
            second_item.id,
            successful_result(b"payload-b\x00"),
            raw_payload_ref="blob://payload-b",
        )

        assert first.body_sha256 == hashlib.sha256(b"payload-a\x00").hexdigest()
        assert second.body_sha256 == hashlib.sha256(b"payload-b\x00").hexdigest()
        assert first.body_sha256 != second.body_sha256

    def test_empty_success_body_is_hashed_and_requires_retrievable_payload(
        self, session: Session
    ) -> None:
        item = make_item(session)

        snapshot = FetchSnapshotService(session).record_fetch_result(
            item.id,
            successful_result(b""),
            raw_payload_ref="content://empty-payload",
        )

        assert snapshot.body_sha256 == hashlib.sha256(b"").hexdigest()
        assert snapshot.body_size_bytes == 0
        assert snapshot.raw_payload_ref == "content://empty-payload"


class TestPayloadBoundary:
    @pytest.mark.parametrize("raw_payload_ref", [None, "", "   "])
    def test_body_without_reference_is_rejected_before_any_write(
        self, session: Session, raw_payload_ref: str | None
    ) -> None:
        item = make_item(session)

        with pytest.raises(MissingRawPayloadReferenceError):
            FetchSnapshotService(session).record_fetch_result(
                item.id,
                successful_result(),
                raw_payload_ref=raw_payload_ref,
            )

        assert snapshot_count(session) == 0
        assert item.lifecycle_state is DiscoveryLifecycleState.ACCEPTED

    def test_success_without_body_is_invalid_and_preserves_state(self, session: Session) -> None:
        item = make_item(session)
        result = successful_result()
        result = FetchResult(
            requested_url=result.requested_url,
            outcome=result.outcome,
            retry=result.retry,
            robots_decision=result.robots_decision,
            fetched_at=result.fetched_at,
            duration_ms=result.duration_ms,
        )

        with pytest.raises(InvalidFetchSnapshotInputError):
            FetchSnapshotService(session).record_fetch_result(item.id, result)

        assert snapshot_count(session) == 0
        assert item.lifecycle_state is DiscoveryLifecycleState.ACCEPTED

    def test_reference_without_body_is_rejected(self, session: Session) -> None:
        item = make_item(session)

        with pytest.raises(InvalidFetchSnapshotInputError):
            FetchSnapshotService(session).record_fetch_result(
                item.id,
                failed_result(),
                raw_payload_ref="object://fabricated-reference",
            )

        assert snapshot_count(session) == 0
        assert item.lifecycle_state is DiscoveryLifecycleState.ACCEPTED


class TestFailuresAndRetries:
    def test_failed_attempt_is_persisted_without_fabricated_payload(self, session: Session) -> None:
        item = make_item(session)
        result = failed_result()

        snapshot = FetchSnapshotService(session).record_fetch_result(item.id, result)

        assert snapshot.fetch_outcome is FetchOutcome.TIMEOUT
        assert snapshot.retry_classification is RetryClassification.RETRYABLE
        assert snapshot.failure_detail == "read_timeout"
        assert snapshot.body_sha256 is None
        assert snapshot.body_size_bytes is None
        assert snapshot.raw_payload_ref is None
        assert snapshot.selected_headers == {"cache-control": "no-cache"}
        assert snapshot.retry_after_seconds == 30.0
        assert item.lifecycle_state is DiscoveryLifecycleState.FETCH_FAILED

    def test_explicit_requeue_then_success_retains_both_attempts(self, session: Session) -> None:
        item = make_item(session)
        snapshots = FetchSnapshotService(session)
        first = snapshots.record_fetch_result(item.id, failed_result())
        DiscoveryService(session).requeue_fetch(item.id, reason="operator retry")

        second = snapshots.record_fetch_result(
            item.id,
            replace(
                successful_result(b"recovered"),
                fetched_at=FETCHED_AT + timedelta(minutes=1),
            ),
            raw_payload_ref="object://recovered",
        )
        history = FetchSnapshotRepository(session).list_for_discovery_item(item.id)

        assert history == [first, second]
        assert [attempt.fetch_outcome for attempt in history] == [
            FetchOutcome.TIMEOUT,
            FetchOutcome.SUCCESS,
        ]
        assert item.lifecycle_state is DiscoveryLifecycleState.FETCHED

    @pytest.mark.parametrize(
        ("outcome", "retry", "robots", "detail", "status_code"),
        [
            (
                FetchOutcome.TIMEOUT,
                RetryClassification.RETRYABLE,
                RobotsDecision.ALLOWED,
                "read_timeout",
                None,
            ),
            (
                FetchOutcome.HTTP_ERROR,
                RetryClassification.RETRYABLE,
                RobotsDecision.ALLOWED,
                "http_status",
                503,
            ),
            (
                FetchOutcome.ROBOTS_DISALLOWED,
                RetryClassification.TERMINAL,
                RobotsDecision.DISALLOWED,
                "robots_policy",
                None,
            ),
            (
                FetchOutcome.SSRF_BLOCKED,
                RetryClassification.TERMINAL,
                RobotsDecision.NOT_EVALUATED,
                "unsafe_address",
                None,
            ),
            (
                FetchOutcome.NETWORK_ERROR,
                RetryClassification.RETRYABLE,
                RobotsDecision.ALLOWED,
                "transport_error",
                None,
            ),
            (
                FetchOutcome.DISALLOWED_MIME,
                RetryClassification.TERMINAL,
                RobotsDecision.ALLOWED,
                "content_type",
                None,
            ),
            (
                FetchOutcome.TOO_LARGE,
                RetryClassification.TERMINAL,
                RobotsDecision.ALLOWED,
                "streamed",
                None,
            ),
        ],
    )
    def test_failure_classifications_are_preserved_exactly(
        self,
        session: Session,
        outcome: FetchOutcome,
        retry: RetryClassification,
        robots: RobotsDecision,
        detail: str,
        status_code: int | None,
    ) -> None:
        item = make_item(session)

        snapshot = FetchSnapshotService(session).record_fetch_result(
            item.id,
            failed_result(
                outcome,
                retry=retry,
                robots=robots,
                failure_detail=detail,
                status_code=status_code,
            ),
        )

        assert snapshot.fetch_outcome is outcome
        assert snapshot.retry_classification is retry
        assert snapshot.robots_decision is robots
        assert snapshot.failure_detail == detail
        assert snapshot.status_code == status_code


class TestLifecycleAndErrors:
    def test_missing_item_is_typed_and_writes_nothing(self, session: Session) -> None:
        with pytest.raises(FetchSnapshotItemNotFoundError):
            FetchSnapshotService(session).record_fetch_result(
                uuid.uuid4(), successful_result(), raw_payload_ref=PAYLOAD_REF
            )

        assert snapshot_count(session) == 0

    @pytest.mark.parametrize(
        "state",
        [
            DiscoveryLifecycleState.DISCOVERED,
            DiscoveryLifecycleState.REJECTED,
            DiscoveryLifecycleState.FETCHED,
            DiscoveryLifecycleState.FETCH_FAILED,
        ],
    )
    def test_only_accepted_items_can_record_attempts(
        self, session: Session, state: DiscoveryLifecycleState
    ) -> None:
        service = DiscoveryService(session)
        item = make_item(session, accepted=False)
        if state is DiscoveryLifecycleState.REJECTED:
            service.reject_item(item.id, DiscoveryRejectionReason.OUT_OF_SCOPE)
        elif state is DiscoveryLifecycleState.FETCHED:
            service.accept_item(item.id)
            service.mark_fetched(item.id)
        elif state is DiscoveryLifecycleState.FETCH_FAILED:
            service.accept_item(item.id)
            service.mark_fetch_failed(item.id)

        with pytest.raises(FetchSnapshotItemNotEligibleError):
            FetchSnapshotService(session).record_fetch_result(
                item.id, successful_result(), raw_payload_ref=PAYLOAD_REF
            )

        assert snapshot_count(session) == 0
        assert item.lifecycle_state is state

    def test_sqlalchemy_failure_is_not_the_service_contract(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        item = make_item(session)
        service = FetchSnapshotService(session)

        def fail_add(_snapshot: FetchSnapshot) -> FetchSnapshot:
            raise IntegrityError("insert", {}, Exception("database detail"))

        monkeypatch.setattr(service._snapshots, "add", fail_add)

        with pytest.raises(FetchSnapshotPersistenceError):
            service.record_fetch_result(item.id, successful_result(), raw_payload_ref=PAYLOAD_REF)

        assert item.lifecycle_state is DiscoveryLifecycleState.ACCEPTED

    def test_transition_failure_rolls_back_appended_snapshot_savepoint(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        item = make_item(session)
        service = FetchSnapshotService(session)

        def fail_transition(_item_id: uuid.UUID) -> DiscoveryItem:
            raise InvalidDiscoveryTransitionError("simulated concurrent transition")

        monkeypatch.setattr(service._discovery, "mark_fetched", fail_transition)

        with pytest.raises(FetchSnapshotItemNotEligibleError):
            service.record_fetch_result(item.id, successful_result(), raw_payload_ref=PAYLOAD_REF)

        assert snapshot_count(session) == 0
        session.refresh(item)
        assert item.lifecycle_state is DiscoveryLifecycleState.ACCEPTED
