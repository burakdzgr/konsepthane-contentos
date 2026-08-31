"""Hostile-input-safe deterministic baseline HTML research extractor."""

import json
import re
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

from contentos.normalization.extractors.base import (
    MAX_ANCHOR_TEXT_CHARS,
    MAX_AUTHOR_NAME_CHARS,
    MAX_CLEAN_TEXT_CHARS,
    MAX_HEADING_TEXT_CHARS,
    MAX_HEADINGS,
    MAX_HREF_CHARS,
    MAX_JSON_LD_BLOCKS,
    MAX_JSON_LD_CHARS,
    MAX_JSON_LD_SUMMARIES,
    MAX_LINKS,
    MAX_METADATA_VALUE_CHARS,
    MAX_PARSED_ELEMENTS,
    MAX_SECTION_TEXT_CHARS,
    MAX_SECTIONS,
    MAX_STRUCTURED_DEPTH,
    MAX_STRUCTURED_ITEMS,
    MAX_TITLE_CHARS,
    ExtractedDocument,
    ExtractedHeading,
    ExtractedLink,
    ExtractedSection,
    ExtractionContext,
    ExtractorParseError,
    ExtractorPolicyError,
    clean_text_from_blocks,
    decode_payload,
    normalize_inline_text,
)

_SUPPRESSED_TAGS = frozenset(
    {"script", "style", "noscript", "template", "svg", "canvas", "nav", "footer", "form"}
)
_BLOCK_TAGS = frozenset(
    {"address", "article", "blockquote", "div", "figcaption", "li", "main", "p", "pre", "section"}
)
_HEADING_TAGS = {f"h{level}": level for level in range(1, 7)}
_SELECTED_META_NAMES = frozenset(
    {
        "description",
        "author",
        "og:title",
        "og:description",
        "og:type",
        "article:title",
        "article:published_time",
        "article:author",
    }
)
_LANGUAGE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")


class HtmlExtractor:
    """Extract bounded metadata and visible research text without resource loading."""

    name = "html-basic"
    version = "1"
    parser_version = "stdlib-html-parser-v1"
    supported_media_types = frozenset({"text/html", "application/xhtml+xml"})

    def extract(self, payload: bytes, context: ExtractionContext) -> ExtractedDocument:
        decoded = decode_payload(payload, context.content_type, inspect_html=True)
        parser = _BoundedHtmlParser(context.base_url)
        try:
            parser.feed(decoded)
            parser.close()
            parser.finish()
        except ExtractorPolicyError:
            raise
        except Exception:
            raise ExtractorParseError("HTML could not be parsed deterministically") from None

        clean_text = clean_text_from_blocks(parser.blocks)
        headings = tuple(parser.headings[:MAX_HEADINGS])
        sections = _build_sections(parser.events)
        metadata = parser.structured_metadata()
        title = _first_nonempty(
            parser.meta.get("og:title"),
            parser.meta.get("article:title"),
            parser.document_title,
            next((heading.text for heading in headings if heading.level == 1), None),
        )
        author = _first_nonempty(
            parser.meta.get("author"),
            parser.meta.get("article:author"),
            _json_ld_author(parser.json_ld_summaries),
        )
        published = _parse_publication_date(
            _first_nonempty(
                parser.meta.get("article:published_time"),
                _json_ld_value(parser.json_ld_summaries, "datePublished"),
                parser.publication_time,
            )
        )
        return ExtractedDocument(
            title=_bounded(title, MAX_TITLE_CHARS),
            clean_text=clean_text,
            language=_normalize_language(parser.language),
            author_name=_bounded(author, MAX_AUTHOR_NAME_CHARS),
            external_published_at=published,
            headings=headings,
            sections=sections,
            links=tuple(parser.links[:MAX_LINKS]),
            structured_metadata=metadata,
            parser_version=self.parser_version,
        )


