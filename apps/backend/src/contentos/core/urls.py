"""Shared, versioned, network-free URL canonicalization for research URLs.

This is syntax-level identity only: a canonical URL is NOT a safe-to-fetch
URL. The future fetch boundary must still perform DNS/IP safety checks,
private-network rejection, redirect safety, robots policy, and response-size
limits — none of that belongs here, and this module performs no network I/O.

Deliberately separate from ``contentos.sources.urls``: Source base-URL
normalization is a committed registration-identity contract with different
semantics (no root slash, query untouched, no tracking removal) and must not
drift when canonicalization evolves.

Version 1 semantics are frozen. Any behavioral change requires a new version.
"""

import hashlib
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

URL_CANONICALIZATION_VERSION = 1

ALLOWED_SCHEMES = ("http", "https")
_DEFAULT_PORTS = {"http": 80, "https": 443}

# Frozen v1 tracking-parameter policy: removed keys never carry content
# semantics. Matched case-insensitively. Expanding this set is a new version.
TRACKING_PARAMETER_PREFIXES: tuple[str, ...] = ("utm_",)
TRACKING_PARAMETERS: frozenset[str] = frozenset({"gclid", "fbclid", "msclkid"})


class InvalidUrlError(ValueError):
    """The URL cannot be canonicalized. Messages never echo the raw URL."""


@dataclass(frozen=True, slots=True)
class CanonicalUrl:
    """A canonical URL together with the rules version that produced it."""

    url: str
    version: int


def _is_tracking_parameter(key: str) -> bool:
    lowered = key.lower()
    return lowered in TRACKING_PARAMETERS or lowered.startswith(TRACKING_PARAMETER_PREFIXES)


def canonicalize_url(raw_url: str) -> CanonicalUrl:
    """Canonicalize an absolute http(s) URL with frozen v1 rules.

    Rules: lowercase scheme/host, strip default ports, drop fragments, empty
    path becomes ``/``, non-root trailing slash removed, path left otherwise
    untouched (no percent re-encoding), tracking parameters removed, remaining
    query pairs sorted by (key, value) with duplicates preserved.
    """
    candidate = raw_url.strip()
    if not candidate:
        raise InvalidUrlError("URL must not be empty")

    parts = urlsplit(candidate)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise InvalidUrlError("URL must be absolute and use the http or https scheme")
    if not parts.hostname:
        raise InvalidUrlError("URL must include a host")
    if parts.username is not None or parts.password is not None:
        raise InvalidUrlError("URL must not embed credentials")

    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidUrlError("URL has an invalid port") from exc

    host = parts.hostname.lower()
    netloc = host if port is None or port == _DEFAULT_PORTS[scheme] else f"{host}:{port}"

    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"

    meaningful_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_parameter(key)
    ]
    query = urlencode(sorted(meaningful_pairs))

    return CanonicalUrl(
        url=urlunsplit((scheme, netloc, path, query, "")),
        version=URL_CANONICALIZATION_VERSION,
    )


def canonical_url_hash(canonical_url: str) -> str:
    """SHA-256 lowercase hex of the canonical URL's UTF-8 bytes. No salt."""
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
