"""Deterministic evidence extractor tests."""

import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import contentos.research.extractor as extractor_module
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
from contentos.normalization.enums import NormalizationFailureCode
from contentos.normalization.models import NormalizedDocument
from contentos.normalization.service import NormalizationService
from contentos.research.enums import EvidenceType, ExtractionMethod, VerificationStatus
from contentos.research.extractor import (
    AUTHOR_STATEMENT_TEMPLATE,
    DATE_STATEMENT_TEMPLATE,
    DATE_TEXT_STATEMENT_TEMPLATE,
    MAX_EVIDENCE_CANDIDATES_PER_DOCUMENT,
    MAX_EXACT_EXCERPT_CANDIDATES,
    MAX_METADATA_VALUE_LENGTH,
    DeterministicEvidenceExtractor,
    EvidenceCandidate,
)
from contentos.research.models import ResearchEvidence
from contentos.research.repository import ResearchEvidenceRepository
from contentos.research.service import ResearchEvidenceService
from contentos.research.validation import (
    MAX_SOURCE_LOCATOR_LENGTH,
    MAX_STATEMENT_LENGTH,
    ResearchDocumentNotEligibleError,
    ResearchDocumentNotFoundError,
)
from contentos.sources.enums import DiscoveryStrategy, SourceKind, TrustTier
from contentos.sources.models import Source
from contentos.sources.service import SourceRegistryService

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
PUBLISHED = datetime(2026, 8, 30, 9, 30, tzinfo=UTC)
CLEAN_TEXT = "İstanbul'da kutlama 🎉\nTarih: 30 Ağustos 2026."


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
    suffix: str | None = None,
    *,
    author_name: str | None = None,
    external_published_at: datetime | None = None,
    structured_metadata: dict[str, Any] | None = None,
    failed: bool = False,
) -> tuple[Source, FetchSnapshot, NormalizedDocument]:
    suffix = suffix or str(uuid.uuid4())
    source = SourceRegistryService(session).register_source(
        slug=f"extractor-{suffix}",
        name=f"Extractor {suffix}",
        kind=SourceKind.MANUAL,
        base_url=f"https://extractor-{suffix}.example.test/",
        trust_tier=TrustTier.GENERAL,
        discovery_strategy=DiscoveryStrategy.MANUAL,
    )
    discoveries = DiscoveryService(session)
    item = discoveries.discover_manual(
        source.id, f"https://extractor-{suffix}.example.test/article"
    )
    discoveries.accept_item(item.id)
    body = CLEAN_TEXT.encode()
    snapshot = FetchSnapshotService(session).record_fetch_result(
        item.id,
        FetchResult(
            requested_url=item.canonical_url,
            outcome=FetchOutcome.SUCCESS,
            retry=RetryClassification.NOT_APPLICABLE,
            robots_decision=RobotsDecision.ALLOWED,
            fetched_at=NOW,
            duration_ms=2.0,
            final_url=f"https://extractor-{suffix}.example.test/final",
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=body,
        ),
        raw_payload_ref=f"memory:sha256:{hashlib.sha256(body).hexdigest()}",
    )
    normalizer = NormalizationService(session)
    if failed:
        document = normalizer.record_failure(
            snapshot.id,
            extractor_name="html-basic",
            extractor_version="1",
            failure_code=NormalizationFailureCode.PARSE_ERROR,
            failure_detail="synthetic failure",
        )
    else:
        document = normalizer.record_success(
            snapshot.id,
            extractor_name="html-basic",
            extractor_version="1",
            clean_text=CLEAN_TEXT,
            author_name=author_name,
            external_published_at=external_published_at,
            structured_metadata=structured_metadata or {},
        )
    return source, snapshot, document


def evidence_rows(session: Session, document: NormalizedDocument) -> list[ResearchEvidence]:
    return ResearchEvidenceRepository(session).list_for_normalized_document(document.id)


def total_evidence(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(ResearchEvidence)) or 0


class TestEligibility:
    def test_missing_document_is_typed(self, session: Session) -> None:
        with pytest.raises(ResearchDocumentNotFoundError):
            DeterministicEvidenceExtractor(session).extract_and_record(uuid.uuid4())

    def test_failed_document_is_rejected(self, session: Session) -> None:
        _, _, failed = create_document(session, failed=True)
        with pytest.raises(ResearchDocumentNotEligibleError):
            DeterministicEvidenceExtractor(session).extract_and_record(failed.id)

    def test_document_without_facts_yields_empty_result(self, session: Session) -> None:
        _, _, document = create_document(session)

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        assert result.candidates_seen == 0
        assert result.created == () and result.existing == ()
        assert result.skipped_invalid == 0
        assert total_evidence(session) == 0


