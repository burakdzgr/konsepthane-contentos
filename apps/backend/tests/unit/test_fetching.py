"""Tests for the safe HTTP fetch client boundary."""

from collections.abc import Callable

import httpx
import pytest
from pydantic import ValidationError

from contentos.core.config import Environment, LogLevel, Settings
from contentos.fetching.client import FetchClient
from contentos.fetching.dns import (
    DnsResolutionError,
    UnsafeAddressError,
    is_safe_address,
    resolve_safe_addresses,
)
from contentos.fetching.models import (
    FetchOutcome,
    RetryClassification,
    RobotsDecision,
)
from contentos.fetching.policy import (
    DEFAULT_USER_AGENT,
    FetchPolicy,
    build_fetch_policy,
)
from contentos.fetching.ratelimit import HostRateLimiter

SAFE_DNS: dict[str, list[str]] = {
    "example.com": ["93.184.216.34"],
    "other.example": ["8.8.8.8"],
    "redirect.example": ["1.1.1.1"],
    "evil.example": ["10.0.0.5"],
    "mixed.example": ["93.184.216.34", "10.0.0.5"],
}


def fake_resolver(host: str, port: int) -> list[str]:
    try:
        return SAFE_DNS[host]
    except KeyError:
        raise DnsResolutionError(f"cannot resolve host '{host}'") from None


Handler = Callable[[httpx.Request], httpx.Response]

ROBOTS_ALLOW_ALL = "User-agent: *\nAllow: /\n"


def make_client(
    handler: Handler,
    *,
    policy: FetchPolicy | None = None,
    recorded: list[httpx.Request] | None = None,
    sleeper: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> FetchClient:
    requests = recorded if recorded is not None else []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return FetchClient(
        policy or FetchPolicy(min_host_interval_seconds=0.0),
        resolver=fake_resolver,
        transport=httpx.MockTransport(recording_handler),
        clock=clock or (lambda: 0.0),
        sleeper=sleeper or (lambda seconds: None),
    )


def simple_site(
    robots_body: str = ROBOTS_ALLOW_ALL,
    page_body: str = "<html>ok</html>",
    page_headers: dict[str, str] | None = None,
) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots_body, headers={"content-type": "text/plain"})
        headers = {"content-type": "text/html; charset=utf-8"}
        headers.update(page_headers or {})
        return httpx.Response(200, text=page_body, headers=headers)

    return handler


class TestUrlValidation:
    @pytest.mark.parametrize(
        ("url", "detail"),
        [
            ("ftp://example.com/x", "unsupported_scheme"),
            ("file:///etc/passwd", "unsupported_scheme"),
            ("/relative/only", "unsupported_scheme"),
            ("https://user:pw@example.com/x", "embedded_credentials"),
            ("https://example.com:notaport/x", "invalid_port"),
            ("https:///no-host", "missing_host"),
        ],
    )
    def test_invalid_urls_are_terminal(self, url: str, detail: str) -> None:
        with make_client(simple_site()) as client:
            result = client.fetch(url)

        assert result.outcome is FetchOutcome.INVALID_URL
        assert result.retry is RetryClassification.TERMINAL
        assert result.failure_detail == detail

    def test_http_and_https_are_accepted(self) -> None:
        with make_client(simple_site()) as client:
            assert client.fetch("http://example.com/page").is_success
            assert client.fetch("https://example.com/page").is_success


class TestAddressSafety:
    @pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:4700::6810:84e5"])
    def test_public_addresses_are_safe(self, address: str) -> None:
        assert is_safe_address(address)

    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "10.1.2.3",
            "172.16.0.9",
            "192.168.1.1",
            "169.254.1.1",
            "169.254.169.254",
            "100.64.0.1",
            "192.0.2.1",
            "0.0.0.0",
            "::1",
            "fe80::1",
            "fc00::1",
            "fd12:3456::1",
            "ff02::1",
            "::",
            "::ffff:10.0.0.1",
            "not-an-ip",
        ],
    )
    def test_unsafe_addresses_are_rejected(self, address: str) -> None:
        assert not is_safe_address(address)

    def test_mixed_dns_answers_fail_closed(self) -> None:
        with pytest.raises(UnsafeAddressError):
            resolve_safe_addresses("mixed.example", 443, fake_resolver)

    def test_ip_literal_hosts_are_validated_directly(self) -> None:
        assert resolve_safe_addresses("93.184.216.34", 443, fake_resolver) == ["93.184.216.34"]
        with pytest.raises(UnsafeAddressError):
            resolve_safe_addresses("127.0.0.1", 443, fake_resolver)


