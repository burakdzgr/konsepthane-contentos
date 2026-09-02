"""The OpenAI image adapter behind StructuredGenerationProvider.

Reuses the provider-neutral protocol: the "structured output" is the
bounded media-image envelope (`image_base64` + `media_type`), so the
whole attempt boundary (identity hashing, idempotency, safe metadata,
no raw persistence) applies unchanged. The Images API returns PNG
base64; nothing else is invented. SDK objects and exceptions never
leave this module — failures become typed ProviderFailureError values
with the same sanitized error classes as the text adapter.

The prompt handed to the API is composed IN MEMORY from the request's
instructions + canonical input projection; it is never persisted.
"""

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
from contentos.ai.providers.openai_provider import (
    ERROR_CLASS_API_STATUS,
    ERROR_CLASS_CONNECTION,
    ERROR_CLASS_MALFORMED,
    ERROR_CLASS_RATE_LIMIT,
    ERROR_CLASS_SDK,
    ERROR_CLASS_TIMEOUT,
    OPENAI_PROVIDER_NAME,
)
from contentos.core.config import Settings


class OpenAiImageProvider:
    """One configured OpenAI image model behind the provider protocol."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 120.0,
        image_size: str = "1024x1024",
        client: Any | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise InvalidProviderIdentityError("an OpenAI API key is required")
        self._identity = ProviderIdentity(
            provider=OPENAI_PROVIDER_NAME, model_name=model, model_version=None
        )
        self._image_size = image_size
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
        prompt = f"{request.instructions}\n\n{canonical_json(request.input_projection)}"
        started = time.monotonic()
        try:
            response = self._client.images.generate(
                model=self._identity.model_name,
                prompt=prompt,
                size=self._image_size,
                n=1,
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

        data = getattr(response, "data", None) or []
        first = data[0] if data else None
        image_base64 = getattr(first, "b64_json", None) if first is not None else None
        if not image_base64:
            raise ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_MALFORMED)
        return ProviderResult(
            payload={"image_base64": image_base64, "media_type": "image/png"},
            provider=self._identity.provider,
            model_name=self._identity.model_name,
            model_version=None,
            finish_reason="completed",
            usage=GenerationUsage(latency_ms=round(latency_ms, 3)),
        )


def create_openai_image_provider_from_settings(settings: Settings) -> OpenAiImageProvider:
    """Build the adapter from typed settings; key and image model required."""
    api_key = settings.openai_api_key
    model = settings.openai_image_model
    if api_key is None or model is None:
        raise InvalidProviderIdentityError(
            "CONTENTOS_OPENAI_API_KEY and CONTENTOS_OPENAI_IMAGE_MODEL must be "
            "configured to use the OpenAI image provider"
        )
    return OpenAiImageProvider(
        api_key=api_key.get_secret_value(),
        model=model,
        timeout_seconds=settings.openai_image_timeout_seconds,
    )
