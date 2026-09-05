# ADR 0011: Subcontractor AI Gateway as a Selectable Generation Provider

Status: Accepted
Date: 2026-09-04

## Context

ADR 0009 made OpenAI the first adapter behind the provider-neutral
`StructuredGenerationProvider` boundary (Responses API, strict JSON-schema
outputs). In operation the OpenAI key was never configured, every AI command
silently failed, and the team decided to source AI capacity from
`subcontractor-ai` (github.com/OktayCennetoglu/subcontractor-ai), a
self-hosted gateway the team controls. The gateway relays prompts to
licensed browser sessions (ChatGPT, Claude, Gemini, …) through Nstbrowser
profiles, queues work on RabbitMQ, and exposes it to customers behind
`ksk_live_...` API keys:

- `POST /v1/jobs` (`model`, `type: text|image`, `prompt`, `meta`) →
  `jobId`; `GET /v1/jobs/{id}` → `queued | running | succeeded | failed`
  with `text`, `images[].url`, `error.code`.
- `POST /v1/chat/completions` (OpenAI-compatible, messages flattened to one
  prompt; no `response_format`, no tools, no real token usage).

Two properties of the gateway shape the design: jobs take 5–90 s (image
jobs longer) and the model answers as FREE TEXT — nothing enforces a JSON
schema on the gateway side.

## Decision

1. Add `contentos.ai.providers.subcontractor_provider` implementing the
   existing protocol; the boundary, attempt persistence, validation and
   retry semantics do not change. Selection is configuration:
   `CONTENTOS_AI_PROVIDER = openai | subcontractor` (default `openai`, so
   nothing changes for anyone who does not opt in).
2. Transport is submit-and-poll on `/v1/jobs`, never a long-held
   `/v1/chat/completions` request: the worker must not block on a 90 s HTTP
   call behind proxies, and the job record carries `status`, `error.code`
   and `images` explicitly. Overall deadline = configured job timeout plus
   two poll intervals; the adapter sleeps between polls.
3. Structured output is a PROMPT CONTRACT plus extraction: the adapter
   appends the exact JSON schema and a "reply with one JSON object only"
   rule to the ContentOS instructions and input projection, then extracts
   the single JSON object from the reply (fenced blocks and surrounding
   prose tolerated). Schema validation stays in the AI boundary, so a
   non-conforming reply becomes a durable `validation_failed` attempt —
   exactly like an OpenAI malformed output, never a silent success.
4. Images: `type: image`; the first produced image is downloaded from the
   gateway and returned as the same `image_base64` + `media_type` envelope
   the media boundary already consumes. A text-only reply is `no_image`.
5. Identity and honesty: `provider = subcontractor`, `model_name` = the
   gateway model id (`chatgpt`, `claude`, …), `model_version = None`. Usage
   carries latency only; the gateway's token counts are estimates and are
   not persisted as real usage.
6. Failures are bounded classes `subcontractor_*` (timeout, rate_limit,
   auth, connection, api_error, malformed_response, malformed_structured_
   output, no_image, `job_<sanitized code>`); gateway messages, URLs and
   keys are never persisted.
7. Configuration truth follows the SELECTED provider:
   `Settings.text_provider_configured` / `image_provider_configured`, the
   API's fail-fast 503 guard, the dashboard `ai.provider` field and the
   admin notices all name the variables the selected provider needs.
   compose passes `CONTENTOS_SUBCONTRACTOR_*` through and adds
   `host.docker.internal:host-gateway` so containers reach a gateway
   running on the host.

## Consequences

- AI capacity comes from accounts the team licenses; throughput is the
  gateway's account count (one concurrent job per account). Long jobs are
  normal; the worker's Celery time limits must stay above the configured
  gateway timeout.
- Prompt-contract JSON is less reliable than strict structured outputs.
  The boundary's validation and retry policy absorb that; the admin's AI
  attempt list shows `validation_failed` when a model ignores the contract.
  If that rate is high for a model, switch `CONTENTOS_SUBCONTRACTOR_MODEL`
  rather than loosening validation.
- The OpenAI adapter remains intact and selectable; ADR 0009 is not
  superseded, only complemented.
- Operational prerequisites live outside this repo: a running gateway
  (Docker on the host, port 8090 by default), a logged-in browser profile
  per account, and a customer key created with `npm run keys -- create`.
