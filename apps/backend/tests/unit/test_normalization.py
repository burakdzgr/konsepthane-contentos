"""Contract tests for immutable NormalizedDocument recording."""

import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
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
from contentos.normalization.enums import NormalizationFailureCode, NormalizationStatus
from contentos.normalization.models import NormalizedDocument
from contentos.normalization.repository import NormalizedDocumentRepository
from contentos.normalization.service import (
    MAX_AUTHOR_NAME_LENGTH,
    MAX_CLEAN_TEXT_LENGTH,
    MAX_EXTRACTOR_NAME_LENGTH,
    MAX_EXTRACTOR_VERSION_LENGTH,
    MAX_FAILURE_DETAIL_LENGTH,
    MAX_JSON_DEPTH,
    MAX_JSON_ITEMS,
    MAX_LANGUAGE_LENGTH,
    MAX_TITLE_LENGTH,
    NORMALIZED_CONTENT_FINGERPRINT_VERSION,
    FetchSnapshotNotEligibleError,
    FetchSnapshotNotFoundError,
    InvalidNormalizationInputError,
    NormalizationConflictError,
    NormalizationPersistenceError,
    NormalizationService,
)
from contentos.sources.enums import DiscoveryStrategy, SourceKind, TrustTier
from contentos.sources.service import SourceRegistryService

NOW = datetime(2026, 9, 1, 9, 30, tzinfo=UTC)


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session
    engine.dispose()


def make_item(session: Session, suffix: str = "story") -> uuid.UUID:
    source = SourceRegistryService(session).register_source(
        slug=f"source-{suffix}",
        name=f"Source {suffix}",
        kind=SourceKind.MANUAL,
        base_url=f"https://{suffix}.example.test/",
        trust_tier=TrustTier.GENERAL,
        discovery_strategy=DiscoveryStrategy.MANUAL,
    )
    discovery = DiscoveryService(session)
    item = discovery.discover_manual(source.id, f"https://{suffix}.example.test/story")
    discovery.accept_item(item.id)
    return item.id


def successful_snapshot(session: Session, suffix: str = "story") -> FetchSnapshot:
    item_id = make_item(session, suffix)
    result = FetchResult(
        requested_url=f"https://{suffix}.example.test/story",
        outcome=FetchOutcome.SUCCESS,
        retry=RetryClassification.NOT_APPLICABLE,
        robots_decision=RobotsDecision.ALLOWED,
        fetched_at=NOW,
        duration_ms=2.5,
        final_url=f"https://{suffix}.example.test/story",
        status_code=200,
        content_type="text/html",
        body=f"payload-{suffix}".encode(),
    )
    return FetchSnapshotService(session).record_fetch_result(
        item_id,
        result,
        raw_payload_ref=f"object://payload/{suffix}",
    )


def failed_snapshot(session: Session) -> FetchSnapshot:
    item_id = make_item(session, "failed-fetch")
    result = FetchResult(
        requested_url="https://example.test/failed-fetch",
        outcome=FetchOutcome.TIMEOUT,
        retry=RetryClassification.RETRYABLE,
        robots_decision=RobotsDecision.ALLOWED,
        fetched_at=NOW,
        duration_ms=100.0,
        failure_detail="read_timeout",
    )
    return FetchSnapshotService(session).record_fetch_result(item_id, result)


def success_args() -> dict[str, object]:
    return {
        "extractor_name": "article-extractor",
        "extractor_version": "1.0.0",
        "parser_version": "html-parser-3",
        "clean_text": "İstanbul'da Özgün İçerik!",
        "title": "Özgün başlık",
        "language": "tr",
        "author_name": "Yazar",
        "external_published_at": NOW,
        "headings": [{"level": 1, "text": "Başlık"}],
        "sections": [{"heading": "Başlık", "text": "Bölüm"}],
        "links": [{"url": "https://example.test/reference", "text": "Kaynak"}],
        "structured_metadata": {"schema": {"type": "Article"}},
    }


