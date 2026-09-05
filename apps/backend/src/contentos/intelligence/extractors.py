"""Role-aware, deterministic signal extractors. No AI, no raw text.

Each extractor reads ONE normalized document (title, headings, clean text)
plus its source and yields bounded ``SignalDraft`` rows. Which extractors
run is decided by the source's capabilities: a community source yields
community needs, a shop yields taxonomy terms, a Turkish editorial site
yields market context and competing pieces. ``inspiration`` is produced by
``contentos.inspiration`` and is never duplicated here.

Honesty rules: heuristics are bounded keyword/cue matching; nothing here
infers demand, volume or sentiment. A document that matches nothing yields
nothing (UNKNOWN downstream), never a zero-valued signal.

All vocabularies are written in natural Turkish and normalized at import
with the same ``normalize_phrase`` used on the text, so dotless ``ı`` and
diacritics can never drift between the two sides.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from contentos.intelligence.enums import SignalFamily
from contentos.intelligence.models import (
    MAX_CONCEPT_KEY_LENGTH,
    MAX_SUBJECT_LENGTH,
    MAX_VALUE_KEYS,
    MAX_VALUE_TEXT_LENGTH,
)
from contentos.intelligence.privacy import bounded_pattern
from contentos.normalization.models import NormalizedDocument
from contentos.sources.models import Source
from contentos.strategy.service import StrategyService, normalize_phrase

COMMUNITY_NEED_PROVIDER = "community-need-extractor/1"
TAXONOMY_PROVIDER = "taxonomy-extractor/1"
MARKET_PROVIDER = "market-context-extractor/1"
COMPETITION_PROVIDER = "competition-extractor/1"

PROVIDER_FOR_FAMILY: dict[SignalFamily, str] = {
    SignalFamily.COMMUNITY_NEED: COMMUNITY_NEED_PROVIDER,
    SignalFamily.TAXONOMY: TAXONOMY_PROVIDER,
    SignalFamily.MARKET: MARKET_PROVIDER,
    SignalFamily.COMPETITION: COMPETITION_PROVIDER,
}

# Families this module extracts; the rest are owned elsewhere or reserved.
EXTRACTED_FAMILIES: tuple[SignalFamily, ...] = (
    SignalFamily.COMMUNITY_NEED,
    SignalFamily.TAXONOMY,
    SignalFamily.MARKET,
    SignalFamily.COMPETITION,
)

DEFAULT_CAPABILITIES: tuple[str, ...] = ("inspiration",)

MAX_COMMUNITY_DRAFTS = 5
MAX_TAXONOMY_DRAFTS = 12
MAX_PARAGRAPHS_SCANNED = 3
MAX_PARAGRAPH_CHARS = 1_500
MAX_MARKET_TEXT_CHARS = 2_000
MAX_LIST_ITEMS = 8
MIN_NEED_TOKENS = 3
MAX_CONCEPT_TOKENS = 8
MAX_TAXONOMY_TOKENS = 8
MAX_TAXONOMY_TERM_CHARS = 80
SHORT_TERM_TOKENS = 4

CATEGORY_OTHER = "diğer"


def _normalized(*items: str) -> frozenset[str]:
    return frozenset(normalize_phrase(item) for item in items)


# Category guess: Turkish label -> normalized keyword tuple.
_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (label, tuple(normalize_phrase(keyword) for keyword in keywords))
    for label, keywords in (
        ("doğum günü", ("doğum günü", "doğumgünü", "yaş günü", "yaş partisi", "yaş doğum")),
        ("düğün", ("düğün", "nikah", "gelin", "damat", "kına gecesi")),
        ("nişan", ("nişan", "söz kesme", "söz merasimi", "isteme")),
        ("baby shower", ("baby shower", "bebek partisi", "cinsiyet partisi", "hoşgeldin bebek")),
        ("evlilik teklifi", ("evlilik teklifi", "evlenme teklifi", "teklif")),
    )
)

# Need cues: (normalized form, display form kept in ``value.cues``).
_NEED_CUES: tuple[tuple[str, str], ...] = tuple(
    (normalize_phrase(display), display)
    for display in (
        "nasıl",
        "nereden",
        "nerede",
        "önerir misiniz",
        "önerisi olan",
        "öneri",
        "tavsiye",
        "fikir",
        "ne yapabilirim",
        "ne yapsam",
        "hangi",
        "bilen var mı",
        "yardım",
    )
)
_QUESTION_CUE = "?"

_NEED_STOPWORDS = _normalized(
    "bir",
    "ve",
    "ile",
    "için",
    "bu",
    "şu",
    "o",
    "da",
    "de",
    "mi",
    "mı",
    "mu",
    "mü",
    "çok",
    "ne",
    "nasıl",
    "nereden",
    "nerede",
    "hangi",
    "misiniz",
    "mısınız",
    "musunuz",
    "misin",
    "var",
    "yok",
    "ben",
    "biz",
    "siz",
    "bana",
    "bize",
    "acaba",
    "ya",
    "ama",
    "gibi",
    "kadar",
    "daha",
    "en",
    "hiç",
    "ad",
    "e",
    "posta",
    "telefon",
    "hesap",
    "bağlantı",
    "olacak",
    "olan",
    "diye",
    "lütfen",
    "arkadaşlar",
    "merhaba",
    "selam",
    "herkese",
    "yardımcı",
    "olur",
    "olabilir",
    "ederim",
    "rica",
    "teşekkürler",
    "önerir",
    "öneri",
    "önerisi",
    "tavsiye",
    "fikir",
    "yapabilirim",
    "yapsam",
    "yardım",
    "bilen",
    "edebilir",
)

_NAV_TERMS = _normalized(
    "sepet",
    "sepetim",
    "giriş",
    "giriş yap",
    "hesabım",
    "anasayfa",
    "ana sayfa",
    "iletişim",
    "hakkımızda",
    "kampanyalar",
    "blog",
    "sipariş",
    "siparişlerim",
    "kargo",
    "iade",
    "üye ol",
    "kategoriler",
    "ürünler",
    "tüm ürünler",
    "favoriler",
    "favorilerim",
    "sss",
    "yardım",
    "çerez",
    "gizlilik",
    "kvkk",
    "menü",
    "ara",
    "arama",
    "popüler",
    "yeni",
    "indirim",
    "indirimler",
    "öne çıkanlar",
    "çok satanlar",
    "yorumlar",
    "ödeme",
    "adres",
    "hesap",
)
_THEME_CUES = _normalized("temalı", "tema", "teması", "konsept", "konsepti")
_PRODUCT_TERMS = _normalized(
    "balon",
    "balonları",
    "pasta",
    "süs",
    "süsü",
    "süsleme",
    "süsleri",
    "set",
    "seti",
    "kutu",
    "kutusu",
    "kart",
    "davetiye",
    "afiş",
    "banner",
    "kapı süsü",
    "masa örtüsü",
    "parti malzemesi",
    "mum",
    "konfeti",
    "çerçeve",
    "tabak",
    "bardak",
    "peçete",
    "cupcake",
    "topper",
    "hediyelik",
    "hediye",
    "magnet",
    "kurdele",
    "pinyata",
    "figür",
    "taç",
    "kostüm",
    "şapka",
    "pipet",
    "örtü",
    "yazı",
    "harf",
    "çiçek",
    "buket",
    "sticker",
    "etiket",
)

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n|\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+")


@dataclass(frozen=True, slots=True)
class SignalDraft:
    family: SignalFamily
    subject: str
    concept_key: str
    value: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DocumentContext:
    """Everything an extractor may look at: never more than this."""

    document: NormalizedDocument
    source: Source
    url_host: str | None = None


def capabilities_of(source: Source) -> frozenset[str]:
    """Source capability values; defensive against a registry without them."""
    raw = getattr(source, "capabilities", None)
    if not isinstance(raw, list | tuple | set | frozenset):
        return frozenset(DEFAULT_CAPABILITIES)
    return frozenset(str(getattr(item, "value", item)) for item in raw)


def families_for(capabilities: Iterable[str]) -> tuple[SignalFamily, ...]:
    """Extracted families selected by capability, in stable order."""
    wanted = {str(item) for item in capabilities}
    return tuple(family for family in EXTRACTED_FAMILIES if family.value in wanted)


def extract_drafts(
    context: DocumentContext,
    *,
    strategy: StrategyService | None = None,
    capabilities: Iterable[str] | None = None,
) -> list[SignalDraft]:
    """Run only the extractors the source's capabilities allow."""
    selected = families_for(
        capabilities if capabilities is not None else capabilities_of(context.source)
    )
    drafts: list[SignalDraft] = []
    for family in selected:
        if family is SignalFamily.COMMUNITY_NEED:
            drafts.extend(extract_community_needs(context))
        elif family is SignalFamily.TAXONOMY:
            drafts.extend(extract_taxonomy_terms(context))
        elif family is SignalFamily.MARKET:
            drafts.extend(extract_market_context(context, strategy))
        elif family is SignalFamily.COMPETITION:
            drafts.extend(extract_competition(context))
    return drafts


