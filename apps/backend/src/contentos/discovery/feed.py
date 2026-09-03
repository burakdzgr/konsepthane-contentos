"""Defensive RSS/Atom discovery through the governed fetch and admission boundaries."""

import re
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urljoin

from sqlalchemy.orm import Session

from contentos.core.urls import InvalidUrlError
from contentos.discovery.service import (
    DiscoveryService,
    SourceNotEligibleForDiscoveryError,
)
from contentos.fetching.models import FetchOutcome, FetchResult, RetryClassification
from contentos.sources.service import SourceNotFoundError

# Aligned with the fetch layer's body cap (fetch_max_body_bytes, 5 MiB
# default), matching the sitemap parser bound.
MAX_FEED_DOCUMENT_BYTES = 5_242_880
MAX_FEED_ELEMENTS = 10_000
MAX_FEED_ENTRIES = 100
MAX_FEED_TITLE_LENGTH = 500
MAX_FEED_SNIPPET_LENGTH = 2_000
MAX_FEED_URL_LENGTH = 2_000

_ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
_ATOM = f"{{{_ATOM_NAMESPACE}}}"
_ACCEPTED_FEED_CONTENT_TYPES = frozenset(
    {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}
)
_PROHIBITED_XML_DECLARATIONS = (b"<!DOCTYPE", b"<!ENTITY")
_WHITESPACE = re.compile(r"\s+")


class FeedDiscoveryError(Exception):
    """Base class for feed-strategy domain failures."""


class FeedSourceNotEligibleError(FeedDiscoveryError):
    """The requested source does not meet feed-discovery eligibility rules."""


