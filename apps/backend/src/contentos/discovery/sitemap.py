"""Defensive sitemap discovery through governed fetch and admission boundaries."""

import uuid
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from contentos.core.urls import InvalidUrlError, canonicalize_url
from contentos.discovery.service import (
    DiscoveryService,
    SourceNotEligibleForDiscoveryError,
)
from contentos.fetching.models import FetchOutcome, FetchResult, RetryClassification
from contentos.sources.service import SourceNotFoundError

# Aligned with the fetch layer's body cap (fetch_max_body_bytes, 5 MiB
# default): real split sitemaps from large sites routinely exceed 1 MB.
MAX_SITEMAP_DOCUMENT_BYTES = 5_242_880
# XML-bomb guard over an already byte-capped body (a 5 MB urlset with
# loc/lastmod/changefreq/priority per URL is ~30k elements).
MAX_SITEMAP_ELEMENTS = 100_000
MAX_SITEMAP_DEPTH = 3
MAX_SITEMAP_DOCUMENTS = 50
MAX_SITEMAP_INDEX_ENTRIES = 50
MAX_SITEMAP_URL_ENTRIES = 5_000
MAX_SITEMAP_URLS = 5_000
MAX_SITEMAP_URL_LENGTH = 2_000

_SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
# Real sites still publish the legacy Google 0.84 schema (and a trailing
# slash variant); the element vocabulary is identical.
_ACCEPTED_SITEMAP_NAMESPACES = frozenset(
    {
        "",
        _SITEMAP_NAMESPACE,
        "http://www.sitemaps.org/schemas/sitemap/0.9/",
        "http://www.google.com/schemas/sitemap/0.84",
    }
)
_ACCEPTED_SITEMAP_CONTENT_TYPES = frozenset({"application/xml", "text/xml"})
# Media types that say nothing about the body: accept only when the body
# itself sniffs as sitemap XML.
_SNIFFABLE_CONTENT_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream"})
_XML_SNIFF_PREFIXES = (b"<?xml", b"<urlset", b"<sitemapindex")
# Warnings recorded when a CHILD sitemap is skipped instead of failing the run.
WARNING_CHILD_FETCH_SKIPPED = "child_sitemap_fetch_skipped"
WARNING_CHILD_UNSUPPORTED = "child_sitemap_unsupported_skipped"
WARNING_CHILD_UNPARSEABLE = "child_sitemap_unparseable_skipped"
WARNING_DEPTH_SKIPPED = "depth_limit_child_skipped"
WARNING_DOCUMENT_LIMIT = "document_limit_truncated"
WARNING_INDEX_ENTRIES_TRUNCATED = "index_entries_truncated"
WARNING_URL_ENTRIES_TRUNCATED = "url_entries_truncated"
_PROHIBITED_XML_DECLARATIONS = (b"<!DOCTYPE", b"<!ENTITY")


class SitemapDiscoveryError(Exception):
    """Base class for sitemap-strategy domain failures."""


class SitemapSourceNotEligibleError(SitemapDiscoveryError):
    """The requested source does not meet sitemap-discovery eligibility rules."""


