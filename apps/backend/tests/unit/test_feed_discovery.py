"""Offline tests for defensive RSS/Atom feed discovery."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from xml.sax.saxutils import escape

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from contentos.db.base import Base
from contentos.discovery.enums import (
    DiscoveryLifecycleState,
    DiscoveryMethod,
    DiscoveryRejectionReason,
)
from contentos.discovery.feed import (
    MAX_FEED_DOCUMENT_BYTES,
    MAX_FEED_ELEMENTS,
    MAX_FEED_ENTRIES,
    MAX_FEED_SNIPPET_LENGTH,
    MAX_FEED_TITLE_LENGTH,
    FeedDiscoveryStrategy,
    FeedFetchRetryableError,
    FeedFetchTerminalError,
    FeedParseError,
    FeedSourceNotEligibleError,
    UnsupportedFeedContentError,
)
from contentos.discovery.models import DiscoveryItem
from contentos.discovery.service import DiscoveryService
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

FEED_URL = "https://feeds.example.test/news/feed.xml"
FETCHED_AT = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)


class FakeFetchClient:
    """Deterministic FetchClient substitute; it never performs network I/O."""

    def __init__(self, result: FetchResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.calls.append(url)
        return self.result


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
    slug: str = "haber-akisi",
    kind: SourceKind = SourceKind.RSS_FEED,
    strategy: DiscoveryStrategy = DiscoveryStrategy.FEED,
) -> Source:
    return SourceRegistryService(session).register_source(
        slug=slug,
        name=f"Kaynak {slug}",
        kind=kind,
        base_url=FEED_URL,
        trust_tier=TrustTier.GENERAL,
        discovery_strategy=strategy,
    )


def successful_fetch(
    body: bytes,
    *,
    content_type: str = "application/rss+xml",
    final_url: str = FEED_URL,
) -> FetchResult:
    return FetchResult(
        requested_url=FEED_URL,
        outcome=FetchOutcome.SUCCESS,
        retry=RetryClassification.NOT_APPLICABLE,
        robots_decision=RobotsDecision.ALLOWED,
        fetched_at=FETCHED_AT,
        duration_ms=4.2,
        final_url=final_url,
        status_code=200,
        content_type=content_type,
        body=body,
    )


def failed_fetch(
    outcome: FetchOutcome,
    retry: RetryClassification,
    *,
    body: bytes | None = None,
    retry_after_seconds: float | None = None,
) -> FetchResult:
    return FetchResult(
        requested_url=FEED_URL,
        outcome=outcome,
        retry=retry,
        robots_decision=(
            RobotsDecision.DISALLOWED
            if outcome is FetchOutcome.ROBOTS_DISALLOWED
            else RobotsDecision.NOT_EVALUATED
        ),
        fetched_at=FETCHED_AT,
        duration_ms=1.0,
        body=body,
        retry_after_seconds=retry_after_seconds,
    )


def rss_feed(items: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel><title>Synthetic feed</title>'
        f"{items}</channel></rss>"
    ).encode()


def rss_item(
    link: str | None,
    *,
    title: str = "Entry title",
    description: str = "Entry summary",
    published: str | None = None,
) -> str:
    link_xml = f"<link>{escape(link)}</link>" if link is not None else ""
    published_xml = f"<pubDate>{published}</pubDate>" if published is not None else ""
    return (
        f"<item><title>{title}</title>{link_xml}"
        f"<description>{description}</description>{published_xml}</item>"
    )


def all_items(session: Session) -> list[DiscoveryItem]:
    return list(
        session.execute(select(DiscoveryItem).order_by(DiscoveryItem.canonical_url)).scalars()
    )


class TestSourceEligibility:
    def test_active_feed_source_is_allowed(self, session: Session) -> None:
        source = make_source(session)
        fetcher = FakeFetchClient(successful_fetch(rss_feed("")))

        result = FeedDiscoveryStrategy(session, fetcher).execute(source.id)

        assert result.source_id == source.id
        assert result.entries_seen == 0
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
        fetcher = FakeFetchClient(successful_fetch(rss_feed("")))

        with pytest.raises(FeedSourceNotEligibleError):
            FeedDiscoveryStrategy(session, fetcher).execute(source.id)

        assert fetcher.calls == []

    @pytest.mark.parametrize(
        ("kind", "strategy"),
        [
            (SourceKind.MANUAL, DiscoveryStrategy.FEED),
            (SourceKind.RSS_FEED, DiscoveryStrategy.SITEMAP),
        ],
    )
    def test_wrong_kind_or_strategy_is_rejected(
        self,
        session: Session,
        kind: SourceKind,
        strategy: DiscoveryStrategy,
    ) -> None:
        source = make_source(session, kind=kind, strategy=strategy)
        fetcher = FakeFetchClient(successful_fetch(rss_feed("")))

        with pytest.raises(FeedSourceNotEligibleError):
            FeedDiscoveryStrategy(session, fetcher).execute(source.id)

        assert fetcher.calls == []

    def test_missing_source_is_a_typed_eligibility_error(self, session: Session) -> None:
        fetcher = FakeFetchClient(successful_fetch(rss_feed("")))

        with pytest.raises(FeedSourceNotEligibleError):
            FeedDiscoveryStrategy(session, fetcher).execute(uuid.uuid4())

        assert fetcher.calls == []


class TestRssDiscovery:
    def test_rss_items_store_sanitized_hints_dates_and_resolved_urls(
        self, session: Session
    ) -> None:
        source = make_source(session)
        body = rss_feed(
            rss_item(
                "https://articles.example.test/one?utm_source=feed#fragment",
                title="First title",
                description="&lt;p&gt;First &lt;strong&gt;summary&lt;/strong&gt;&lt;/p&gt;",
                published="Sun, 31 Aug 2026 10:30:00 +0300",
            )
            + rss_item(
                "../articles/two",
                title="Second title",
                description="Second summary",
            )
        )

        result = FeedDiscoveryStrategy(session, FakeFetchClient(successful_fetch(body))).execute(
            source.id
        )
        items = all_items(session)

        assert result.entries_seen == 2
        assert result.admitted_new == 2
        assert result.rediscovered_existing == 0
        assert result.feed_url == FEED_URL
        assert result.fetched_at == FETCHED_AT
        assert result.fetch_outcome is FetchOutcome.SUCCESS
        assert [item.discovery_method for item in items] == [DiscoveryMethod.FEED] * 2
        assert items[0].canonical_url == "https://articles.example.test/one"
        assert items[0].title_hint == "First title"
        assert items[0].snippet_hint == "First summary"
        assert items[0].external_published_at is not None
        assert items[0].external_published_at.replace(tzinfo=UTC) == datetime(
            2026, 8, 31, 7, 30, tzinfo=UTC
        )
        assert items[0].locale == source.locale
        assert items[1].canonical_url == "https://feeds.example.test/articles/two"

    def test_missing_and_invalid_links_are_skipped_without_aborting(self, session: Session) -> None:
        source = make_source(session)
        body = rss_feed(
            rss_item(None)
            + rss_item("ftp://example.test/not-http")
            + rss_item("http://[broken")
            + rss_item("https://example.test/" + "x" * 2_000)
            + rss_item("https://articles.example.test/valid")
        )

        result = FeedDiscoveryStrategy(session, FakeFetchClient(successful_fetch(body))).execute(
            source.id
        )

        assert result.entries_seen == 5
        assert result.admitted_new == 1
        assert result.skipped_missing_url == 1
        assert result.skipped_invalid == 3
        assert len(all_items(session)) == 1

    def test_relative_link_uses_fetch_result_final_url(self, session: Session) -> None:
        source = make_source(session)
        final_url = "https://redirected.example.test/feeds/current.xml"
        body = rss_feed(rss_item("../articles/redirected"))

        result = FeedDiscoveryStrategy(
            session,
            FakeFetchClient(successful_fetch(body, final_url=final_url)),
        ).execute(source.id)

        assert result.feed_url == final_url
        assert all_items(session)[0].canonical_url == (
            "https://redirected.example.test/articles/redirected"
        )

    def test_malformed_publication_date_becomes_null_warning(self, session: Session) -> None:
        source = make_source(session)
        body = rss_feed(rss_item("https://example.test/a", published="not-a-date"))

        result = FeedDiscoveryStrategy(session, FakeFetchClient(successful_fetch(body))).execute(
            source.id
        )
        item = all_items(session)[0]

        assert item.external_published_at is None
        assert "unparseable_publication_date" in result.parse_warnings


class TestAtomDiscovery:
    def test_namespaced_atom_prefers_alternate_link_and_parses_updated(
        self, session: Session
    ) -> None:
        source = make_source(session)
        body = b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>Synthetic Atom</title>
          <entry>
            <title type="html">Atom &amp; entry</title>
            <link rel="self" href="/api/entry/1" />
            <link rel="alternate" href="../articles/atom-entry?fbclid=x#part" />
            <summary type="html">&lt;p&gt;Atom &lt;b&gt;summary&lt;/b&gt;&lt;/p&gt;</summary>
            <updated>2026-08-31T07:15:30Z</updated>
          </entry>
        </feed>"""

        result = FeedDiscoveryStrategy(
            session,
            FakeFetchClient(successful_fetch(body, content_type="application/atom+xml")),
        ).execute(source.id)
        item = all_items(session)[0]

        assert result.admitted_new == 1
        assert item.canonical_url == "https://feeds.example.test/articles/atom-entry"
        assert item.title_hint == "Atom & entry"
        assert item.snippet_hint == "Atom summary"
        assert item.external_published_at is not None
        assert item.external_published_at.replace(tzinfo=UTC) == datetime(
            2026, 8, 31, 7, 15, 30, tzinfo=UTC
        )

    def test_atom_content_is_a_summary_fallback_and_relative_link_is_resolved(
        self, session: Session
    ) -> None:
        source = make_source(session)
        body = b"""<feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Content fallback</title>
            <link href="article" />
            <content type="html">&lt;div&gt;Content hint&lt;/div&gt;</content>
            <published>2026-08-31T08:00:00+00:00</published>
          </entry>
        </feed>"""

        FeedDiscoveryStrategy(
            session,
            FakeFetchClient(successful_fetch(body, content_type="text/xml")),
        ).execute(source.id)
        item = all_items(session)[0]

        assert item.canonical_url == "https://feeds.example.test/news/article"
        assert item.snippet_hint == "Content hint"
        assert item.external_published_at is not None
        assert item.external_published_at.replace(tzinfo=UTC) == FETCHED_AT