class TestAuthorExtraction:
    def test_author_name_produces_one_unverified_machine_observation(
        self, session: Session
    ) -> None:
        _, _, document = create_document(session, author_name="Ayşe Yılmaz")

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        assert len(result.created) == 1
        evidence = result.created[0]
        assert evidence.evidence_type is EvidenceType.OBSERVATION
        assert evidence.statement == AUTHOR_STATEMENT_TEMPLATE.format(value="Ayşe Yılmaz")
        assert evidence.source_locator == "normalized.author_name"
        assert evidence.extraction_method is ExtractionMethod.MACHINE
        assert evidence.verification_status is VerificationStatus.UNVERIFIED
        assert evidence.excerpt is None
        assert evidence.excerpt_start is None
        assert evidence.confidence is None
        assert evidence.metadata_json == {"rule": "author_attribution"}

    def test_duplicate_structured_author_is_suppressed(self, session: Session) -> None:
        _, _, document = create_document(
            session,
            author_name="Ayşe Yılmaz",
            structured_metadata={
                "article": {"article:author": "Ayşe Yılmaz"},
                "json_ld": [{"author": "Ayşe Yılmaz"}],
            },
        )

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        author_rows = [
            row
            for row in evidence_rows(session, document)
            if row.metadata_json["rule"] == "author_attribution"
        ]
        assert len(author_rows) == 1
        assert author_rows[0].source_locator == "normalized.author_name"
        assert result.candidates_seen == 1

    def test_structured_article_author_is_the_first_fallback(self, session: Session) -> None:
        _, _, document = create_document(
            session,
            structured_metadata={
                "article": {"article:author": "Mehmet Demir"},
                "json_ld": [{"author": "Başka Yazar"}],
            },
        )

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        assert len(result.created) == 1
        assert result.created[0].source_locator == "structured_metadata.article:author"
        assert "Mehmet Demir" in result.created[0].statement

    def test_json_ld_author_is_the_last_fallback(self, session: Session) -> None:
        _, _, document = create_document(
            session, structured_metadata={"json_ld": [{"author": "Zeynep Kaya"}]}
        )

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        assert result.created[0].source_locator == "structured_metadata.json_ld.author"

    def test_malformed_author_value_is_skipped_with_warning_and_fallback(
        self, session: Session
    ) -> None:
        _, _, document = create_document(
            session,
            structured_metadata={
                "article": {"article:author": 123},
                "json_ld": [{"author": "Geçerli Yazar"}],
            },
        )

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        assert result.skipped_invalid == 1
        assert any("article:author" in warning for warning in result.warnings)
        assert result.created[0].source_locator == "structured_metadata.json_ld.author"

    def test_oversized_author_value_is_skipped(self, session: Session) -> None:
        _, _, document = create_document(
            session,
            structured_metadata={
                "article": {"article:author": "y" * (MAX_METADATA_VALUE_LENGTH + 1)}
            },
        )

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        assert result.created == ()
        assert result.skipped_invalid == 1


class TestDateExtraction:
    def test_external_published_at_produces_iso_statement(self, session: Session) -> None:
        _, _, document = create_document(session, external_published_at=PUBLISHED)

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        assert len(result.created) == 1
        evidence = result.created[0]
        assert evidence.statement == DATE_STATEMENT_TEMPLATE.format(value=PUBLISHED.isoformat())
        assert evidence.source_locator == "normalized.external_published_at"
        assert evidence.metadata_json == {"rule": "publication_date"}
        assert evidence.verification_status is VerificationStatus.UNVERIFIED

    def test_duplicate_metadata_date_is_suppressed(self, session: Session) -> None:
        _, _, document = create_document(
            session,
            external_published_at=PUBLISHED,
            structured_metadata={
                "article": {"article:published_time": PUBLISHED.isoformat()},
                "json_ld": [{"datePublished": PUBLISHED.isoformat()}],
            },
        )

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        date_rows = [
            row
            for row in evidence_rows(session, document)
            if row.metadata_json["rule"] == "publication_date"
        ]
        assert len(date_rows) == 1
        assert date_rows[0].source_locator == "normalized.external_published_at"
        assert result.candidates_seen == 1

    def test_article_published_time_is_the_first_fallback(self, session: Session) -> None:
        _, _, document = create_document(
            session,
            structured_metadata={
                "article": {"article:published_time": "2026-08-30T09:30:00+00:00"},
                "json_ld": [{"datePublished": "farklı"}],
            },
        )

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        evidence = result.created[0]
        assert evidence.source_locator == "structured_metadata.article:published_time"
        assert evidence.statement == DATE_TEXT_STATEMENT_TEMPLATE.format(
            value="2026-08-30T09:30:00+00:00"
        )

    def test_json_ld_date_is_the_last_fallback(self, session: Session) -> None:
        _, _, document = create_document(
            session, structured_metadata={"json_ld": [{"datePublished": "30 Ağustos 2026"}]}
        )

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        assert result.created[0].source_locator == "structured_metadata.json_ld.datePublished"


