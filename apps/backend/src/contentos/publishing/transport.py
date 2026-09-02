"""The publishing transport boundary (Phase 7 P3; live contract in P-LIVE).

The ONLY path toward Konsepthane production is the versioned +
authenticated + idempotent Publishing API defined in
`docs/PUBLISHING_API_CONTRACT.md` (operator-accepted v1). The HTTP
adapter implements that contract exactly:

1. every manifest asset is uploaded content-addressed via
   `PUT /v1/media/{sha256}` (idempotent; the receiver recomputes the
   SHA and refuses mismatches);
2. the immutable approved package is published via
   `POST /v1/publications` with the ContentOS idempotency key and the
   request correlation id;
3. `publication_ref` is the one required result field; 200 and 201 are
   both success (201 first publish, 200 idempotent replay).

There is NO default endpoint: the adapter refuses to construct without
explicit `publishing_api_url` + `publishing_api_key` settings (a typed
error, never a silent no-op or fabricated success), and the
deterministic fake is what the unit suite and the full-loop CI lane
use. Expected dispatch failures are RESULTS (the bounded non-editorial
attempt vocabulary), never exceptions: the caller records every outcome
as a durable publication attempt. Per the contract note, `429` is
transient rate limiting — recorded as `transport_error` so bounded
retries apply — while validation/rejection 4xx map to
`rejected_by_api`. Media bytes cross the boundary only through the
bounded reader callable — the transport never sees the store layout.
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
        *,
        request_id: str | None = None,
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
        *,
        request_id: str | None = None,
    ) -> TransportOutcome:
        self.calls.append(
            {
                "idempotency_key": idempotency_key,
                "request_id": request_id,
                "payload_keys": sorted(payload),
                "manifest_needs": sorted(media_manifest.get("needs", {})),
            }
        )
        return self.outcome


class HttpPublishingTransport:
    """The Publishing API v1 client (`docs/PUBLISHING_API_CONTRACT.md`)."""

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        timeout_seconds: float = 30.0,
        client: Any | None = None,
    ) -> None:
        if not api_url.strip() or not api_key.strip():
            raise TransportConfigurationError(
                "CONTENTOS_PUBLISHING_API_URL and CONTENTOS_PUBLISHING_API_KEY "
                "must be configured to use the HTTP publishing transport"
            )
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        # Injectable for tests (httpx.MockTransport); production builds a
        # real client per adapter instance, closed with the process.
        self._client = client

    @property
    def name(self) -> str:
        return "konsepthane-publishing-api"

    def publish(
        self,
        payload: dict[str, Any],
        media_manifest: dict[str, Any],
        media_reader: MediaReader,
        idempotency_key: str,
        *,
        request_id: str | None = None,
    ) -> TransportOutcome:
        import httpx

        client = (
            self._client
            if self._client is not None
            else httpx.Client(timeout=self._timeout_seconds)
        )
        owns_client = self._client is None
        try:
            # Contract media rule: every manifest SHA is uploaded BEFORE the
            # publication references it. PUT is idempotent on the receiver.
            for entry in (media_manifest.get("needs") or {}).values():
                failure = self._upload_media(client, entry, media_reader)
                if failure is not None:
                    return failure
            return self._post_publication(
                client, payload, media_manifest, idempotency_key, request_id
            )
        finally:
            if owns_client:
                client.close()

    # --- contract steps -------------------------------------------------------

    def _upload_media(
        self, client: Any, entry: dict[str, Any], media_reader: MediaReader
    ) -> TransportOutcome | None:
        import httpx

        sha = str(entry.get("content_sha256", ""))
        media_type = str(entry.get("media_type", "application/octet-stream"))
        try:
            data = media_reader(sha)
        except Exception:  # noqa: BLE001 - the reader's failure detail stays local
            return TransportOutcome(
                status="transport_error", error_class="publishing_media_read_failed"
            )
        try:
            response = client.put(
                f"{self._api_url}/v1/media/{sha}",
                content=data,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": media_type,
                    "X-Content-SHA256": sha,
                    "Idempotency-Key": f"media:{sha}",
                },
            )
        except httpx.TimeoutException:
            return TransportOutcome(status="timeout", error_class="publishing_api_timeout")
        except httpx.HTTPError:
            return TransportOutcome(
                status="transport_error", error_class="publishing_api_connection_error"
            )
        if response.status_code in (200, 201):
            body = _safe_json(response)
            media_ref = body.get("media_ref") if isinstance(body, dict) else None
            if not isinstance(media_ref, str) or not media_ref.strip():
                return TransportOutcome(
                    status="transport_error",
                    error_class="publishing_media_missing_ref",
                )
            return None  # uploaded (or already stored) — continue
        return self._failure_for_status(response.status_code, prefix="publishing_media")

    def _post_publication(
        self,
        client: Any,
        payload: dict[str, Any],
        media_manifest: dict[str, Any],
        idempotency_key: str,
        request_id: str | None,
    ) -> TransportOutcome:
        import httpx

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Idempotency-Key": idempotency_key,
            "Content-Type": "application/json",
        }
        if request_id:
            headers["X-Request-Id"] = request_id
        try:
            response = client.post(
                f"{self._api_url}/v1/publications",
                json={"package": payload, "media_manifest": media_manifest},
                headers=headers,
            )
        except httpx.TimeoutException:
            return TransportOutcome(status="timeout", error_class="publishing_api_timeout")
        except httpx.HTTPError:
            return TransportOutcome(
                status="transport_error", error_class="publishing_api_connection_error"
            )
        # 201 = first publish; 200 = idempotent replay. Both are success.
        if response.status_code in (200, 201):
            body = _safe_json(response)
            ref = body.get("publication_ref") if isinstance(body, dict) else None
            if not isinstance(ref, str) or not ref.strip():
                return TransportOutcome(
                    status="transport_error", error_class="publishing_api_missing_ref"
                )
            return TransportOutcome(status="succeeded", remote_publication_ref=ref)
        return self._failure_for_status(response.status_code, prefix="publishing_api")

    @staticmethod
    def _failure_for_status(status_code: int, *, prefix: str) -> TransportOutcome:
        if status_code == 429:
            # Contract note: rate limiting is transient, never a package
            # rejection — bounded retries apply.
            return TransportOutcome(status="transport_error", error_class=f"{prefix}_rate_limited")
        if 400 <= status_code < 500:
            # Sanitized: the class carries the status family, never the body.
            return TransportOutcome(
                status="rejected_by_api", error_class=f"{prefix}_rejected_{status_code}"
            )
        return TransportOutcome(
            status="transport_error", error_class=f"{prefix}_status_{status_code}"
        )


def _safe_json(response: Any) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


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