class _BoundedHtmlParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.element_count = 0
        self.suppressed_depth = 0
        self.in_title = False
        self.in_head = False
        self.title_parts: list[str] = []
        self.document_title: str | None = None
        self.current_parts: list[str] = []
        self.current_heading_level: int | None = None
        self.blocks: list[str] = []
        self.headings: list[ExtractedHeading] = []
        self.events: list[tuple[str, int | None, str]] = []
        self.links: list[ExtractedLink] = []
        self.seen_link_urls: set[str] = set()
        self.active_link_href: str | None = None
        self.active_link_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical_url: str | None = None
        self.language: str | None = None
        self.publication_time: str | None = None
        self.json_ld_summaries: list[dict[str, Any]] = []
        self.json_ld_parts: list[str] | None = None
        self.json_ld_chars = 0
        self.json_ld_block_count = 0
        self.json_ld_oversized = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        self._count_element()
        attributes = {name.casefold(): value or "" for name, value in attrs}

        if self.suppressed_depth:
            self.suppressed_depth += 1
            return
        if tag == "script":
            if (
                attributes.get("type", "").split(";", 1)[0].strip().casefold()
                == "application/ld+json"
                and self.json_ld_block_count < MAX_JSON_LD_BLOCKS
            ):
                self.json_ld_block_count += 1
                self.json_ld_parts = []
                self.json_ld_chars = 0
                self.json_ld_oversized = False
            self.suppressed_depth = 1
            return
        if tag in _SUPPRESSED_TAGS:
            self._flush_block()
            self.suppressed_depth = 1
            return
        if tag == "title":
            self.in_title = True
            self.title_parts = []
            return
        if tag == "head":
            self.in_head = True
            return
        if tag == "html" and not self.language:
            self.language = attributes.get("lang") or None
        if tag == "meta":
            self._capture_meta(attributes)
        elif tag == "link":
            self._capture_canonical(attributes)
        elif tag == "time" and not self.publication_time:
            itemprop = attributes.get("itemprop", "").casefold()
            if itemprop == "datepublished":
                self.publication_time = _bounded(attributes.get("datetime"), 100)
        elif tag == "a":
            self.active_link_href = attributes.get("href") or None
            self.active_link_parts = []

        if tag in _HEADING_TAGS:
            self._flush_block()
            self.current_heading_level = _HEADING_TAGS[tag]
        elif tag in _BLOCK_TAGS:
            self._flush_block()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in {"meta", "link", "br", "img", "input", "hr"}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self.suppressed_depth:
            self.suppressed_depth -= 1
            if tag == "script" and self.suppressed_depth == 0 and self.json_ld_parts is not None:
                self._finish_json_ld()
            return
        if tag == "title":
            self.document_title = _bounded(
                normalize_inline_text(" ".join(self.title_parts), limit=MAX_TITLE_CHARS),
                MAX_TITLE_CHARS,
            )
            self.in_title = False
            return
        if tag == "head":
            self.in_head = False
            return
        if tag == "a":
            self._finish_link()
        if tag in _HEADING_TAGS or tag in _BLOCK_TAGS or tag in {"body", "html"}:
            self._flush_block()

    def handle_data(self, data: str) -> None:
        if self.json_ld_parts is not None:
            self.json_ld_chars += len(data)
            if self.json_ld_chars <= MAX_JSON_LD_CHARS:
                self.json_ld_parts.append(data)
            else:
                self.json_ld_oversized = True
            return
        if self.suppressed_depth:
            return
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.in_head:
            return
        self.current_parts.append(data)
        if self.active_link_href is not None:
            self.active_link_parts.append(data)

    def finish(self) -> None:
        self._flush_block()

    def structured_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if self.canonical_url:
            metadata["canonical_url"] = self.canonical_url
        if description := self.meta.get("description"):
            metadata["description"] = description
        open_graph = {
            key: value
            for key, value in self.meta.items()
            if key in {"og:title", "og:description", "og:type"}
        }
        if open_graph:
            metadata["open_graph"] = open_graph
        article = {
            key: value
            for key, value in self.meta.items()
            if key in {"article:title", "article:published_time", "article:author"}
        }
        if article:
            metadata["article"] = article
        if self.json_ld_summaries:
            metadata["json_ld"] = self.json_ld_summaries[:MAX_JSON_LD_SUMMARIES]
        return metadata

    def _count_element(self) -> None:
        self.element_count += 1
        if self.element_count > MAX_PARSED_ELEMENTS:
            raise ExtractorPolicyError("HTML element count exceeds the extractor limit")

    def _capture_meta(self, attrs: dict[str, str]) -> None:
        key = (attrs.get("property") or attrs.get("name") or "").strip().casefold()
        if key not in _SELECTED_META_NAMES:
            return
        content = normalize_inline_text(attrs.get("content", ""), limit=MAX_METADATA_VALUE_CHARS)
        if content and key not in self.meta:
            self.meta[key] = content

    def _capture_canonical(self, attrs: dict[str, str]) -> None:
        if self.canonical_url or "canonical" not in attrs.get("rel", "").casefold().split():
            return
        self.canonical_url = _resolve_http_url(attrs.get("href", ""), self.base_url)

    def _flush_block(self) -> None:
        text = normalize_inline_text(" ".join(self.current_parts), limit=MAX_CLEAN_TEXT_CHARS)
        self.current_parts = []
        if not text:
            self.current_heading_level = None
            return
        self.blocks.append(text)
        if self.current_heading_level is not None:
            heading = ExtractedHeading(
                level=self.current_heading_level,
                text=text[:MAX_HEADING_TEXT_CHARS],
            )
            if len(self.headings) < MAX_HEADINGS:
                self.headings.append(heading)
                self.events.append(("heading", heading.level, heading.text))
        else:
            self.events.append(("text", None, text))
        self.current_heading_level = None

    def _finish_link(self) -> None:
        href = self.active_link_href
        anchor = normalize_inline_text(
            " ".join(self.active_link_parts), limit=MAX_ANCHOR_TEXT_CHARS
        )
        self.active_link_href = None
        self.active_link_parts = []
        if not href or len(self.links) >= MAX_LINKS:
            return
        resolved = _resolve_http_url(href, self.base_url)
        if not resolved or resolved in self.seen_link_urls:
            return
        self.seen_link_urls.add(resolved)
        self.links.append(ExtractedLink(href=href[:MAX_HREF_CHARS], url=resolved, text=anchor))

    def _finish_json_ld(self) -> None:
        parts = self.json_ld_parts
        oversized = self.json_ld_oversized
        self.json_ld_parts = None
        if not parts or oversized:
            return
        try:
            parsed = json.loads("".join(parts))
            _validate_json_bounds(parsed)
        except (json.JSONDecodeError, ExtractorPolicyError):
            return
        for candidate in _json_ld_candidates(parsed):
            summary = _json_ld_summary(candidate)
            if summary:
                self.json_ld_summaries.append(summary)
                if len(self.json_ld_summaries) >= MAX_JSON_LD_SUMMARIES:
                    break