class TestModelAndRepositoryContract:
    def test_model_has_exact_durable_shape_without_raw_or_mutable_fields(self) -> None:
        assert set(NormalizedDocument.__table__.columns.keys()) == {
            "id",
            "fetch_snapshot_id",
            "extractor_name",
            "extractor_version",
            "parser_version",
            "normalization_status",
            "failure_code",
            "failure_detail",
            "title",
            "clean_text",
            "language",
            "author_name",
            "external_published_at",
            "headings",
            "sections",
            "links",
            "structured_metadata",
            "content_fingerprint",
            "fingerprint_version",
            "normalized_at",
            "created_at",
        }
        assert "updated_at" not in NormalizedDocument.__table__.columns
        assert "raw_body" not in NormalizedDocument.__table__.columns

    def test_persisted_enum_values_are_frozen(self) -> None:
        assert [status.value for status in NormalizationStatus] == ["succeeded", "failed"]
        assert [code.value for code in NormalizationFailureCode] == [
            "unsupported_content",
            "decode_error",
            "parse_error",
            "empty_content",
            "extractor_error",
            "policy_rejected",
        ]

    def test_fk_is_restrict_and_identity_is_unique(self) -> None:
        foreign_key = next(iter(NormalizedDocument.__table__.foreign_keys))
        assert foreign_key.target_fullname == "fetch_snapshots.id"
        assert foreign_key.ondelete == "RESTRICT"
        assert any(
            constraint.name == "uq_normalized_documents_snapshot_extractor"
            for constraint in NormalizedDocument.__table__.constraints
        )

    def test_repository_is_append_and_read_only(self, session: Session) -> None:
        repository = NormalizedDocumentRepository(session)
        assert callable(repository.add)
        assert callable(repository.get_by_id)
        assert callable(repository.get_by_snapshot_and_extractor)
        assert callable(repository.list_for_snapshot)
        assert not hasattr(repository, "update")
        assert not hasattr(repository, "delete")


class TestSuccessfulRecording:
    def test_success_persists_content_structure_and_provenance(self, session: Session) -> None:
        snapshot = successful_snapshot(session)
        args = success_args()

        document = NormalizationService(session).record_success(snapshot.id, **args)

        assert document.fetch_snapshot_id == snapshot.id
        assert document.extractor_name == "article-extractor"
        assert document.extractor_version == "1.0.0"
        assert document.parser_version == "html-parser-3"
        assert document.normalization_status is NormalizationStatus.SUCCEEDED
        assert document.failure_code is None
        assert document.failure_detail is None
        assert document.title == "Özgün başlık"
        assert document.clean_text == args["clean_text"]
        assert document.language == "tr"
        assert document.author_name == "Yazar"
        assert document.external_published_at == NOW
        assert document.headings == args["headings"]
        assert document.sections == args["sections"]
        assert document.links == args["links"]
        assert document.structured_metadata == args["structured_metadata"]
        assert document.created_at is not None

    def test_fingerprint_is_exact_utf8_sha256_without_hidden_transformation(
        self, session: Session
    ) -> None:
        first = successful_snapshot(session, "turkish")
        second = successful_snapshot(session, "lowercase")
        service = NormalizationService(session)
        exact_text = "İSTANBUL, Iğdır ve Şişli!"

        exact = service.record_success(
            first.id,
            extractor_name="text",
            extractor_version="v1",
            clean_text=exact_text,
        )
        changed = service.record_success(
            second.id,
            extractor_name="text",
            extractor_version="v1",
            clean_text=exact_text.lower(),
        )

        assert exact.content_fingerprint == hashlib.sha256(exact_text.encode("utf-8")).hexdigest()
        assert exact.fingerprint_version == NORMALIZED_CONTENT_FINGERPRINT_VERSION == 1
        assert exact.content_fingerprint != changed.content_fingerprint

    def test_caller_owned_json_is_copied(self, session: Session) -> None:
        snapshot = successful_snapshot(session)
        headings = [{"level": 1, "text": "Original"}]
        document = NormalizationService(session).record_success(
            snapshot.id,
            extractor_name="text",
            extractor_version="v1",
            clean_text="Text",
            headings=headings,
        )
        headings[0]["text"] = "Mutated"

        assert document.headings == [{"level": 1, "text": "Original"}]


