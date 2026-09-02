# Phase 7 — Publishing (architecture)

Media closed with packages that can be fully satisfied; governance
closed with hash-bound approvals and the SCHEDULED → APPROVAL_EXPIRED
wiring waiting for a consumer. Phase 7 builds the ContentOS SIDE of
publishing: assembling the exact approved package into a durable
publication payload and moving it through APPROVED → SCHEDULED →
PUBLISHING → PUBLISHED behind artifact gates — while the LIVE
integration stays explicitly blocked on unresolved operator inputs.

## 1. Scope and binding decisions

**Decision — the boundary is an API, never a filesystem.** ContentOS
never touches the Konsepthane production database or filesystem. The
only path to production is a versioned + authenticated + idempotent
**Publishing API** owned by the Konsepthane side. Three inputs are OPEN
(tracked in `docs/memory/CURRENT_STATE.md`) and BLOCK the live
integration, not this phase's design:

1. the Publishing API contract (endpoint shapes, payload format,
   versioning);
2. the service authentication method (key exchange, rotation, owner);
3. the production owner sign-off.

Phase 7 therefore ships: the durable publication package, the workflow
wiring, the idempotent dispatch machinery, and a `PublishingTransport`
protocol with (a) a deterministic in-repo fake used by every test and
real-PG verification and (b) the HTTP adapter SKELETON that refuses to
construct without explicit configuration. No default endpoint, no
guessed contract: an unconfigured transport is a typed error, never a
silent no-op or a fabricated success.

**Decision — publish exactly what was approved, or nothing.** The
publication package is assembled ONLY from the pinned approved
artifacts: the ACTIVE draft whose `content_hash` equals the approval's
pinned hash (enforced by `DecisionService.require_current_approval` —
the guard, never a re-derived rule), the ACTIVE brief, the ACTIVE
`ready_for_human_review` QA report, and the ACTIVE media bindings.
Assembly is deterministic and hashed (`package_hash`); the package row
is immutable and versioned per work item, and every downstream step
pins its id + hash. A stale approval at ANY step surfaces through the
already-wired `expire_stale_approval` (SCHEDULED → APPROVAL_EXPIRED)
— it is never ridden and never silently re-approved.

**Decision — rendering is NOT ContentOS's job in v1.** The package
carries the validated STRUCTURE (sections/blocks exactly as approved,
claim references stripped to plain provenance metadata, media as asset
references with alt/licensing plus upload instructions) — HTML/theme
rendering belongs to the consuming side per the open contract. Nothing
in the package may exceed what the approved draft contains: no
enrichment, no rewriting, no added links.

**Decision — humans schedule; machines only execute.** APPROVED →
SCHEDULED is an OPERATOR command (`schedule-publication`) gated on a
current approval AND a durable publication package; PUBLISHING and
PUBLISHED are SYSTEM transitions gated on durable dispatch results. A
transport/execution failure leaves the item in PUBLISHING with a
durable failed attempt (bounded retries), then BLOCKED — execution
failure is NEVER an editorial decision and never REJECTED.

**Decision — idempotency end to end.** One publication attempt is
identified by `(work_item_id, package_hash, attempt_number)`; the
idempotency key sent to the Publishing API is derived from
`(work_item_id, package_hash)` so redelivery and retries can never
double-publish. The remote publication identity returned by the API is
stored durably; redelivery after success reuses it.

## 2. Workflow wiring (canonical rows, now implemented)

- `APPROVED → SCHEDULED`: operator command; gates: current approval
  (the guard) + durable package whose hash equals the approved hash;
  pins {publication_package_id, package_hash, human_decision_id}.
- `SCHEDULED → PUBLISHING`: SYSTEM, when the publish task starts a
  dispatch; gates: current approval re-checked — if stale,
  `expire_stale_approval` fires instead (SCHEDULED →
  APPROVAL_EXPIRED, already wired in G5).
- `PUBLISHING → PUBLISHED`: SYSTEM, gated on a durable SUCCEEDED
  dispatch with the remote publication reference pinned.
- `PUBLISHING → BLOCKED`: SYSTEM, after bounded retries exhaust; the
  durable failed attempts stay visible; resume follows the existing
  BLOCKED machinery (operator resolves; the entry state derives the
  exit).
- `APPROVAL_EXPIRED → QA_REVIEW | AWAITING_HUMAN_REVIEW`: operator
  resolution commands (deterministic gate: QA_REVIEW when the ACTIVE
  QA report no longer covers the ACTIVE draft, else
  AWAITING_HUMAN_REVIEW).
- `PUBLISHED → …` (measuring/distribution) stays out of scope.

## 3. Data model (migration `0025`)

