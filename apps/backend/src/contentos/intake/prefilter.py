"""Deterministic, cheap URL prefilter for autonomous intake.

Classifies a discovered URL WITHOUT fetching it: archive/tag/category/
pagination pages, non-article assets, and obviously non-editorial paths
are rejected with a coded reason and a named rule; everything else is
eligible for the bounded fetch pipeline. Purely syntactic — a URL is a
machine fact here, never an editorial decision.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

from contentos.discovery.enums import DiscoveryRejectionReason

MAX_URL_LENGTH = 2000

_ASSET_SUFFIXES = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".pdf",
    ".zip",
    ".mp3",
    ".mp4",
    ".xml",
    ".xsl",
    ".css",
    ".js",
    ".txt",
)

# Path SEGMENTS that mark listing/utility pages rather than articles.
_LISTING_SEGMENTS = frozenset(
    {
        "tag",
        "tags",
        "category",
        "categories",
        "author",
        "page",
        "feed",
        "archive",
        "archives",
        "search",
        "wp-content",
        "wp-json",
        "wp-admin",
        "cart",
        "checkout",
        "shop",
        "store",
        "product",
        "products",
        "product-category",
        "login",
        "signup",
        "account",
    }
)

_UTILITY_PAGES = frozenset(
    {
        "about",
        "about-us",
        "contact",
        "contact-us",
        "privacy",
        "privacy-policy",
        "terms",
        "terms-of-service",
        "advertise",
        "sitemap",
        "disclosure",
        "faq",
    }
)


@dataclass(frozen=True)
class PrefilterRejection:
    reason: DiscoveryRejectionReason
    rule: str


def classify_url(url: str) -> PrefilterRejection | None:
    """None means eligible for bounded fetch; a rejection carries the
    coded reason plus the specific deterministic rule that fired."""
    candidate = url.strip()
    if not candidate or len(candidate) > MAX_URL_LENGTH:
        return PrefilterRejection(DiscoveryRejectionReason.INVALID_URL, "url_length")
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return PrefilterRejection(DiscoveryRejectionReason.INVALID_URL, "url_parse")
    if parts.scheme not in ("http", "https"):
        return PrefilterRejection(DiscoveryRejectionReason.UNSUPPORTED_SCHEME, "scheme")
    if not parts.netloc:
        return PrefilterRejection(DiscoveryRejectionReason.INVALID_URL, "missing_host")

    path = parts.path.lower().rstrip("/")
    if not path:
        return PrefilterRejection(DiscoveryRejectionReason.OUT_OF_SCOPE, "site_root")
    for suffix in _ASSET_SUFFIXES:
        if path.endswith(suffix):
            return PrefilterRejection(DiscoveryRejectionReason.OUT_OF_SCOPE, "asset_extension")

    segments = [segment for segment in path.split("/") if segment]
    for segment in segments:
        if segment in _LISTING_SEGMENTS:
            return PrefilterRejection(DiscoveryRejectionReason.OUT_OF_SCOPE, f"listing:{segment}")
    last = segments[-1]
    stem = last[: -len(".html")] if last.endswith((".html", ".htm")) else last
    if stem in _UTILITY_PAGES:
        return PrefilterRejection(DiscoveryRejectionReason.OUT_OF_SCOPE, f"utility:{stem}")
    # Pure date archives like /2024 or /2024/05 (no article slug).
    if all(segment.isdigit() for segment in segments):
        return PrefilterRejection(DiscoveryRejectionReason.OUT_OF_SCOPE, "date_archive")
    return None
