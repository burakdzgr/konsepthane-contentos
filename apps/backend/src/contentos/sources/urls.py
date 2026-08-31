"""Base-URL normalization for Source registration only.

This is deliberately NOT the future general Discovery URL canonicalizer; it
normalizes exactly what Source identity needs and performs no network I/O.
"""

from urllib.parse import urlsplit, urlunsplit

ALLOWED_SCHEMES = ("http", "https")
_DEFAULT_PORTS = {"http": 80, "https": 443}


class InvalidSourceUrlError(ValueError):
    """The provided base URL cannot form a valid source identity."""


def normalize_base_url(raw_url: str) -> str:
    """Return the canonical base URL for source identity.

    Lowercases scheme/host, strips default ports, drops fragments, and removes
    a meaningless trailing slash. Rejects non-http(s) schemes, missing hosts,
    and embedded credentials.
    """
    candidate = raw_url.strip()
    if not candidate:
        raise InvalidSourceUrlError("base_url must not be empty")

    parts = urlsplit(candidate)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise InvalidSourceUrlError("base_url must use the http or https scheme")
    if not parts.hostname:
        raise InvalidSourceUrlError("base_url must include a host")
    if parts.username is not None or parts.password is not None:
        raise InvalidSourceUrlError("base_url must not embed credentials")

    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidSourceUrlError("base_url has an invalid port") from exc

    host = parts.hostname.lower()
    netloc = host if port is None or port == _DEFAULT_PORTS[scheme] else f"{host}:{port}"

    path = parts.path.rstrip("/")

    return urlunsplit((scheme, netloc, path, parts.query, ""))
