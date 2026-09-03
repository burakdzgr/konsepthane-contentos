"""Offline contract tests for bounded sitemap discovery."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from html import escape

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import contentos.discovery.sitemap as sitemap_module
from contentos.db.base import Base
from contentos.discovery.enums import (
    DiscoveryLifecycleState,
    DiscoveryMethod,
    DiscoveryRejectionReason,
)
from contentos.discovery.models import DiscoveryItem
from contentos.discovery.service import DiscoveryService
from contentos.discovery.sitemap import (
    MAX_SITEMAP_DOCUMENT_BYTES,
    SitemapDiscoveryStrategy,
    SitemapFetchRetryableError,
    SitemapFetchTerminalError,
    SitemapParseError,
    SitemapSourceNotEligibleError,
    SitemapTraversalLimitExceededError,
    UnsupportedSitemapContentError,
)
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
)
from contentos.sources.enums import (
    DiscoveryStrategy,
    SourceKind,
    SourceLifecycleState,
    TrustTier,
)
from contentos.sources.models import Source
from contentos.sources.service import SourceRegistryService

SITEMAP_URL = "https://www.example.test/sitemap.xml"
FETCHED_AT = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
XMLNS = ' xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


class FakeFetchClient:
    """Deterministic FetchClient substitute; it never performs network I/O."""

    def __init__(self, responses: dict[str, FetchResult]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        return self.responses[url]


@pytest.fixture()
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session
    engine.dispose()


def make_source(
    session: Session,
    *,
    kind: SourceKind = SourceKind.SITEMAP,
    strategy: DiscoveryStrategy = DiscoveryStrategy.SITEMAP,
) -> Source:
    return SourceRegistryService(session).register_source(
        slug="site-haritasi",
        name="Site haritasi",
        kind=kind,
        base_url=SITEMAP_URL,
        trust_tier=TrustTier.GENERAL,
        discovery_strategy=strategy,
    )


def successful_fetch(
    url: str,
    body: bytes,
    *,
    content_type: str = "application/xml",
    final_url: str | None = None,
) -> FetchResult:
    return FetchResult(
        requested_url=url,
        outcome=FetchOutcome.SUCCESS,
        retry=RetryClassification.NOT_APPLICABLE,
        robots_decision=RobotsDecision.ALLOWED,
        fetched_at=FETCHED_AT,
        duration_ms=3.5,
        final_url=final_url or url,
        status_code=200,
        content_type=content_type,
        body=body,
    )


def failed_fetch(
    url: str,
    outcome: FetchOutcome,
    retry: RetryClassification,
    *,
    retry_after_seconds: float | None = None,
) -> FetchResult:
    return FetchResult(
        requested_url=url,
        outcome=outcome,
        retry=retry,
        robots_decision=(
            RobotsDecision.DISALLOWED
            if outcome is FetchOutcome.ROBOTS_DISALLOWED
            else RobotsDecision.NOT_EVALUATED
        ),
        fetched_at=FETCHED_AT,
        duration_ms=1.0,
        retry_after_seconds=retry_after_seconds,
    )


def urlset(*entries: tuple[str | None, str | None], namespaced: bool = True) -> bytes:
    items = []
    for url, lastmod in entries:
        loc = f"<loc>{escape(url)}</loc>" if url is not None else ""
        modified = f"<lastmod>{escape(lastmod)}</lastmod>" if lastmod is not None else ""
        items.append(f"<url>{loc}{modified}</url>")
    namespace = XMLNS if namespaced else ""
    return f"<?xml version='1.0'?><urlset{namespace}>{''.join(items)}</urlset>".encode()


def sitemap_index(*entries: str | None, namespaced: bool = True) -> bytes:
    items = []
    for url in entries:
        loc = f"<loc>{escape(url)}</loc>" if url is not None else ""
        items.append(f"<sitemap>{loc}</sitemap>")
    namespace = XMLNS if namespaced else ""
    return f"<sitemapindex{namespace}>{''.join(items)}</sitemapindex>".encode()


def all_items(session: Session) -> list[DiscoveryItem]:
    return list(
        session.execute(select(DiscoveryItem).order_by(DiscoveryItem.canonical_url)).scalars()
    )


class TestSourceEligibility:
    def test_active_sitemap_source_is_allowed(self, session: Session) -> None:
        source = make_source(session)
        fetcher = FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, urlset())})

        result = SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        assert result.source_id == source.id
        assert result.sitemap_documents_fetched == 1
        assert fetcher.calls == [source.base_url]

    @pytest.mark.parametrize(
        "state",
        [
            SourceLifecycleState.PAUSED,
            SourceLifecycleState.DISABLED,
            SourceLifecycleState.BLOCKED,
        ],
    )
    def test_inactive_source_is_rejected_before_fetch(
        self, session: Session, state: SourceLifecycleState
    ) -> None:
        source = make_source(session)
        SourceRegistryService(session).transition_source_state(source.id, state, reason="test")
        fetcher = FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, urlset())})

        with pytest.raises(SitemapSourceNotEligibleError):
            SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        assert fetcher.calls == []

    @pytest.mark.parametrize(
        ("kind", "strategy"),
        [
            (SourceKind.MANUAL, DiscoveryStrategy.SITEMAP),
            (SourceKind.SITEMAP, DiscoveryStrategy.FEED),
            (SourceKind.RSS_FEED, DiscoveryStrategy.SITEMAP),
        ],
    )
    def test_wrong_kind_or_strategy_is_rejected(
        self, session: Session, kind: SourceKind, strategy: DiscoveryStrategy
    ) -> None:
        source = make_source(session, kind=kind, strategy=strategy)
        fetcher = FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, urlset())})

        with pytest.raises(SitemapSourceNotEligibleError):
            SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        assert fetcher.calls == []

    def test_missing_source_is_a_typed_eligibility_error(self, session: Session) -> None:
        fetcher = FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, urlset())})

        with pytest.raises(SitemapSourceNotEligibleError):
            SitemapDiscoveryStrategy(session, fetcher).execute(uuid.uuid4())

        assert fetcher.calls == []


class TestUrlSetDiscovery:
    def test_namespaced_urlset_admits_candidates_through_discovery_service(
        self, session: Session
    ) -> None:
        source = make_source(session)
        body = urlset(
            ("https://www.example.test/articles/one?utm_source=map#top", "2026-08-30"),
            ("HTTPS://WWW.EXAMPLE.TEST:443/articles/two/", "2026-08-31T08:30:00Z"),
        )

        result = SitemapDiscoveryStrategy(
            session,
            FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, body)}),
        ).execute(source.id)
        items = all_items(session)

        assert result.entries_seen == 2
        assert result.admitted_new == 2
        assert result.rediscovered_existing == 0
        assert result.root_sitemap_url == SITEMAP_URL
        assert result.fetch_outcomes == (FetchOutcome.SUCCESS,)
        assert [item.canonical_url for item in items] == [
            "https://www.example.test/articles/one",
            "https://www.example.test/articles/two",
        ]
        assert [item.discovery_method for item in items] == [DiscoveryMethod.SITEMAP] * 2
        assert all(item.title_hint is None for item in items)
        assert all(item.snippet_hint is None for item in items)
        assert all(item.external_published_at is None for item in items)

    def test_unnamespaced_urlset_is_supported(self, session: Session) -> None:
        source = make_source(session)
        body = urlset(("https://www.example.test/plain", None), namespaced=False)

        result = SitemapDiscoveryStrategy(
            session,
            FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, body)}),
        ).execute(source.id)

        assert result.admitted_new == 1

    def test_missing_relative_malformed_and_oversized_urls_are_skipped(
        self, session: Session
    ) -> None:
        source = make_source(session)
        body = urlset(
            (None, None),
            ("../relative", None),
            ("http://[broken", None),
            ("https://www.example.test/" + "x" * 2_000, None),
            ("https://www.example.test/valid", None),
        )

        result = SitemapDiscoveryStrategy(
            session,
            FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, body)}),
        ).execute(source.id)

        assert result.entries_seen == 5
        assert result.admitted_new == 1
        assert result.skipped_missing_url == 1
        assert result.skipped_invalid == 3

    def test_invalid_lastmod_is_warned_but_never_used_as_publication_time(
        self, session: Session
    ) -> None:
        source = make_source(session)
        body = urlset(("https://www.example.test/story", "not-a-date"))

        result = SitemapDiscoveryStrategy(
            session,
            FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, body)}),
        ).execute(source.id)

        assert "unparseable_lastmod" in result.parse_warnings
        assert all_items(session)[0].external_published_at is None

    def test_extension_elements_do_not_change_core_namespace_parsing(
        self, session: Session
    ) -> None:
        source = make_source(session)
        body = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
          xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
          <url><loc>https://www.example.test/image-story</loc>
          <image:image><image:loc>https://cdn.example.test/image.jpg</image:loc></image:image>
          </url></urlset>"""

        result = SitemapDiscoveryStrategy(
            session,
            FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, body)}),
        ).execute(source.id)

        assert result.admitted_new == 1