# --- community_need -------------------------------------------------------


def extract_community_needs(context: DocumentContext) -> list[SignalDraft]:
    """Question/need-like sentences from title, headings and first paragraphs.

    Only a PII-scrubbed single sentence (max 300 chars) survives; the
    paragraph itself is never part of the draft.
    """
    drafts: list[SignalDraft] = []
    seen: set[str] = set()
    for sentence in _candidate_sentences(context.document):
        normalized = normalize_phrase(sentence)
        cues = _matched_cues(sentence, normalized)
        if not cues or len(normalized.split()) < MIN_NEED_TOKENS:
            continue
        pattern = bounded_pattern(sentence)
        if not pattern:
            continue
        concept_key = _need_concept_key(pattern)
        if not concept_key or concept_key in seen:
            continue
        seen.add(concept_key)
        drafts.append(
            SignalDraft(
                family=SignalFamily.COMMUNITY_NEED,
                subject=pattern[:MAX_SUBJECT_LENGTH],
                concept_key=concept_key,
                value=bounded_value(
                    {
                        "pattern": pattern,
                        "category": guess_category(normalized),
                        "cues": cues,
                    }
                ),
            )
        )
        if len(drafts) >= MAX_COMMUNITY_DRAFTS:
            break
    return drafts


def _candidate_sentences(document: NormalizedDocument) -> list[str]:
    texts: list[str] = []
    if document.title and document.title.strip():
        texts.append(document.title.strip())
    texts.extend(_heading_texts(document))
    paragraphs = [
        part.strip()
        for part in _PARAGRAPH_SPLIT.split(document.clean_text or "")
        if part and part.strip()
    ]
    for paragraph in paragraphs[:MAX_PARAGRAPHS_SCANNED]:
        texts.append(paragraph[:MAX_PARAGRAPH_CHARS])
    sentences: list[str] = []
    for text in texts:
        for sentence in _SENTENCE_SPLIT.split(text):
            cleaned = sentence.strip()
            if cleaned:
                sentences.append(cleaned)
    return sentences