def _build_sections(events: list[tuple[str, int | None, str]]) -> tuple[ExtractedSection, ...]:
    sections: list[ExtractedSection] = []
    heading: tuple[int, str] | None = None
    content: list[str] = []

    def flush() -> None:
        if heading is None or len(sections) >= MAX_SECTIONS:
            return
        sections.append(
            ExtractedSection(
                level=heading[0],
                heading=heading[1],
                text="\n\n".join(content)[:MAX_SECTION_TEXT_CHARS],
            )
        )

    for kind, level, text in events:
        if kind == "heading" and level is not None:
            flush()
            heading = (level, text)
            content = []
        elif heading is not None:
            content.append(text)
    flush()
    return tuple(sections)


def _resolve_http_url(href: str, base_url: str) -> str | None:
    href = href.strip()
    if not href or href.startswith("#"):
        return None
    try:
        resolved = urljoin(base_url, href)
        parts = urlsplit(resolved)
    except ValueError:
        return None
    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    return resolved


def _validate_json_bounds(value: Any) -> None:
    count = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal count
        if depth > MAX_STRUCTURED_DEPTH:
            raise ExtractorPolicyError("JSON-LD exceeds the depth limit")
        if isinstance(node, dict):
            count += len(node)
            for child in node.values():
                walk(child, depth + 1)
        elif isinstance(node, list):
            count += len(node)
            for child in node:
                walk(child, depth + 1)
        elif node is not None and not isinstance(node, (str, int, float, bool)):
            raise ExtractorPolicyError("JSON-LD contains an unsupported value")
        if count > MAX_STRUCTURED_ITEMS:
            raise ExtractorPolicyError("JSON-LD exceeds the item limit")

    walk(value, 1)


def _json_ld_candidates(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    graph = value.get("@graph")
    if isinstance(graph, list):
        return [item for item in graph if isinstance(item, dict)]
    return [value]


def _json_ld_summary(value: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("@type", "headline", "description", "datePublished", "url"):
        candidate = value.get(key)
        if isinstance(candidate, (str, int, float, bool)):
            summary[key] = str(candidate)[:MAX_METADATA_VALUE_CHARS]
    if author := _author_value(value.get("author")):
        summary["author"] = author
    return summary


def _author_value(value: Any) -> str | None:
    if isinstance(value, str):
        return _bounded(
            normalize_inline_text(value, limit=MAX_AUTHOR_NAME_CHARS),
            MAX_AUTHOR_NAME_CHARS,
        )
    if isinstance(value, dict) and isinstance(value.get("name"), str):
        return _bounded(
            normalize_inline_text(value["name"], limit=MAX_AUTHOR_NAME_CHARS),
            MAX_AUTHOR_NAME_CHARS,
        )
    if isinstance(value, list):
        names = [_author_value(item) for item in value]
        return _bounded(", ".join(name for name in names if name), MAX_AUTHOR_NAME_CHARS)
    return None


def _json_ld_value(summaries: list[dict[str, Any]], key: str) -> str | None:
    for summary in summaries:
        value = summary.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _json_ld_author(summaries: list[dict[str, Any]]) -> str | None:
    return _json_ld_value(summaries, "author")


def _parse_publication_date(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
            parsed_date = date.fromisoformat(candidate)
            return datetime(
                parsed_date.year,
                parsed_date.month,
                parsed_date.day,
                tzinfo=UTC,
            )
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _normalize_language(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if len(candidate) > 35 or _LANGUAGE.fullmatch(candidate) is None:
        return None
    parts = candidate.split("-")
    normalized = [parts[0].lower()]
    normalized.extend(part.upper() if len(part) == 2 else part for part in parts[1:])
    return "-".join(normalized)


def _bounded(value: str | None, limit: int) -> str | None:
    return value[:limit] if value else None


def _first_nonempty(*values: str | None) -> str | None:
    return next((value for value in values if value), None)
