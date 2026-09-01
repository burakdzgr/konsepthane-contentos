"""OpenAI adapter tests against an injected mocked client (no network)."""

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel
from pydantic import Field as PydanticField

from contentos.ai.dto import (
    GenerationRequest,
    GenerationUsage,
    ProviderOutputSchema,
)
from contentos.ai.enums import GenerationPurpose, ProviderFailureKind
from contentos.ai.errors import InvalidProviderIdentityError, ProviderFailureError
from contentos.ai.providers.openai_provider import (
    OpenAiStructuredProvider,
    create_openai_provider_from_settings,
)
from contentos.core.config import Settings


class OutlineTestPayload(BaseModel):
    title: str = PydanticField(min_length=1, max_length=200)


OUTPUT_SCHEMA = ProviderOutputSchema(
    name="outline-test",
    version="1",
    json_schema=OutlineTestPayload.model_json_schema(),
)


def make_request(**overrides: Any) -> GenerationRequest:
    values: dict[str, Any] = {
        "purpose": GenerationPurpose.IDEA_CANDIDATES,
        "schema_name": "outline-test",
        "schema_version": "1",
        "template_name": "outline-template",
        "template_version": "1",
        "input_projection": {"topic": "parti"},
        "generation_bounds": {"max_output_tokens": 512},
        "instructions": "Test talimatı.",
    }
    values.update(overrides)
    return GenerationRequest(**values)


def fake_response(
    *,
    status: str = "completed",
    output_text: str = '{"title": "Deterministik"}',
    refusal: bool = False,
    usage: Any = None,
) -> Any:
    content: list[Any] = []
    if refusal:
        content.append(SimpleNamespace(type="refusal", refusal="no"))
    else:
        content.append(SimpleNamespace(type="output_text", text=output_text))
    response = SimpleNamespace(
        status=status,
        output=[SimpleNamespace(type="message", content=content)],
        usage=usage,
    )
    # Mirror the SDK convenience property.
    response.output_text = output_text if not refusal else ""
    return response


@dataclass
class FakeResponsesResource:
    response: Any = None
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


@dataclass
class FakeOpenAiClient:
    responses: FakeResponsesResource


def make_provider(
    *, response: Any = None, error: Exception | None = None
) -> tuple[OpenAiStructuredProvider, FakeResponsesResource]:
    resource = FakeResponsesResource(response=response, error=error)
    provider = OpenAiStructuredProvider(
        api_key="test-key-never-logged",
        model="test-model-id",
        client=FakeOpenAiClient(responses=resource),
    )
    return provider, resource


class TestRequestShape:
    def test_responses_api_called_with_strict_schema_store_false_no_tools(self) -> None:
        provider, resource = make_provider(response=fake_response())
        result = provider.generate(make_request(), OUTPUT_SCHEMA)

        [call] = resource.calls
        assert call["model"] == "test-model-id"
        assert call["instructions"] == "Test talimatı."
        assert call["store"] is False
        assert call["max_output_tokens"] == 512
        assert call["text"]["format"]["type"] == "json_schema"
        assert call["text"]["format"]["strict"] is True
        assert call["text"]["format"]["schema"] == OutlineTestPayload.model_json_schema()
        assert call["text"]["format"]["name"] == "outline-test-v1"
        assert "tools" not in call and "tool_choice" not in call
        # The bounded projection crosses as canonical JSON, never raw dumps.
        assert json.loads(call["input"]) == {"topic": "parti"}
        assert result.payload == {"title": "Deterministik"}

    def test_identity_is_truthful(self) -> None:
        provider, _ = make_provider(response=fake_response())
        assert provider.identity.provider == "openai"
        assert provider.identity.model_name == "test-model-id"
        # No fabricated model version: the API exposes none.
        assert provider.identity.model_version is None

    def test_no_sdk_object_crosses_the_boundary(self) -> None:
        provider, _ = make_provider(response=fake_response())
        result = provider.generate(make_request(), OUTPUT_SCHEMA)
        assert isinstance(result.payload, dict)
        assert result.provider == "openai"
        assert result.finish_reason == "completed"


class TestUsageMapping:
    def test_reported_usage_is_mapped_and_latency_measured(self) -> None:
        usage = SimpleNamespace(input_tokens=120, output_tokens=30, total_tokens=150)
        provider, _ = make_provider(response=fake_response(usage=usage))
        result = provider.generate(make_request(), OUTPUT_SCHEMA)
        assert result.usage is not None
        assert result.usage.input_tokens == 120
        assert result.usage.output_tokens == 30
        assert result.usage.total_tokens == 150
        assert result.usage.latency_ms is not None and result.usage.latency_ms >= 0
        # Cost is never invented.
        assert result.usage.cost_amount is None

    def test_absent_usage_stays_absent(self) -> None:
        provider, _ = make_provider(response=fake_response(usage=None))
        result = provider.generate(make_request(), OUTPUT_SCHEMA)
        assert result.usage is not None
        assert result.usage.input_tokens is None
        assert isinstance(result.usage, GenerationUsage)