def _matched_cues(sentence: str, normalized: str) -> list[str]:
    cues: list[str] = []
    if _QUESTION_CUE in sentence:
        cues.append(_QUESTION_CUE)
    padded = f" {normalized} "
    for key, display in _NEED_CUES:
        if f" {key} " in padded:
            cues.append(display)
    return cues


def _need_concept_key(pattern: str) -> str:
    tokens = [
        token
        for token in normalize_phrase(pattern).split()
        if token not in _NEED_STOPWORDS and len(token) > 1
    ]
    key = " ".join(tokens[:MAX_CONCEPT_TOKENS])
    if not key:
        key = normalize_phrase(pattern)
    return key[:MAX_CONCEPT_KEY_LENGTH]


def guess_category(normalized_text: str) -> str:
    padded = f" {normalized_text} "
    for label, keywords in _CATEGORY_KEYWORDS:
        if any(f" {keyword} " in padded for keyword in keywords):
            return label
    return CATEGORY_OTHER


# --- taxonomy -------------------------------------------------------------


def extract_taxonomy_terms(context: DocumentContext) -> list[SignalDraft]:
    """Theme/product/category term candidates from title and headings."""
    drafts: list[SignalDraft] = []
    seen: set[str] = set()
    candidates: list[str] = []
    if context.document.title and context.document.title.strip():
        candidates.append(context.document.title.strip())
    candidates.extend(_heading_texts(context.document))
    for candidate in candidates:
        term = bounded_pattern(candidate, MAX_TAXONOMY_TERM_CHARS)
        normalized = normalize_phrase(term)
        if not normalized or normalized in _NAV_TERMS or normalized in seen:
            continue
        if len(normalized.split()) > MAX_TAXONOMY_TOKENS or len(term) > MAX_TAXONOMY_TERM_CHARS:
            continue
        kind = _taxonomy_kind(normalized)
        if kind is None:
            continue
        seen.add(normalized)
        drafts.append(
            SignalDraft(
                family=SignalFamily.TAXONOMY,
                subject=term[:MAX_SUBJECT_LENGTH],
                concept_key=normalized[:MAX_CONCEPT_KEY_LENGTH],
                value=bounded_value({"term": term, "kind": kind}),
            )
        )
        if len(drafts) >= MAX_TAXONOMY_DRAFTS:
            break
    return drafts