**`publication_packages`** (immutable, versioned): `id`,
`work_item_id` RESTRICT, `version` (UNIQUE per work item),
`human_decision_id` RESTRICT (the approval), `content_draft_id`,
`content_brief_id`, `qa_report_id` RESTRICT pins, `content_hash` (the
approved draft hash), `payload` JSONB (the bounded assembled
structure), `payload_schema_version` (`publication-package/1`),
`package_hash` (sha256 of the canonical payload), `media_manifest`
JSONB (asset id → sha256/media_type/alt/license), `assembled_by_user_id`
RESTRICT, `created_at`; append-only trigger; partial-unique ACTIVE not
needed (packages are pinned by id, never "current").

**`publication_attempts`** (append-only execution facts): `id`,
`publication_package_id` RESTRICT, `attempt_number`
(UNIQUE per package), `idempotency_key` (derived, indexed), `status`
CHECK {succeeded, transport_error, rejected_by_api, timeout},
`error_class` (bounded, sanitized — no bodies/URLs/keys),
`remote_publication_ref` NULL (present iff succeeded),
`transport_name`, `request_id`, `created_at`. No editorial vocabulary:
an attempt can fail, it can never "reject content".

## 4. Mechanics

- **Assembler** (`contentos.publishing.assembler`): deterministic
  projection of the approved artifacts into
  `publication-package/1`; refuses (typed preconditions) without a
  current approval, a covering ready QA report, or with unmet unwaived
  media needs; canonical-JSON hashing.
- **`PublishingTransport` protocol**: `identity` (name + version) and
  `publish(package_payload, media_provider, idempotency_key) →
  TransportResult`; media bytes are handed over through a bounded
  callable so the transport never touches the store layout. In-repo:
  `FakePublishingTransport` (deterministic, records invocations,
  configurable failures). The HTTP adapter ships as configuration-
  gated skeleton (`publishing_api_url`, `publishing_api_key` settings,
  both default-None; constructing without them is a typed error).
- **Queue task `publish_package`** (11th editorial task): SCHEDULED →
  re-check approval (expire path on stale) → SYSTEM → PUBLISHING →
  dispatch through the transport with the idempotency key → durable
  attempt → on success SYSTEM → PUBLISHED with
  {publication_package_id, package_hash, remote_publication_ref}
  pinned; on failure bounded Celery retries, then SYSTEM → BLOCKED
  with the truthful reason. Redelivery guards mirror the QA task.
- **Operator commands**: `assemble-publication-package` (direct,
  durable package), `schedule-publication` (transition with pins),
  `publish` (queue command; only from SCHEDULED), APPROVAL_EXPIRED
  resolution commands.

## 5. Read models and admin

- `work-items/{id}/publication` read model: packages (payload summary,
  hashes, pins), attempts exactly as recorded (status, sanitized error
  class, remote ref), and the approval-currency of the latest package.
- Admin detail page: Publication section — package assembly/schedule/
  publish commands state-gated; the attempt history with honest
  failure classes; the APPROVAL_EXPIRED state renders with its
  resolution commands and the exact hash mismatch shown.
- Leak tests: no publishing URL/key material in any response or page.

## 6. Exit criteria

- [ ] a publication package is assembled ONLY from the pinned approved
      artifacts under a current approval, deterministically hashed,
      immutable, versioned; unmet unwaived media needs refuse assembly
- [ ] APPROVED → SCHEDULED → PUBLISHING → PUBLISHED advance ONLY via
      WorkflowService behind artifact gates; humans schedule, machines
      execute; every pin resolvable
- [ ] a stale approval at scheduling or publish time surfaces via
      APPROVAL_EXPIRED (never ridden); the expired state has governed
      resolution commands with a deterministic target gate
- [ ] publishing failures are durable attempts with sanitized error
      classes; bounded retries then BLOCKED; REJECTED unreachable from
      any publishing path
- [ ] dispatch is idempotent end to end (attempt identity + API
      idempotency key + remote ref reuse on redelivery)
- [ ] the transport boundary holds: no Konsepthane DB/filesystem
      access, no default endpoint, unconfigured transport is a typed
      error, keys only in server settings, media bytes only through
      the bounded provider
- [ ] read models/admin expose packages and attempts with leak tests
- [ ] migration `0025` verified on real PostgreSQL; deterministic
      tests throughout (fake transport); the LIVE integration remains
      explicitly blocked on the three open inputs
- [ ] a publishing closure audit against these criteria

## 7. Implementation order (atomic, dependency-correct)

**Task P1 — publication package foundation.** Migration `0025`,
assembler + package persistence, preconditions, unit tests, real-PG
verification.

**Task P2 — scheduling + expiry resolution.** `schedule-publication`
command with the gates, APPROVAL_EXPIRED resolution commands
(deterministic target), tests.

**Task P3 — transport + publish task.** Protocol, fake transport,
HTTP-skeleton settings gating, `publish_package` task + queue command,
idempotency + failure paths, real-PG + real-Redis verification with
the fake transport.

**Task P4 — read models + admin publication surface.** Coverage +
attempts, admin section, leak tests.

**Task P5 — publishing closure audit** (docs-only, against §6),
re-verifying that the no-publication invariant is retired the intended
way: publication exists ONLY as this governed, approval-guarded path.
