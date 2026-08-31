"""Immutable ResearchEvidence persistence and exact provenance tests."""

import hashlib
import inspect
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from contentos.db.base import Base
from contentos.discovery.models import DiscoveryItem
from contentos.discovery.service import DiscoveryService
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.snapshot_service import FetchSnapshotService
from contentos.fetching.snapshots import FetchSnapshot
from contentos.normalization.enums import NormalizationFailureCode
from contentos.normalization.models import NormalizedDocument
from contentos.normalization.service import NormalizationService
from contentos.research.enums import EvidenceType, ExtractionMethod, VerificationStatus
from contentos.research.models import ResearchEvidence
from contentos.research.repository import ResearchEvidenceRepository
from contentos.research.service import (
    DEFAULT_EXTRACTOR_NAME,
    DEFAULT_EXTRACTOR_VERSION,
    ResearchEvidenceService,
)
from contentos.research.validation import (
    EVIDENCE_KEY_VERSION,
    MAX_EXCERPT_LENGTH,
    MAX_LICENSING_NOTES_LENGTH,
    MAX_METADATA_DEPTH,
    MAX_METADATA_ITEMS,
    MAX_STATEMENT_LENGTH,
    RESEARCH_EVIDENCE_OFFSET_VERSION,
    ExcerptMismatchError,
    InvalidEvidenceInputError,
    InvalidExcerptBoundsError,
    ResearchDocumentNotEligibleError,
    ResearchDocumentNotFoundError,
    ResearchEvidenceConflictError,
    ResearchEvidencePersistenceError,
    ResearchProvenanceMissingError,
    compute_evidence_key,
    evidence_key_payload,
)
from contentos.sources.enums import DiscoveryStrategy, SourceKind, TrustTier
from contentos.sources.models import Source
from contentos.sources.service import SourceRegistryService

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
DEFAULT_EXCERPT = "İstanbul'da kutlama 🎉"


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session
    engine.dispose()


def create_document(
    session: Session,
    suffix: str = "main",
    *,
    clean_text: str = "İstanbul'da kutlama 🎉\nTarih: 31 Ağustos 2026.",
    failed: bool = False,
) -> tuple[Source, DiscoveryItem, FetchSnapshot, NormalizedDocument]:
    source = SourceRegistryService(session).register_source(
        slug=f"research-{suffix}",
        name=f"Research {suffix}",
        kind=SourceKind.MANUAL,
        base_url=f"https://source-{suffix}.example.test/",
        trust_tier=TrustTier.GENERAL,
        discovery_strategy=DiscoveryStrategy.MANUAL,
        terms_notes="Rights status has not been independently verified.",
    )
    discoveries = DiscoveryService(session)
    item = discoveries.discover_manual(source.id, f"https://source-{suffix}.example.test/article")
    discoveries.accept_item(item.id)
    body = clean_text.encode()
    snapshot = FetchSnapshotService(session).record_fetch_result(
        item.id,
        FetchResult(
            requested_url=item.canonical_url,
            outcome=FetchOutcome.SUCCESS,
            retry=RetryClassification.NOT_APPLICABLE,
            robots_decision=RobotsDecision.ALLOWED,
            fetched_at=NOW,
            duration_ms=2.0,
            final_url=f"https://source-{suffix}.example.test/final",
            status_code=200,
            content_type="text/plain; charset=utf-8",
            body=body,
        ),
        raw_payload_ref=f"memory:sha256:{hashlib.sha256(body).hexdigest()}",
    )
    normalizer = NormalizationService(session)
    if failed:
        document = normalizer.record_failure(
            snapshot.id,
            extractor_name="text-basic",
            extractor_version="1",
            failure_code=NormalizationFailureCode.PARSE_ERROR,
            failure_detail="synthetic failure",
        )
    else:
        document = normalizer.record_success(
            snapshot.id,
            extractor_name="text-basic",
            extractor_version="1",
            clean_text=clean_text,
        )
    return source, item, snapshot, document


