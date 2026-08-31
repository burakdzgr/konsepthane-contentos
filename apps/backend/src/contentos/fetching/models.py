"""Fetch transport contracts: outcomes, retry classification, results.

These are in-memory transport results. FetchSnapshot persistence maps this
contract in a separate module. Raw httpx/socket exceptions are never part of
this contract.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class FetchOutcome(StrEnum):
    """Stable classification of one fetch attempt (design section 3)."""

    SUCCESS = "success"
    INVALID_URL = "invalid_url"
    SSRF_BLOCKED = "ssrf_blocked"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    TOO_LARGE = "too_large"
    DISALLOWED_MIME = "disallowed_mime"
    REDIRECT_LIMIT_EXCEEDED = "redirect_limit_exceeded"
    ROBOTS_DISALLOWED = "robots_disallowed"
    ROBOTS_UNAVAILABLE = "robots_unavailable"
    HTTP_ERROR = "http_error"


class RetryClassification(StrEnum):
    """Whether future orchestration may retry; the client itself never retries."""

    NOT_APPLICABLE = "not_applicable"
    RETRYABLE = "retryable"
    TERMINAL = "terminal"


class RobotsDecision(StrEnum):
    """Robots evaluation for a fetched URL."""

    ALLOWED = "allowed"
    DISALLOWED = "disallowed"
    UNAVAILABLE = "unavailable"
    NOT_EVALUATED = "not_evaluated"


_RETRYABLE_OUTCOMES = frozenset(
    {FetchOutcome.TIMEOUT, FetchOutcome.NETWORK_ERROR, FetchOutcome.ROBOTS_UNAVAILABLE}
)
_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429})


def classify_http_status(status_code: int) -> RetryClassification:
    """Deterministic retry classification for a non-2xx, non-3xx status."""
    if status_code in _RETRYABLE_STATUS_CODES or 500 <= status_code <= 599:
        return RetryClassification.RETRYABLE
    return RetryClassification.TERMINAL


def classify_outcome(outcome: FetchOutcome, status_code: int | None = None) -> RetryClassification:
    """Retry classification for a fetch outcome per the design's fetch policy."""
    if outcome is FetchOutcome.SUCCESS:
        return RetryClassification.NOT_APPLICABLE
    if outcome is FetchOutcome.HTTP_ERROR and status_code is not None:
        return classify_http_status(status_code)
    if outcome in _RETRYABLE_OUTCOMES:
        return RetryClassification.RETRYABLE
    return RetryClassification.TERMINAL


@dataclass(frozen=True, slots=True)
class FetchResult:
    """In-memory result of one bounded, policy-checked fetch attempt."""

    requested_url: str
    outcome: FetchOutcome
    retry: RetryClassification
    robots_decision: RobotsDecision
    fetched_at: datetime
    duration_ms: float
    final_url: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    body: bytes | None = None
    headers: dict[str, str] = field(default_factory=dict)
    redirect_chain: tuple[str, ...] = ()
    failure_detail: str | None = None
    retry_after_seconds: float | None = None

    @property
    def is_success(self) -> bool:
        return self.outcome is FetchOutcome.SUCCESS
