# Phase 6 — Media (architecture)

Phase 5 closed with `APPROVED` real and governed. The QA `media_needs`
gate, however, still knows only three honest answers: `not_applicable`,
`unsatisfied` (blocking), and `waived_by_human`. Phase 6 makes the
fourth answer possible — **`satisfied`** — by giving media needs a
durable, provenance-carrying, human-accepted artifact to be satisfied
BY. Scope ends there: publishing, upload-to-Konsepthane, and rendering
belong to the publishing phase.

## 1. Scope and binding decisions

**What a media need is (already shipped, unchanged).** The brief owns
`media_needs` — bounded NEED records `{role, purpose, constraints}`
(never an asset, URL, or license claim), identified positionally:
`(content_brief_id, need_index)`. Writer drafts reference them through
`media_need` blocks with a validated `media_need_ref`. Nothing in
Phase 6 changes briefs or drafts.

**Decision — a satisfied need is a bound pair, not a flag.** A need is
satisfied when an explicit, audited, human-recorded SATISFACTION binds
it to exactly one durable **media asset**. No implicit satisfaction: an
asset existing in the library satisfies nothing by itself, and an AI
generation succeeding satisfies nothing by itself (ADR 0004 — asset
acceptance is an editorial judgment).

**Decision — assets are content-addressed and immutable.** A media
asset row carries the authoritative metadata (sha256 of the bytes —
UNIQUE, byte size, media type, dimensions, required `alt_text`,
licensing posture) and the bytes live in a ContentOS-OWNED store
addressed by that hash (`media_store_root` setting; a volume in
compose). Assets are never edited — replacing media means a NEW asset
and a NEW satisfaction superseding the old one. No Konsepthane
production filesystem or DB is ever touched; the publishing phase will
move bytes through the versioned + authenticated + idempotent
Publishing API only.

**Decision — two origins, both provenance-carrying.**
- `human_upload`: an operator uploads through the backend API
  (multipart, size/type-bounded, hash-deduplicated) with REQUIRED
  licensing fields (`license_note`, optional `source_attribution`).
  The browser never talks to the store; the backend is the only
  writer.
- `ai_generated`: produced through `contentos.ai` with a new
  `GenerationPurpose.MEDIA_IMAGE`, reusing the whole boundary — the
  attempt table records safe metadata (provider, model, status, usage,
  error class), prompts and provider payloads are NEVER persisted, and
  provider keys never reach the admin/browser. The IMAGE ITSELF is the
  durable deliverable (that is not "raw model output" in the forbidden
  sense — it is the artifact, stored content-addressed with
  `generation_attempt_id` provenance, enforced by CHECK:
  `(origin='ai_generated') = (generation_attempt_id IS NOT NULL)`).
  AI never invents licensing: generated assets carry the fixed posture
  `generated_in_house`.

**Decision — failure is never an editorial decision.** A failed or
rejected-by-validation generation leaves a visible attempt and changes
nothing else; no workflow transition, no BLOCKED, no fake asset.

**Decision — the waiver stays.** `waived_by_human` remains a valid,
audited answer; Phase 6 adds the ability to satisfy, it does not
remove the ability to consciously defer.

## 2. Workflow wiring

**No new workflow states.** Media work is artifact-level. Satisfaction
commands are permitted while the work item is in
{DRAFTING, EDITING, QA_REVIEW, CHANGES_REQUESTED} — before the
package is under terminal review; AWAITING_HUMAN_REVIEW/APPROVED
packages are frozen (changing media under a reviewer's feet would make
the review dishonest). QA is NOT re-run implicitly: satisfactions
change gate INPUT, and the operator re-runs QA explicitly (existing
idempotent command) to produce a report that sees them.

## 3. Data model (migration `0023`)

**`media_assets`** (append-only by trigger; content immutable):
`id UUID`, `origin` CHECK {human_upload, ai_generated},
`content_sha256` (64 hex, UNIQUE — dedupe by construction),
`byte_size`, `media_type` CHECK (v1: {image/png, image/jpeg,
image/webp}), `width`/`height`, `alt_text` (REQUIRED — accessibility
is not optional), `title`, `license_note` (required), `source_attribution`
NULL, `generation_attempt_id` NULL UNIQUE FK → ai_generation_attempts
(with the origin CHECK above), `created_by_user_id` FK → users
RESTRICT (the named human who uploaded or commissioned),
`request_id`, `created_at`.

**`media_need_satisfactions`** (the binding; ACTIVE-row pattern like
drafts/reviews/reports): `id UUID`, `work_item_id` RESTRICT,
`content_brief_id` RESTRICT, `need_index` INT >= 0, `media_asset_id`
RESTRICT, `status` {active, superseded} with the two-shape guarded
supersession trigger + `superseded_by_satisfaction_id` one-shot
pointer, partial-unique ACTIVE per `(work_item_id, content_brief_id,
need_index)`, `satisfied_by_user_id` FK → users RESTRICT (a named
human), required `reason`, `request_id`, `created_at`. Unsatisfying
without a replacement = supersession with a NULL-pointer… no: the
two-shape trigger requires the pointer flow; explicit UNSATISFY is a
supersession event where the new state is simply "no ACTIVE row"
(content immutable; `active→superseded` with NULL pointer allowed,
exactly the shape the existing draft triggers already permit).