class SitemapFetchError(SitemapDiscoveryError):
    """A safe fetch result prevented sitemap parsing."""

    def __init__(
        self,
        source_id: uuid.UUID,
        sitemap_url: str,
        outcome: FetchOutcome,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(f"sitemap fetch for source {source_id} ended with {outcome.value}")
        self.source_id = source_id
        self.sitemap_url = sitemap_url
        self.outcome = outcome
        self.retry_after_seconds = retry_after_seconds


class SitemapFetchRetryableError(SitemapFetchError):
    """Future orchestration may retry this fetch outcome."""


class SitemapFetchTerminalError(SitemapFetchError):
    """Future orchestration must not retry this fetch outcome automatically."""


class UnsupportedSitemapContentError(SitemapDiscoveryError):
    """The fetched representation is not a supported sitemap XML document."""


class SitemapParseError(SitemapDiscoveryError):
    """The bounded untrusted XML document could not be parsed safely."""


class SitemapTraversalLimitExceededError(SitemapDiscoveryError):
    """A bounded sitemap traversal would exceed a configured execution limit."""

    def __init__(self, limit_name: str) -> None:
        super().__init__(f"sitemap traversal exceeded the {limit_name} limit")
        self.limit_name = limit_name


class SitemapFetcher(Protocol):
    """The narrow FetchClient interface used by sitemap discovery."""

    def fetch(self, url: str) -> FetchResult: ...


@dataclass(frozen=True, slots=True)
class SitemapDiscoveryResult:
    """Immutable summary of one successful sitemap-strategy execution."""

    source_id: uuid.UUID
    root_sitemap_url: str
    sitemap_documents_fetched: int
    entries_seen: int
    admitted_new: int
    rediscovered_existing: int
    skipped_invalid: int
    skipped_missing_url: int
    skipped_duplicate_sitemap: int
    skipped_cross_origin_sitemap: int
    parse_warnings: tuple[str, ...]
    fetch_outcomes: tuple[FetchOutcome, ...]
    # Child sitemaps skipped for a bounded reason (terminal fetch failure,
    # unsupported content, unparseable XML, depth); the run still completes.
    skipped_child_sitemaps: int = 0


@dataclass(frozen=True, slots=True)
class _SitemapEntry:
    url: str | None
    last_modified: datetime | None


@dataclass(frozen=True, slots=True)
class _ParsedSitemap:
    is_index: bool
    entries: tuple[_SitemapEntry, ...]
    warnings: tuple[str, ...]


class SitemapDiscoveryStrategy:
    """Fetch, traverse, parse, and idempotently admit one sitemap source."""

    def __init__(self, session: Session, fetch_client: SitemapFetcher) -> None:
        self._discovery = DiscoveryService(session)
        self._fetch_client = fetch_client

    def execute(self, source_id: uuid.UUID) -> SitemapDiscoveryResult:
        try:
            source = self._discovery.require_sitemap_source(source_id)
        except (SourceNotFoundError, SourceNotEligibleForDiscoveryError) as exc:
            raise SitemapSourceNotEligibleError(f"source {source_id} is not eligible") from exc

        root_key = _canonical_key(source.base_url)
        pending: deque[tuple[str, int]] = deque([(source.base_url, 0)])
        scheduled = {root_key}
        allowed_origin: tuple[str, str, int | None] | None = None
        root_sitemap_url = source.base_url
        documents_fetched = 0
        entries_seen = 0
        admitted_new = 0
        rediscovered_existing = 0
        skipped_invalid = 0
        skipped_missing_url = 0
        skipped_duplicate_sitemap = 0
        skipped_cross_origin_sitemap = 0
        warnings: list[str] = []
        fetch_outcomes: list[FetchOutcome] = []
        skipped_child_sitemaps = 0
        url_limit_reached = False

        while pending and not url_limit_reached:
            if documents_fetched >= MAX_SITEMAP_DOCUMENTS:
                # A CAPACITY bound (like the URL cap below): keep what was
                # admitted, say so, stop — never fail a big site's run.
                _add_warning(warnings, WARNING_DOCUMENT_LIMIT)
                break

            requested_url, depth = pending.popleft()
            is_root_document = documents_fetched == 0
            fetch_result = self._fetch_client.fetch(requested_url)
            fetch_outcomes.append(fetch_result.outcome)
            if not fetch_result.is_success:
                if is_root_document or fetch_result.retry is RetryClassification.RETRYABLE:
                    # The root must be readable; a retryable child failure
                    # (timeout, network) is the intake step's retry to take.
                    self._raise_fetch_error(source.id, requested_url, fetch_result)
                # A terminal child failure (too large, 404, robots, media
                # type) removes ONE child from the traversal, not the run.
                skipped_child_sitemaps += 1
                _add_warning(warnings, WARNING_CHILD_FETCH_SKIPPED)
                continue
            try:
                _require_xml_content(fetch_result)
            except UnsupportedSitemapContentError:
                if is_root_document:
                    raise
                skipped_child_sitemaps += 1
                _add_warning(warnings, WARNING_CHILD_UNSUPPORTED)
                continue
            if fetch_result.body is None:
                raise SitemapParseError("successful sitemap fetch did not provide a body")

            document_url = fetch_result.final_url or requested_url
            if is_root_document:
                root_sitemap_url = document_url
                allowed_origin = _origin(document_url)
            documents_fetched += 1
            scheduled.add(_canonical_key(document_url))
            if not is_root_document and _origin(document_url) != allowed_origin:
                skipped_cross_origin_sitemap += 1
                _add_warning(warnings, "cross_origin_sitemap_redirect_skipped")
                continue

            try:
                parsed = _parse_sitemap(fetch_result.body)
            except (SitemapParseError, UnsupportedSitemapContentError):
                if is_root_document:
                    raise
                skipped_child_sitemaps += 1
                _add_warning(warnings, WARNING_CHILD_UNPARSEABLE)
                continue
            for warning in parsed.warnings:
                _add_warning(warnings, warning)

            if parsed.is_index:
                for entry in parsed.entries:
                    if entry.url is None or not entry.url.strip():
                        skipped_missing_url += 1
                        continue
                    child_url = entry.url.strip()
                    if len(child_url) > MAX_SITEMAP_URL_LENGTH:
                        skipped_invalid += 1
                        continue
                    try:
                        child_key = _canonical_key(child_url)
                        child_origin = _origin(child_url)
                    except (InvalidUrlError, ValueError):
                        skipped_invalid += 1
                        continue
                    if child_origin != allowed_origin:
                        skipped_cross_origin_sitemap += 1
                        _add_warning(warnings, "cross_origin_sitemap_skipped")
                        continue
                    if child_key in scheduled:
                        skipped_duplicate_sitemap += 1
                        continue
                    if depth >= MAX_SITEMAP_DEPTH:
                        # Deeper nesting is not traversed; the child is
                        # skipped and the truncation recorded.
                        skipped_child_sitemaps += 1
                        _add_warning(warnings, WARNING_DEPTH_SKIPPED)
                        continue
                    scheduled.add(child_key)
                    pending.append((child_url, depth + 1))
                continue

            for entry in parsed.entries:
                if entries_seen >= MAX_SITEMAP_URLS:
                    # A CAPACITY bound, not a safety bound (depth and
                    # document count stay hard failures): keep everything
                    # admitted so far, record the truncation honestly, and
                    # stop instead of failing the whole run on large sites.
                    _add_warning(warnings, "url_limit_truncated")
                    url_limit_reached = True
                    break
                entries_seen += 1
                if entry.url is None or not entry.url.strip():
                    skipped_missing_url += 1
                    continue
                candidate_url = entry.url.strip()
                if len(candidate_url) > MAX_SITEMAP_URL_LENGTH:
                    skipped_invalid += 1
                    continue
                try:
                    admission = self._discovery.discover_sitemap(source.id, candidate_url)
                except (InvalidUrlError, ValueError):
                    skipped_invalid += 1
                    continue
                if admission.is_new:
                    admitted_new += 1
                else:
                    rediscovered_existing += 1

        return SitemapDiscoveryResult(
            source_id=source.id,
            root_sitemap_url=root_sitemap_url,
            sitemap_documents_fetched=documents_fetched,
            entries_seen=entries_seen,
            admitted_new=admitted_new,
            rediscovered_existing=rediscovered_existing,
            skipped_invalid=skipped_invalid,
            skipped_missing_url=skipped_missing_url,
            skipped_duplicate_sitemap=skipped_duplicate_sitemap,
            skipped_cross_origin_sitemap=skipped_cross_origin_sitemap,
            parse_warnings=tuple(warnings),
            fetch_outcomes=tuple(fetch_outcomes),
            skipped_child_sitemaps=skipped_child_sitemaps,
        )

    @staticmethod
    def _raise_fetch_error(source_id: uuid.UUID, sitemap_url: str, result: FetchResult) -> None:
        if result.outcome is FetchOutcome.DISALLOWED_MIME:
            raise UnsupportedSitemapContentError("fetch policy rejected the sitemap media type")
        error_type = (
            SitemapFetchRetryableError
            if result.retry is RetryClassification.RETRYABLE
            else SitemapFetchTerminalError
        )
        raise error_type(
            source_id,
            sitemap_url,
            result.outcome,
            retry_after_seconds=result.retry_after_seconds,
        )


def _require_xml_content(result: FetchResult) -> None:
    media_type = (result.content_type or "").partition(";")[0].strip().casefold()
    if media_type in _ACCEPTED_SITEMAP_CONTENT_TYPES:
        return
    if media_type in _SNIFFABLE_CONTENT_TYPES and _looks_like_sitemap_xml(result.body):
        # Servers that hand XML out as octet-stream: the body decides.
        return
    raise UnsupportedSitemapContentError("fetched content is not application/xml or text/xml")


def _looks_like_sitemap_xml(body: bytes | None) -> bool:
    if not body:
        return False
    head = body[:256].lstrip(b"\xef\xbb\xbf \t\r\n")
    return head.startswith(_XML_SNIFF_PREFIXES)


def _parse_sitemap(body: bytes) -> _ParsedSitemap:
    if len(body) > MAX_SITEMAP_DOCUMENT_BYTES:
        raise SitemapParseError("sitemap XML exceeds the parser byte limit")
    uppercase_prefixes = body.upper()
    if any(declaration in uppercase_prefixes for declaration in _PROHIBITED_XML_DECLARATIONS):
        raise SitemapParseError("sitemap XML contains a prohibited DTD or entity declaration")

    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise SitemapParseError("sitemap XML is malformed") from None

    for index, _element in enumerate(root.iter(), start=1):
        if index > MAX_SITEMAP_ELEMENTS:
            raise SitemapParseError("sitemap XML exceeds the element limit")

    namespace, root_name = _split_tag(root.tag)
    if namespace not in _ACCEPTED_SITEMAP_NAMESPACES:
        raise UnsupportedSitemapContentError("sitemap XML uses an unsupported namespace")
    if root_name not in {"urlset", "sitemapindex"}:
        raise UnsupportedSitemapContentError("XML root is not a sitemap urlset or sitemapindex")

    item_name = "sitemap" if root_name == "sitemapindex" else "url"
    qualified_item = _qualified(namespace, item_name)
    qualified_loc = _qualified(namespace, "loc")
    qualified_lastmod = _qualified(namespace, "lastmod")
    items = root.findall(qualified_item)
    entry_limit = (
        MAX_SITEMAP_INDEX_ENTRIES if root_name == "sitemapindex" else MAX_SITEMAP_URL_ENTRIES
    )
    entries: list[_SitemapEntry] = []
    warnings: list[str] = []
    if len(items) > entry_limit:
        # Capacity bound: the first `entry_limit` entries (document order)
        # are used and the truncation is recorded; nothing fails.
        _add_warning(
            warnings,
            WARNING_INDEX_ENTRIES_TRUNCATED
            if root_name == "sitemapindex"
            else WARNING_URL_ENTRIES_TRUNCATED,
        )
        items = items[:entry_limit]
    for item in items:
        lastmod_text = _child_text(item, qualified_lastmod)
        last_modified = _parse_lastmod(lastmod_text)
        if lastmod_text and last_modified is None:
            _add_warning(warnings, "unparseable_lastmod")
        entries.append(
            _SitemapEntry(
                url=_child_text(item, qualified_loc),
                last_modified=last_modified,
            )
        )
    return _ParsedSitemap(
        is_index=root_name == "sitemapindex",
        entries=tuple(entries),
        warnings=tuple(warnings),
    )


def _parse_lastmod(value: str | None) -> datetime | None:
    if not value:
        return None
    iso_value = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        return None
    if "T" not in iso_value:
        return parsed
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _canonical_key(url: str) -> str:
    return canonicalize_url(url).url


def _origin(url: str) -> tuple[str, str, int | None]:
    canonical = canonicalize_url(url).url
    parts = urlsplit(canonical)
    return parts.scheme, parts.hostname or "", parts.port


def _split_tag(tag: str) -> tuple[str, str]:
    if tag.startswith("{") and "}" in tag:
        namespace, local_name = tag[1:].split("}", 1)
        return namespace, local_name
    return "", tag


def _qualified(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}" if namespace else local_name


def _child_text(parent: ET.Element, tag: str) -> str | None:
    child = parent.find(tag)
    if child is None:
        return None
    value = "".join(child.itertext()).strip()
    return value or None


def _add_warning(warnings: list[str], warning: str) -> None:
    if warning not in warnings:
        warnings.append(warning)
