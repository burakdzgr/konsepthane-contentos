"""The OpenAI adapter behind StructuredGenerationProvider (ADR 0009).

Uses the official OpenAI Python SDK's Responses API with strict Structured
Outputs (`text.format` = json_schema, strict=True) — never the Assistants
API, never legacy JSON mode. Provider-side response storage is disabled
(store=False): PostgreSQL remains authoritative for attempt state. No
tools of any kind are exposed to the model — research is gathered by
ContentOS and arrives only as the bounded deterministic projection.

SDK objects and exceptions never leave this module: results cross the
boundary as provider-neutral DTOs, and SDK failures are translated into
typed ProviderFailureError values with stable sanitized error classes
(no messages, bodies, URLs, headers, or keys are ever persisted).

The SDK's automatic retries are disabled (max_retries=0) so ONE ContentOS
retry_number always means ONE provider invocation; retry policy belongs to
future orchestration.
"""

import json
import time
from typing import Any

import openai

from contentos.ai.dto import (
    GenerationRequest,
    GenerationUsage,
    ProviderIdentity,
    ProviderOutputSchema,
    ProviderResult,
)
from contentos.ai.enums import ProviderFailureKind
from contentos.ai.errors import InvalidProviderIdentityError, ProviderFailureError
from contentos.ai.hashing import canonical_json
from contentos.core.config import Settings

OPENAI_PROVIDER_NAME = "openai"

# Stable sanitized error classes (never raw provider text).
ERROR_CLASS_TIMEOUT = "openai_timeout"
ERROR_CLASS_RATE_LIMIT = "openai_rate_limit"
ERROR_CLASS_CONNECTION = "openai_connection_error"
ERROR_CLASS_API_STATUS = "openai_api_error"
ERROR_CLASS_SDK = "openai_sdk_error"
ERROR_CLASS_REFUSAL = "openai_refusal"
ERROR_CLASS_INCOMPLETE = "openai_incomplete_response"
ERROR_CLASS_NOT_COMPLETED = "openai_response_not_completed"
ERROR_CLASS_MALFORMED = "openai_malformed_structured_output"


class OpenAiStructuredProvider:
    """One configured OpenAI model behind the provider-neutral protocol.

    `model` is the exact configured model identifier; `model_version` is
    None — the Responses API exposes no genuinely distinct model-version
    identity, and nothing is invented or parsed out of the model name.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        client: Any | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise InvalidProviderIdentityError("an OpenAI API key is required")
        self._identity = ProviderIdentity(
            provider=OPENAI_PROVIDER_NAME, model_name=model, model_version=None
        )
        # Injectable for tests; production constructs the official client
        # explicitly (no import-time or global client, no SDK retries).
        self._client = (
            client
            if client is not None
            else openai.OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=0)
        )

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

    def generate(
        self, request: GenerationRequest, output_schema: ProviderOutputSchema
    ) -> ProviderResult:
        started = time.monotonic()
        try:
            response = self._client.responses.create(
                model=self._identity.model_name,
                instructions=request.instructions or None,
                input=canonical_json(request.input_projection),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": _schema_format_name(output_schema),
                        "schema": output_schema.json_schema,
                        "strict": output_schema.strict,
                    }
                },
                store=False,
                max_output_tokens=request.generation_bounds.get("max_output_tokens"),
            )
        except openai.APITimeoutError:
            raise ProviderFailureError(ProviderFailureKind.TIMEOUT, ERROR_CLASS_TIMEOUT) from None
        except openai.RateLimitError:
            raise ProviderFailureError(
                ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_RATE_LIMIT
            ) from None
        except openai.APIConnectionError:
            raise ProviderFailureError(
                ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_CONNECTION
            ) from None
        except openai.APIStatusError:
            raise ProviderFailureError(
                ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_API_STATUS
            ) from None
        except openai.OpenAIError:
            raise ProviderFailureError(
                ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_SDK
            ) from None
        latency_ms = (time.monotonic() - started) * 1000.0

        payload = self._extract_structured_payload(response)
        return ProviderResult(
            payload=payload,
            provider=self._identity.provider,
            model_name=self._identity.model_name,
            model_version=None,
            finish_reason=getattr(response, "status", None),
            usage=_map_usage(response, latency_ms),
        )

    def _extract_structured_payload(self, response: Any) -> dict[str, Any]:
        """Extract ONLY the structured result; never return the Response."""
        status = getattr(response, "status", None)
        if status == "cancelled":
            raise ProviderFailureError(ProviderFailureKind.CANCELLED, ERROR_CLASS_NOT_COMPLETED)
        if status == "incomplete":
            raise ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_INCOMPLETE)
        if status != "completed":
            raise ProviderFailureError(
                ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_NOT_COMPLETED
            )
        if _contains_refusal(response):
            raise ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_REFUSAL)
        text = getattr(response, "output_text", "") or ""
        if not text.strip():
            raise ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_MALFORMED)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            raise ProviderFailureError(
                ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_MALFORMED
            ) from None
        if not isinstance(payload, dict):
            raise ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_MALFORMED)
        return payload


def _schema_format_name(output_schema: ProviderOutputSchema) -> str:
    """OpenAI format names allow [a-zA-Z0-9_-] up to 64 chars."""
    combined = f"{output_schema.name}-v{output_schema.version}"
    sanitized = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in combined)
    return sanitized[:64]


def _contains_refusal(response: Any) -> bool:
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) == "message":
            for content in getattr(item, "content", []) or []:
                if getattr(content, "type", None) == "refusal":
                    return True
    return False


def _map_usage(response: Any, latency_ms: float) -> GenerationUsage:
    """Map only genuinely provider-reported usage; nothing is invented.

    Cost stays absent: the Responses API supplies no cost metadata and no
    pricing is ever calculated here.
    """
    usage = getattr(response, "usage", None)
    return GenerationUsage(
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
        latency_ms=round(latency_ms, 3),
    )


def create_openai_provider_from_settings(settings: Settings) -> OpenAiStructuredProvider:
    """Build the adapter from typed settings; both key and model required."""
    api_key = settings.openai_api_key
    model = settings.openai_model
    if api_key is None or model is None:
        raise InvalidProviderIdentityError(
            "CONTENTOS_OPENAI_API_KEY and CONTENTOS_OPENAI_MODEL must be configured "
            "to use the OpenAI provider"
        )
    return OpenAiStructuredProvider(
        api_key=api_key.get_secret_value(),
        model=model,
        timeout_seconds=settings.openai_timeout_seconds,
    )
