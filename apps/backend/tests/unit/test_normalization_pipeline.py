"""Executable normalization pipeline tests over synthetic stored payloads."""

import hashlib
import socket
import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
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
from contentos.normalization.enums import NormalizationFailureCode, NormalizationStatus
from contentos.normalization.extractors import (
    ExtractedDocument,
    ExtractionContext,
    ExtractorDecodeError,
    ExtractorEmptyContentError,
    ExtractorParseError,
    ExtractorPolicyError,
    HtmlExtractor,
    PlainTextExtractor,
)
from contentos.normalization.models import NormalizedDocument
from contentos.normalization.pipeline import (
    NormalizationPipeline,
    NormalizationPipelineConfigurationError,
    NormalizationPipelineIntegrityError,
    NormalizationPipelinePayloadError,
)
from contentos.normalization.service import (
    FetchSnapshotNotEligibleError,
    FetchSnapshotNotFoundError,
    NormalizationConflictError,
)
from contentos.payloads.models import RawPayloadRef
from contentos.payloads.store import InMemoryRawPayloadStore, RawPayloadReader
from contentos.sources.enums import DiscoveryStrategy, SourceKind, TrustTier
from contentos.sources.models import Source
from contentos.sources.service import SourceRegistryService

NOW = datetime(2026, 9, 1, 10, 30, tzinfo=UTC)
MAX_TEST_PAYLOAD_BYTES = 2_000_000


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session
    engine.dispose()


def make_snapshot(
    session: Session,
    payload: bytes,
    *,
    content_type: str | None = "text/html; charset=utf-8",
    suffix: str = "article",
    final_url: str | None = None,
) -> tuple[FetchSnapshot, InMemoryRawPayloadStore, Source, DiscoveryItem]:
    source = SourceRegistryService(session).register_source(
        slug=f"source-{suffix}",
        name=f"Source {suffix}",
        kind=SourceKind.MANUAL,
        base_url=f"https://{suffix}.example.test/",
        trust_tier=TrustTier.GENERAL,
        discovery_strategy=DiscoveryStrategy.MANUAL,
    )
    discoveries = DiscoveryService(session)
    item = discoveries.discover_manual(
        source.id,
        f"https://{suffix}.example.test/research/original",
    )
    discoveries.accept_item(item.id)
    store = InMemoryRawPayloadStore(chunk_size=7)
    stored = store.put(payload)
    result = FetchResult(
        requested_url=item.canonical_url,
        outcome=FetchOutcome.SUCCESS,
        retry=RetryClassification.NOT_APPLICABLE,
        robots_decision=RobotsDecision.ALLOWED,
        fetched_at=NOW,
        duration_ms=3.5,
        final_url=final_url or f"https://{suffix}.example.test/research/final/index.html",
        status_code=200,
        content_type=content_type,
        body=payload,
    )
    snapshot = FetchSnapshotService(session).record_fetch_result(
        item.id,
        result,
        raw_payload_ref=str(stored.ref),
    )
    return snapshot, store, source, item


def make_failed_snapshot(session: Session) -> FetchSnapshot:
    source = SourceRegistryService(session).register_source(
        slug="failed-source",
        name="Failed source",
        kind=SourceKind.MANUAL,
        base_url="https://failed.example.test/",
        trust_tier=TrustTier.GENERAL,
        discovery_strategy=DiscoveryStrategy.MANUAL,
    )
    discoveries = DiscoveryService(session)
    item = discoveries.discover_manual(source.id, "https://failed.example.test/article")
    discoveries.accept_item(item.id)
    return FetchSnapshotService(session).record_fetch_result(
        item.id,
        FetchResult(
            requested_url=item.canonical_url,
            outcome=FetchOutcome.TIMEOUT,
            retry=RetryClassification.RETRYABLE,
            robots_decision=RobotsDecision.ALLOWED,
            fetched_at=NOW,
            duration_ms=100.0,
            failure_detail="read_timeout",
        ),
    )