## 4. Mechanics

- **`MediaStore`**: a small backend abstraction (put/open/exists by
  sha256 under `media_store_root`); local volume in v1, a production
  object store is backlog, the interface keeps it swappable. The store
  path/key is internal — never rendered in API responses or admin.
- **Upload**: `POST /internal/editorial/media-assets` (operator;
  multipart; bounded size, e.g. 10 MiB; type sniffed, not trusted from
  the client; hash computed server-side; duplicate hash returns the
  existing asset honestly).
- **Generation**: queue task `generate_media_image` (10th editorial
  task) with the bounded command carrying `(work_item_id, need_index)`;
  the prompt is composed from the durable brief need + draft context
  (projection-bounded like writer/editor), sent through
  `contentos.ai`, the returned image stored content-addressed, the
  asset row written with attempt provenance. Durable result → commit;
  NO workflow transition, NO satisfaction.
- **Satisfy / replace / unsatisfy**: explicit operator commands binding
  `(work_item_id, need_index) → media_asset_id` with a required
  reason; state-bounded per §2; supersession audited.
- **QA gate v2**: `_media_needs` learns `satisfied` — every
  `(brief, need_index)` of the ACTIVE brief has an ACTIVE satisfaction
  whose asset exists; otherwise `unsatisfied` with the exact unmet
  indexes listed (never a count that hides which). The gate policy
  snapshot version bumps (`qa-gates/2`); old reports stay truthful
  under their recorded `qa-gates/1`.
- **Serving bytes**: one authenticated backend route streams asset
  bytes by asset id (operator session; correct content-type; no
  redirect to storage internals). The admin `<img>` goes through the
  admin's server side, never directly to the backend from the browser.

## 5. Read models and admin

- `work-items/{id}/media` read model: the ACTIVE brief's needs with,
  per need, the ACTIVE satisfaction (asset metadata incl. origin,
  alt_text, licensing, provenance attempt for AI) or an honest
  UNSATISFIED; plus the satisfaction/supersession history. Password/
  token/storage-key material never leaves by construction.
- Admin detail page gains a **Media** section: the needs coverage
  table (satisfied → thumbnail + metadata; unsatisfied → upload form +
  generate command + satisfy-from-library picker), state-gated per §2,
  with the same honest-empty and leak-test discipline as every other
  section.

## 6. Exit criteria

- [ ] media assets are durable, content-addressed, immutable,
      provenance-carrying (named uploader or generation attempt), with
      required alt text and licensing posture; bytes live only in the
      ContentOS-owned store (no Konsepthane access anywhere)
- [ ] needs are satisfied ONLY by explicit audited human commands
      binding need → asset (append-only history, guarded supersession,
      one ACTIVE binding per need); AI generation alone satisfies
      nothing
- [ ] the QA media gate reports satisfied/unsatisfied (with exact
      unmet indexes)/waived_by_human/not_applicable truthfully under a
      bumped policy version; old reports remain valid under theirs
- [ ] the AI boundary holds for images: purpose-tagged attempts with
      safe metadata only, no prompts/raw payloads persisted, no
      provider keys client-side, failure never an editorial decision
- [ ] satisfaction commands are state-bounded (never under a frozen
      terminal-review package); QA re-runs stay explicit
- [ ] read models/admin expose coverage with leak tests (no storage
      keys, no credential material); bytes served only through the
      authenticated route
- [ ] migration `0023` verified on real PostgreSQL (cycle over
      populated data + trigger negatives); deterministic tests
      throughout
- [ ] a media closure audit against these criteria

## 7. Implementation order (atomic, dependency-correct)

**Task M1 — media foundation.** Migration `0023` (both tables +
triggers), `MediaStore`, `contentos.media` service (asset
registration, satisfy/replace/unsatisfy with state bounds), unit
tests, real-PG verification.

**Task M2 — commands + read models.** Upload route (multipart,
bounded), satisfaction routes, the byte-streaming route, the
`work-items/{id}/media` read model, leak tests.

**Task M3 — QA gate v2.** `satisfied` + exact unmet indexes,
`qa-gates/2` snapshot, tests proving old reports stay under `1`.

**Task M4 — AI image generation.** `GenerationPurpose.MEDIA_IMAGE`,
image support in the provider boundary, `generate_media_image` task +
dispatch command, attempt metadata parity, tests (fake provider
deterministic-image).

**Task M5 — admin media surface.** Needs coverage section with
upload/generate/satisfy forms, state gating, tests.

**Task M6 — media closure audit** (docs-only, against §6).