def _taxonomy_kind(normalized: str) -> str | None:
    tokens = normalized.split()
    padded = f" {normalized} "
    if any(f" {term} " in padded for term in _PRODUCT_TERMS):
        return "product"
    if any(cue in tokens for cue in _THEME_CUES):
        return "theme"
    if guess_category(normalized) != CATEGORY_OTHER:
        return "category"
    if len(tokens) <= SHORT_TERM_TOKENS:
        return "theme"
    return None


# --- market ---------------------------------------------------------------


def extract_market_context(
    context: DocumentContext, strategy: StrategyService | None
) -> list[SignalDraft]:
    """Which strategy clusters/keywords the document touches. Nothing matched
    means no signal (UNKNOWN), never an empty market row."""
    if strategy is None:
        return []
    document = context.document
    text_parts = [document.title or "", *_heading_texts(document)]
    text_parts.append((document.clean_text or "")[:MAX_MARKET_TEXT_CHARS])
    strategy_context = strategy.context_for_text(
        " ".join(part for part in text_parts if part),
        locale=context.source.locale,
        market=context.source.market,
    )
    keywords = [row.phrase for row in strategy_context.keywords][:MAX_LIST_ITEMS]
    clusters = [row.name for row in strategy_context.clusters][:MAX_LIST_ITEMS]
    if not keywords and not clusters:
        return []
    fallback = keywords[0] if keywords else clusters[0]
    subject = bounded_pattern(document.title or fallback)
    concept_key = normalize_phrase(subject)[:MAX_CONCEPT_KEY_LENGTH]
    if not subject or not concept_key:
        return []
    return [
        SignalDraft(
            family=SignalFamily.MARKET,
            subject=subject[:MAX_SUBJECT_LENGTH],
            concept_key=concept_key,
            value=bounded_value(
                {
                    "clusters": clusters,
                    "keywords": keywords,
                    "published_at": _iso(document.external_published_at),
                }
            ),
        )
    ]


# --- competition ----------------------------------------------------------


def extract_competition(context: DocumentContext) -> list[SignalDraft]:
    """The document is a competing piece for the concept its title names."""
    document = context.document
    if not document.title or not document.title.strip():
        return []
    title = bounded_pattern(document.title)
    concept_key = normalize_phrase(title)[:MAX_CONCEPT_KEY_LENGTH]
    if not title or not concept_key:
        return []
    return [
        SignalDraft(
            family=SignalFamily.COMPETITION,
            subject=title[:MAX_SUBJECT_LENGTH],
            concept_key=concept_key,
            value=bounded_value(
                {
                    "title_pattern": title,
                    "url_host": context.url_host,
                    "published_at": _iso(document.external_published_at),
                }
            ),
        )
    ]


# --- shared helpers -------------------------------------------------------


def _heading_texts(document: NormalizedDocument) -> list[str]:
    texts: list[str] = []
    for heading in document.headings:
        if not isinstance(heading, dict):
            continue
        value = heading.get("text") or heading.get("heading") or heading.get("title")
        if isinstance(value, str) and value.strip():
            texts.append(value.strip())
    return texts


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def bounded_value(value: dict[str, Any]) -> dict[str, Any]:
    """Cap key count, list length and string length so JSON stays small."""
    bounded: dict[str, Any] = {}
    for key, item in list(value.items())[:MAX_VALUE_KEYS]:
        bounded[str(key)[:MAX_VALUE_TEXT_LENGTH]] = _bound_item(item)
    return bounded


def _bound_item(item: Any) -> Any:
    if isinstance(item, str):
        return item[:MAX_VALUE_TEXT_LENGTH]
    if isinstance(item, list | tuple):
        return [_bound_item(entry) for entry in list(item)[:MAX_VALUE_KEYS]]
    if isinstance(item, dict):
        return bounded_value(item)
    if item is None or isinstance(item, bool | int | float):
        return item
    return str(item)[:MAX_VALUE_TEXT_LENGTH]
