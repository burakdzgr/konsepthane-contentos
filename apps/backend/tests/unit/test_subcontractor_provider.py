"""Subcontractor gateway adapter (ADR 0011): submit + poll + JSON extraction."""

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from contentos.ai.dto import GenerationRequest, ProviderOutputSchema
from contentos.ai.enums import GenerationPurpose, ProviderFailureKind
from contentos.ai.errors import InvalidProviderIdentityError, ProviderFailureError
from contentos.ai.providers.subcontractor_provider import (
    ERROR_CLASS_AUTH,
    ERROR_CLASS_MALFORMED,
    ERROR_CLASS_NO_IMAGE,
    ERROR_CLASS_RATE_LIMIT,
    ERROR_CLASS_TIMEOUT,
    SubcontractorGatewayClient,
    SubcontractorImageProvider,
    SubcontractorStructuredProvider,
    build_structured_prompt,
    create_subcontractor_provider_from_settings,
    extract_json_object,
)
from contentos.core.config import Settings

SCHEMA = ProviderOutputSchema(
    name="idea-candidates",
    version="1",
    json_schema={
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
        "additionalProperties": False,
    },
)


def request() -> GenerationRequest:
    return GenerationRequest(
        purpose=GenerationPurpose.IDEA_CANDIDATES,
        schema_name="idea-candidates",
        schema_version="1",
        template_name="idea-template",
        template_version="1",
        input_projection={"topic": "Evde doğum günü"},
        instructions="Konsepthane için fikir üret.",
    )


class FakeGateway:
    """A scripted `/v1/jobs` gateway behind httpx.MockTransport."""

    def __init__(self, polls: list[dict[str, Any]], *, submit_status: int = 200) -> None:
        self.polls = list(polls)
        self.submit_status = submit_status
        self.submitted: list[dict[str, Any]] = []
        self.image_bytes = b"\x89PNG-fake"

    def handler(self, http_request: httpx.Request) -> httpx.Response:
        if http_request.method == "POST" and http_request.url.path == "/v1/jobs":
            self.submitted.append(json.loads(http_request.content))
            if self.submit_status != 200:
                return httpx.Response(self.submit_status, json={"error": "nope"})
            return httpx.Response(200, json={"jobId": "job-1", "status": "queued"})
        if http_request.method == "GET" and http_request.url.path == "/v1/jobs/job-1":
            record = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
            return httpx.Response(200, json=record)
        if http_request.method == "GET" and http_request.url.path.startswith("/images/"):
            return httpx.Response(200, content=self.image_bytes)
        return httpx.Response(404, json={"error": "unknown"})

    def client(self) -> SubcontractorGatewayClient:
        http = httpx.Client(
            base_url="http://gateway.test",
            transport=httpx.MockTransport(self.handler),
            headers={"Authorization": "Bearer ksk_test"},
        )
        return SubcontractorGatewayClient(
            base_url="http://gateway.test",
            api_key="ksk_test",
            timeout_seconds=30.0,
            poll_interval_seconds=1.0,
            http_client=http,
            sleep=lambda _seconds: None,
        )


def test_prompt_embeds_schema_instructions_and_input() -> None:
    prompt = build_structured_prompt(request(), SCHEMA)
    assert prompt.startswith("Konsepthane için fikir üret.")
    assert "JSON ŞEMASI (idea-candidates v1)" in prompt
    assert '"additionalProperties": false' in prompt
    assert '"topic":"Evde doğum günü"' in prompt


@pytest.mark.parametrize(
    "text",
    [
        '{"title": "Balon"}',
        'Tabii, işte sonuç:\n```json\n{"title": "Balon"}\n```\nBaşka bir şey?',
        'Sonuç: {"title": "Balon"} — umarım işe yarar.',
    ],
)
def test_extracts_the_single_json_object_from_free_text(text: str) -> None:
    assert extract_json_object(text) == {"title": "Balon"}


@pytest.mark.parametrize("text", ["", "sadece metin", "[1, 2]", "{broken"])
def test_non_object_replies_are_malformed(text: str) -> None:
    with pytest.raises(ProviderFailureError) as info:
        extract_json_object(text)
    assert info.value.error_class == ERROR_CLASS_MALFORMED


