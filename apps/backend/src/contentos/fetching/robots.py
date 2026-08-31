"""Robots-aware gate for research fetching. Fails closed when undeterminable.

The raw fetcher supplied here must apply the full SSRF/redirect/timeout/body
protections but must NOT itself consult robots — that would recurse.
"""

import time
from collections.abc import Callable
from urllib import robotparser
from urllib.parse import urlsplit

from contentos.fetching.models import FetchOutcome, FetchResult, RobotsDecision

RawFetcher = Callable[[str], FetchResult]

_CacheEntry = tuple[float, robotparser.RobotFileParser | None, RobotsDecision | None]


class RobotsChecker:
    """Per-origin robots evaluation with a bounded, TTL-based in-memory cache.

    Semantics (RFC 9309-leaning, per the design): a parsable robots.txt is
    evaluated against the ContentOS user agent; a 4xx robots response means no
    crawl restrictions exist (ALLOWED); anything else — 5xx, timeouts, network
    errors, or SSRF-blocked robots redirects — is UNAVAILABLE and fails
    closed. Malformed robots content is parsed leniently and deterministically
    by the stdlib parser. The cache is process-local and optional state only.
    """

    def __init__(
        self,
        *,
        user_agent: str,
        fetch_raw: RawFetcher,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_entries: int = 512,
    ) -> None:
        self._user_agent = user_agent
        self._fetch_raw = fetch_raw
        self._ttl = ttl_seconds
        self._clock = clock
        self._max_entries = max_entries
        self._cache: dict[str, _CacheEntry] = {}

    def evaluate(self, url: str) -> RobotsDecision:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}".lower()
        entry = self._cache.get(origin)
        if entry is None or entry[0] <= self._clock():
            entry = self._load(origin)
            if len(self._cache) >= self._max_entries:
                self._cache.pop(next(iter(self._cache)))
            self._cache[origin] = entry
        _, parser, fixed_decision = entry
        if fixed_decision is not None:
            return fixed_decision
        assert parser is not None
        if parser.can_fetch(self._user_agent, url):
            return RobotsDecision.ALLOWED
        return RobotsDecision.DISALLOWED

    def _load(self, origin: str) -> _CacheEntry:
        expires_at = self._clock() + self._ttl
        result = self._fetch_raw(f"{origin}/robots.txt")
        if result.outcome is FetchOutcome.SUCCESS and result.body is not None:
            parser = robotparser.RobotFileParser()
            parser.parse(result.body.decode("utf-8", errors="replace").splitlines())
            return (expires_at, parser, None)
        if (
            result.outcome is FetchOutcome.HTTP_ERROR
            and result.status_code is not None
            and 400 <= result.status_code <= 499
        ):
            return (expires_at, None, RobotsDecision.ALLOWED)
        return (expires_at, None, RobotsDecision.UNAVAILABLE)