def record(
    session: Session,
    document: NormalizedDocument,
    *,
    statement: str = "Kutlama İstanbul'da yapılır.",
    excerpt: str = DEFAULT_EXCERPT,
    **overrides: object,
) -> ResearchEvidence:
    assert document.clean_text is not None
    start = (
        int(overrides["excerpt_start"])
        if "excerpt_start" in overrides
        else document.clean_text.index(excerpt)
    )
    values: dict[str, object] = {
        "evidence_type": EvidenceType.SOURCE_ASSERTION,
        "statement": statement,
        "extraction_method": ExtractionMethod.MACHINE,
        "excerpt": excerpt,
        "excerpt_start": start,
        "excerpt_end": start + len(excerpt),
        "verification_status": VerificationStatus.VERIFIED,
        "extracted_at": NOW,
    }
    values.update(overrides)
    return ResearchEvidenceService(session).record_evidence(document.id, **values)  # type: ignore[arg-type]


def evidence_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(ResearchEvidence)) or 0


class TestModelAndVocabulary:
    def test_model_shape_and_three_restrict_provenance_foreign_keys(self) -> None:
        columns = set(ResearchEvidence.__table__.columns.keys())
        assert {
            "id",
            "normalized_document_id",
            "fetch_snapshot_id",
            "source_id",
            "source_url",
            "fetched_at",
            "evidence_type",
            "statement",
            "excerpt",
            "excerpt_start",
            "excerpt_end",
            "offset_version",
            "source_locator",
            "verification_status",
            "confidence",
            "confidence_basis",
            "extractor_name",
            "extractor_version",
            "extraction_method",
            "licensing_notes",
            "metadata",
            "evidence_key",
            "evidence_key_version",
            "extracted_at",
            "created_at",
        } == columns
        assert "updated_at" not in columns
        assert {
            (foreign_key.target_fullname, foreign_key.ondelete)
            for foreign_key in ResearchEvidence.__table__.foreign_keys
        } == {
            ("normalized_documents.id", "RESTRICT"),
            ("fetch_snapshots.id", "RESTRICT"),
            ("sources.id", "RESTRICT"),
        }

    def test_enums_and_versions_are_frozen(self) -> None:
        assert [item.value for item in EvidenceType] == [
            "source_assertion",
            "observation",
            "statistic",
            "quote",
            "instruction",
        ]
        assert [item.value for item in ExtractionMethod] == ["machine", "human"]
        assert [item.value for item in VerificationStatus] == [
            "unverified",
            "verified",
            "disputed",
            "retracted",
        ]
        assert RESEARCH_EVIDENCE_OFFSET_VERSION == 1
        assert EVIDENCE_KEY_VERSION == 1
        assert (DEFAULT_EXTRACTOR_NAME, DEFAULT_EXTRACTOR_VERSION) == (
            "deterministic-evidence",
            "1",
        )

    def test_repository_is_append_and_read_only(self, session: Session) -> None:
        repository = ResearchEvidenceRepository(session)
        assert callable(repository.add)
        assert callable(repository.get_by_id)
        assert callable(repository.get_by_identity)
        assert callable(repository.list_for_normalized_document)
        assert not hasattr(repository, "update")
        assert not hasattr(repository, "delete")
        assert not hasattr(repository, "commit")