class TestSsrfThroughClient:
    def test_private_destination_is_blocked(self) -> None:
        with make_client(simple_site()) as client:
            result = client.fetch("https://evil.example/page")

        assert result.outcome is FetchOutcome.SSRF_BLOCKED
        assert result.retry is RetryClassification.TERMINAL

    def test_mixed_answers_are_blocked(self) -> None:
        with make_client(simple_site()) as client:
            result = client.fetch("https://mixed.example/page")

        assert result.outcome is FetchOutcome.SSRF_BLOCKED

    def test_unresolvable_host_is_retryable_network_error(self) -> None:
        with make_client(simple_site()) as client:
            result = client.fetch("https://unknown.example/page")

        assert result.outcome is FetchOutcome.NETWORK_ERROR
        assert result.retry is RetryClassification.RETRYABLE
        assert result.failure_detail == "dns_resolution"


class TestPinnedConnections:
    def test_transport_receives_validated_ip_with_original_host_and_sni(self) -> None:
        recorded: list[httpx.Request] = []
        with make_client(simple_site(), recorded=recorded) as client:
            result = client.fetch("https://example.com/page?a=1")

        assert result.is_success
        assert recorded, "transport was never called"
        for request in recorded:
            assert request.url.host == "93.184.216.34"
            assert request.headers["host"] == "example.com"
            assert request.extensions.get("sni_hostname") == "example.com"

    def test_transport_never_sees_the_original_hostname(self) -> None:
        recorded: list[httpx.Request] = []
        with make_client(simple_site(), recorded=recorded) as client:
            client.fetch("https://example.com/page")

        assert all(request.url.host != "example.com" for request in recorded)

    def test_non_default_port_is_preserved_in_target_and_host_header(self) -> None:
        recorded: list[httpx.Request] = []
        with make_client(simple_site(), recorded=recorded) as client:
            client.fetch("https://example.com:8443/page")

        page_requests = [r for r in recorded if r.url.path == "/page"]
        assert page_requests[0].url.port == 8443
        assert page_requests[0].headers["host"] == "example.com:8443"


