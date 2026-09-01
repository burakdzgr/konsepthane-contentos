"""The provider-neutral structured-generation protocol.

Adapters (none exist yet — the first real adapter is a later task with its
own dependency/ADR checkpoint) implement this narrow contract:

- expose a stable, honest `identity` (model_version None when genuinely
  unavailable — never fabricated);
- return a `ProviderResult` whose payload is a plain JSON-compatible
  object; SDK/HTTP objects never cross this boundary;
- translate every provider/SDK failure into a typed
  `ProviderFailureError` with a bounded sanitized error class.
"""

from typing import Protocol, runtime_checkable

from contentos.ai.dto import GenerationRequest, ProviderIdentity, ProviderResult


@runtime_checkable
class StructuredGenerationProvider(Protocol):
    @property
    def identity(self) -> ProviderIdentity: ...

    def generate(self, request: GenerationRequest) -> ProviderResult: ...
