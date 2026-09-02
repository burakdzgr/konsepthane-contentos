"""HttpPublishingTransport against a contract-faithful API double.

The double implements `docs/PUBLISHING_API_CONTRACT.md` v1 semantics —
content-addressed media PUT with server-side SHA recomputation and
duplicate convergence, idempotent publication POST with replay and
conflict — so these tests prove the CLIENT side of the wire contract
without any network. The live endpoint run still awaits the operator's
staging URL + key.
"""

import hashlib
import json
from typing import Any

import httpx
import pytest

from contentos.publishing.transport import (
    FakePublishingTransport,
    HttpPublishingTransport,
    TransportConfigurationError,
    TransportOutcome,
    create_http_publishing_transport_from_settings,
)

API_URL = "https://konsepthane.test/api/internal/contentos"
API_KEY = "service-token-under-test"

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"contract-double-image"
PNG_SHA = hashlib.sha256(PNG_BYTES).hexdigest()


def sample_payload() -> dict[str, Any]:
    return {
        "schema_version": "publication-package/1",
        "work_item_id": "a1111111-2222-4333-8444-555555555555",
        "locale": "tr-TR",
        "market": "TR",
        "title_proposal": "Evde Doğum Günü Partisi Rehberi",
        "body_schema_version": "writer-draft-body/1",
        "body": {"sections": []},
    }


def sample_manifest() -> dict[str, Any]:
    return {
        "needs": {
            "0": {
                "media_asset_id": "c2000000-0000-4000-8000-00000000000c",
                "content_sha256": PNG_SHA,
                "media_type": "image/png",
                "byte_size": len(PNG_BYTES),
                "alt_text": "Balonlu masa",
                "license_note": "Konsepthane arşivi",
                "source_attribution": None,
                "origin": "human_upload",
            }
        },
        "waived_unmet_indexes": [],
    }


class ContractDouble:
    """In-process Publishing API v1 double (contract semantics only)."""

    def __init__(self) -> None:
        self.media: dict[str, str] = {}  # sha -> media_ref
        self.publications: dict[str, tuple[str, dict[str, Any]]] = {}
        self.requests: list[dict[str, Any]] = []
        self.next_status_override: int | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(
            {
                "method": request.method,
                "path": request.url.path,
                "headers": dict(request.headers),
            }
        )
        if request.headers.get("authorization") != f"Bearer {API_KEY}":
            return httpx.Response(401, json={"error": {"code": "authentication_failed"}})
        if self.next_status_override is not None:
            status = self.next_status_override
            self.next_status_override = None
            return httpx.Response(status, json={"error": {"code": "forced"}})
        if request.method == "PUT" and request.url.path.startswith(
            "/api/internal/contentos/v1/media/"
        ):
            return self._put_media(request)
        if (
            request.method == "POST"
            and request.url.path == "/api/internal/contentos/v1/publications"
        ):
            return self._post_publication(request)
        return httpx.Response(400, json={"error": {"code": "malformed_request"}})

    def _put_media(self, request: httpx.Request) -> httpx.Response:
        claimed = request.url.path.rsplit("/", 1)[-1]
        actual = hashlib.sha256(request.content).hexdigest()
        if claimed != actual or request.headers.get("x-content-sha256") != claimed:
            return httpx.Response(422, json={"error": {"code": "media_sha_mismatch"}})
        if request.headers.get("idempotency-key") != f"media:{claimed}":
            return httpx.Response(400, json={"error": {"code": "malformed_request"}})
        existed = claimed in self.media
        media_ref = self.media.setdefault(claimed, f"media-{claimed[:12]}")
        return httpx.Response(
            200 if existed else 201,
            json={
                "schema_version": "media-upload-result/1",
                "media_ref": media_ref,
                "content_sha256": claimed,
                "status": "stored",
            },
        )

    def _post_publication(self, request: httpx.Request) -> httpx.Response:
        key = request.headers.get("idempotency-key", "")
        body = json.loads(request.content)
        for entry in (body.get("media_manifest", {}).get("needs") or {}).values():
            if entry["content_sha256"] not in self.media:
                return httpx.Response(422, json={"error": {"code": "media_not_uploaded"}})
        payload_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        if key in self.publications:
            stored_hash, result = self.publications[key]
            if stored_hash != payload_hash:
                return httpx.Response(409, json={"error": {"code": "idempotency_conflict"}})
            return httpx.Response(200, json=result)  # idempotent replay
        result = {
            "schema_version": "publication-result/1",
            "publication_ref": f"article:{len(self.publications) + 1}",
            "content_id": "11111111-2222-4333-8444-555555555555",
            "version": 1,
            "status": "published",
            "canonical_url": "https://konsepthane.com/x",
            "published_at": "2026-09-02T20:00:00Z",
        }
        self.publications[key] = (payload_hash, result)
        return httpx.Response(201, json=result)


@pytest.fixture()
def double() -> ContractDouble:
    return ContractDouble()


def transport_for(double: ContractDouble) -> HttpPublishingTransport:
    client = httpx.Client(transport=httpx.MockTransport(double.handler))
    return HttpPublishingTransport(api_url=API_URL, api_key=API_KEY, client=client)


def reader(sha: str) -> bytes:
    assert sha == PNG_SHA
    return PNG_BYTES


