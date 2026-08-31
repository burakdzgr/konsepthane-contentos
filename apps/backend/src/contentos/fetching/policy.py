"""Explicit, conservative fetch policy. No magic numbers in client code."""

from dataclasses import dataclass

from contentos.core.config import Settings

DEFAULT_USER_AGENT = "Konsepthane-ContentOS/0.1 (+https://konsepthane.net)"

# Conservative research-oriented media types; charset parameters are ignored
# when comparing. Content parsing itself is a later task.
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "text/plain",
        "application/xml",
        "text/xml",
        "application/rss+xml",
        "application/atom+xml",
    }
)

# Only these response headers are ever returned to callers. Set-Cookie and
# other headers are deliberately dropped.
RESPONSE_HEADER_ALLOWLIST: tuple[str, ...] = (
    "content-type",
    "content-language",
    "content-length",
    "etag",
    "last-modified",
    "cache-control",
)

ROBOTS_MAX_BODY_BYTES = 512 * 1024


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    """Immutable limits governing every request the fetch client makes."""

    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 10.0
    write_timeout_seconds: float = 5.0
    pool_timeout_seconds: float = 5.0
    max_redirects: int = 5
    max_body_bytes: int = 5 * 1024 * 1024
    allowed_content_types: frozenset[str] = ALLOWED_CONTENT_TYPES
    user_agent: str = DEFAULT_USER_AGENT
    per_host_concurrency: int = 1
    min_host_interval_seconds: float = 1.0
    robots_cache_ttl_seconds: float = 900.0


def build_fetch_policy(settings: Settings) -> FetchPolicy:
    """Build the operational fetch policy from typed application settings."""
    return FetchPolicy(
        connect_timeout_seconds=float(settings.fetch_connect_timeout_seconds),
        read_timeout_seconds=float(settings.fetch_read_timeout_seconds),
        max_body_bytes=settings.fetch_max_body_bytes,
        max_redirects=settings.fetch_max_redirects,
        min_host_interval_seconds=settings.fetch_min_host_interval_seconds,
        user_agent=settings.fetch_user_agent,
    )
