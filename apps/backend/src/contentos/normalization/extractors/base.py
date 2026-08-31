"""Versioned extractor contracts, immutable results, decoding, and limits."""

import codecs
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

MAX_PARSED_ELEMENTS = 20_000
MAX_CLEAN_TEXT_CHARS = 1_000_000
MAX_TITLE_CHARS = 500
MAX_AUTHOR_NAME_CHARS = 300
MAX_HEADINGS = 500
MAX_HEADING_TEXT_CHARS = 500
MAX_SECTIONS = 500
MAX_SECTION_TEXT_CHARS = 100_000
MAX_LINKS = 1_000
MAX_ANCHOR_TEXT_CHARS = 500
MAX_HREF_CHARS = 2_000
MAX_METADATA_VALUE_CHARS = 2_000
MAX_JSON_LD_BLOCKS = 10
MAX_JSON_LD_CHARS = 20_000
MAX_JSON_LD_SUMMARIES = 20
MAX_STRUCTURED_ITEMS = 1_000
MAX_STRUCTURED_DEPTH = 8
HTML_CHARSET_SCAN_BYTES = 8_192

_CHARSET_PARAMETER = re.compile(r"(?:^|;)\s*charset\s*=\s*[\"']?([^;\s\"']+)", re.I)
_HTML_META_CHARSET = re.compile(
    rb"<meta\b[^>]{0,1024}?charset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)",
    re.I,
)
_ALLOWED_CODECS = frozenset(
    {"ascii", "utf-8", "utf-8-sig", "cp1252", "cp1254", "iso8859-1", "iso8859-9"}
)
_INLINE_WHITESPACE = re.compile(r"\s+")


class ExtractorFailure(Exception):
    """Expected deterministic extractor failure with a safe persisted detail."""


class ExtractorUnsupportedContentError(ExtractorFailure):
    """The selected extractor does not support the snapshot media type."""


class ExtractorDecodeError(ExtractorFailure):
    """Exact payload bytes could not be decoded under the explicit charset policy."""


class ExtractorParseError(ExtractorFailure):
    """Decoded input could not be parsed into the baseline document model."""


class ExtractorEmptyContentError(ExtractorFailure):
    """Parsing produced no usable research text."""


class ExtractorPolicyError(ExtractorFailure):
    """Input or derived output exceeded a deterministic extraction limit."""


@dataclass(frozen=True, slots=True)
class ExtractionContext:
    """Immutable snapshot context available to an extractor without database access."""

    media_type: str
    content_type: str | None
    base_url: str


@dataclass(frozen=True, slots=True)
class ExtractedHeading:
    level: int
    text: str


@dataclass(frozen=True, slots=True)
class ExtractedSection:
    level: int
    heading: str
    text: str


@dataclass(frozen=True, slots=True)
class ExtractedLink:
    href: str
    url: str
    text: str


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    """Immutable in-memory extraction output; raw bytes are deliberately absent."""

    clean_text: str
    parser_version: str
    title: str | None = None
    language: str | None = None
    author_name: str | None = None
    external_published_at: datetime | None = None
    headings: tuple[ExtractedHeading, ...] = ()
    sections: tuple[ExtractedSection, ...] = ()
    links: tuple[ExtractedLink, ...] = ()
    structured_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "structured_metadata", _copy_json(self.structured_metadata))


class Extractor(Protocol):
    """Deterministic synchronous extractor whose identity is persisted verbatim."""

    name: str
    version: str
    parser_version: str
    supported_media_types: frozenset[str]

    def extract(self, payload: bytes, context: ExtractionContext) -> ExtractedDocument: ...


def decode_payload(payload: bytes, content_type: str | None, *, inspect_html: bool) -> str:
    """Decode exact bytes using explicit response/meta charset, then strict UTF-8."""
    charset = _charset_from_content_type(content_type)
    if charset is None and inspect_html:
        charset = _charset_from_html_prefix(payload[:HTML_CHARSET_SCAN_BYTES])
    codec = _validated_codec(charset or "utf-8")
    try:
        return payload.decode(codec, errors="strict")
    except UnicodeDecodeError:
        raise ExtractorDecodeError("payload bytes are invalid for the selected charset") from None


def normalize_inline_text(value: str, *, limit: int) -> str:
    """Collapse whitespace without changing case, punctuation, or language characters."""
    normalized = _INLINE_WHITESPACE.sub(" ", value).strip()
    return normalized[:limit]


def clean_text_from_blocks(blocks: list[str]) -> str:
    """Join meaningful normalized blocks with stable paragraph separation."""
    cleaned = [normalize_inline_text(block, limit=MAX_CLEAN_TEXT_CHARS) for block in blocks]
    result = "\n\n".join(block for block in cleaned if block)
    if not result:
        raise ExtractorEmptyContentError("extractor produced no usable text")
    if len(result) > MAX_CLEAN_TEXT_CHARS:
        raise ExtractorPolicyError("clean text exceeds the extractor limit")
    return result


def _charset_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    match = _CHARSET_PARAMETER.search(content_type)
    return match.group(1) if match else None


def _charset_from_html_prefix(prefix: bytes) -> str | None:
    match = _HTML_META_CHARSET.search(prefix)
    return match.group(1).decode("ascii") if match else None


def _validated_codec(charset: str) -> str:
    try:
        canonical = codecs.lookup(charset).name
    except LookupError:
        raise ExtractorDecodeError("payload declares an unsupported charset") from None
    if canonical not in _ALLOWED_CODECS:
        raise ExtractorDecodeError("payload declares an unsupported charset")
    return canonical


def _copy_json(value: Any, *, depth: int = 1, count: list[int] | None = None) -> Any:
    if count is None:
        count = [0]
    if depth > MAX_STRUCTURED_DEPTH:
        raise ExtractorPolicyError("structured metadata exceeds the depth limit")
    if isinstance(value, dict):
        count[0] += len(value)
        _check_item_count(count)
        return {
            str(key): _copy_json(child, depth=depth + 1, count=count)
            for key, child in value.items()
        }
    if isinstance(value, (list, tuple)):
        count[0] += len(value)
        _check_item_count(count)
        return [_copy_json(child, depth=depth + 1, count=count) for child in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ExtractorPolicyError("structured metadata contains an unsupported value")


def _check_item_count(count: list[int]) -> None:
    if count[0] > MAX_STRUCTURED_ITEMS:
        raise ExtractorPolicyError("structured metadata exceeds the item limit")
