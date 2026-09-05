"""PII scrubbing for community-derived signal patterns.

Community raw text is NEVER persisted. Before any fragment of a community
document becomes a signal it passes through ``scrub_pii`` and is cut to
``MAX_PATTERN_LENGTH`` characters. The rules are deliberately eager: a
false positive costs one word of a need pattern, a false negative costs a
person's privacy.
"""

import re

MAX_PATTERN_LENGTH = 300

EMAIL_TOKEN = "[e-posta]"
PHONE_TOKEN = "[telefon]"
HANDLE_TOKEN = "[hesap]"
LINK_TOKEN = "[bağlantı]"
NAME_TOKEN = "[ad]"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)
# Any run that looks like a phone number: optional +, then digits with
# spaces/dashes/parentheses/dots between them. The digit count is checked in
# the replacement so years and prices (2026, 1500) survive.
_PHONE_CANDIDATE = re.compile(r"\+?\(?\d[\d\s().-]{7,}\d")
_MIN_PHONE_DIGITS = 10
_HANDLE = re.compile(r"(?<![\w.])@[\w.]{2,}", re.UNICODE)
_QUERY_URL = re.compile(r"(?:https?://|www\.)\S*\?\S*", re.IGNORECASE)
# "adım X", "benim adım X", "ismim X", "kızım X", "oğlum X", "eşim X",
# "kızımın adı X", "oğlumun adı X", "adı X" -> the name token becomes [ad].
_NAME_CUE = re.compile(
    r"(?P<cue>\b(?:benim\s+adım|adım|ismim|kızım(?:ın\s+adı)?|oğlum(?:un\s+adı)?"
    r"|eşim(?:in\s+adı)?|kocam|karım|annem|babam|arkadaşım|adı|ismi)\b)"
    r"(?P<sep>[\s:,]+)(?P<name>[^\W\d_]+)",
    re.IGNORECASE | re.UNICODE,
)
# Function words that may follow a cue without being a name.
_NOT_A_NAME = frozenset(
    {
        "için",
        "ile",
        "ve",
        "çok",
        "bu",
        "şu",
        "o",
        "da",
        "de",
        "artık",
        "yakında",
        "bugün",
        "yarın",
        "hemen",
        "henüz",
        "daha",
        "ne",
        "nasıl",
        "bir",
        "hiç",
        "bana",
        "bize",
        "benim",
        "bizim",
        "diye",
        "yok",
        "var",
        "ama",
        "fakat",
        "sürekli",
        "hep",
        "önümüzdeki",
        "geçen",
    }
)
_WHITESPACE = re.compile(r"\s+")


def _replace_phone(match: re.Match[str]) -> str:
    digits = sum(char.isdigit() for char in match.group(0))
    return PHONE_TOKEN if digits >= _MIN_PHONE_DIGITS else match.group(0)


def _replace_name(match: re.Match[str]) -> str:
    name = match.group("name")
    if name.casefold() in _NOT_A_NAME:
        return match.group(0)
    return f"{match.group('cue')}{match.group('sep')}{NAME_TOKEN}"


def scrub_pii(text: str) -> str:
    """Return ``text`` with e-mails, phones, handles, query URLs and named
    persons replaced by neutral tokens, whitespace collapsed."""
    cleaned = _QUERY_URL.sub(LINK_TOKEN, text)
    cleaned = _EMAIL.sub(EMAIL_TOKEN, cleaned)
    cleaned = _PHONE_CANDIDATE.sub(_replace_phone, cleaned)
    cleaned = _HANDLE.sub(HANDLE_TOKEN, cleaned)
    cleaned = _NAME_CUE.sub(_replace_name, cleaned)
    return _WHITESPACE.sub(" ", cleaned).strip()


def is_pii_free(text: str) -> bool:
    """True when scrubbing would change nothing (whitespace aside)."""
    return scrub_pii(text) == _WHITESPACE.sub(" ", text).strip()


def bounded_pattern(text: str, limit: int = MAX_PATTERN_LENGTH) -> str:
    """Scrub, then cut to ``limit`` characters on a word boundary."""
    cleaned = scrub_pii(text)
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.strip()