class TestRedirects:
    def test_safe_cross_host_redirect_is_followed_with_revalidation(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
            if request.headers["host"] == "example.com":
                return httpx.Response(302, headers={"location": "https://other.example/final"})
            return httpx.Response(200, text="done", headers={"content-type": "text/plain"})

        recorded: list[httpx.Request] = []
        with make_client(handler, recorded=recorded) as client:
            result = client.fetch("https://example.com/start")

        assert result.is_success
        assert result.final_url == "https://other.example/final"
        assert result.redirect_chain == ("https://example.com/start",)
        robots_hosts = {r.headers["host"] for r in recorded if r.url.path == "/robots.txt"}
        assert robots_hosts == {"example.com", "other.example"}

    def test_redirect_to_private_destination_is_blocked(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
            if request.headers["host"] == "example.com":
                return httpx.Response(302, headers={"location": "https://evil.example/inside"})
            raise AssertionError("private destination must never be contacted")

        with make_client(handler) as client:
            result = client.fetch("https://example.com/start")

        assert result.outcome is FetchOutcome.SSRF_BLOCKED

    def test_relative_location_is_resolved_against_current_url(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
            if request.url.path == "/start":
                return httpx.Response(302, headers={"location": "/next"})
            return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})

        with make_client(handler) as client:
            result = client.fetch("https://example.com/start")

        assert result.is_success
        assert result.final_url == "https://example.com/next"

    def test_redirect_limit_is_enforced(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
            target = "/a" if request.url.path == "/b" else "/b"
            return httpx.Response(302, headers={"location": target})

        policy = FetchPolicy(min_host_interval_seconds=0.0, max_redirects=3)
        with make_client(handler, policy=policy) as client:
            result = client.fetch("https://example.com/a")

        assert result.outcome is FetchOutcome.REDIRECT_LIMIT_EXCEEDED
        assert result.retry is RetryClassification.TERMINAL
        assert len(result.redirect_chain) == 4

    def test_redirect_without_location_is_a_network_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
            return httpx.Response(302)

        with make_client(handler) as client:
            result = client.fetch("https://example.com/start")

        assert result.outcome is FetchOutcome.NETWORK_ERROR
        assert result.failure_detail == "redirect_without_location"


class TestRobots:
    def test_disallowed_path_is_denied_without_page_request(self) -> None:
        recorded: list[httpx.Request] = []
        handler = simple_site(robots_body="User-agent: *\nDisallow: /private\n")
        with make_client(handler, recorded=recorded) as client:
            result = client.fetch("https://example.com/private/page")

        assert result.outcome is FetchOutcome.ROBOTS_DISALLOWED
        assert result.retry is RetryClassification.TERMINAL
        assert result.robots_decision is RobotsDecision.DISALLOWED
        assert all(r.url.path == "/robots.txt" for r in recorded)

    def test_allowed_path_succeeds_and_robots_is_cached(self) -> None:
        recorded: list[httpx.Request] = []
        handler = simple_site(robots_body="User-agent: *\nDisallow: /private\n")
        with make_client(handler, recorded=recorded) as client:
            first = client.fetch("https://example.com/public")
            second = client.fetch("https://example.com/also-public")

        assert first.is_success and second.is_success
        assert first.robots_decision is RobotsDecision.ALLOWED
        robots_requests = [r for r in recorded if r.url.path == "/robots.txt"]
        assert len(robots_requests) == 1

    def test_specific_user_agent_group_is_honoured(self) -> None:
        robots = "User-agent: Konsepthane-ContentOS\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
        with make_client(simple_site(robots_body=robots)) as client:
            result = client.fetch("https://example.com/page")

        assert result.outcome is FetchOutcome.ROBOTS_DISALLOWED

    def test_missing_robots_means_allowed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})

        with make_client(handler) as client:
            result = client.fetch("https://example.com/page")

        assert result.is_success
        assert result.robots_decision is RobotsDecision.ALLOWED

    def test_unavailable_robots_fails_closed_and_is_retryable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(503)
            raise AssertionError("page must not be fetched when robots is unavailable")

        with make_client(handler) as client:
            result = client.fetch("https://example.com/page")

        assert result.outcome is FetchOutcome.ROBOTS_UNAVAILABLE
        assert result.retry is RetryClassification.RETRYABLE
        assert result.robots_decision is RobotsDecision.UNAVAILABLE

    def test_robots_redirecting_to_private_target_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(302, headers={"location": "https://evil.example/robots.txt"})
            raise AssertionError("page must not be fetched")

        with make_client(handler) as client:
            result = client.fetch("https://example.com/page")

        assert result.outcome is FetchOutcome.ROBOTS_UNAVAILABLE

    def test_malformed_robots_is_deterministically_lenient(self) -> None:
        handler = simple_site(robots_body="\x00\x01 not robots at all \x02")
        with make_client(handler) as client:
            first = client.fetch("https://example.com/page")

        assert first.is_success

    def test_robots_cache_expires_with_clock(self) -> None:
        recorded: list[httpx.Request] = []
        now = {"value": 0.0}
        policy = FetchPolicy(min_host_interval_seconds=0.0, robots_cache_ttl_seconds=100.0)
        with make_client(
            simple_site(), recorded=recorded, policy=policy, clock=lambda: now["value"]
        ) as client:
            client.fetch("https://example.com/a")
            now["value"] = 50.0
            client.fetch("https://example.com/b")
            now["value"] = 500.0
            client.fetch("https://example.com/c")

        robots_requests = [r for r in recorded if r.url.path == "/robots.txt"]
        assert len(robots_requests) == 2


