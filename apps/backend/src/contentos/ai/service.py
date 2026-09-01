"""The transport-neutral structured-generation runner.

Flow: validate request/spec agreement -> canonical input + attempt identity
-> return the already-stored identical attempt if one exists -> invoke the
provider ONCE -> map provider-neutral failures -> schema validation ->
optional domain validation -> persist ONE immutable completed attempt row.
The service flushes; the caller commits. No workflow, opportunity,
selection, pack, or evidence side effects of any kind.

Expected outcomes (validation/provider failures, timeout, cancellation) are
returned as durable attempt facts — never raised — so committing the
caller's transaction preserves failure history. Contract errors (invalid
request/spec/provider identity) raise typed errors BEFORE any provider
invocation and persist nothing.

SUCCEEDED means exactly: the provider invocation succeeded, the structured
output satisfied the explicit versioned Pydantic schema, and the supplied
domain validation (if any) passed. It never means an idea was selected,
content was approved, workflow advanced, or any factual claim is proven.

Concurrency (documented, truthful): the attempt identity is derived BEFORE
provider invocation and a stored identical attempt short-circuits the call,
so sequential retries never invoke the provider twice. Under truly
concurrent execution of the same identity, both callers may invoke the
provider (the
external call happens before an INSERT race is observable); the DB UNIQUE
identity then guarantees exactly ONE durable attempt row, and the loser
returns the winner's row. Serializing the provider call itself would need a
mutable reservation model that conflicts with the accepted append-only
completed-outcome design — that remains a future orchestration boundary.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.ai.dto import (
    GenerationRequest,
    ProviderIdentity,
    ProviderOutputSchema,
    ProviderResult,
)
from contentos.ai.enums import GenerationStatus, ProviderFailureKind
from contentos.ai.errors import (
    GenerationConflictError,
    InvalidSchemaSpecError,
    ProviderFailureError,
)
from contentos.ai.hashing import attempt_identity_hash, generation_input_hash
from contentos.ai.models import AiGenerationAttempt
from contentos.ai.protocol import StructuredGenerationProvider
from contentos.ai.repository import AiGenerationAttemptRepository
from contentos.ai.validation import (
    DOMAIN_VALIDATION_ERROR_CLASS,
    SCHEMA_VALIDATION_ERROR_CLASS,
    StructuredOutputSpec,
)

PROVIDER_IDENTITY_MISMATCH_ERROR_CLASS = "provider_identity_mismatch"

_FAILURE_STATUS: dict[ProviderFailureKind, GenerationStatus] = {
    ProviderFailureKind.PROVIDER_ERROR: GenerationStatus.PROVIDER_ERROR,
    ProviderFailureKind.TIMEOUT: GenerationStatus.TIMEOUT,
    ProviderFailureKind.CANCELLED: GenerationStatus.CANCELLED,
}


@dataclass(frozen=True, slots=True)
class GenerationExecution[PayloadT: BaseModel]:
    """Typed result handed to future engines.

    `payload` is present ONLY when this execution newly produced a
    SUCCEEDED attempt. An idempotent reuse returns the stored attempt with
    no payload: raw output is never persisted, so replayed content must
    come from the engine's own domain artifact tables.
    """

    attempt: AiGenerationAttempt
    status: GenerationStatus
    created: bool
    payload: PayloadT | None = None


class StructuredGenerationService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = AiGenerationAttemptRepository(session)

    def execute[PayloadT: BaseModel](
        self,
        request: GenerationRequest,
        spec: StructuredOutputSpec[PayloadT],
        provider: StructuredGenerationProvider,
    ) -> GenerationExecution[PayloadT]:
        _require_schema_agreement(request, spec)
        identity = provider.identity

        input_hash = generation_input_hash(
            input_refs=request.input_refs,
            input_projection=request.input_projection,
            generation_bounds=request.generation_bounds,
        )
        identity_hash = attempt_identity_hash(
            purpose=request.purpose.value,
            input_hash=input_hash,
            provider=identity.provider,
            model_name=identity.model_name,
            model_version=identity.model_version,
            schema_name=request.schema_name,
            schema_version=request.schema_version,
            template_name=request.template_name,
            template_version=request.template_version,
            retry_number=request.retry_number,
        )

        existing = self._repository.get_by_identity_hash(identity_hash)
        if existing is not None:
            return GenerationExecution(
                attempt=existing, status=existing.status, created=False, payload=None
            )

        status: GenerationStatus
        error_class: str | None
        usage: dict[str, Any] = {}
        payload: PayloadT | None = None

        output_schema = ProviderOutputSchema(
            name=spec.schema_name,
            version=spec.schema_version,
            json_schema=spec.model_type.model_json_schema(),
            strict=True,
        )
        try:
            result = provider.generate(request, output_schema)
        except ProviderFailureError as failure:
            status = _FAILURE_STATUS[failure.kind]
            error_class = _bounded_error_class(failure.error_class)
        else:
            usage = _persisted_usage(result)
            if not _identity_matches(identity, result):
                status = GenerationStatus.PROVIDER_ERROR
                error_class = PROVIDER_IDENTITY_MISMATCH_ERROR_CLASS
            else:
                status, error_class, payload = _validate_payload(spec, result)

        attempt = AiGenerationAttempt(
            purpose=request.purpose,
            provider=identity.provider,
            model_name=identity.model_name,
            model_version=identity.model_version,
            schema_name=request.schema_name,
            schema_version=request.schema_version,
            template_name=request.template_name,
            template_version=request.template_version,
            input_refs=request.input_refs,
            input_hash=input_hash,
            attempt_identity_hash=identity_hash,
            status=status,
            error_class=error_class,
            retry_number=request.retry_number,
            usage=usage,
        )
        try:
            with self._session.begin_nested():
                self._repository.add(attempt)
        except IntegrityError:
            winner = self._repository.get_by_identity_hash(identity_hash)
            if winner is not None:
                return GenerationExecution(
                    attempt=winner, status=winner.status, created=False, payload=None
                )
            raise GenerationConflictError(
                "attempt persistence conflicted with concurrently written state"
            ) from None

        return GenerationExecution(
            attempt=attempt,
            status=status,
            created=True,
            payload=payload if status is GenerationStatus.SUCCEEDED else None,
        )


def _require_schema_agreement[PayloadT: BaseModel](
    request: GenerationRequest, spec: StructuredOutputSpec[PayloadT]
) -> None:
    if request.schema_name != spec.schema_name or request.schema_version != spec.schema_version:
        raise InvalidSchemaSpecError(
            "the output-schema spec disagrees with the request's schema identity"
        )


def _identity_matches(declared: ProviderIdentity, result: ProviderResult) -> bool:
    return (
        result.provider == declared.provider
        and result.model_name == declared.model_name
        and result.model_version == declared.model_version
    )


def _validate_payload[PayloadT: BaseModel](
    spec: StructuredOutputSpec[PayloadT], result: ProviderResult
) -> tuple[GenerationStatus, str | None, PayloadT | None]:
    try:
        validated = spec.model_type.model_validate(result.payload)
    except ValidationError:
        # The rejected raw payload is discarded after classification; no
        # validation traceback or input echo becomes domain data.
        return GenerationStatus.VALIDATION_FAILED, SCHEMA_VALIDATION_ERROR_CLASS, None
    if spec.domain_validator is not None and spec.domain_validator(validated) is not None:
        return GenerationStatus.VALIDATION_FAILED, DOMAIN_VALIDATION_ERROR_CLASS, None
    return GenerationStatus.SUCCEEDED, None, validated


def _persisted_usage(result: ProviderResult) -> dict[str, Any]:
    usage = result.usage.to_persisted() if result.usage is not None else {}
    if result.finish_reason is not None:
        usage["finish_reason"] = result.finish_reason
    return usage


def _bounded_error_class(value: str) -> str:
    cleaned = " ".join(value.split()) or "provider_failure"
    return cleaned[:100]


__all__ = [
    "PROVIDER_IDENTITY_MISMATCH_ERROR_CLASS",
    "GenerationExecution",
    "StructuredGenerationService",
]