class TestIdempotency:
    def test_canonical_variants_dedupe_through_discovery_service(self, session: Session) -> None:
        source = make_source(session)
        body = rss_feed(
            rss_item("https://example.test/story?b=2&a=1&utm_source=feed#top")
            + rss_item("HTTPS://EXAMPLE.TEST:443/story/?a=1&b=2")
        )

        result = FeedDiscoveryStrategy(session, FakeFetchClient(successful_fetch(body))).execute(
            source.id
        )

        assert result.admitted_new == 1
        assert result.rediscovered_existing == 1
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
            successful_fetch(rss_feed(rss_item("https://example.test/story", title="Original")))
        )
        strategy = FeedDiscoveryStrategy(session, fetcher)
        strategy.execute(source.id)
        item = all_items(session)[0]
        service = DiscoveryService(session)
        if terminal_state is DiscoveryLifecycleState.REJECTED:
            service.reject_item(item.id, DiscoveryRejectionReason.OUT_OF_SCOPE)
        else:
            service.accept_item(item.id)
            service.mark_fetched(item.id)
        fetcher.result = successful_fetch(
            rss_feed(rss_item("https://example.test/story?utm_medium=rss", title="Changed"))
        )

        result = strategy.execute(source.id)

        assert result.admitted_new == 0
        assert result.rediscovered_existing == 1
        assert item.lifecycle_state is terminal_state
        assert item.title_hint == "Original"