class TestFailureAndEligibility:
    def test_failure_records_classification_without_fake_content(self, session: Session) -> None:
        snapshot = successful_snapshot(session)

        document = NormalizationService(session).record_failure(
            snapshot.id,
            extractor_name="article-extractor",
            extractor_version="1.0.0",
            failure_code=NormalizationFailureCode.PARSE_ERROR,
            failure_detail="  invalid   markup  ",
        )

        assert document.normalization_status is NormalizationStatus.FAILED
        assert document.failure_code is NormalizationFailureCode.PARSE_ERROR
        assert document.failure_detail == "invalid markup"
        assert document.clean_text is None
        assert document.title is None
        assert document.content_fingerprint is None
        assert document.fingerprint_version is None
        assert document.headings == []
        assert document.structured_metadata == {}

    def test_missing_snapshot_has_typed_error(self, session: Session) -> None:
        with pytest.raises(FetchSnapshotNotFoundError):
            NormalizationService(session).record_success(
                uuid.uuid4(),
                extractor_name="text",
                extractor_version="v1",
                clean_text="Text",
            )

    def test_failed_fetch_is_ineligible_for_success_or_failure_normalization(
        self, session: Session
    ) -> None:
        snapshot = failed_snapshot(session)
        service = NormalizationService(session)

        with pytest.raises(FetchSnapshotNotEligibleError):
            service.record_success(
                snapshot.id,
                extractor_name="text",
                extractor_version="v1",
                clean_text="Text",
            )
        with pytest.raises(FetchSnapshotNotEligibleError):
            service.record_failure(
                snapshot.id,
                extractor_name="text",
                extractor_version="v1",
                failure_code=NormalizationFailureCode.PARSE_ERROR,
            )

    @pytest.mark.parametrize("missing_field", ["raw_payload_ref", "body_sha256", "body_size_bytes"])
    def test_incomplete_payload_provenance_is_ineligible(
        self, session: Session, missing_field: str
    ) -> None:
        snapshot = successful_snapshot(session)
        setattr(snapshot, missing_field, None)
        session.flush()

        with pytest.raises(FetchSnapshotNotEligibleError):
            NormalizationService(session).record_success(
                snapshot.id,
                extractor_name="text",
                extractor_version="v1",
                clean_text="Text",
            )

    def test_failure_code_must_be_stable_enum(self, session: Session) -> None:
        snapshot = successful_snapshot(session)

        with pytest.raises(InvalidNormalizationInputError):
            NormalizationService(session).record_failure(
                snapshot.id,
                extractor_name="text",
                extractor_version="v1",
                failure_code="traceback: ValueError",  # type: ignore[arg-type]
            )