class TestSitemapIndexTraversal:
    def test_index_and_nested_index_fetch_every_child_through_fetch_client(
        self, session: Session
    ) -> None:
        source = make_source(session)
        first = "https://www.example.test/maps/first.xml"
        nested = "https://www.example.test/maps/nested.xml"
        second = "https://www.example.test/maps/second.xml"
        fetcher = FakeFetchClient(
            {
                SITEMAP_URL: successful_fetch(SITEMAP_URL, sitemap_index(first, nested)),
                first: successful_fetch(first, urlset(("https://www.example.test/first", None))),
                nested: successful_fetch(nested, sitemap_index(second)),
                second: successful_fetch(second, urlset(("https://www.example.test/second", None))),
            }
        )

        result = SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        assert result.sitemap_documents_fetched == 4
        assert result.entries_seen == 2
        assert result.admitted_new == 2
        assert fetcher.calls == [SITEMAP_URL, first, nested, second]

    def test_duplicate_and_circular_child_sitemaps_are_not_refetched(
        self, session: Session
    ) -> None:
        source = make_source(session)
        child = "https://www.example.test/child.xml"
        fetcher = FakeFetchClient(
            {
                SITEMAP_URL: successful_fetch(SITEMAP_URL, sitemap_index(child, child)),
                child: successful_fetch(child, sitemap_index(SITEMAP_URL)),
            }
        )

        result = SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        assert result.sitemap_documents_fetched == 2
        assert result.skipped_duplicate_sitemap == 2
        assert fetcher.calls == [SITEMAP_URL, child]

    def test_cross_origin_and_relative_child_sitemaps_are_skipped(self, session: Session) -> None:
        source = make_source(session)
        cross_origin = "https://other.example.test/child.xml"
        fetcher = FakeFetchClient(
            {
                SITEMAP_URL: successful_fetch(
                    SITEMAP_URL, sitemap_index(cross_origin, "maps/relative.xml")
                )
            }
        )

        result = SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        assert result.sitemap_documents_fetched == 1
        assert result.skipped_cross_origin_sitemap == 1
        assert result.skipped_invalid == 1
        assert "cross_origin_sitemap_skipped" in result.parse_warnings
        assert fetcher.calls == [SITEMAP_URL]

    def test_root_redirect_final_origin_governs_children(self, session: Session) -> None:
        source = make_source(session)
        final_root = "https://canonical.example.test/sitemap.xml"
        child = "https://canonical.example.test/child.xml"
        fetcher = FakeFetchClient(
            {
                SITEMAP_URL: successful_fetch(
                    SITEMAP_URL, sitemap_index(child), final_url=final_root
                ),
                child: successful_fetch(child, urlset()),
            }
        )

        result = SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        assert result.root_sitemap_url == final_root
        assert result.sitemap_documents_fetched == 2

    def test_child_redirect_to_cross_origin_is_not_parsed(self, session: Session) -> None:
        source = make_source(session)
        child = "https://www.example.test/child.xml"
        cross_origin_final = "https://other.example.test/child.xml"
        fetcher = FakeFetchClient(
            {
                SITEMAP_URL: successful_fetch(SITEMAP_URL, sitemap_index(child)),
                child: successful_fetch(
                    child,
                    urlset(("https://www.example.test/must-not-be-admitted", None)),
                    final_url=cross_origin_final,
                ),
            }
        )

        result = SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        assert result.sitemap_documents_fetched == 2
        assert result.skipped_cross_origin_sitemap == 1
        assert "cross_origin_sitemap_redirect_skipped" in result.parse_warnings
        assert result.admitted_new == 0


