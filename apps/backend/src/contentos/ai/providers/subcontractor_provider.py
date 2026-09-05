"""The Subcontractor AI gateway adapter behind StructuredGenerationProvider
(ADR 0011).

`subcontractor-ai` is a self-hosted gateway that relays prompts to licensed
browser sessions (ChatGPT, Claude, …) and exposes them behind an API key:
`POST /v1/jobs` submits a text or image job, `GET /v1/jobs/{id}` reports
`queued | running | succeeded | failed` with the produced `text` / `images`.
Jobs take 5–90 s, so the adapter submits and POLLS instead of holding one
HTTP request open.

The gateway cannot enforce a JSON schema (the model answers as free text),
so this adapter embeds the ContentOS output schema as an explicit
instruction in the prompt, then extracts and parses the single JSON object
from the reply (code fences and surrounding prose are tolerated). Schema
VALIDATION stays where it always was — in the AI boundary on top of the
returned payload — so a non-conforming reply becomes a durable
validation_failed attempt, never a silent success.

No HTTP object, URL, key, or raw body ever leaves this module: results
cross the boundary as provider-neutral DTOs and failures as typed
ProviderFailureError values with bounded, sanitized error classes.
"""

import base64
import json
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

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

SUBCONTRACTOR_PROVIDER_NAME = "subcontractor"

# Stable sanitized error classes (never raw gateway text).
ERROR_CLASS_TIMEOUT = "subcontractor_timeout"
ERROR_CLASS_RATE_LIMIT = "subcontractor_rate_limit"
ERROR_CLASS_CONNECTION = "subcontractor_connection_error"
ERROR_CLASS_AUTH = "subcontractor_auth_error"
ERROR_CLASS_API_STATUS = "subcontractor_api_error"
ERROR_CLASS_MALFORMED_RESPONSE = "subcontractor_malformed_response"
ERROR_CLASS_MALFORMED = "subcontractor_malformed_structured_output"
ERROR_CLASS_NO_IMAGE = "subcontractor_no_image"
ERROR_CLASS_JOB_FAILED_PREFIX = "subcontractor_job_"

_JOB_TERMINAL = frozenset({"succeeded", "failed"})
_JOB_CODE_SAFE = re.compile(r"[^a-z0-9_]+")
_FENCE = re.compile(r"```[a-zA-Z0-9_-]*\s*(.*?)```", re.S)

Sleeper = Callable[[float], None]