class TestIdempotencyAndVersioning:
    def test_identical_success_and_failure_retries_return_existing_rows(
        self, session: Session
    ) -> None:
        success_snapshot = successful_snapshot(session, "success-retry")
        failure_snapshot = successful_snapshot(session, "failure-retry")
        service = NormalizationService(session)

        success = service.record_success(success_snapshot.id, **success_args())
        success_retry = service.record_success(success_snapshot.id, **success_args())
        failure = service.record_failure(
            failure_snapshot.id,
            extractor_name="article-extractor",
            extractor_version="1.0.0",
            failure_code=NormalizationFailureCode.EMPTY_CONTENT,
            failure_detail="empty body",
        )
        failure_retry = service.record_failure(
            failure_snapshot.id,
            extractor_name="article-extractor",
            extractor_version="1.0.0",
            failure_code=NormalizationFailureCode.EMPTY_CONTENT,
            failure_detail="empty body",
        )

        assert success_retry is success
        assert failure_retry is failure

    def test_same_identity_with_different_result_is_typed_conflict(self, session: Session) -> None:
        snapshot = successful_snapshot(session)
        service = NormalizationService(session)
        service.record_success(
            snapshot.id,
            extractor_name="text",
            extractor_version="v1",
            clean_text="First",
        )

        with pytest.raises(NormalizationConflictError):
            service.record_success(
                snapshot.id,
                extractor_name="text",
                extractor_version="v1",
                clean_text="Changed",
            )

    def test_versions_and_extractors_coexist_in_deterministic_order(self, session: Session) -> None:
        snapshot = successful_snapshot(session)
        service = NormalizationService(session)
        first = service.record_success(
            snapshot.id,
            extractor_name="article",
            extractor_version="v1",
            clean_text="First",
        )
        second = service.record_success(
            snapshot.id,
            extractor_name="article",
            extractor_version="v2",
            clean_text="Second",
        )
        third = service.record_success(
            snapshot.id,
            extractor_name="metadata",
            extractor_version="v1",
            clean_text="Third",
        )
        first.normalized_at = NOW
        second.normalized_at = NOW + timedelta(seconds=1)
        third.normalized_at = NOW + timedelta(seconds=2)
        session.flush()

        assert NormalizedDocumentRepository(session).list_for_snapshot(snapshot.id) == [
            first,
            second,
            third,
        ]

    def test_uniqueness_race_returns_identical_winner(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        snapshot = successful_snapshot(session)
        initial_service = NormalizationService(session)
        winner = initial_service.record_success(
            snapshot.id,
            extractor_name="text",
            extractor_version="v1",
            clean_text="Same",
        )
        service = NormalizationService(session)
        lookups = iter([None, winner])
        monkeypatch.setattr(
            service._documents,
            "get_by_snapshot_and_extractor",
            lambda *_args: next(lookups),
        )

        def lose_race(_document: NormalizedDocument) -> NormalizedDocument:
            raise IntegrityError("insert", {}, Exception("unique"))

        monkeypatch.setattr(service._documents, "add", lose_race)

        assert (
            service.record_success(
                snapshot.id,
                extractor_name="text",
                extractor_version="v1",
                clean_text="Same",
            )
            is winner
        )

    def test_unresolved_database_failure_is_mapped(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        snapshot = successful_snapshot(session)
        service = NormalizationService(session)
        monkeypatch.setattr(
            service._documents,
            "get_by_snapshot_and_extractor",
            lambda *_args: None,
        )

        def fail_add(_document: NormalizedDocument) -> NormalizedDocument:
            raise IntegrityError("insert", {}, Exception("database"))

        monkeypatch.setattr(service._documents, "add", fail_add)
        with pytest.raises(NormalizationPersistenceError):
            service.record_success(
                snapshot.id,
                extractor_name="text",
                extractor_version="v1",
                clean_text="Text",
            )


class TestInputLimits:
    @pytest.mark.parametrize(
        ("field", "limit"),
        [
            ("extractor_name", MAX_EXTRACTOR_NAME_LENGTH),
            ("extractor_version", MAX_EXTRACTOR_VERSION_LENGTH),
            ("title", MAX_TITLE_LENGTH),
            ("language", MAX_LANGUAGE_LENGTH),
            ("author_name", MAX_AUTHOR_NAME_LENGTH),
        ],
    )
    def test_scalar_limits(self, session: Session, field: str, limit: int) -> None:
        snapshot = successful_snapshot(session)
        args: dict[str, object] = {
            "extractor_name": "text",
            "extractor_version": "v1",
            "clean_text": "Text",
            field: "x" * (limit + 1),
        }

        with pytest.raises(InvalidNormalizationInputError):
            NormalizationService(session).record_success(snapshot.id, **args)

    def test_clean_text_and_failure_detail_limits(self, session: Session) -> None:
        snapshot = successful_snapshot(session)
        service = NormalizationService(session)
        with pytest.raises(InvalidNormalizationInputError):
            service.record_success(
                snapshot.id,
                extractor_name="text",
                extractor_version="v1",
                clean_text="x" * (MAX_CLEAN_TEXT_LENGTH + 1),
            )
        with pytest.raises(InvalidNormalizationInputError):
            service.record_failure(
                snapshot.id,
                extractor_name="text",
                extractor_version="v1",
                failure_code=NormalizationFailureCode.PARSE_ERROR,
                failure_detail="x" * (MAX_FAILURE_DETAIL_LENGTH + 1),
            )

    def test_empty_success_and_naive_timestamp_are_rejected(self, session: Session) -> None:
        snapshot = successful_snapshot(session)
        service = NormalizationService(session)
        with pytest.raises(InvalidNormalizationInputError):
            service.record_success(
                snapshot.id,
                extractor_name="text",
                extractor_version="v1",
                clean_text="   ",
            )
        with pytest.raises(InvalidNormalizationInputError):
            service.record_success(
                snapshot.id,
                extractor_name="text",
                extractor_version="v1",
                clean_text="Text",
                external_published_at=datetime(2026, 9, 1),
            )

    def test_json_depth_count_shape_and_values_are_bounded(self, session: Session) -> None:
        snapshot = successful_snapshot(session)
        service = NormalizationService(session)
        too_deep: dict[str, object] = {}
        cursor = too_deep
        for _ in range(MAX_JSON_DEPTH):
            child: dict[str, object] = {}
            cursor["child"] = child
            cursor = child

        invalid_values = [
            {"headings": {"not": "a list"}},
            {"headings": ["not an object"]},
            {"structured_metadata": too_deep},
            {"structured_metadata": {str(i): i for i in range(MAX_JSON_ITEMS + 1)}},
            {"structured_metadata": {"score": float("inf")}},
            {"structured_metadata": {"value": object()}},
        ]
        for invalid in invalid_values:
            with pytest.raises(InvalidNormalizationInputError):
                service.record_success(
                    snapshot.id,
                    extractor_name="text",
                    extractor_version="v1",
                    clean_text="Text",
                    **invalid,
                )


def test_database_check_rejects_contradictory_failed_row(session: Session) -> None:
    snapshot = successful_snapshot(session)
    session.add(
        NormalizedDocument(
            fetch_snapshot_id=snapshot.id,
            extractor_name="invalid",
            extractor_version="v1",
            normalization_status=NormalizationStatus.FAILED,
            failure_code=NormalizationFailureCode.PARSE_ERROR,
            clean_text="pretend success",
            headings=[],
            sections=[],
            links=[],
            structured_metadata={},
            normalized_at=NOW,
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()