class TestLimitsAndParserSecurity:
    def test_sitemap_index_entry_limit_is_enforced(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = make_source(session)
        monkeypatch.setattr(sitemap_module, "MAX_SITEMAP_INDEX_ENTRIES", 1)
        body = sitemap_index(
            "https://www.example.test/one.xml",
            "https://www.example.test/two.xml",
        )

        with pytest.raises(SitemapTraversalLimitExceededError) as captured:
            SitemapDiscoveryStrategy(
                session,
                FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, body)}),
            ).execute(source.id)

        assert captured.value.limit_name == "sitemap-index entry count"

    def test_per_document_url_entry_limit_is_enforced(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = make_source(session)
        monkeypatch.setattr(sitemap_module, "MAX_SITEMAP_URL_ENTRIES", 1)
        body = urlset(
            ("https://www.example.test/one", None),
            ("https://www.example.test/two", None),
        )

        with pytest.raises(SitemapTraversalLimitExceededError) as captured:
            SitemapDiscoveryStrategy(
                session,
                FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, body)}),
            ).execute(source.id)

        assert captured.value.limit_name == "URL entries"

    def test_depth_limit_is_enforced_before_fetching_deeper_child(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = make_source(session)
        child = "https://www.example.test/child.xml"
        too_deep = "https://www.example.test/too-deep.xml"
        monkeypatch.setattr(sitemap_module, "MAX_SITEMAP_DEPTH", 1)
        fetcher = FakeFetchClient(
            {
                SITEMAP_URL: successful_fetch(SITEMAP_URL, sitemap_index(child)),
                child: successful_fetch(child, sitemap_index(too_deep)),
            }
        )

        with pytest.raises(SitemapTraversalLimitExceededError) as captured:
            SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        assert captured.value.limit_name == "depth"
        assert fetcher.calls == [SITEMAP_URL, child]

    def test_document_limit_is_enforced(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = make_source(session)
        first = "https://www.example.test/first.xml"
        second = "https://www.example.test/second.xml"
        monkeypatch.setattr(sitemap_module, "MAX_SITEMAP_DOCUMENTS", 2)
        fetcher = FakeFetchClient(
            {
                SITEMAP_URL: successful_fetch(SITEMAP_URL, sitemap_index(first, second)),
                first: successful_fetch(first, urlset()),
                second: successful_fetch(second, urlset()),
            }
        )

        with pytest.raises(SitemapTraversalLimitExceededError) as captured:
            SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        assert captured.value.limit_name == "document count"
        assert fetcher.calls == [SITEMAP_URL, first]

    def test_total_url_limit_is_enforced(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = make_source(session)
        monkeypatch.setattr(sitemap_module, "MAX_SITEMAP_URLS", 2)
        first = "https://www.example.test/first.xml"
        second = "https://www.example.test/second.xml"
        fetcher = FakeFetchClient(
            {
                SITEMAP_URL: successful_fetch(SITEMAP_URL, sitemap_index(first, second)),
                first: successful_fetch(
                    first,
                    urlset(
                        ("https://www.example.test/one", None),
                        ("https://www.example.test/two", None),
                    ),
                ),
                second: successful_fetch(second, urlset(("https://www.example.test/three", None))),
            }
        )

        result = SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        # The URL cap TRUNCATES honestly instead of failing the run:
        # everything admitted before the cap stays, the truncation is a
        # recorded warning, and traversal stops.
        assert result.admitted_new == 2
        assert result.entries_seen == 2
        assert "url_limit_truncated" in result.parse_warnings
        assert session.scalar(select(func.count()).select_from(DiscoveryItem)) == 2

    @pytest.mark.parametrize(
        "body",
        [
            b"<urlset><url></urlset>",
            b'<!DOCTYPE urlset [<!ENTITY x SYSTEM "file:///etc/passwd">]><urlset/>',
            b'<!DOCTYPE urlset [<!ENTITY x "ha">]><urlset>&x;</urlset>',
        ],
    )
    def test_malformed_or_declared_entity_xml_is_rejected(
        self, session: Session, body: bytes
    ) -> None:
        source = make_source(session)

        with pytest.raises(SitemapParseError):
            SitemapDiscoveryStrategy(
                session,
                FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, body)}),
            ).execute(source.id)

    def test_document_byte_limit_is_enforced_before_xml_parse(self, session: Session) -> None:
        source = make_source(session)
        body = b"x" * (MAX_SITEMAP_DOCUMENT_BYTES + 1)

        with pytest.raises(SitemapParseError, match="byte limit"):
            SitemapDiscoveryStrategy(
                session,
                FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, body)}),
            ).execute(source.id)

    def test_element_limit_is_enforced(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = make_source(session)
        monkeypatch.setattr(sitemap_module, "MAX_SITEMAP_ELEMENTS", 2)

        with pytest.raises(SitemapParseError, match="element limit"):
            SitemapDiscoveryStrategy(
                session,
                FakeFetchClient(
                    {
                        SITEMAP_URL: successful_fetch(
                            SITEMAP_URL,
                            urlset(("https://www.example.test/one", None)),
                        )
                    }
                ),
            ).execute(source.id)

    @pytest.mark.parametrize(
        "body",
        [
            b"<html><body>not a sitemap</body></html>",
            b'<urlset xmlns="https://example.test/not-sitemap"><url /></urlset>',
            b"<urlset-extra><url /></urlset-extra>",
        ],
    )
    def test_unsupported_root_or_namespace_is_rejected(self, session: Session, body: bytes) -> None:
        source = make_source(session)

        with pytest.raises(UnsupportedSitemapContentError):
            SitemapDiscoveryStrategy(
                session,
                FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, body)}),
            ).execute(source.id)


