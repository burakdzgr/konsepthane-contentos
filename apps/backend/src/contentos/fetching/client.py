"""Safe HTTP fetch client: pinned-IP, robots-aware, bounded, redirect-checked.

Worker-independent: future Celery tasks call this; it never touches the queue
and persists nothing. Every failure maps to a stable FetchOutcome; raw
httpx/socket exceptions never escape.

DNS-rebinding protection: each hop is resolved and validated first, then the
TCP connection targets the validated IP literal while the original hostname is
preserved in the Host header and — for HTTPS — in the ``sni_hostname`` request
extension, so TLS SNI and certificate verification still run against the real
hostname. TLS verification is never disabled.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

import httpx
import structlog

from contentos.fetching.dns import (
    DnsResolutionError,
    Resolver,
    UnsafeAddressError,
    default_resolver,
    resolve_safe_addresses,
)
from contentos.fetching.models import (
    FetchOutcome,
    FetchResult,
    RetryClassification,
    RobotsDecision,
    classify_http_status,
    classify_outcome,
)
from contentos.fetching.policy import (
    RESPONSE_HEADER_ALLOWLIST,
    ROBOTS_MAX_BODY_BYTES,
    FetchPolicy,
)
from contentos.fetching.ratelimit import HostRateLimiter
from contentos.fetching.robots import RobotsChecker

_logger = structlog.get_logger("contentos.fetching")

_DEFAULT_PORTS = {"http": 80, "https": 443}
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class _FetchDenied(Exception):
    """Internal control-flow only; never escapes the client."""

    def __init__(self, outcome: FetchOutcome, detail: str | None = None) -> None:
        super().__init__(detail or outcome.value)
        self.outcome = outcome
        self.detail = detail


def _validate_fetch_url(url: str) -> SplitResult:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise _FetchDenied(FetchOutcome.INVALID_URL, "unsupported_scheme")
    if not parts.hostname:
        raise _FetchDenied(FetchOutcome.INVALID_URL, "missing_host")
    if parts.username is not None or parts.password is not None:
        raise _FetchDenied(FetchOutcome.INVALID_URL, "embedded_credentials")
    try:
        _ = parts.port
    except ValueError:
        raise _FetchDenied(FetchOutcome.INVALID_URL, "invalid_port") from None
    return parts


class FetchClient:
    """Synchronous fetch client enforcing the Phase 2 crawl policy boundary."""

    def __init__(
        self,
        policy: FetchPolicy | None = None,
        *,
        resolver: Resolver = default_resolver,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._policy = policy or FetchPolicy()
        self._resolver = resolver
        self._clock = clock
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(
                connect=self._policy.connect_timeout_seconds,
                read=self._policy.read_timeout_seconds,
                write=self._policy.write_timeout_seconds,
                pool=self._policy.pool_timeout_seconds,
            ),
            follow_redirects=False,  # redirects are validated hop by hop here
            trust_env=False,  # never adopt environment proxies/credentials
            verify=True,  # TLS verification must never be weakened
        )
        self._rate_limiter = HostRateLimiter(
            min_interval_seconds=self._policy.min_host_interval_seconds,
            max_concurrency=self._policy.per_host_concurrency,
            clock=clock,
            sleeper=sleeper,
        )
        self._robots = RobotsChecker(
            user_agent=self._policy.user_agent,
            fetch_raw=self._fetch_robots_file,
            ttl_seconds=self._policy.robots_cache_ttl_seconds,
            clock=clock,
        )

    def __enter__(self) -> "FetchClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch(self, url: str) -> FetchResult:
        """Fetch one URL under the full policy boundary (robots included)."""
        return self._fetch(
            url,
            consult_robots=True,
            enforce_mime=True,
            max_body=self._policy.max_body_bytes,
        )

    def _fetch_robots_file(self, url: str) -> FetchResult:
        return self._fetch(
            url,
            consult_robots=False,  # robots retrieval must not recurse into robots
            enforce_mime=False,  # robots.txt is often served with odd media types
            max_body=min(ROBOTS_MAX_BODY_BYTES, self._policy.max_body_bytes),
        )

    def _fetch(
        self, url: str, *, consult_robots: bool, enforce_mime: bool, max_body: int
    ) -> FetchResult:
        started = self._clock()
        fetched_at = datetime.now(UTC)
        redirect_chain: list[str] = []
        robots_decision = RobotsDecision.NOT_EVALUATED
        current_url = url
        result: FetchResult

        try:
            for _hop in range(self._policy.max_redirects + 1):
                parts = _validate_fetch_url(current_url)
                # SSRF/DNS gate FIRST: an unsafe destination is terminal
                # SSRF_BLOCKED and must never look like a robots problem.
                addresses = self._resolve_validated(parts)
                if consult_robots:
                    robots_decision = self._robots.evaluate(current_url)
                    if robots_decision is RobotsDecision.DISALLOWED:
                        raise _FetchDenied(FetchOutcome.ROBOTS_DISALLOWED)
                    if robots_decision is RobotsDecision.UNAVAILABLE:
                        raise _FetchDenied(FetchOutcome.ROBOTS_UNAVAILABLE)

                response = self._send_pinned(parts, addresses)
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    response.close()
                    if not location:
                        raise _FetchDenied(FetchOutcome.NETWORK_ERROR, "redirect_without_location")
                    redirect_chain.append(current_url)
                    current_url = urljoin(current_url, location)
                    continue
                result = self._finalize(
                    response,
                    requested_url=url,
                    final_url=current_url,
                    redirect_chain=tuple(redirect_chain),
                    robots_decision=robots_decision,
                    fetched_at=fetched_at,
                    started=started,
                    enforce_mime=enforce_mime,
                    max_body=max_body,
                )
                break
            else:
                raise _FetchDenied(FetchOutcome.REDIRECT_LIMIT_EXCEEDED)
        except _FetchDenied as denied:
            result = FetchResult(
                requested_url=url,
                outcome=denied.outcome,
                retry=classify_outcome(denied.outcome),
                robots_decision=robots_decision,
                fetched_at=fetched_at,
                duration_ms=self._elapsed_ms(started),
                final_url=current_url if current_url != url else None,
                redirect_chain=tuple(redirect_chain),
                failure_detail=denied.detail,
            )

        self._log_result(result)
        return result

    def _resolve_validated(self, parts: SplitResult) -> list[str]:
        scheme = parts.scheme.lower()
        host = parts.hostname
        assert host is not None  # _validate_fetch_url guarantees this
        try:
            return resolve_safe_addresses(
                host.lower(), parts.port or _DEFAULT_PORTS[scheme], self._resolver
            )
        except UnsafeAddressError:
            raise _FetchDenied(FetchOutcome.SSRF_BLOCKED, "unsafe_address") from None
        except DnsResolutionError:
            raise _FetchDenied(FetchOutcome.NETWORK_ERROR, "dns_resolution") from None

    def _send_pinned(self, parts: SplitResult, addresses: list[str]) -> httpx.Response:
        scheme = parts.scheme.lower()
        host = parts.hostname
        assert host is not None  # _validate_fetch_url guarantees this
        host = host.lower()
        port = parts.port

        with self._rate_limiter.acquire(host):
            target_ip = addresses[0]
            ip_host = f"[{target_ip}]" if ":" in target_ip else target_ip
            netloc = ip_host if port is None else f"{ip_host}:{port}"
            pinned_url = urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))
            host_header = host if port is None else f"{host}:{port}"
            extensions: dict[str, str] = {"sni_hostname": host} if scheme == "https" else {}
            request = httpx.Request(
                "GET",
                pinned_url,
                headers={"Host": host_header, "User-Agent": self._policy.user_agent},
                extensions=extensions,
            )
            try:
                response = self._client.send(request, stream=True)
            except httpx.ConnectTimeout:
                raise _FetchDenied(FetchOutcome.TIMEOUT, "connect_timeout") from None
            except httpx.ReadTimeout:
                raise _FetchDenied(FetchOutcome.TIMEOUT, "read_timeout") from None
            except httpx.TimeoutException:
                raise _FetchDenied(FetchOutcome.TIMEOUT, "timeout") from None
            except httpx.TransportError as exc:
                raise _FetchDenied(FetchOutcome.NETWORK_ERROR, type(exc).__name__) from None
            # The anonymous crawler never stores or replays cookies.
            self._client.cookies.clear()
            return response

    def _finalize(
        self,
        response: httpx.Response,
        *,
        requested_url: str,
        final_url: str,
        redirect_chain: tuple[str, ...],
        robots_decision: RobotsDecision,
        fetched_at: datetime,
        started: float,
        enforce_mime: bool,
        max_body: int,
    ) -> FetchResult:
        status = response.status_code
        headers = {
            name: response.headers[name]
            for name in RESPONSE_HEADER_ALLOWLIST
            if name in response.headers
        }
        raw_content_type = response.headers.get("content-type", "")
        content_type = raw_content_type.split(";")[0].strip().lower() or None

        if not 200 <= status < 300:
            response.close()
            return FetchResult(
                requested_url=requested_url,
                outcome=FetchOutcome.HTTP_ERROR,
                retry=classify_http_status(status),
                robots_decision=robots_decision,
                fetched_at=fetched_at,
                duration_ms=self._elapsed_ms(started),
                final_url=final_url,
                status_code=status,
                content_type=content_type,
                headers=headers,
                redirect_chain=redirect_chain,
                retry_after_seconds=_parse_retry_after(response.headers.get("retry-after")),
            )

        if enforce_mime and (
            content_type is None or content_type not in self._policy.allowed_content_types
        ):
            response.close()
            raise _FetchDenied(FetchOutcome.DISALLOWED_MIME, content_type or "missing")

        declared_length = response.headers.get("content-length")
        if declared_length is not None and declared_length.isdigit():
            if int(declared_length) > max_body:
                response.close()
                raise _FetchDenied(FetchOutcome.TOO_LARGE, "content_length")

        body = bytearray()
        try:
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > max_body:
                    raise _FetchDenied(FetchOutcome.TOO_LARGE, "streamed")
        finally:
            response.close()

        return FetchResult(
            requested_url=requested_url,
            outcome=FetchOutcome.SUCCESS,
            retry=RetryClassification.NOT_APPLICABLE,
            robots_decision=robots_decision,
            fetched_at=fetched_at,
            duration_ms=self._elapsed_ms(started),
            final_url=final_url,
            status_code=status,
            content_type=content_type,
            body=bytes(body),
            headers=headers,
            redirect_chain=redirect_chain,
        )

    def _elapsed_ms(self, started: float) -> float:
        return round((self._clock() - started) * 1000, 3)

    @staticmethod
    def _log_result(result: FetchResult) -> None:
        # Host only: full URLs and query strings never reach logs.
        host = urlsplit(result.requested_url).hostname
        _logger.info(
            "fetch_completed",
            host=host,
            outcome=result.outcome.value,
            retry=result.retry.value,
            status_code=result.status_code,
            duration_ms=result.duration_ms,
        )


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