class TestLimitsAndParserSecurity:
    def test_maximum_entry_count_is_enforced(self, session: Session) -> None:
        source = make_source(session)
        items = "".join(
            rss_item(f"https://example.test/items/{index}") for index in range(MAX_FEED_ENTRIES + 5)
        )

        result = FeedDiscoveryStrategy(
            session, FakeFetchClient(successful_fetch(rss_feed(items)))
        ).execute(source.id)

        assert result.entries_seen == MAX_FEED_ENTRIES
        assert result.admitted_new == MAX_FEED_ENTRIES
        assert "entry_limit_reached" in result.parse_warnings

    def test_title_and_snippet_are_plain_text_and_truncated(self, session: Session) -> None:
        source = make_source(session)
        title = "T" * (MAX_FEED_TITLE_LENGTH + 20)
        description = "S" * (MAX_FEED_SNIPPET_LENGTH + 20)
        body = rss_feed(rss_item("https://example.test/long", title=title, description=description))

        result = FeedDiscoveryStrategy(session, FakeFetchClient(successful_fetch(body))).execute(
            source.id
        )
        item = all_items(session)[0]

        assert len(item.title_hint or "") == MAX_FEED_TITLE_LENGTH
        assert len(item.snippet_hint or "") == MAX_FEED_SNIPPET_LENGTH
        assert result.parse_warnings == ("title_truncated", "snippet_truncated")

    @pytest.mark.parametrize(
        "body",
        [
            b"<rss><channel><item></channel></rss>",
            b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss/>',
            b'<!DOCTYPE rss [<!ENTITY x "ha">]><rss>&x;</rss>',
        ],
    )
    def test_malformed_or_declared_entity_xml_is_rejected(
        self, session: Session, body: bytes
    ) -> None:
        source = make_source(session)

        with pytest.raises(FeedParseError):
            FeedDiscoveryStrategy(session, FakeFetchClient(successful_fetch(body))).execute(
                source.id
            )

    def test_document_byte_limit_is_enforced_before_xml_parse(self, session: Session) -> None:
        source = make_source(session)
        body = b"x" * (MAX_FEED_DOCUMENT_BYTES + 1)

        with pytest.raises(FeedParseError, match="byte limit"):
            FeedDiscoveryStrategy(session, FakeFetchClient(successful_fetch(body))).execute(
                source.id
            )

    def test_element_limit_is_enforced(self, session: Session) -> None:
        source = make_source(session)
        body = rss_feed("<x/>" * MAX_FEED_ELEMENTS)

        with pytest.raises(FeedParseError, match="element limit"):
            FeedDiscoveryStrategy(session, FakeFetchClient(successful_fetch(body))).execute(
                source.id
            )

    @pytest.mark.parametrize(
        "body",
        [
            b"<html><body>not a feed</body></html>",
            b'<feed xmlns="https://example.test/not-atom"><entry /></feed>',
            b'<rss version="2.0"></rss>',
        ],
    )
    def test_unsupported_root_namespace_or_structure_is_rejected(
        self, session: Session, body: bytes
    ) -> None:
        source = make_source(session)

        with pytest.raises(UnsupportedFeedContentError):
            FeedDiscoveryStrategy(session, FakeFetchClient(successful_fetch(body))).execute(
                source.id
            )


