"""Bounded HTTP transport shared by every provider adapter.

One place maps transport outcomes to typed provider errors: 401/403 →
`access_required`, 429 → `rate_limited` (honouring `Retry-After`), 5xx and
timeouts → `degraded` after bounded exponential backoff (max 2 retries),
connection failures → `error`. Response bodies are never copied into error
classes; only the status or a short token is.
"""

import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from contentos.integrations.base import ProviderError, sanitize_error_class
from contentos.integrations.enums import ProviderState

MAX_RETRIES = 2
BACKOFF_BASE_SECONDS = 0.5
# A Retry-After longer than this is reported instead of waited for.
MAX_WAIT_SECONDS = 5.0

Sleep = Callable[[float], None]
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def parse_retry_after(value: str | None, *, now: datetime) -> float | None:
    """Seconds to wait from a `Retry-After` header (delta-seconds or HTTP-date)."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return float(text)
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - now).total_seconds())


class ProviderHttp:
    """httpx wrapper with retry/backoff and typed error mapping."""

    def __init__(
        self,
        prefix: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 20.0,
        sleep: Sleep | None = None,
        clock: Clock | None = None,
        user_agent: str = "Konsepthane-ContentOS/0.1 (+https://konsepthane.net)",
    ) -> None:
        self._prefix = prefix
        self._timeout = timeout_seconds
        self._sleep: Sleep = sleep if sleep is not None else time.sleep
        self._clock: Clock = clock if clock is not None else utc_now
        self._client = client if client is not None else httpx.Client(timeout=timeout_seconds)
        self._user_agent = user_agent

    @property
    def prefix(self) -> str:
        return self._prefix

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json_body: Any | None = None,
        data: Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> httpx.Response:
        """Perform one request; retry bounded on 429/5xx/timeouts."""
        merged_headers = {"User-Agent": self._user_agent, **dict(headers or {})}
        attempt = 0
        while True:
            try:
                response = self._client.request(
                    method,
                    url,
                    params=params,
                    headers=merged_headers,
                    json=json_body,
                    data=data,
                    timeout=timeout_seconds if timeout_seconds is not None else self._timeout,
                )
            except httpx.TimeoutException:
                if attempt < MAX_RETRIES:
                    self._sleep(BACKOFF_BASE_SECONDS * (2**attempt))
                    attempt += 1
                    continue
                raise ProviderError(
                    f"{self._prefix}: request timed out",
                    kind=ProviderState.DEGRADED,
                    error_class=sanitize_error_class(self._prefix, "timeout"),
                ) from None
            except httpx.HTTPError as error:
                raise ProviderError(
                    f"{self._prefix}: connection failed ({type(error).__name__})",
                    kind=ProviderState.ERROR,
                    error_class=sanitize_error_class(self._prefix, "connection"),
                ) from None

            status = response.status_code
            if status < 400:
                return response
            if status in (401, 403):
                raise ProviderError(
                    f"{self._prefix}: access refused (HTTP {status})",
                    kind=ProviderState.ACCESS_REQUIRED,
                    error_class=sanitize_error_class(self._prefix, f"http_{status}"),
                )
            if status == 429:
                wait = parse_retry_after(response.headers.get("Retry-After"), now=self._clock())
                if attempt < MAX_RETRIES and (wait is None or wait <= MAX_WAIT_SECONDS):
                    self._sleep(wait if wait is not None else BACKOFF_BASE_SECONDS * (2**attempt))
                    attempt += 1
                    continue
                raise ProviderError(
                    f"{self._prefix}: rate limited (HTTP 429)",
                    kind=ProviderState.RATE_LIMITED,
                    error_class=sanitize_error_class(self._prefix, "http_429"),
                    retry_after_seconds=wait,
                )
            if status >= 500:
                if attempt < MAX_RETRIES:
                    self._sleep(BACKOFF_BASE_SECONDS * (2**attempt))
                    attempt += 1
                    continue
                raise ProviderError(
                    f"{self._prefix}: upstream failure (HTTP {status})",
                    kind=ProviderState.DEGRADED,
                    error_class=sanitize_error_class(self._prefix, f"http_{status}"),
                )
            raise ProviderError(
                f"{self._prefix}: request rejected (HTTP {status})",
                kind=ProviderState.ERROR,
                error_class=sanitize_error_class(self._prefix, f"http_{status}"),
            )

    def json(self, response: httpx.Response) -> Any:
        """Decode a JSON body or raise the bounded malformed-body error."""
        try:
            return response.json()
        except ValueError:
            raise ProviderError(
                f"{self._prefix}: malformed JSON body",
                kind=ProviderState.ERROR,
                error_class=sanitize_error_class(self._prefix, "malformed_body"),
            ) from None

    def close(self) -> None:
        self._client.close()