def count_documents(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(NormalizedDocument)) or 0


class TrackingReader:
    def __init__(self, delegate: RawPayloadReader) -> None:
        self.delegate = delegate
        self.refs: list[RawPayloadRef] = []
        self.limits: list[int] = []

    def iter_bytes(self, ref: RawPayloadRef, *, max_bytes: int) -> Iterator[bytes]:
        self.refs.append(ref)
        self.limits.append(max_bytes)
        yield from self.delegate.iter_bytes(ref, max_bytes=max_bytes)


class StaticReader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def iter_bytes(self, ref: RawPayloadRef, *, max_bytes: int) -> Iterator[bytes]:
        del ref, max_bytes
        yield self.payload


class ConfigurableExtractor:
    name = "test-extractor"
    version = "1"
    parser_version = "test-parser-v1"
    supported_media_types = frozenset({"text/html"})

    def __init__(self, output: ExtractedDocument | Exception) -> None:
        self.output = output

    def extract(self, payload: bytes, context: ExtractionContext) -> ExtractedDocument:
        del payload, context
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


SYNTHETIC_HTML = """<!doctype html>
<html lang="tr-TR">
<head>
  invisible head prose
  <title>Başlık yedeği</title>
  <meta property="og:title" content="Özgün Konsept Başlığı">
  <meta name="description" content="Kısa açıklama">
  <meta property="og:description" content="Kısa açıklama">
  <meta property="og:type" content="article">
  <meta name="author" content="Ada Yazar">
  <meta property="article:published_time" content="2026-08-31T21:15:00+03:00">
  <link rel="canonical" href="/kalici-adres">
  <style>.secret { display: block }</style>
  <script>window.secret = 'çalıştırma';</script>
  <script type="application/ld+json">
    {"@type":"Article","headline":"Şema Başlığı","datePublished":"2020-01-01",
     "author":{"name":"Şema Yazarı"},"description":"Sınırlı şema"}
  </script>
  <script type="application/ld+json">{bozuk json</script>
</head>
<body>
  <nav>Menü kromu</nav>
  <h1>Ana Başlık</h1>
  <p>İstanbul'da özgün içerik &amp; Türkçe noktalama korunur.</p>
  <ul><li>Birinci fikir</li><li>İkinci fikir</li></ul>
  <a href="../kaynak">Kaynak sayfası</a>
  <a href="../kaynak">Tekrar</a>
  <a href="javascript:alert(1)">Tehlikeli</a>
  <a href="data:text/plain,no">Veri</a>
  <a href="mailto:x@example.test">E-posta</a>
  <a href="tel:+90000">Telefon</a>
  <a href="#yerel">Parça</a>
  <h2>Alt Bölüm</h2>
  <p>Alt bölümün araştırma metni.</p>
  <footer>Alt bilgi kromu</footer>
</body>
</html>"""