class TestFetchOutcomeMapping:
    @pytest.mark.parametrize(
        "outcome",
        [FetchOutcome.TIMEOUT, FetchOutcome.NETWORK_ERROR, FetchOutcome.ROBOTS_UNAVAILABLE],
    )
    def test_retryable_fetch_outcomes_are_mapped(
        self, session: Session, outcome: FetchOutcome
    ) -> None:
        source = make_source(session)
        result = failed_fetch(
            outcome,
            RetryClassification.RETRYABLE,
            retry_after_seconds=30.0,
        )

        with pytest.raises(FeedFetchRetryableError) as captured:
            FeedDiscoveryStrategy(session, FakeFetchClient(result)).execute(source.id)

        assert captured.value.outcome is outcome
        assert captured.value.retry_after_seconds == 30.0

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
        result = failed_fetch(outcome, RetryClassification.TERMINAL)

        with pytest.raises(FeedFetchTerminalError) as captured:
            FeedDiscoveryStrategy(session, FakeFetchClient(result)).execute(source.id)

        assert captured.value.outcome is outcome

    def test_fetch_disallowed_mime_never_reaches_parser(self, session: Session) -> None:
        source = make_source(session)
        result = failed_fetch(
            FetchOutcome.DISALLOWED_MIME,
            RetryClassification.TERMINAL,
            body=b"definitely not XML",
        )

        with pytest.raises(UnsupportedFeedContentError):
            FeedDiscoveryStrategy(session, FakeFetchClient(result)).execute(source.id)

    @pytest.mark.parametrize("content_type", ["text/html", "text/plain", None])
    def test_successful_non_feed_media_type_is_rejected_before_parse(
        self, session: Session, content_type: str | None
    ) -> None:
        source = make_source(session)
        result = successful_fetch(b"not XML", content_type=content_type or "")

        with pytest.raises(UnsupportedFeedContentError):
            FeedDiscoveryStrategy(session, FakeFetchClient(result)).execute(source.id)

    @pytest.mark.parametrize(
        "content_type",
        ["application/rss+xml", "application/xml; charset=utf-8", "text/xml"],
    )
    def test_supported_xml_media_types_reach_parser(
        self, session: Session, content_type: str
    ) -> None:
        source = make_source(session)

        result = FeedDiscoveryStrategy(
            session,
            FakeFetchClient(successful_fetch(rss_feed(""), content_type=content_type)),
        ).execute(source.id)

        assert result.fetch_outcome is FetchOutcome.SUCCESS