class SubcontractorGatewayClient:
    """Submit-and-poll transport for the gateway's `/v1/jobs` surface."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        poll_interval_seconds: float,
        http_client: httpx.Client | None = None,
        sleep: Sleeper = time.sleep,
    ) -> None:
        if not base_url or not base_url.strip():
            raise InvalidProviderIdentityError("a Subcontractor gateway base URL is required")
        if not api_key or not api_key.strip():
            raise InvalidProviderIdentityError("a Subcontractor gateway API key is required")
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._sleep = sleep
        # Injectable for tests (httpx.MockTransport); production builds one
        # client per adapter with a bounded per-request timeout.
        self._http = (
            http_client
            if http_client is not None
            else httpx.Client(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=httpx.Timeout(30.0, read=60.0),
            )
        )

    def run_job(
        self, *, model: str, job_type: str, prompt: str, meta: dict[str, Any]
    ) -> dict[str, Any]:
        """Submit one job and poll until it is terminal; return the record.

        Raises ProviderFailureError for transport failures, gateway refusals,
        a failed job, or the overall deadline (job timeout + a poll grace)."""
        body = {
            "model": model,
            "type": job_type,
            "prompt": prompt,
            "options": {"timeoutMs": int(self._timeout_seconds * 1000), "newChat": True},
            "meta": meta,
        }
        submitted = self._request("POST", "/v1/jobs", json=body)
        job_id = submitted.get("jobId") or submitted.get("id")
        if not isinstance(job_id, str) or not job_id:
            raise ProviderFailureError(
                ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_MALFORMED_RESPONSE
            )
        deadline = time.monotonic() + self._timeout_seconds + 2 * self._poll_interval_seconds
        record = submitted
        while record.get("status") not in _JOB_TERMINAL:
            if time.monotonic() >= deadline:
                raise ProviderFailureError(ProviderFailureKind.TIMEOUT, ERROR_CLASS_TIMEOUT)
            self._sleep(self._poll_interval_seconds)
            record = self._request("GET", f"/v1/jobs/{job_id}")
        if record.get("status") == "failed":
            raise _job_failure(record.get("error"))
        return record

    def fetch_bytes(self, url: str) -> bytes:
        """Download a produced image. Relative `/images/...` paths resolve
        against the gateway; absolute URLs are fetched as given."""
        target = url if url.startswith(("http://", "https://")) else f"{self._base_url}{url}"
        try:
            response = self._http.get(target)
        except httpx.TimeoutException:
            raise ProviderFailureError(ProviderFailureKind.TIMEOUT, ERROR_CLASS_TIMEOUT) from None
        except httpx.HTTPError:
            raise ProviderFailureError(
                ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_CONNECTION
            ) from None
        if response.status_code != 200 or not response.content:
            raise ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_NO_IMAGE)
        return response.content

    def _request(self, method: str, path: str, *, json: Any | None = None) -> dict[str, Any]:
        try:
            response = self._http.request(method, path, json=json)
        except httpx.TimeoutException:
            raise ProviderFailureError(ProviderFailureKind.TIMEOUT, ERROR_CLASS_TIMEOUT) from None
        except httpx.HTTPError:
            raise ProviderFailureError(
                ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_CONNECTION
            ) from None
        if response.status_code == 429:
            raise ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_RATE_LIMIT)
        if response.status_code in (401, 403):
            raise ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_AUTH)
        if response.status_code >= 400:
            raise ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_API_STATUS)
        try:
            payload = response.json()
        except ValueError:
            raise ProviderFailureError(
                ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_MALFORMED_RESPONSE
            ) from None
        if not isinstance(payload, dict):
            raise ProviderFailureError(
                ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_MALFORMED_RESPONSE
            )
        return payload


def _job_failure(error: Any) -> ProviderFailureError:
    """Map a failed job to a bounded class; the gateway's message is dropped."""
    code = ""
    if isinstance(error, dict):
        raw = error.get("code")
        if isinstance(raw, str):
            code = _JOB_CODE_SAFE.sub("_", raw.strip().lower())[:40]
    if code in ("timeout", "deadline"):
        return ProviderFailureError(ProviderFailureKind.TIMEOUT, ERROR_CLASS_TIMEOUT)
    if code == "rate_limited":
        return ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_RATE_LIMIT)
    if code == "no_image":
        return ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_NO_IMAGE)
    return ProviderFailureError(
        ProviderFailureKind.PROVIDER_ERROR,
        f"{ERROR_CLASS_JOB_FAILED_PREFIX}{code or 'failed'}",
    )


def build_structured_prompt(request: GenerationRequest, output_schema: ProviderOutputSchema) -> str:
    """The prompt the browser model sees: ContentOS instructions, the exact
    output schema as an explicit contract, then the bounded input projection.
    Everything the model must know is in the prompt — the gateway is
    stateless per job and no tools exist."""
    schema_json = json.dumps(output_schema.json_schema, ensure_ascii=False, indent=2)
    parts = []
    if request.instructions:
        parts.append(request.instructions.strip())
    parts.append(
        "ÇIKTI KURALI: Yanıtı YALNIZCA aşağıdaki JSON şemasına birebir uyan TEK bir "
        "JSON nesnesi olarak ver. Açıklama, başlık, kod bloğu işareti veya ek metin "
        "yazma; yanıtın ilk karakteri '{' ve son karakteri '}' olsun. Şemada olmayan "
        "alan ekleme, zorunlu alanları boş bırakma, metin değerlerinde geçerli JSON "
        "kaçışları kullan."
    )
    parts.append(f"JSON ŞEMASI ({output_schema.name} v{output_schema.version}):\n{schema_json}")
    parts.append(f"GİRDİ (JSON):\n{canonical_json(request.input_projection)}")
    return "\n\n".join(parts)


def extract_json_object(text: str) -> dict[str, Any]:
    """Pull the single JSON object out of a free-text reply.

    Tolerates a fenced block and prose around the object; refuses anything
    that is not exactly one JSON object."""
    candidate = text.strip()
    if not candidate:
        raise ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_MALFORMED)
    fenced = _FENCE.search(candidate)
    if fenced is not None:
        candidate = fenced.group(1).strip()
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_MALFORMED)
        candidate = candidate[start : end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        raise ProviderFailureError(
            ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_MALFORMED
        ) from None
    if not isinstance(payload, dict):
        raise ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_MALFORMED)
    return payload