class TestBodyLimits:
    def test_body_under_limit_is_returned(self) -> None:
        handler = simple_site(page_body="körfez " * 10)
        with make_client(handler) as client:
            result = client.fetch("https://example.com/page")

        assert result.is_success
        assert result.body is not None
        assert "körfez" in result.body.decode("utf-8")

    def test_declared_content_length_over_limit_rejects_early(self) -> None:
        handler = simple_site(page_headers={"content-length": str(50_000_000)})
        policy = FetchPolicy(min_host_interval_seconds=0.0, max_body_bytes=1024)
        with make_client(handler, policy=policy) as client:
            result = client.fetch("https://example.com/page")

        assert result.outcome is FetchOutcome.TOO_LARGE
        assert result.failure_detail == "content_length"

    def test_streamed_body_over_limit_is_rejected(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
            chunks = iter([b"x" * 512] * 10)  # no content-length: chunked-style
            return httpx.Response(200, content=chunks, headers={"content-type": "text/html"})

        policy = FetchPolicy(min_host_interval_seconds=0.0, max_body_bytes=2048)
        with make_client(handler, policy=policy) as client:
            result = client.fetch("https://example.com/page")

        assert result.outcome is FetchOutcome.TOO_LARGE
        assert result.failure_detail == "streamed"
        assert result.retry is RetryClassification.TERMINAL


class TestMimePolicy:
    @pytest.mark.parametrize(
        "content_type",
        [
            "text/html; charset=utf-8",
            "application/rss+xml",
            "application/atom+xml",
            "text/plain",
            "application/xml",
        ],
    )
    def test_allowed_media_types_pass(self, content_type: str) -> None:
        handler = simple_site(page_headers={"content-type": content_type})
        with make_client(handler) as client:
            assert client.fetch("https://example.com/page").is_success

    @pytest.mark.parametrize(
        "content_type", ["image/png", "application/pdf", "application/zip", "video/mp4"]
    )
    def test_disallowed_media_types_are_rejected(self, content_type: str) -> None:
        handler = simple_site(page_headers={"content-type": content_type})
        with make_client(handler) as client:
            result = client.fetch("https://example.com/page")

        assert result.outcome is FetchOutcome.DISALLOWED_MIME
        assert result.retry is RetryClassification.TERMINAL


class TestResponseHeaders:
    def test_only_allowlisted_headers_are_returned(self) -> None:
        handler = simple_site(
            page_headers={
                "etag": '"abc"',
                "last-modified": "Mon, 31 Aug 2026 10:00:00 GMT",
                "set-cookie": "session=secret",
                "x-powered-by": "leaky-server",
            }
        )
        with make_client(handler) as client:
            result = client.fetch("https://example.com/page")

        assert result.headers["etag"] == '"abc"'
        assert "set-cookie" not in result.headers
        assert "x-powered-by" not in result.headers
        assert set(result.headers) <= {
            "content-type",
            "content-language",
            "content-length",
            "etag",
            "last-modified",
            "cache-control",
        }


class TestStatusClassification:
    @pytest.mark.parametrize(
        ("status", "expected_retry"),
        [
            (404, RetryClassification.TERMINAL),
            (410, RetryClassification.TERMINAL),
            (403, RetryClassification.TERMINAL),
            (408, RetryClassification.RETRYABLE),
            (429, RetryClassification.RETRYABLE),
            (500, RetryClassification.RETRYABLE),
            (503, RetryClassification.RETRYABLE),
        ],
    )
    def test_http_error_classification(
        self, status: int, expected_retry: RetryClassification
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
            return httpx.Response(status)

        with make_client(handler) as client:
            result = client.fetch("https://example.com/page")

        assert result.outcome is FetchOutcome.HTTP_ERROR
        assert result.status_code == status
        assert result.retry is expected_retry

    def test_retry_after_is_metadata_only(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
            return httpx.Response(429, headers={"retry-after": "120"})

        sleeps: list[float] = []
        with make_client(handler, sleeper=sleeps.append) as client:
            result = client.fetch("https://example.com/page")

        assert result.retry_after_seconds == 120.0
        assert sleeps == []  # no in-client waiting on Retry-After

    def test_timeouts_and_transport_errors_are_classified(self) -> None:
        errors: dict[str, Exception] = {
            "/connect": httpx.ConnectTimeout("slow connect"),
            "/read": httpx.ReadTimeout("slow read"),
            "/broken": httpx.ConnectError("connection refused"),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text=ROBOTS_ALLOW_ALL)
            raise errors[request.url.path]

        with make_client(handler) as client:
            connect = client.fetch("https://example.com/connect")
            read = client.fetch("https://example.com/read")
            broken = client.fetch("https://example.com/broken")

        assert connect.outcome is FetchOutcome.TIMEOUT
        assert connect.failure_detail == "connect_timeout"
        assert read.failure_detail == "read_timeout"
        assert broken.outcome is FetchOutcome.NETWORK_ERROR
        assert all(r.retry is RetryClassification.RETRYABLE for r in (connect, read, broken))


class TestRateLimiting:
    def test_minimum_interval_is_enforced_per_host(self) -> None:
        sleeps: list[float] = []
        now = {"value": 100.0}
        limiter = HostRateLimiter(
            min_interval_seconds=5.0,
            clock=lambda: now["value"],
            sleeper=sleeps.append,
        )

        with limiter.acquire("example.com"):
            pass
        with limiter.acquire("example.com"):
            pass

        assert sleeps == [5.0]

    def test_different_hosts_are_independent(self) -> None:
        sleeps: list[float] = []
        limiter = HostRateLimiter(
            min_interval_seconds=5.0, clock=lambda: 100.0, sleeper=sleeps.append
        )

        with limiter.acquire("example.com"):
            pass
        with limiter.acquire("other.example"):
            pass

        assert sleeps == []

    def test_same_host_is_serialized_and_other_hosts_are_not(self) -> None:
        limiter = HostRateLimiter(min_interval_seconds=0.0)

        with limiter.acquire("example.com"):
            same = limiter._semaphore_for("example.com")
            other = limiter._semaphore_for("other.example")
            assert same.acquire(blocking=False) is False
            assert other.acquire(blocking=False) is True
            other.release()


class TestSecurityConfiguration:
    def test_client_construction_never_weakens_security(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}
        real_client = httpx.Client

        def capturing_client(**kwargs: object) -> httpx.Client:
            captured.update(kwargs)
            return real_client(**kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr("contentos.fetching.client.httpx.Client", capturing_client)
        client = FetchClient(FetchPolicy(min_host_interval_seconds=0.0), resolver=fake_resolver)
        client.close()

        assert captured["trust_env"] is False
        assert captured["follow_redirects"] is False
        assert captured["verify"] is True

    def test_cookies_are_never_replayed(self) -> None:
        recorded: list[httpx.Request] = []
        handler = simple_site(page_headers={"set-cookie": "tracker=1; Path=/"})
        with make_client(handler, recorded=recorded) as client:
            client.fetch("https://example.com/first")
            client.fetch("https://example.com/second")

        assert all("cookie" not in request.headers for request in recorded)

    def test_user_agent_is_identified_contentos(self) -> None:
        recorded: list[httpx.Request] = []
        with make_client(simple_site(), recorded=recorded) as client:
            client.fetch("https://example.com/page")

        for request in recorded:
            assert request.headers["user-agent"] == DEFAULT_USER_AGENT
            assert "Mozilla" not in request.headers["user-agent"]


class TestSettingsIntegration:
    def make_settings(self, **overrides: object) -> Settings:
        values: dict[str, object] = {
            "environment": Environment.TEST,
            "service_name": "ContentOS Fetch Test",
            "application_version": "1.0.0-test",
            "log_level": LogLevel.INFO,
            "api_docs_enabled": False,
        }
        values.update(overrides)
        return Settings(**values)  # type: ignore[arg-type]

    def test_defaults_and_policy_mapping(self) -> None:
        settings = self.make_settings(
            fetch_connect_timeout_seconds=3,
            fetch_read_timeout_seconds=20,
            fetch_max_body_bytes=2048,
            fetch_max_redirects=2,
            fetch_min_host_interval_seconds=0.5,
            fetch_user_agent="Konsepthane-ContentOS/0.1-test",
        )

        policy = build_fetch_policy(settings)

        assert policy.connect_timeout_seconds == 3.0
        assert policy.read_timeout_seconds == 20.0
        assert policy.max_body_bytes == 2048
        assert policy.max_redirects == 2
        assert policy.min_host_interval_seconds == 0.5
        assert policy.user_agent == "Konsepthane-ContentOS/0.1-test"

    def test_settings_default_user_agent_matches_policy_default(self) -> None:
        assert self.make_settings().fetch_user_agent == DEFAULT_USER_AGENT

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("fetch_max_redirects", 99),
            ("fetch_connect_timeout_seconds", 0),
            ("fetch_max_body_bytes", 1),
            ("fetch_min_host_interval_seconds", 999.0),
        ],
    )
    def test_invalid_fetch_settings_are_rejected(self, field: str, value: object) -> None:
        with pytest.raises(ValidationError):
            self.make_settings(**{field: value})