class FeedFetchError(FeedDiscoveryError):
    """A safe fetch result prevented feed parsing."""

    def __init__(
        self,
        source_id: uuid.UUID,
        outcome: FetchOutcome,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(f"feed fetch for source {source_id} ended with {outcome.value}")
        self.source_id = source_id
        self.outcome = outcome
        self.retry_after_seconds = retry_after_seconds


class FeedFetchRetryableError(FeedFetchError):
    """Future orchestration may retry this fetch outcome."""


class FeedFetchTerminalError(FeedFetchError):
    """Future orchestration must not retry this fetch outcome automatically."""


class UnsupportedFeedContentError(FeedDiscoveryError):
    """The fetched representation is not an accepted RSS/Atom XML document."""


class FeedParseError(FeedDiscoveryError):
    """The bounded untrusted XML document could not be parsed safely."""


class FeedFetcher(Protocol):
    """The narrow FetchClient interface used by feed discovery."""

    def fetch(self, url: str) -> FetchResult: ...


@dataclass(frozen=True, slots=True)
class FeedDiscoveryResult:
    """Immutable summary of one successful feed-strategy execution."""

    source_id: uuid.UUID
    feed_url: str
    fetched_at: datetime
    entries_seen: int
    admitted_new: int
    rediscovered_existing: int
    skipped_invalid: int
    skipped_missing_url: int
    parse_warnings: tuple[str, ...]
    fetch_outcome: FetchOutcome


@dataclass(frozen=True, slots=True)
class _FeedEntry:
    url: str | None
    title: str | None
    snippet: str | None
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class _ParsedFeed:
    entries: tuple[_FeedEntry, ...]
    warnings: tuple[str, ...]


class _PlainTextParser(HTMLParser):
    """Extract text from bounded feed hints without retaining markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class FeedDiscoveryStrategy:
    """Fetch, parse, and idempotently admit candidates from one feed source."""

    def __init__(self, session: Session, fetch_client: FeedFetcher) -> None:
        self._discovery = DiscoveryService(session)
        self._fetch_client = fetch_client

    def execute(self, source_id: uuid.UUID) -> FeedDiscoveryResult:
        try:
            source = self._discovery.require_feed_source(source_id)
        except (SourceNotFoundError, SourceNotEligibleForDiscoveryError) as exc:
            raise FeedSourceNotEligibleError(f"source {source_id} is not eligible") from exc

        fetch_result = self._fetch_client.fetch(source.base_url)
        if not fetch_result.is_success:
            self._raise_fetch_error(source_id, fetch_result)

        media_type = _media_type(fetch_result.content_type)
        if media_type not in _ACCEPTED_FEED_CONTENT_TYPES:
            raise UnsupportedFeedContentError("fetched content is not an accepted feed XML type")
        if fetch_result.body is None:
            raise FeedParseError("successful feed fetch did not provide a body")

        feed_url = fetch_result.final_url or source.base_url
        parsed = _parse_feed(fetch_result.body)
        warnings = list(parsed.warnings)
        admitted_new = 0
        rediscovered_existing = 0
        skipped_invalid = 0
        skipped_missing_url = 0

        for entry in parsed.entries:
            if entry.url is None or not entry.url.strip():
                skipped_missing_url += 1
                continue
            try:
                candidate_url = urljoin(feed_url, entry.url.strip())
            except ValueError:
                skipped_invalid += 1
                continue
            if len(candidate_url) > MAX_FEED_URL_LENGTH:
                skipped_invalid += 1
                continue
            try:
                admission = self._discovery.discover_feed(
                    source.id,
                    candidate_url,
                    title_hint=entry.title,
                    snippet_hint=entry.snippet,
                    external_published_at=entry.published_at,
                )
            except InvalidUrlError:
                skipped_invalid += 1
                continue
            if admission.is_new:
                admitted_new += 1
            else:
                rediscovered_existing += 1

        return FeedDiscoveryResult(
            source_id=source.id,
            feed_url=feed_url,
            fetched_at=fetch_result.fetched_at,
            entries_seen=len(parsed.entries),
            admitted_new=admitted_new,
            rediscovered_existing=rediscovered_existing,
            skipped_invalid=skipped_invalid,
            skipped_missing_url=skipped_missing_url,
            parse_warnings=tuple(warnings),
            fetch_outcome=fetch_result.outcome,
        )

    @staticmethod
    def _raise_fetch_error(source_id: uuid.UUID, result: FetchResult) -> None:
        if result.outcome is FetchOutcome.DISALLOWED_MIME:
            raise UnsupportedFeedContentError("fetch policy rejected the feed media type")
        error_type = (
            FeedFetchRetryableError
            if result.retry is RetryClassification.RETRYABLE
            else FeedFetchTerminalError
        )
        raise error_type(
            source_id,
            result.outcome,
            retry_after_seconds=result.retry_after_seconds,
        )


def _parse_feed(body: bytes) -> _ParsedFeed:
    if len(body) > MAX_FEED_DOCUMENT_BYTES:
        raise FeedParseError("feed XML exceeds the parser byte limit")
    uppercase_prefixes = body.upper()
    if any(declaration in uppercase_prefixes for declaration in _PROHIBITED_XML_DECLARATIONS):
        raise FeedParseError("feed XML contains a prohibited DTD or entity declaration")

    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise FeedParseError("feed XML is malformed") from None

    for index, _element in enumerate(root.iter(), start=1):
        if index > MAX_FEED_ELEMENTS:
            raise FeedParseError("feed XML exceeds the element limit")

    root_name = _local_name(root.tag)
    if root_name == "rss":
        return _parse_rss(root)
    if root.tag == f"{_ATOM}feed":
        return _parse_atom(root)
    raise UnsupportedFeedContentError("XML root is not supported RSS 2.x or Atom")


def _parse_rss(root: ET.Element) -> _ParsedFeed:
    channel = root.find("channel")
    if channel is None:
        raise UnsupportedFeedContentError("RSS document has no channel")
    items = channel.findall("item")
    selected, warnings = _bounded_entries(items)
    entries: list[_FeedEntry] = []
    for item in selected:
        published_text = _child_text(item, "pubDate")
        published_at = _parse_publication_date(published_text)
        if published_text and published_at is None:
            _add_warning(warnings, "unparseable_publication_date")
        title, title_truncated = _hint(_child(item, "title"), MAX_FEED_TITLE_LENGTH)
        snippet, snippet_truncated = _hint(_child(item, "description"), MAX_FEED_SNIPPET_LENGTH)
        if title_truncated:
            _add_warning(warnings, "title_truncated")
        if snippet_truncated:
            _add_warning(warnings, "snippet_truncated")
        entries.append(
            _FeedEntry(
                url=_child_text(item, "link"),
                title=title,
                snippet=snippet,
                published_at=published_at,
            )
        )
    return _ParsedFeed(entries=tuple(entries), warnings=tuple(warnings))


def _parse_atom(root: ET.Element) -> _ParsedFeed:
    items = root.findall(f"{_ATOM}entry")
    selected, warnings = _bounded_entries(items)
    entries: list[_FeedEntry] = []
    for item in selected:
        published_text = _child_text(item, f"{_ATOM}published") or _child_text(
            item, f"{_ATOM}updated"
        )
        published_at = _parse_publication_date(published_text)
        if published_text and published_at is None:
            _add_warning(warnings, "unparseable_publication_date")
        title, title_truncated = _hint(_child(item, f"{_ATOM}title"), MAX_FEED_TITLE_LENGTH)
        summary_element = _child(item, f"{_ATOM}summary")
        if summary_element is None:
            summary_element = _child(item, f"{_ATOM}content")
        snippet, snippet_truncated = _hint(summary_element, MAX_FEED_SNIPPET_LENGTH)
        if title_truncated:
            _add_warning(warnings, "title_truncated")
        if snippet_truncated:
            _add_warning(warnings, "snippet_truncated")
        entries.append(
            _FeedEntry(
                url=_atom_link(item),
                title=title,
                snippet=snippet,
                published_at=published_at,
            )
        )
    return _ParsedFeed(entries=tuple(entries), warnings=tuple(warnings))


def _bounded_entries(elements: list[ET.Element]) -> tuple[list[ET.Element], list[str]]:
    warnings: list[str] = []
    if len(elements) > MAX_FEED_ENTRIES:
        warnings.append("entry_limit_reached")
    return elements[:MAX_FEED_ENTRIES], warnings


def _atom_link(entry: ET.Element) -> str | None:
    fallback: str | None = None
    for link in entry.findall(f"{_ATOM}link"):
        href = link.get("href")
        if not href:
            continue
        relation = link.get("rel", "alternate").casefold()
        if relation == "alternate":
            return href
        if fallback is None:
            fallback = href
    return fallback


def _child(parent: ET.Element, tag: str) -> ET.Element | None:
    return parent.find(tag)


def _child_text(parent: ET.Element, tag: str) -> str | None:
    child = _child(parent, tag)
    if child is None:
        return None
    value = "".join(child.itertext()).strip()
    return value or None


def _hint(element: ET.Element | None, limit: int) -> tuple[str | None, bool]:
    if element is None:
        return None, False
    raw_text = " ".join(element.itertext())
    parser = _PlainTextParser()
    parser.feed(raw_text)
    parser.close()
    cleaned = _WHITESPACE.sub(" ", " ".join(parser.parts)).strip()
    if not cleaned:
        return None, False
    return cleaned[:limit], len(cleaned) > limit


def _parse_publication_date(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed: datetime | None = None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        pass
    if parsed is None:
        iso_value = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _media_type(content_type: str | None) -> str:
    return (content_type or "").partition(";")[0].strip().casefold()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _add_warning(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)
