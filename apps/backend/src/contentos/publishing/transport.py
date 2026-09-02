"""The publishing transport boundary (Phase 7 P3).

The ONLY path toward Konsepthane production is a versioned +
authenticated + idempotent Publishing API behind this narrow protocol.
There is NO default endpoint: the HTTP adapter refuses to construct
without explicit `publishing_api_url` + `publishing_api_key` settings
(a typed error, never a silent no-op or fabricated success), and the
deterministic fake is what every test and verification uses until the
real contract, auth method, and production owner are resolved.

Expected dispatch failures are RESULTS (the bounded non-editorial
attempt vocabulary), never exceptions: the caller records every
outcome as a durable publication attempt. Media bytes cross the
boundary only through the bounded reader callable — the transport
never sees the store layout.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from contentos.publishing.errors import PublishingError

MediaReader = Callable[[str], bytes]
"""Reads one manifest asset's bytes by its content sha256."""

AttemptStatus = Literal["succeeded", "transport_error", "rejected_by_api", "timeout"]


class TransportConfigurationError(PublishingError):
    """The transport cannot be constructed: required configuration is
    missing. Raised BEFORE any dispatch — never after."""


@dataclass(frozen=True, slots=True)
class TransportOutcome:
    """One dispatch outcome, exactly as it happened."""

    status: AttemptStatus
    remote_publication_ref: str | None = None
    error_class: str | None = None

    def __post_init__(self) -> None:
        if (self.status == "succeeded") != (self.remote_publication_ref is not None):
            raise PublishingError(
                "a remote publication reference exists exactly when the dispatch succeeded"
            )


@runtime_checkable
class PublishingTransport(Protocol):
    @property
    def name(self) -> str: ...

    def publish(
        self,
        payload: dict[str, Any],
        media_manifest: dict[str, Any],
        media_reader: MediaReader,
        idempotency_key: str,
    ) -> TransportOutcome: ...


@dataclass
class FakePublishingTransport:
    """Deterministic transport double for tests and real-infra
    verification. Configurable outcome; records every dispatch."""

    outcome: TransportOutcome = field(
        default_factory=lambda: TransportOutcome(
            status="succeeded", remote_publication_ref="fake-publication-1"
        )
    )
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "fake-publishing-transport"

    def publish(
        self,
        payload: dict[str, Any],
        media_manifest: dict[str, Any],
        media_reader: MediaReader,
        idempotency_key: str,
    ) -> TransportOutcome:
        self.calls.append(
            {
                "idempotency_key": idempotency_key,
                "payload_keys": sorted(payload),
                "manifest_needs": sorted(media_manifest.get("needs", {})),
            }
        )
        return self.outcome


class HttpPublishingTransport:
    """Configuration-gated skeleton for the REAL Publishing API adapter.

    The endpoint shapes below are a PLACEHOLDER pending the open
    contract inputs; nothing can reach them without explicit settings,
    and the live integration stays blocked until the operator supplies
    the contract, the auth method, and the production owner sign-off.
    """

    def __init__(self, *, api_url: str, api_key: str, timeout_seconds: float = 30.0) -> None:
        if not api_url.strip() or not api_key.strip():
            raise TransportConfigurationError(
                "CONTENTOS_PUBLISHING_API_URL and CONTENTOS_PUBLISHING_API_KEY "
                "must be configured to use the HTTP publishing transport"
            )
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return "konsepthane-publishing-api"

    def publish(
        self,
        payload: dict[str, Any],
        media_manifest: dict[str, Any],
        media_reader: MediaReader,
        idempotency_key: str,
    ) -> TransportOutcome:
        import httpx

        try:
            response = httpx.post(
                f"{self._api_url}/v1/publications",
                json={"package": payload, "media_manifest": media_manifest},
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Idempotency-Key": idempotency_key,
                },
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException:
            return TransportOutcome(status="timeout", error_class="publishing_api_timeout")
        except httpx.HTTPError:
            return TransportOutcome(
                status="transport_error", error_class="publishing_api_connection_error"
            )
        if response.status_code in (200, 201):
            try:
                body = response.json()
            except ValueError:
                return TransportOutcome(
                    status="transport_error", error_class="publishing_api_malformed_response"
                )
            ref = body.get("publication_ref") if isinstance(body, dict) else None
            if not isinstance(ref, str) or not ref.strip():
                return TransportOutcome(
                    status="transport_error", error_class="publishing_api_missing_ref"
                )
            return TransportOutcome(status="succeeded", remote_publication_ref=ref)
        if 400 <= response.status_code < 500:
            # Sanitized: the class carries the status family, never the body.
            return TransportOutcome(
                status="rejected_by_api",
                error_class=f"publishing_api_rejected_{response.status_code}",
            )
        return TransportOutcome(
            status="transport_error",
            error_class=f"publishing_api_status_{response.status_code}",
        )


def create_http_publishing_transport_from_settings(settings: Any) -> HttpPublishingTransport:
    api_url = settings.publishing_api_url
    api_key = settings.publishing_api_key
    if api_url is None or api_key is None:
        raise TransportConfigurationError(
            "CONTENTOS_PUBLISHING_API_URL and CONTENTOS_PUBLISHING_API_KEY "
            "must be configured to use the HTTP publishing transport"
        )
    return HttpPublishingTransport(
        api_url=api_url,
        api_key=api_key.get_secret_value(),
        timeout_seconds=settings.publishing_timeout_seconds,
    )
