# ADR 0009: OpenAI as the First Structured-Generation Provider Adapter

Status: Accepted
Date: 2026-09-01

## Context

ARCHITECTURE.md fixed "Provider abstraction; OpenAI adapter first" at
project start, and the accepted Phase 3 design (§6, §17 module rules)
requires a provider-neutral `StructuredGenerationProvider` boundary with a
deterministic fake provider proven BEFORE any real adapter, and permits
provider SDKs only inside `contentos.ai.providers.*`. Task 8 delivered that
boundary (protocol, DTOs, versioned Pydantic validation pipeline, generic
append-only `ai_generation_attempts`, deterministic fake provider) with no
vendor code. Phase 3 implementation-order item 8 (this task) is the
designated dependency/ADR checkpoint for the first real adapter.

## Decision

1. **OpenAI is the first real provider adapter**, implemented as
   `contentos.ai.providers.openai_provider.OpenAiStructuredProvider` behind
   the existing `StructuredGenerationProvider` protocol. Domain engines
   depend on the protocol only and must work unchanged with the
   deterministic fake provider; they never know OpenAI exists.
2. **Official OpenAI Python SDK only** (`openai`, pinned in `uv.lock`;
   3.6.0 at adoption). No LangChain/LlamaIndex/instructor/litellm/wrapper
   frameworks — the ContentOS boundary IS the abstraction.
3. **Responses API with strict Structured Outputs**: `responses.create`
   with `text.format = {type: json_schema, strict: true}` and the JSON
   Schema derived from the versioned Pydantic output spec. No Assistants
   API, no legacy JSON mode, no Chat Completions fallback. Provider-side
   strictness is defense layer 1; the boundary's own Pydantic + domain
   validation remains defense layer 2 and always runs.
4. **`store=false` always**: no provider-side response persistence;
   PostgreSQL remains authoritative for attempt/artifact state.
5. **No provider tools** for editorial generation (no web search, file
   search, code interpreter, MCP, function tools): ContentOS supplies the
   bounded deterministic research projection; the model never browses.
6. **No SDK types cross the boundary**: results become provider-neutral
   DTOs; SDK exceptions are translated at the adapter into typed
   provider-neutral failures with stable sanitized error classes
   (timeout/rate-limit/connection/API/SDK). No raw messages, bodies, URLs,
   headers, or request IDs are persisted; `ai_generation_attempts` keeps
   its provenance/metadata-only contract (no raw output, no prompts).
7. **SDK automatic retries are disabled** (`max_retries=0`): one ContentOS
   `retry_number` means exactly one provider invocation; retry policy
   belongs to future orchestration.
8. **Provider and model are configuration, not domain constants**:
   `CONTENTOS_OPENAI_API_KEY` (SecretStr, never logged/persisted),
   `CONTENTOS_OPENAI_MODEL`, `CONTENTOS_OPENAI_TIMEOUT_SECONDS`. The
   application and every non-OpenAI feature run without a key; the
   recorded `model_version` stays NULL because the API exposes no distinct
   version identity (never fabricated).
9. **Automated tests never depend on live OpenAI**: adapter tests inject a
   mocked client boundary; the fake provider remains the deterministic
   test/default provider for all domain-engine tests; no gate makes a
   billable call.
10. **Additional providers** can be introduced later as further
    `contentos.ai.providers.*` adapters without changing domain engines,
    the attempt schema, or the protocol.

## Consequences

The first model-assisted engine (idea candidates) and all future ones
(intent synthesis, brief composition, evidence organization) consume one
stable boundary; swapping or adding providers is an adapter + configuration
concern. Attempt provenance stays vendor-neutral and audit-honest. The
known Task 8 limitation stands: truly concurrent identical requests may
invoke the provider twice while the database still guarantees one durable
attempt — serialization of the external call is a future orchestration
boundary, deliberately not solved with mutable reservation state.