class TestContractHappyPath:
    def test_media_uploads_then_publishes_with_all_contract_headers(
        self, double: ContractDouble
    ) -> None:
        outcome = transport_for(double).publish(
            sample_payload(),
            sample_manifest(),
            reader,
            "contentos-pub-abc",
            request_id="req-42",
        )
        assert outcome == TransportOutcome(status="succeeded", remote_publication_ref="article:1")
        put, post = double.requests
        assert put["method"] == "PUT"
        assert put["path"].endswith(f"/v1/media/{PNG_SHA}")
        assert put["headers"]["content-type"] == "image/png"
        assert put["headers"]["x-content-sha256"] == PNG_SHA
        assert put["headers"]["idempotency-key"] == f"media:{PNG_SHA}"
        assert post["method"] == "POST"
        assert post["headers"]["idempotency-key"] == "contentos-pub-abc"
        assert post["headers"]["x-request-id"] == "req-42"
        assert double.media[PNG_SHA]  # stored content-addressed

    def test_idempotent_replay_returns_the_same_reference(self, double: ContractDouble) -> None:
        transport = transport_for(double)
        first = transport.publish(sample_payload(), sample_manifest(), reader, "key-1")
        again = transport.publish(sample_payload(), sample_manifest(), reader, "key-1")
        assert first.remote_publication_ref == again.remote_publication_ref
        assert len(double.publications) == 1  # no second content
        # The media re-PUT converged on the stored asset (200, same ref).
        assert len([r for r in double.requests if r["method"] == "PUT"]) == 2

    def test_waived_empty_manifest_skips_media_entirely(self, double: ContractDouble) -> None:
        outcome = transport_for(double).publish(
            sample_payload(),
            {"needs": {}, "waived_unmet_indexes": [0]},
            reader,
            "key-2",
        )
        assert outcome.status == "succeeded"
        assert all(r["method"] == "POST" for r in double.requests)


class TestContractFailures:
    def test_tampered_bytes_are_rejected_by_the_receiver(self, double: ContractDouble) -> None:
        outcome = transport_for(double).publish(
            sample_payload(),
            sample_manifest(),
            lambda sha: b"tampered-bytes",  # SHA no longer matches
            "key-3",
        )
        assert outcome.status == "rejected_by_api"
        assert outcome.error_class == "publishing_media_rejected_422"
        assert double.publications == {}  # publish never attempted

    def test_conflicting_payload_under_the_same_key_is_a_rejection(
        self, double: ContractDouble
    ) -> None:
        transport = transport_for(double)
        assert (
            transport.publish(sample_payload(), sample_manifest(), reader, "key-4").status
            == "succeeded"
        )
        changed = sample_payload()
        changed["title_proposal"] = "Farklı başlık"
        outcome = transport.publish(changed, sample_manifest(), reader, "key-4")
        assert outcome.status == "rejected_by_api"
        assert outcome.error_class == "publishing_api_rejected_409"

    def test_rate_limiting_is_transient_not_a_rejection(self, double: ContractDouble) -> None:
        double.next_status_override = 429
        outcome = transport_for(double).publish(
            sample_payload(), sample_manifest(), reader, "key-5"
        )
        assert outcome.status == "transport_error"
        assert outcome.error_class == "publishing_media_rate_limited"

    def test_timeout_and_missing_ref_stay_truthful(self, double: ContractDouble) -> None:
        def timeout_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("slow", request=request)

        client = httpx.Client(transport=httpx.MockTransport(timeout_handler))
        transport = HttpPublishingTransport(api_url=API_URL, api_key=API_KEY, client=client)
        outcome = transport.publish(sample_payload(), {"needs": {}}, reader, "key-6")
        assert outcome == TransportOutcome(status="timeout", error_class="publishing_api_timeout")

        def missing_ref_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json={"status": "published"})

        client = httpx.Client(transport=httpx.MockTransport(missing_ref_handler))
        transport = HttpPublishingTransport(api_url=API_URL, api_key=API_KEY, client=client)
        outcome = transport.publish(sample_payload(), {"needs": {}}, reader, "key-7")
        assert outcome.status == "transport_error"
        assert outcome.error_class == "publishing_api_missing_ref"

    def test_unreadable_store_content_never_reaches_the_wire(self, double: ContractDouble) -> None:
        def broken_reader(sha: str) -> bytes:
            raise RuntimeError("store unavailable")

        outcome = transport_for(double).publish(
            sample_payload(), sample_manifest(), broken_reader, "key-8"
        )
        assert outcome.status == "transport_error"
        assert outcome.error_class == "publishing_media_read_failed"
        assert double.requests == []  # nothing was sent


class TestConfigurationGating:
    def test_settings_gating_is_unchanged(self) -> None:
        from contentos.core.config import Environment, LogLevel, Settings

        bare = Settings(
            environment=Environment.TEST,
            service_name="ContentOS Transport Test",
            application_version="1.0.0-test",
            log_level=LogLevel.INFO,
            api_docs_enabled=False,
        )
        with pytest.raises(TransportConfigurationError):
            create_http_publishing_transport_from_settings(bare)
        configured = Settings(
            environment=Environment.TEST,
            service_name="ContentOS Transport Test",
            application_version="1.0.0-test",
            log_level=LogLevel.INFO,
            api_docs_enabled=False,
            publishing_api_url=API_URL,
            publishing_api_key="a-service-token",
        )
        transport = create_http_publishing_transport_from_settings(configured)
        assert transport.name == "konsepthane-publishing-api"

    def test_fake_records_the_request_id(self) -> None:
        fake = FakePublishingTransport()
        fake.publish(sample_payload(), {"needs": {}}, reader, "key-9", request_id="rid")
        assert fake.calls[0]["request_id"] == "rid"