class SubcontractorStructuredProvider:
    """One gateway model (chatgpt, claude, …) behind the provider protocol.

    `model_version` is None: the gateway drives a browser session and
    exposes no genuine model-version identity; nothing is invented."""

    def __init__(self, *, client: SubcontractorGatewayClient, model: str) -> None:
        self._client = client
        self._identity = ProviderIdentity(
            provider=SUBCONTRACTOR_PROVIDER_NAME, model_name=model, model_version=None
        )

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

    def generate(
        self, request: GenerationRequest, output_schema: ProviderOutputSchema
    ) -> ProviderResult:
        started = time.monotonic()
        record = self._client.run_job(
            model=self._identity.model_name,
            job_type="text",
            prompt=build_structured_prompt(request, output_schema),
            meta={
                "source": "contentos",
                "purpose": request.purpose.value,
                "schema": f"{output_schema.name}-v{output_schema.version}",
                "retry": request.retry_number,
            },
        )
        latency_ms = (time.monotonic() - started) * 1000.0
        text = record.get("text")
        payload = extract_json_object(text if isinstance(text, str) else "")
        return ProviderResult(
            payload=payload,
            provider=self._identity.provider,
            model_name=self._identity.model_name,
            model_version=None,
            finish_reason=str(record.get("status") or "succeeded"),
            usage=GenerationUsage(latency_ms=round(latency_ms, 3)),
        )


class SubcontractorImageProvider:
    """Image jobs through the same gateway (only models that produce images).

    Returns the media envelope the media boundary expects
    (`image_base64` + `media_type`) by downloading the first produced image
    from the gateway; a text-only reply is a NO_IMAGE failure."""

    def __init__(self, *, client: SubcontractorGatewayClient, model: str) -> None:
        self._client = client
        self._identity = ProviderIdentity(
            provider=SUBCONTRACTOR_PROVIDER_NAME, model_name=model, model_version=None
        )

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

    def generate(
        self, request: GenerationRequest, output_schema: ProviderOutputSchema
    ) -> ProviderResult:
        prompt = f"{request.instructions}\n\n{canonical_json(request.input_projection)}".strip()
        started = time.monotonic()
        record = self._client.run_job(
            model=self._identity.model_name,
            job_type="image",
            prompt=prompt,
            meta={"source": "contentos", "purpose": request.purpose.value},
        )
        images = record.get("images")
        first = images[0] if isinstance(images, list) and images else None
        url = first.get("url") if isinstance(first, dict) else None
        if not isinstance(url, str) or not url:
            raise ProviderFailureError(ProviderFailureKind.PROVIDER_ERROR, ERROR_CLASS_NO_IMAGE)
        content = self._client.fetch_bytes(url)
        latency_ms = (time.monotonic() - started) * 1000.0
        media_type = first.get("contentType") if isinstance(first, dict) else None
        return ProviderResult(
            payload={
                "image_base64": base64.b64encode(content).decode("ascii"),
                "media_type": media_type
                if isinstance(media_type, str) and media_type
                else "image/png",
            },
            provider=self._identity.provider,
            model_name=self._identity.model_name,
            model_version=None,
            finish_reason="completed",
            usage=GenerationUsage(latency_ms=round(latency_ms, 3)),
        )


def _client_from_settings(settings: Settings) -> SubcontractorGatewayClient:
    base_url = settings.subcontractor_base_url
    api_key = settings.subcontractor_api_key
    if base_url is None or api_key is None:
        raise InvalidProviderIdentityError(
            "CONTENTOS_SUBCONTRACTOR_BASE_URL and CONTENTOS_SUBCONTRACTOR_API_KEY must be "
            "configured to use the Subcontractor provider"
        )
    return SubcontractorGatewayClient(
        base_url=base_url,
        api_key=api_key.get_secret_value(),
        timeout_seconds=settings.subcontractor_timeout_seconds,
        poll_interval_seconds=settings.subcontractor_poll_interval_seconds,
    )


def create_subcontractor_provider_from_settings(
    settings: Settings,
) -> SubcontractorStructuredProvider:
    return SubcontractorStructuredProvider(
        client=_client_from_settings(settings), model=settings.subcontractor_model
    )


def create_subcontractor_image_provider_from_settings(
    settings: Settings,
) -> SubcontractorImageProvider:
    return SubcontractorImageProvider(
        client=_client_from_settings(settings), model=settings.subcontractor_image_model
    )