class TestFetchOutcomeMapping:
    @pytest.mark.parametrize(
        "outcome",
        [FetchOutcome.TIMEOUT, FetchOutcome.NETWORK_ERROR, FetchOutcome.ROBOTS_UNAVAILABLE],
    )
    def test_retryable_fetch_outcomes_are_mapped(
        self, session: Session, outcome: FetchOutcome
    ) -> None:
        source = make_source(session)
        fetcher = FakeFetchClient(
            {
                SITEMAP_URL: failed_fetch(
                    SITEMAP_URL,
                    outcome,
                    RetryClassification.RETRYABLE,
                    retry_after_seconds=45.0,
                )
            }
        )

        with pytest.raises(SitemapFetchRetryableError) as captured:
            SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        assert captured.value.outcome is outcome
        assert captured.value.retry_after_seconds == 45.0

    @pytest.mark.parametrize(
        "outcome",
        [
            FetchOutcome.SSRF_BLOCKED,
            FetchOutcome.ROBOTS_DISALLOWED,
            FetchOutcome.INVALID_URL,
            FetchOutcome.TOO_LARGE,
            FetchOutcome.REDIRECT_LIMIT_EXCEEDED,
        ],
    )
    def test_terminal_fetch_outcomes_are_mapped(
        self, session: Session, outcome: FetchOutcome
    ) -> None:
        source = make_source(session)
        fetcher = FakeFetchClient(
            {SITEMAP_URL: failed_fetch(SITEMAP_URL, outcome, RetryClassification.TERMINAL)}
        )

        with pytest.raises(SitemapFetchTerminalError) as captured:
            SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        assert captured.value.outcome is outcome

    def test_child_fetch_failure_uses_same_typed_contract(self, session: Session) -> None:
        source = make_source(session)
        child = "https://www.example.test/child.xml"
        fetcher = FakeFetchClient(
            {
                SITEMAP_URL: successful_fetch(SITEMAP_URL, sitemap_index(child)),
                child: failed_fetch(
                    child, FetchOutcome.NETWORK_ERROR, RetryClassification.RETRYABLE
                ),
            }
        )

        with pytest.raises(SitemapFetchRetryableError) as captured:
            SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

        assert captured.value.sitemap_url == child
        assert fetcher.calls == [SITEMAP_URL, child]

    def test_fetch_disallowed_mime_never_reaches_parser(self, session: Session) -> None:
        source = make_source(session)
        fetcher = FakeFetchClient(
            {
                SITEMAP_URL: failed_fetch(
                    SITEMAP_URL,
                    FetchOutcome.DISALLOWED_MIME,
                    RetryClassification.TERMINAL,
                )
            }
        )

        with pytest.raises(UnsupportedSitemapContentError):
            SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

    @pytest.mark.parametrize(
        "content_type", ["text/html", "text/plain", "application/rss+xml", "application/gzip"]
    )
    def test_successful_non_sitemap_media_type_is_rejected(
        self, session: Session, content_type: str
    ) -> None:
        source = make_source(session)
        fetcher = FakeFetchClient(
            {SITEMAP_URL: successful_fetch(SITEMAP_URL, urlset(), content_type=content_type)}
        )

        with pytest.raises(UnsupportedSitemapContentError):
            SitemapDiscoveryStrategy(session, fetcher).execute(source.id)

    @pytest.mark.parametrize("content_type", ["application/xml; charset=utf-8", "text/xml"])
    def test_supported_xml_media_types_reach_parser(
        self, session: Session, content_type: str
    ) -> None:
        source = make_source(session)

        result = SitemapDiscoveryStrategy(
            session,
            FakeFetchClient(
                {SITEMAP_URL: successful_fetch(SITEMAP_URL, urlset(), content_type=content_type)}
            ),
        ).execute(source.id)

        assert result.fetch_outcomes == (FetchOutcome.SUCCESS,)