class TestHtmlExtraction:
    def test_extracts_visible_research_structure_and_bounded_metadata(self) -> None:
        document = HtmlExtractor().extract(
            SYNTHETIC_HTML.encode(),
            ExtractionContext(
                media_type="text/html",
                content_type="text/html; charset=utf-8",
                base_url="https://example.test/research/final/index.html",
            ),
        )

        assert document.title == "Özgün Konsept Başlığı"
        assert document.language == "tr-TR"
        assert document.author_name == "Ada Yazar"
        assert document.external_published_at == datetime(2026, 8, 31, 18, 15, tzinfo=UTC)
        assert [heading.text for heading in document.headings] == ["Ana Başlık", "Alt Bölüm"]
        assert document.sections[0].heading == "Ana Başlık"
        assert "İkinci fikir" in document.sections[0].text
        assert document.sections[1].text == "Alt bölümün araştırma metni."
        assert [link.url for link in document.links] == ["https://example.test/research/kaynak"]
        assert document.links[0].text == "Kaynak sayfası"
        assert "İstanbul'da özgün içerik & Türkçe noktalama korunur." in document.clean_text
        for excluded in (
            "invisible head prose",
            "Menü kromu",
            "window.secret",
            ".secret",
            "Alt bilgi kromu",
        ):
            assert excluded not in document.clean_text
        assert document.structured_metadata["canonical_url"] == (
            "https://example.test/kalici-adres"
        )
        assert document.structured_metadata["description"] == "Kısa açıklama"
        assert document.structured_metadata["open_graph"]["og:type"] == "article"
        assert document.structured_metadata["json_ld"] == [
            {
                "@type": "Article",
                "headline": "Şema Başlığı",
                "description": "Sınırlı şema",
                "datePublished": "2020-01-01",
                "author": "Şema Yazarı",
            }
        ]

    def test_malformed_html_is_deterministic_and_does_not_crash(self) -> None:
        context = ExtractionContext("text/html", "text/html", "https://example.test/")
        payload = b"<html><body><h1>Open<p>Still visible &amp; safe"

        first = HtmlExtractor().extract(payload, context)
        second = HtmlExtractor().extract(payload, context)

        assert first == second
        assert "Still visible & safe" in first.clean_text

    def test_meta_charset_is_used_after_absent_response_charset(self) -> None:
        payload = (
            '<html><head><meta charset="windows-1254"><title>Şehir</title></head>'
            "<body><p>İzmir, çığ ve öğün.</p></body></html>"
        ).encode("cp1254")

        document = HtmlExtractor().extract(
            payload,
            ExtractionContext("text/html", "text/html", "https://example.test/"),
        )

        assert document.title == "Şehir"
        assert document.clean_text == "İzmir, çığ ve öğün."

    def test_empty_html_is_a_typed_empty_content_failure(self) -> None:
        with pytest.raises(ExtractorEmptyContentError):
            HtmlExtractor().extract(
                b"<html><script>secret</script><style>x</style></html>",
                ExtractionContext("text/html", "text/html", "https://example.test/"),
            )

    def test_element_clean_text_heading_link_and_jsonld_limits_are_enforced(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import contentos.normalization.extractors.base as base_module
        import contentos.normalization.extractors.html as html_module

        context = ExtractionContext("text/html", "text/html", "https://example.test/")
        monkeypatch.setattr(html_module, "MAX_PARSED_ELEMENTS", 2)
        with pytest.raises(ExtractorPolicyError):
            HtmlExtractor().extract(b"<html><body><p>text</p></body></html>", context)

        monkeypatch.setattr(html_module, "MAX_PARSED_ELEMENTS", 100)
        monkeypatch.setattr(html_module, "MAX_HEADINGS", 1)
        monkeypatch.setattr(html_module, "MAX_LINKS", 1)
        limited = HtmlExtractor().extract(
            b'<h1>one</h1><h2>two</h2><a href="/1">one</a><a href="/2">two</a>',
            context,
        )
        assert len(limited.headings) == 1
        assert len(limited.links) == 1

        monkeypatch.setattr(base_module, "MAX_CLEAN_TEXT_CHARS", 5)
        monkeypatch.setattr(html_module, "MAX_CLEAN_TEXT_CHARS", 5)
        with pytest.raises(ExtractorPolicyError):
            HtmlExtractor().extract(b"<p>abcd</p><p>efgh</p>", context)

        monkeypatch.setattr(html_module, "MAX_CLEAN_TEXT_CHARS", 1_000_000)
        monkeypatch.setattr(base_module, "MAX_CLEAN_TEXT_CHARS", 1_000_000)
        monkeypatch.setattr(html_module, "MAX_JSON_LD_CHARS", 5)
        metadata_limited = HtmlExtractor().extract(
            b'<script type="application/ld+json">{"headline":"secret"}</script><p>visible</p>',
            context,
        )
        assert "json_ld" not in metadata_limited.structured_metadata


class TestPlainTextExtraction:
    def test_utf8_turkish_and_line_endings_are_deterministic(self) -> None:
        context = ExtractionContext("text/plain", "text/plain; charset=utf-8", "https://x.test/")
        payload = "  İlk Başlık  \r\n\r\nİstanbul\t güzel.\rSon satır\n\n\n".encode()

        document = PlainTextExtractor().extract(payload, context)

        assert document.title == "İlk Başlık"
        assert document.clean_text == "İlk Başlık\n\nİstanbul güzel.\nSon satır"
        assert document.author_name is None
        assert document.external_published_at is None

    def test_declared_cp1254_is_supported_and_locale_is_irrelevant(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "locale.getpreferredencoding", lambda *_: (_ for _ in ()).throw(AssertionError)
        )
        document = PlainTextExtractor().extract(
            "İzmir çığ öğün".encode("cp1254"),
            ExtractionContext("text/plain", "text/plain; charset=windows-1254", "https://x.test/"),
        )
        assert document.clean_text == "İzmir çığ öğün"

    @pytest.mark.parametrize("payload", [b"", b" \t\r\n \n"])
    def test_empty_text_is_typed(self, payload: bytes) -> None:
        with pytest.raises(ExtractorEmptyContentError):
            PlainTextExtractor().extract(
                payload,
                ExtractionContext("text/plain", "text/plain", "https://x.test/"),
            )


class TestPipelineExecution:
    def test_synthetic_source_to_normalized_document_chain_and_verified_read(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        snapshot, store, source, item = make_snapshot(
            session,
            SYNTHETIC_HTML.encode(),
            final_url="https://article.example.test/research/final/index.html",
        )
        reader = TrackingReader(store)
        monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("network"))
        monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: pytest.fail("network"))

        document = NormalizationPipeline(
            session,
            reader,
            max_payload_bytes=MAX_TEST_PAYLOAD_BYTES,
        ).normalize_snapshot(snapshot.id)

        assert document.normalization_status is NormalizationStatus.SUCCEEDED
        assert document.extractor_name == "html-basic"
        assert document.extractor_version == "1"
        assert document.parser_version == "stdlib-html-parser-v1"
        assert (
            document.content_fingerprint
            == hashlib.sha256(
                document.clean_text.encode()  # type: ignore[union-attr]
            ).hexdigest()
        )
        assert snapshot.body_sha256 == hashlib.sha256(SYNTHETIC_HTML.encode()).hexdigest()
        assert snapshot.body_size_bytes == len(SYNTHETIC_HTML.encode())
        assert reader.refs == [RawPayloadRef(snapshot.raw_payload_ref)]
        assert reader.limits == [MAX_TEST_PAYLOAD_BYTES]
        persisted_snapshot = session.get(FetchSnapshot, document.fetch_snapshot_id)
        persisted_item = session.get(DiscoveryItem, persisted_snapshot.discovery_item_id)
        persisted_source = session.get(Source, persisted_item.source_id)
        assert (persisted_snapshot.id, persisted_item.id, persisted_source.id) == (
            snapshot.id,
            item.id,
            source.id,
        )

    @pytest.mark.parametrize(
        ("content_type", "payload", "extractor_name"),
        [
            ("application/xhtml+xml", b"<html><body><p>XHTML</p></body></html>", "html-basic"),
            ("text/plain", "Başlık\nMetin".encode(), "text-basic"),
        ],
    )
    def test_registry_selects_supported_media_types(
        self,
        session: Session,
        content_type: str,
        payload: bytes,
        extractor_name: str,
    ) -> None:
        snapshot, store, _, _ = make_snapshot(
            session, payload, content_type=content_type, suffix=extractor_name
        )
        document = NormalizationPipeline(
            session, store, max_payload_bytes=MAX_TEST_PAYLOAD_BYTES
        ).normalize_snapshot(snapshot.id)
        assert document.extractor_name == extractor_name
        assert document.normalization_status is NormalizationStatus.SUCCEEDED

    def test_identical_retry_is_idempotent_and_version_two_is_distinct(
        self, session: Session
    ) -> None:
        snapshot, store, _, _ = make_snapshot(session, b"<p>stable output</p>")
        pipeline = NormalizationPipeline(session, store, max_payload_bytes=MAX_TEST_PAYLOAD_BYTES)

        first = pipeline.normalize_snapshot(snapshot.id)
        second = pipeline.normalize_snapshot(snapshot.id)
        version_two = ConfigurableExtractor(
            ExtractedDocument(clean_text="version two", parser_version="test-parser-v2")
        )
        version_two.version = "2"
        third = pipeline.normalize_snapshot(snapshot.id, extractor=version_two)

        assert second is first
        assert third.id != first.id
        assert count_documents(session) == 2

    def test_conflicting_same_extractor_identity_is_protected(self, session: Session) -> None:
        snapshot, store, _, _ = make_snapshot(session, b"<p>input</p>")
        pipeline = NormalizationPipeline(session, store, max_payload_bytes=MAX_TEST_PAYLOAD_BYTES)
        pipeline.normalize_snapshot(
            snapshot.id,
            extractor=ConfigurableExtractor(
                ExtractedDocument(clean_text="first", parser_version="test-parser-v1")
            ),
        )

        with pytest.raises(NormalizationConflictError):
            pipeline.normalize_snapshot(
                snapshot.id,
                extractor=ConfigurableExtractor(
                    ExtractedDocument(clean_text="different", parser_version="test-parser-v1")
                ),
            )

    def test_unsupported_media_records_stable_failure(self, session: Session) -> None:
        snapshot, store, _, _ = make_snapshot(session, b"binary", content_type="application/pdf")
        document = NormalizationPipeline(
            session, store, max_payload_bytes=MAX_TEST_PAYLOAD_BYTES
        ).normalize_snapshot(snapshot.id)

        assert document.normalization_status is NormalizationStatus.FAILED
        assert document.failure_code is NormalizationFailureCode.UNSUPPORTED_CONTENT
        assert document.extractor_name == "unsupported-media"
        assert document.clean_text is None

    def test_payload_over_pipeline_limit_records_policy_failure(self, session: Session) -> None:
        snapshot, store, _, _ = make_snapshot(session, b"<p>bounded payload</p>")
        document = NormalizationPipeline(session, store, max_payload_bytes=5).normalize_snapshot(
            snapshot.id
        )
        assert document.failure_code is NormalizationFailureCode.POLICY_REJECTED