class TestEvidenceKey:
    def test_key_is_direct_hashlib_over_canonical_utf8_json(self) -> None:
        statement = "Türkçe gözlem 🎉"
        payload = json.dumps(
            ["observation", statement, 3, 12],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        assert evidence_key_payload(EvidenceType.OBSERVATION, statement, 3, 12) == payload
        assert (
            compute_evidence_key(EvidenceType.OBSERVATION, statement, 3, 12)
            == hashlib.sha256(payload).hexdigest()
        )

    def test_key_is_deterministic_and_has_no_timestamp_input(self) -> None:
        first = compute_evidence_key(EvidenceType.QUOTE, "Aynı ifade", 0, 10)
        second = compute_evidence_key(EvidenceType.QUOTE, "Aynı ifade", 0, 10)
        assert first == second
        assert len(first) == 64
        assert first == first.lower()
        assert "timestamp" not in inspect.signature(compute_evidence_key).parameters


class TestExactExcerptValidation:
    @pytest.mark.parametrize(
        ("text", "excerpt"),
        [
            ("İzmir'de düğün", "İzmir'de"),
            ("başlangıç 🎉 bitiş", "🎉"),
            ("ilk satır\nikinci satır", "satır\nikinci"),
            ("Tarih: 31 Ağustos 2026.", "31 Ağustos 2026."),
        ],
    )
    def test_turkish_emoji_multiline_and_punctuation_offsets(
        self, session: Session, text: str, excerpt: str
    ) -> None:
        _, _, _, document = create_document(session, str(uuid.uuid4()), clean_text=text)
        start = text.index(excerpt)

        evidence = record(
            session,
            document,
            excerpt=excerpt,
            excerpt_start=start,
            excerpt_end=start + len(excerpt),
        )

        assert evidence.excerpt == excerpt
        assert evidence.excerpt_start == start
        assert evidence.excerpt_end == start + len(excerpt)
        assert evidence.offset_version == 1

    @pytest.mark.parametrize(
        ("start", "end"),
        [(-1, 2), (0, 0), (2, 1), (0, 10_000), (True, 2)],
    )
    def test_invalid_bounds_are_typed(self, session: Session, start: int, end: int) -> None:
        _, _, _, document = create_document(session)
        with pytest.raises(InvalidExcerptBoundsError):
            record(session, document, excerpt="İ", excerpt_start=start, excerpt_end=end)
        assert evidence_count(session) == 0

    def test_wrong_excerpt_or_wrong_start_is_rejected(self, session: Session) -> None:
        _, _, _, document = create_document(session)
        with pytest.raises(ExcerptMismatchError):
            record(
                session,
                document,
                excerpt="İstanbuX'da",
                excerpt_start=0,
                excerpt_end=len("İstanbuX'da"),
            )
        with pytest.raises(ExcerptMismatchError):
            record(session, document, excerpt_start=1, excerpt_end=23)
        assert evidence_count(session) == 0

    def test_partial_excerpt_arguments_are_rejected(self, session: Session) -> None:
        _, _, _, document = create_document(session)
        with pytest.raises(InvalidExcerptBoundsError):
            ResearchEvidenceService(session).record_evidence(
                document.id,
                evidence_type=EvidenceType.OBSERVATION,
                statement="Observation",
                extraction_method=ExtractionMethod.MACHINE,
                excerpt="İstanbul",
            )


class TestServiceAndProvenance:
    def test_exact_evidence_derives_full_chain_and_never_copies_clean_text(
        self, session: Session
    ) -> None:
        source, item, snapshot, document = create_document(session)

        evidence = record(session, document, licensing_notes="Operator note: rights unknown.")

        assert evidence.normalized_document_id == document.id
        assert evidence.fetch_snapshot_id == snapshot.id
        assert evidence.source_id == source.id == item.source_id
        assert evidence.source_url == snapshot.final_url
        assert evidence.fetched_at == snapshot.fetched_at
        assert evidence.licensing_notes == "Operator note: rights unknown."
        assert not hasattr(evidence, "clean_text")
        assert not hasattr(evidence, "body")
        assert evidence.excerpt != document.clean_text

    def test_api_has_no_caller_supplied_provenance_fields(self) -> None:
        parameters = inspect.signature(ResearchEvidenceService.record_evidence).parameters
        assert "source_url" not in parameters
        assert "fetched_at" not in parameters
        assert "fetch_snapshot_id" not in parameters
        assert "source_id" not in parameters

    def test_missing_failed_and_incomplete_documents_are_typed(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = ResearchEvidenceService(session)
        with pytest.raises(ResearchDocumentNotFoundError):
            service.record_evidence(
                uuid.uuid4(),
                evidence_type=EvidenceType.OBSERVATION,
                statement="Missing",
                extraction_method=ExtractionMethod.MACHINE,
                source_locator="structured_metadata.title",
            )

        _, _, _, failed = create_document(session, "failed", failed=True)
        with pytest.raises(ResearchDocumentNotEligibleError):
            service.record_evidence(
                failed.id,
                evidence_type=EvidenceType.OBSERVATION,
                statement="Failed",
                extraction_method=ExtractionMethod.MACHINE,
                source_locator="structured_metadata.title",
            )

        _, _, _, valid = create_document(session, "valid")
        monkeypatch.setattr(service._provenance, "get_provenance", lambda _id: None)
        with pytest.raises(ResearchProvenanceMissingError):
            record_with_service(service, valid)

    def test_verified_is_exact_grounding_not_automatic_machine_truth(
        self, session: Session
    ) -> None:
        _, _, _, document = create_document(session)
        unverified = record(
            session,
            document,
            verification_status=VerificationStatus.UNVERIFIED,
            extractor_version="unverified",
        )
        verified = record(session, document, extractor_version="verified")

        assert unverified.extraction_method is ExtractionMethod.MACHINE
        assert unverified.verification_status is VerificationStatus.UNVERIFIED
        assert verified.verification_status is VerificationStatus.VERIFIED
        assert verified.excerpt == document.clean_text[: len(DEFAULT_EXCERPT)]

    def test_excerpt_less_structured_evidence_requires_safe_locator_and_is_unverified(
        self, session: Session
    ) -> None:
        _, _, _, document = create_document(session)
        service = ResearchEvidenceService(session)
        evidence = service.record_evidence(
            document.id,
            evidence_type=EvidenceType.OBSERVATION,
            statement="A publication date is present in structured metadata.",
            extraction_method=ExtractionMethod.MACHINE,
            source_locator="structured_metadata.article:published_time",
            metadata={"field": "article:published_time"},
            extracted_at=NOW,
        )

        assert evidence.excerpt is None
        assert evidence.offset_version is None
        assert evidence.source_locator == "structured_metadata.article:published_time"
        assert evidence.verification_status is VerificationStatus.UNVERIFIED

        with pytest.raises(InvalidEvidenceInputError):
            service.record_evidence(
                document.id,
                evidence_type=EvidenceType.OBSERVATION,
                statement="No locator",
                extraction_method=ExtractionMethod.MACHINE,
            )
        with pytest.raises(InvalidEvidenceInputError):
            service.record_evidence(
                document.id,
                evidence_type=EvidenceType.OBSERVATION,
                statement="Executable locator",
                extraction_method=ExtractionMethod.MACHINE,
                source_locator="$..article[?(@.published)]",
            )
        with pytest.raises(InvalidEvidenceInputError):
            service.record_evidence(
                document.id,
                evidence_type=EvidenceType.OBSERVATION,
                statement="False verification",
                extraction_method=ExtractionMethod.MACHINE,
                source_locator="structured_metadata.title",
                verification_status=VerificationStatus.VERIFIED,
            )
        with pytest.raises(InvalidEvidenceInputError):
            service.record_evidence(
                document.id,
                evidence_type=EvidenceType.QUOTE,
                statement="A quote must retain exact source text.",
                extraction_method=ExtractionMethod.HUMAN,
                source_locator="structured_metadata.quote",
            )

    def test_optional_confidence_requires_bounded_score_and_basis(self, session: Session) -> None:
        _, _, _, document = create_document(session)
        evidence = record(
            session,
            document,
            confidence=Decimal("0.7500"),
            confidence_basis="Human-assigned source confidence.",
        )
        assert evidence.confidence == Decimal("0.7500")
        assert evidence.confidence_basis is not None

        for confidence, basis in [(1.1, "basis"), (0.5, None), (None, "basis")]:
            with pytest.raises(InvalidEvidenceInputError):
                record(
                    session,
                    document,
                    extractor_version=f"bad-{confidence}-{basis}",
                    confidence=confidence,
                    confidence_basis=basis,
                )

    def test_service_flushes_without_committing(self, session: Session) -> None:
        _, _, _, document = create_document(session)
        evidence = record(session, document)
        assert evidence in session.new or evidence in session


def record_with_service(
    service: ResearchEvidenceService, document: NormalizedDocument
) -> ResearchEvidence:
    return service.record_evidence(
        document.id,
        evidence_type=EvidenceType.OBSERVATION,
        statement="Provenance check",
        extraction_method=ExtractionMethod.MACHINE,
        source_locator="structured_metadata.title",
    )


class TestIdempotencyAndConflicts:
    def test_exact_retry_returns_same_row_and_changed_statement_is_new_identity(
        self, session: Session
    ) -> None:
        _, _, _, document = create_document(session)
        first = record(session, document)
        second = record(session, document, extracted_at=NOW.replace(hour=13))
        changed = record(session, document, statement="A different internal observation.")

        assert second is first
        assert changed.id != first.id
        assert evidence_count(session) == 2

    def test_same_key_with_different_immutable_metadata_is_typed_conflict(
        self, session: Session
    ) -> None:
        _, _, _, document = create_document(session)
        record(session, document, metadata={"rule": "first"})
        with pytest.raises(ResearchEvidenceConflictError):
            record(session, document, metadata={"rule": "changed"})

    def test_extractor_v2_coexists_and_repository_order_is_deterministic(
        self, session: Session
    ) -> None:
        _, _, _, document = create_document(session)
        v1 = record(session, document, extractor_version="1")
        v2 = record(
            session,
            document,
            extractor_version="2",
            extracted_at=NOW.replace(hour=13),
        )
        assert v1.id != v2.id
        assert ResearchEvidenceRepository(session).list_for_normalized_document(document.id) == [
            v1,
            v2,
        ]

    def test_uniqueness_race_and_unresolved_database_error_are_typed(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, _, _, document = create_document(session)
        winner = record(session, document)
        service = ResearchEvidenceService(session)
        calls = 0

        def race_lookup(*_args: object) -> ResearchEvidence | None:
            nonlocal calls
            calls += 1
            return None if calls == 1 else winner

        def fail_add(_evidence: ResearchEvidence) -> ResearchEvidence:
            raise IntegrityError("insert", {}, Exception("race"))

        monkeypatch.setattr(service._evidence, "get_by_identity", race_lookup)
        monkeypatch.setattr(service._evidence, "add", fail_add)
        assert record_with_service_exact(service, document) is winner

        broken = ResearchEvidenceService(session)
        monkeypatch.setattr(broken._evidence, "get_by_identity", lambda *_args: None)
        monkeypatch.setattr(broken._evidence, "add", fail_add)
        with pytest.raises(
            ResearchEvidencePersistenceError, match="database rejected research evidence"
        ):
            record_with_service_exact(broken, document)


def record_with_service_exact(
    service: ResearchEvidenceService, document: NormalizedDocument
) -> ResearchEvidence:
    return service.record_evidence(
        document.id,
        evidence_type=EvidenceType.SOURCE_ASSERTION,
        statement="Kutlama İstanbul'da yapılır.",
        extraction_method=ExtractionMethod.MACHINE,
        excerpt=DEFAULT_EXCERPT,
        excerpt_start=0,
        excerpt_end=len(DEFAULT_EXCERPT),
        verification_status=VerificationStatus.VERIFIED,
        extracted_at=NOW,
    )


class TestLimits:
    def test_statement_excerpt_and_licensing_limits(self, session: Session) -> None:
        _, _, _, document = create_document(session, clean_text="x" * (MAX_EXCERPT_LENGTH + 1))
        with pytest.raises(InvalidEvidenceInputError):
            record(session, document, statement="s" * (MAX_STATEMENT_LENGTH + 1), excerpt="x")
        with pytest.raises(InvalidEvidenceInputError):
            record(session, document, excerpt="x" * (MAX_EXCERPT_LENGTH + 1))
        with pytest.raises(InvalidEvidenceInputError):
            record(
                session,
                document,
                excerpt="x",
                licensing_notes="n" * (MAX_LICENSING_NOTES_LENGTH + 1),
            )
        assert evidence_count(session) == 0

    def test_metadata_depth_items_and_value_types_are_bounded(self, session: Session) -> None:
        _, _, _, document = create_document(session)
        deep: dict[str, object] = {}
        node = deep
        for _ in range(MAX_METADATA_DEPTH + 1):
            child: dict[str, object] = {}
            node["child"] = child
            node = child
        invalid_values = [
            deep,
            {str(index): index for index in range(MAX_METADATA_ITEMS + 1)},
            {"value": object()},
        ]
        for index, metadata in enumerate(invalid_values):
            with pytest.raises(InvalidEvidenceInputError):
                record(
                    session,
                    document,
                    extractor_version=f"metadata-{index}",
                    metadata=metadata,
                )