def test_submit_poll_and_parse_success() -> None:
    gateway = FakeGateway(
        [
            {"status": "running", "phase": "ChatGPT yanıtlıyor"},
            {"status": "succeeded", "text": '```json\n{"title": "Balon"}\n```', "images": []},
        ]
    )
    provider = SubcontractorStructuredProvider(client=gateway.client(), model="chatgpt")
    result = provider.generate(request(), SCHEMA)
    assert result.payload == {"title": "Balon"}
    assert result.provider == "subcontractor"
    assert result.model_name == "chatgpt"
    assert result.model_version is None
    assert result.finish_reason == "succeeded"
    assert result.usage is not None and result.usage.latency_ms is not None
    [submitted] = gateway.submitted
    assert submitted["model"] == "chatgpt"
    assert submitted["type"] == "text"
    assert submitted["options"]["timeoutMs"] == 30000
    assert submitted["meta"]["purpose"] == "idea_candidates"
    assert "JSON ŞEMASI" in submitted["prompt"]


def test_failed_job_maps_to_bounded_error_classes() -> None:
    for code, expected_kind, expected_class in [
        ("RATE_LIMITED", ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_RATE_LIMIT),
        ("TIMEOUT", ProviderFailureKind.TIMEOUT, ERROR_CLASS_TIMEOUT),
        ("NOT_LOGGED_IN", ProviderFailureKind.PROVIDER_ERROR, "subcontractor_job_not_logged_in"),
    ]:
        gateway = FakeGateway(
            [{"status": "failed", "error": {"code": code, "message": "secret detail"}}]
        )
        provider = SubcontractorStructuredProvider(client=gateway.client(), model="chatgpt")
        with pytest.raises(ProviderFailureError) as info:
            provider.generate(request(), SCHEMA)
        assert info.value.kind is expected_kind
        assert info.value.error_class == expected_class
        assert "secret" not in str(info.value)


def test_gateway_refusals_map_to_auth_and_rate_limit() -> None:
    for status, expected in [(401, ERROR_CLASS_AUTH), (429, ERROR_CLASS_RATE_LIMIT)]:
        gateway = FakeGateway([], submit_status=status)
        provider = SubcontractorStructuredProvider(client=gateway.client(), model="claude")
        with pytest.raises(ProviderFailureError) as info:
            provider.generate(request(), SCHEMA)
        assert info.value.error_class == expected


def test_polling_gives_up_at_the_deadline() -> None:
    gateway = FakeGateway([{"status": "running"}])
    http = httpx.Client(
        base_url="http://gateway.test", transport=httpx.MockTransport(gateway.handler)
    )
    client = SubcontractorGatewayClient(
        base_url="http://gateway.test",
        api_key="ksk_test",
        timeout_seconds=10.0,
        poll_interval_seconds=1.0,
        http_client=http,
        sleep=lambda _seconds: None,
    )
    # Deadline is measured with the monotonic clock; drive it past the limit.
    import contentos.ai.providers.subcontractor_provider as module

    clock = iter([0.0, 0.0, 100.0, 200.0, 300.0])
    original = module.time.monotonic
    module.time.monotonic = lambda: next(clock)  # type: ignore[assignment]
    try:
        with pytest.raises(ProviderFailureError) as info:
            client.run_job(model="chatgpt", job_type="text", prompt="x", meta={})
    finally:
        module.time.monotonic = original  # type: ignore[assignment]
    assert info.value.kind is ProviderFailureKind.TIMEOUT


def test_image_job_downloads_the_first_image() -> None:
    gateway = FakeGateway(
        [
            {
                "status": "succeeded",
                "text": "",
                "images": [{"url": "/images/2026/09/04/a.png", "contentType": "image/png"}],
            }
        ]
    )
    provider = SubcontractorImageProvider(client=gateway.client(), model="chatgpt")
    result = provider.generate(request(), SCHEMA)
    assert result.payload["media_type"] == "image/png"
    assert result.payload["image_base64"]
    assert gateway.submitted[0]["type"] == "image"


def test_image_job_without_image_is_no_image() -> None:
    gateway = FakeGateway([{"status": "succeeded", "text": "sadece metin", "images": []}])
    provider = SubcontractorImageProvider(client=gateway.client(), model="chatgpt")
    with pytest.raises(ProviderFailureError) as info:
        provider.generate(request(), SCHEMA)
    assert info.value.error_class == ERROR_CLASS_NO_IMAGE


def test_settings_factory_requires_base_url_and_key() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@localhost:5432/db",
        redis_broker_url="redis://localhost:6379/0",
        ai_provider="subcontractor",
    )
    assert settings.text_provider_configured is False
    with pytest.raises(InvalidProviderIdentityError):
        create_subcontractor_provider_from_settings(settings)
    configured = settings.model_copy(
        update={
            "subcontractor_base_url": "http://host.docker.internal:8090",
            "subcontractor_api_key": SecretStr("ksk_live_x"),
        }
    )
    assert configured.text_provider_configured is True
    assert configured.image_provider_configured is True
    provider = create_subcontractor_provider_from_settings(configured)
    assert provider.identity.provider == "subcontractor"
    assert provider.identity.model_name == "chatgpt"