class TestFailureMapping:
    def test_timeout_maps_to_timeout(self) -> None:
        provider, _ = make_provider(
            error=openai.APITimeoutError(request=httpx.Request("POST", "https://x.invalid"))
        )
        with pytest.raises(ProviderFailureError) as excinfo:
            provider.generate(make_request(), OUTPUT_SCHEMA)
        assert excinfo.value.kind is ProviderFailureKind.TIMEOUT
        assert excinfo.value.error_class == "openai_timeout"

    def test_rate_limit_and_api_errors_map_to_provider_error(self) -> None:
        request = httpx.Request("POST", "https://x.invalid")
        for error, expected_class in (
            (
                openai.RateLimitError(
                    "rate limited",
                    response=httpx.Response(429, request=request),
                    body=None,
                ),
                "openai_rate_limit",
            ),
            (openai.APIConnectionError(request=request), "openai_connection_error"),
            (
                openai.InternalServerError(
                    "boom", response=httpx.Response(500, request=request), body=None
                ),
                "openai_api_error",
            ),
        ):
            provider, _ = make_provider(error=error)
            with pytest.raises(ProviderFailureError) as excinfo:
                provider.generate(make_request(), OUTPUT_SCHEMA)
            assert excinfo.value.kind is ProviderFailureKind.PROVIDER_ERROR
            assert excinfo.value.error_class == expected_class

    def test_refusal_and_incomplete_and_malformed_outputs(self) -> None:
        for response, expected_class, expected_kind in (
            (
                fake_response(refusal=True),
                "openai_refusal",
                ProviderFailureKind.PROVIDER_ERROR,
            ),
            (
                fake_response(status="incomplete"),
                "openai_incomplete_response",
                ProviderFailureKind.PROVIDER_ERROR,
            ),
            (
                fake_response(status="failed"),
                "openai_response_not_completed",
                ProviderFailureKind.PROVIDER_ERROR,
            ),
            (
                fake_response(status="cancelled"),
                "openai_response_not_completed",
                ProviderFailureKind.CANCELLED,
            ),
            (
                fake_response(output_text="not json at all"),
                "openai_malformed_structured_output",
                ProviderFailureKind.PROVIDER_ERROR,
            ),
            (
                fake_response(output_text='["array", "not", "object"]'),
                "openai_malformed_structured_output",
                ProviderFailureKind.PROVIDER_ERROR,
            ),
            (
                fake_response(output_text="   "),
                "openai_malformed_structured_output",
                ProviderFailureKind.PROVIDER_ERROR,
            ),
        ):
            provider, _ = make_provider(response=response)
            with pytest.raises(ProviderFailureError) as excinfo:
                provider.generate(make_request(), OUTPUT_SCHEMA)
            assert excinfo.value.kind is expected_kind
            assert excinfo.value.error_class == expected_class

    def test_error_classes_never_carry_the_api_key(self) -> None:
        request = httpx.Request("POST", "https://x.invalid")
        provider, _ = make_provider(error=openai.APIConnectionError(request=request))
        with pytest.raises(ProviderFailureError) as excinfo:
            provider.generate(make_request(), OUTPUT_SCHEMA)
        assert "test-key-never-logged" not in str(excinfo.value)
        assert "test-key-never-logged" not in excinfo.value.error_class


class TestConfiguration:
    def test_production_client_construction_disables_sdk_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One ContentOS retry_number must mean ONE provider invocation:
        the production OpenAI client is constructed with max_retries=0 so
        the SDK can never silently retry underneath one attempt row."""
        captured: dict[str, Any] = {}
        resource = FakeResponsesResource(response=fake_response())

        class CapturingOpenAI:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)
                self.responses = resource

        monkeypatch.setattr(openai, "OpenAI", CapturingOpenAI)
        provider = OpenAiStructuredProvider(
            api_key="test-key-never-logged", model="test-model-id", timeout_seconds=42.0
        )
        assert captured["max_retries"] == 0
        assert captured["timeout"] == 42.0
        assert captured["api_key"] == "test-key-never-logged"
        # The captured construction path is the client actually used.
        result = provider.generate(make_request(), OUTPUT_SCHEMA)
        assert result.payload == {"title": "Deterministik"}
        assert len(resource.calls) == 1

    def test_blank_api_key_rejected(self) -> None:
        with pytest.raises(InvalidProviderIdentityError):
            OpenAiStructuredProvider(api_key="  ", model="m")

    def test_settings_factory_requires_key_and_model(self) -> None:
        settings = Settings()
        assert settings.openai_api_key is None
        assert settings.openai_model is None
        with pytest.raises(InvalidProviderIdentityError):
            create_openai_provider_from_settings(settings)

    def test_settings_factory_never_leaks_the_key_in_errors(self) -> None:
        settings = Settings(openai_api_key="sk-secret-value")  # type: ignore[arg-type]
        with pytest.raises(InvalidProviderIdentityError) as excinfo:
            create_openai_provider_from_settings(settings)
        assert "sk-secret-value" not in str(excinfo.value)
        assert "sk-secret-value" not in repr(settings)
