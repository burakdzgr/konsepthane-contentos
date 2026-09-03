# Operations: engine and agent intake controls

The control center (`/kontrol` in the admin) exposes the ONLY runtime
controls ContentOS has: audited intake pauses. This document is the
contract for what they do and, just as importantly, what they can never
do.

## Semantics

A pause gates NEW dispatch at the control surface — the API refuses to
publish the scope's queue jobs (HTTP 409 `intake paused (<scope>): …`)
until the scope is resumed. Nothing else changes:

- already-running tasks always finish; nothing is cancelled or killed;
- no workflow state moves; a refusal is an execution condition, never an
  editorial decision (no REJECTED, no BLOCKED);
- direct human commands (commission, idea selection, brief acceptance,
  reviewer decisions, media binding) stay available — pauses stop
  machines from being fed, not humans from deciding;
- worker-internal chains that are already past their entry point (for
  example fetch → normalize → duplicate-check) run to completion.

"Acil Durdurma" (emergency stop) is the `engine` scope: it gates every
dispatchable job at once. It is deliberately a SAFE stop — there is no
process kill, because the architecture does not support safe task
cancellation and a fake kill switch would be worse than none.

## Scopes

`engine` (everything), and per job family: `research` (discover/fetch),
`opportunity` (promote/evaluate), `ideas`, `evidence`, `intent`,
`brief`, `writer`, `editor`, `qa`, `media`, `publisher`.

## Durability and audit

State lives in `operational_pauses` (one row per scope); every change
appends to `operational_pause_events` with the named authenticated
actor, the required reason, and the request id. Pausing an
already-paused scope (or resuming a running one) is idempotent and
records nothing. Enforcement happens inside the API's single dispatch
helper, so no queue command can forget the check.

## API

Operator-guarded, like every pipeline surface:

- `GET /internal/dashboard/summary|agents|activity|publications|controls`
  — bounded read-only projections (durable rows plus a broker LLEN for
  the queue depth; unmeasurable values are `null`, never 0).
- `POST /internal/dashboard/controls/pause` / `resume` with
  `{"scope": "...", "reason": "..."}`.

## What the dashboard never shows

Provider keys, prompts, raw exception traces, broker URLs. AI failures
surface only as their sanitized `error_class`, exactly as stored on
`ai_generation_attempts`.