class TestIdempotency:
    def test_canonical_variants_dedupe_within_and_across_runs(self, session: Session) -> None:
        source = make_source(session)
        body = urlset(
            ("https://www.example.test/story?b=2&a=1&utm_source=map#top", None),
            ("HTTPS://WWW.EXAMPLE.TEST:443/story/?a=1&b=2", None),
        )
        fetcher = FakeFetchClient({SITEMAP_URL: successful_fetch(SITEMAP_URL, body)})
        strategy = SitemapDiscoveryStrategy(session, fetcher)

        first = strategy.execute(source.id)
        second = strategy.execute(source.id)

        assert first.admitted_new == 1
        assert first.rediscovered_existing == 1
        assert second.admitted_new == 0
        assert second.rediscovered_existing == 2
        assert session.scalar(select(func.count()).select_from(DiscoveryItem)) == 1

    @pytest.mark.parametrize(
        "terminal_state",
        [DiscoveryLifecycleState.REJECTED, DiscoveryLifecycleState.FETCHED],
    )
    def test_rerun_preserves_terminal_discovery_state(
        self, session: Session, terminal_state: DiscoveryLifecycleState
    ) -> None:
        source = make_source(session)
        fetcher = FakeFetchClient(
            {
                SITEMAP_URL: successful_fetch(
                    SITEMAP_URL, urlset(("https://www.example.test/story", None))
                )
            }
        )
        strategy = SitemapDiscoveryStrategy(session, fetcher)
        strategy.execute(source.id)
        item = all_items(session)[0]
        service = DiscoveryService(session)
        if terminal_state is DiscoveryLifecycleState.REJECTED:
            service.reject_item(item.id, DiscoveryRejectionReason.OUT_OF_SCOPE)
        else:
            service.accept_item(item.id)
            service.mark_fetched(item.id)

        result = strategy.execute(source.id)

        assert result.rediscovered_existing == 1
        assert item.lifecycle_state is terminal_state