class TestFailureAndIntegrityBoundaries:
    @pytest.mark.parametrize(
        ("error", "expected_code"),
        [
            (ExtractorDecodeError("safe decode"), NormalizationFailureCode.DECODE_ERROR),
            (ExtractorParseError("safe parse"), NormalizationFailureCode.PARSE_ERROR),
            (ExtractorEmptyContentError("safe empty"), NormalizationFailureCode.EMPTY_CONTENT),
            (ExtractorPolicyError("safe policy"), NormalizationFailureCode.POLICY_REJECTED),
            (RuntimeError("secret traceback detail"), NormalizationFailureCode.EXTRACTOR_ERROR),
        ],
    )
    def test_extractor_failures_map_to_existing_vocabulary(
        self,
        session: Session,
        error: Exception,
        expected_code: NormalizationFailureCode,
    ) -> None:
        snapshot, store, _, _ = make_snapshot(session, b"<p>input</p>")
        document = NormalizationPipeline(
            session, store, max_payload_bytes=MAX_TEST_PAYLOAD_BYTES
        ).normalize_snapshot(snapshot.id, extractor=ConfigurableExtractor(error))

        assert document.failure_code is expected_code
        assert document.clean_text is None
        if isinstance(error, RuntimeError):
            assert document.failure_detail == "extractor failed unexpectedly"
            assert "secret" not in document.failure_detail

    def test_real_strict_decode_failure_is_persisted(self, session: Session) -> None:
        snapshot, store, _, _ = make_snapshot(
            session,
            b"\xff\xfe",
            content_type="text/plain; charset=utf-8",
        )
        document = NormalizationPipeline(
            session, store, max_payload_bytes=MAX_TEST_PAYLOAD_BYTES
        ).normalize_snapshot(snapshot.id)
        assert document.failure_code is NormalizationFailureCode.DECODE_ERROR

    @pytest.mark.parametrize("replacement", [b"same size bad", b"short"])
    def test_payload_provenance_violation_raises_without_document(
        self, session: Session, replacement: bytes
    ) -> None:
        original = b"same size ok!"
        snapshot, _store, _, _ = make_snapshot(session, original)
        with pytest.raises(NormalizationPipelineIntegrityError):
            NormalizationPipeline(
                session,
                StaticReader(replacement),
                max_payload_bytes=MAX_TEST_PAYLOAD_BYTES,
            ).normalize_snapshot(snapshot.id)
        assert count_documents(session) == 0

    def test_missing_payload_is_pipeline_error_without_document(self, session: Session) -> None:
        snapshot, _store, _, _ = make_snapshot(session, b"<p>stored elsewhere</p>")
        with pytest.raises(NormalizationPipelinePayloadError):
            NormalizationPipeline(
                session,
                InMemoryRawPayloadStore(),
                max_payload_bytes=MAX_TEST_PAYLOAD_BYTES,
            ).normalize_snapshot(snapshot.id)
        assert count_documents(session) == 0

    @pytest.mark.parametrize("field", ["raw_payload_ref", "body_sha256", "body_size_bytes"])
    def test_missing_provenance_is_not_eligible(self, session: Session, field: str) -> None:
        snapshot, store, _, _ = make_snapshot(session, b"<p>content</p>")
        setattr(snapshot, field, None)
        session.flush()

        with pytest.raises(FetchSnapshotNotEligibleError):
            NormalizationPipeline(
                session, store, max_payload_bytes=MAX_TEST_PAYLOAD_BYTES
            ).normalize_snapshot(snapshot.id)
        assert count_documents(session) == 0

    def test_failed_and_nonexistent_snapshots_are_typed(self, session: Session) -> None:
        failed = make_failed_snapshot(session)
        pipeline = NormalizationPipeline(
            session, InMemoryRawPayloadStore(), max_payload_bytes=MAX_TEST_PAYLOAD_BYTES
        )
        with pytest.raises(FetchSnapshotNotEligibleError):
            pipeline.normalize_snapshot(failed.id)
        with pytest.raises(FetchSnapshotNotFoundError):
            pipeline.normalize_snapshot(uuid.uuid4())

    def test_extractor_result_is_frozen_and_contains_no_raw_payload(self) -> None:
        document = ExtractedDocument(clean_text="immutable", parser_version="parser-v1")
        with pytest.raises(FrozenInstanceError):
            document.clean_text = "changed"  # type: ignore[misc]
        assert not hasattr(document, "payload")
        assert not hasattr(document, "raw_bytes")

    def test_ambiguous_registry_fails_fast(self, session: Session) -> None:
        first = ConfigurableExtractor(
            ExtractedDocument(clean_text="one", parser_version="test-parser-v1")
        )
        second = ConfigurableExtractor(
            ExtractedDocument(clean_text="two", parser_version="test-parser-v1")
        )
        second.version = "2"
        with pytest.raises(NormalizationPipelineConfigurationError):
            NormalizationPipeline(
                session,
                InMemoryRawPayloadStore(),
                max_payload_bytes=MAX_TEST_PAYLOAD_BYTES,
                extractors=(first, second),
            )