class TestStructuredMetadataSafety:
    def test_unknown_keys_are_ignored(self, session: Session) -> None:
        _, _, document = create_document(
            session,
            structured_metadata={
                "description": "özet",
                "open_graph": {"og:title": "Başlık"},
                "tracking": {"utm_source": "spam"},
                "canonical_url": "https://example.test/canonical",
            },
        )

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        assert result.candidates_seen == 0
        assert total_evidence(session) == 0

    def test_malformed_container_shapes_warn_and_do_not_crash(self, session: Session) -> None:
        _, _, document = create_document(
            session,
            structured_metadata={"article": "not-an-object", "json_ld": "not-a-list"},
        )

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        assert result.created == ()
        assert result.skipped_invalid >= 2
        assert any("article" in warning for warning in result.warnings)
        assert any("json_ld" in warning for warning in result.warnings)

    def test_non_object_json_ld_entries_are_ignored(self, session: Session) -> None:
        _, _, document = create_document(
            session,
            structured_metadata={"json_ld": ["metin", 42, {"author": "Gerçek Yazar"}]},
        )

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        assert len(result.created) == 1
        assert "Gerçek Yazar" in result.created[0].statement


class TestIdempotencyAndLimits:
    def test_second_run_creates_no_duplicates_and_returns_existing(self, session: Session) -> None:
        _, _, document = create_document(
            session, author_name="Ayşe Yılmaz", external_published_at=PUBLISHED
        )
        extractor = DeterministicEvidenceExtractor(session)

        first = extractor.extract_and_record(document.id)
        second = extractor.extract_and_record(document.id)

        assert len(first.created) == 2 and first.existing == ()
        assert second.created == () and len(second.existing) == 2
        assert {row.id for row in second.existing} == {row.id for row in first.created}
        assert total_evidence(session) == 2

    def test_extractor_version_two_can_coexist(self, session: Session) -> None:
        _, _, document = create_document(session, author_name="Ayşe Yılmaz")
        extractor = DeterministicEvidenceExtractor(session)
        first = extractor.extract_and_record(document.id)

        v2 = ResearchEvidenceService(session).record_evidence(
            document.id,
            evidence_type=EvidenceType.OBSERVATION,
            statement=first.created[0].statement,
            extraction_method=ExtractionMethod.MACHINE,
            extractor_version="2",
            source_locator="normalized.author_name",
            metadata={"rule": "author_attribution"},
        )

        assert v2.id != first.created[0].id
        assert total_evidence(session) == 2

    def test_candidate_limit_is_enforced_with_warning(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, _, document = create_document(session)
        surplus = MAX_EVIDENCE_CANDIDATES_PER_DOCUMENT + 2
        synthetic = [
            EvidenceCandidate(
                evidence_type=EvidenceType.OBSERVATION,
                statement=f"Sentetik gözlem {index}.",
                source_locator="normalized.author_name",
                rule="author_attribution",
            )
            for index in range(surplus)
        ]
        monkeypatch.setattr(
            extractor_module, "_generate_candidates", lambda _document, _collector: synthetic
        )

        result = DeterministicEvidenceExtractor(session).extract_and_record(document.id)

        assert result.candidates_seen == surplus
        assert len(result.created) == MAX_EVIDENCE_CANDIDATES_PER_DOCUMENT
        assert any("candidate limit exceeded" in warning for warning in result.warnings)

    def test_extractor_limits_stay_within_persistence_limits(self) -> None:
        assert MAX_EXACT_EXCERPT_CANDIDATES == 0
        longest_author = AUTHOR_STATEMENT_TEMPLATE.format(value="y" * MAX_METADATA_VALUE_LENGTH)
        assert len(longest_author) <= MAX_STATEMENT_LENGTH
        assert len("structured_metadata.json_ld.datePublished") <= MAX_SOURCE_LOCATOR_LENGTH


class TestSecurityAndScope:
    def test_extractor_module_has_no_network_or_dynamic_execution(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[2] / "src" / "contentos" / "research" / "extractor.py"
        )
        source = source_path.read_text(encoding="utf-8")

        for forbidden in ("httpx", "socket", "urllib.request", "subprocess", "eval(", "exec("):
            assert forbidden not in source

    def test_extractor_never_touches_the_model_directly(self) -> None:
        source_path = (
            Path(__file__).resolve().parents[2] / "src" / "contentos" / "research" / "extractor.py"
        )
        source = source_path.read_text(encoding="utf-8")

        assert "ResearchEvidence(" not in source.replace("ResearchEvidence]", "")
        assert "session.add" not in source


class TestEndToEnd:
    def test_full_synthetic_chain_produces_provenanced_idempotent_evidence(
        self, session: Session
    ) -> None:
        source, snapshot, document = create_document(
            session,
            "e2e",
            author_name="Ayşe Yılmaz",
            external_published_at=PUBLISHED,
            structured_metadata={"article": {"article:author": "Ayşe Yılmaz"}},
        )
        extractor = DeterministicEvidenceExtractor(session)

        result = extractor.extract_and_record(document.id)
        session.commit()
        rerun = extractor.extract_and_record(document.id)

        rows = evidence_rows(session, document)
        assert len(rows) == 2
        assert {row.metadata_json["rule"] for row in rows} == {
            "author_attribution",
            "publication_date",
        }
        for row in rows:
            assert row.source_id == source.id
            assert row.source_url == snapshot.final_url
            assert row.fetched_at == snapshot.fetched_at
            assert row.extractor_name == "deterministic-evidence"
            assert row.extractor_version == "1"
        assert len(result.created) == 2
        assert rerun.created == () and len(rerun.existing) == 2
        assert total_evidence(session) == 2
