"""The mandatory deterministic fake provider (tests/dev only, no network).

This is infrastructure for proving the boundary before any real adapter
exists — never application business logic, never a stand-in for a real
model. Identity is explicit and frozen in tests: provider ``fake``, model
``deterministic-structured-test-model`` version ``1``. Same configured
request -> same result; no randomness, no environment keys, no I/O.
"""

import copy
from dataclasses import dataclass, field
from typing import Any

from contentos.ai.dto import (
    GenerationRequest,
    GenerationUsage,
    ProviderIdentity,
    ProviderOutputSchema,
    ProviderResult,
)
from contentos.ai.enums import ProviderFailureKind
from contentos.ai.errors import ProviderFailureError

FAKE_PROVIDER_NAME = "fake"
FAKE_MODEL_NAME = "deterministic-structured-test-model"
FAKE_MODEL_VERSION = "1"

DEFAULT_FAKE_IDENTITY = ProviderIdentity(
    provider=FAKE_PROVIDER_NAME,
    model_name=FAKE_MODEL_NAME,
    model_version=FAKE_MODEL_VERSION,
)


@dataclass
class FakeStructuredProvider:
    """Deterministic configurable provider double.

    - `payload`: the fixed structured response (valid or deliberately
      malformed, as the test requires);
    - `failure`: when set, every call raises the corresponding typed
      provider failure (provider error / timeout / cancellation);
    - `usage`: deterministic configured usage; cost stays absent unless a
      test explicitly configures it;
    - `claimed_identity`: lets tests simulate an adapter whose result
      claims a different identity than it declares (a contract violation
      the service must detect);
    - `invocations` counts real generate() calls for idempotency proofs;
    - `last_output_schema` records the schema descriptor the boundary
      handed over, so tests can assert what a real adapter would receive.
    """

    payload: dict[str, Any] = field(default_factory=dict)
    usage: GenerationUsage | None = None
    failure: ProviderFailureKind | None = None
    failure_class: str = "fake_provider_failure"
    finish_reason: str | None = "stop"
    declared_identity: ProviderIdentity = DEFAULT_FAKE_IDENTITY
    claimed_identity: ProviderIdentity | None = None
    invocations: int = 0
    last_output_schema: ProviderOutputSchema | None = None

    @property
    def identity(self) -> ProviderIdentity:
        return self.declared_identity

    def generate(
        self, request: GenerationRequest, output_schema: ProviderOutputSchema
    ) -> ProviderResult:
        self.invocations += 1
        self.last_output_schema = output_schema
        if self.failure is not None:
            raise ProviderFailureError(self.failure, self.failure_class)
        reported = self.claimed_identity or self.declared_identity
        return ProviderResult(
            payload=copy.deepcopy(self.payload),
            provider=reported.provider,
            model_name=reported.model_name,
            model_version=reported.model_version,
            finish_reason=self.finish_reason,
            usage=self.usage,
        )
