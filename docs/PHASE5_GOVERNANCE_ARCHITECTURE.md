# Phase 5 Governance Architecture (design only)

Phase 4 parks validated packages at `AWAITING_HUMAN_REVIEW` with no
exit surface — deliberately, because ADR 0004 binds: **APPROVED
requires a named authorized human, and AI or worker identity can never
satisfy that gate.** Phase 5 builds exactly what that sentence needs
and nothing publishing-shaped: authentication, named authorized
reviewers, the decision surface (approve / request changes / reject),
durable decision records pinning the exact package, and
approval-validity semantics. `SCHEDULED`/`PUBLISHING` remain the
publishing phase behind the future Konsepthane Publishing API.

Every Phase 2–4 rule stays binding: WorkflowService-only transitions
behind artifact gates; append-only audit; typed fail-closed errors;
truthful UNKNOWN; no raw secrets in durable rows or responses.

## 1. Purpose and design decisions

**Decision — authentication is platform-wide, not approval-scoped.**
The recorded production-readiness gap is the unauthenticated
`/internal/*` + admin boundary. Bolting identity onto one command while
the rest stays open would make the approval theater: anyone who can
reach the API could also rewrite the inputs. Phase 5 therefore puts THE
WHOLE admin and internal API behind authentication first, then builds
the decision surface on top of real identities. (Deployment-level
network isolation remains as defense in depth, no longer as the only
boundary.)

**Decision — two roles, explicit and small: `operator` and
`reviewer`.** Operators drive the pipeline (everything Phase 3/4
exposed). Reviewers may additionally decide at
`AWAITING_HUMAN_REVIEW`. A user can hold both roles. No permission
matrix beyond this — the vocabulary can grow later; inventing
enterprise RBAC now would be scope creep.

**Decision — decisions are append-only records pinning the EXACT
package, and the workflow transition is gated on the record.** The
artifact-gate pattern again: durable `HumanDecision` row (reviewer id,
decision, reason, pins incl. content hashes) → commit → WorkflowService
transition with the decision id pinned → commit. A decision can never
be edited; a changed mind is a NEW decision after the state loops back.

**Decision — approval validity is hash-bound.** An approval pins
`content_hash` (draft), `qa_report_id`, and `editorial_review_id`. The
approval is VALID only while the ACTIVE draft's hash equals the pinned
hash. Phase 5 ships the validity CHECK primitive
(`approval_is_current`) and the `APPROVAL_EXPIRED` transition wiring
for later phases; the scheduling-time enforcement belongs to the
publishing phase that consumes it.

**Decision — credentials are boring and standard.** Argon2id password
hashes in an append-only-ish `users` table (credential rotation is an
UPDATE limited to credential fields by trigger — identity fields
immutable), server-side opaque sessions (random token, hashed at rest,
expiring, revocable), cookie-based login in the admin (HttpOnly,
SameSite=Lax, Secure in production), and the admin's server-side
backend client forwarding the session subject to the internal API via a
signed internal header. No OAuth/OIDC in v1 (single-tenant internal
tool; an IdP can replace the credential store later without touching
the decision model). No self-registration: users are provisioned by a
CLI/management command with an audited event.

## 2. Workflow wiring

From `AWAITING_HUMAN_REVIEW` (matrix already canonical):

- `→ APPROVED`: reviewer-only command `approve`; requires the ACTIVE
  QA report to be `ready_for_human_review` and to cover the ACTIVE
  draft (the same pins the entry event carries); artifact refs pin
  `{human_decision_id, qa_report_id, content_draft_id, content_hash,
  reviewer_id}`; actor origin OPERATOR (the enum stays frozen; the
  named identity lives in the decision record and the new
  `actor_user_id` event column, §3).
- `→ CHANGES_REQUESTED`: reviewer command `request-changes` through the
  Task 6 routing foundation; new
  `PERMITTED_RESPONSIBLE_STATES[AWAITING_HUMAN_REVIEW] =
  {DRAFTING, EDITING, QA_REVIEW}` (bounded choice, default DRAFTING);
  decision record pinned.
- `→ REJECTED`: reviewer command `reject` with a required reason and a
  decision record; existing REJECTED semantics unchanged.
- `APPROVED → CHANGES_REQUESTED` (canonical row): reviewer command
  `revoke-approval` — responsible vocabulary
  `PERMITTED_RESPONSIBLE_STATES[APPROVED] = {DRAFTING, EDITING,
  QA_REVIEW}`; the approval record is never deleted, the revocation is
  a new decision record referencing it.
- `APPROVED → SCHEDULED` is NOT built (publishing phase).

## 3. Data model (implementation-ready; migrations in the tasks)

**`users`**: `id UUID`, `username` (unique, immutable), `display_name`,
`password_hash` (argon2id), `roles` JSONB array from the frozen
vocabulary {operator, reviewer}, `is_active`, `created_at`,
`credentials_rotated_at`. Trigger: DELETE forbidden; UPDATE may touch
only `password_hash`, `roles`, `is_active`,
`credentials_rotated_at` (identity immutable).
**`user_events`**: append-only audit of provisioning/role/activation
changes (actor, action, reason).

**`auth_sessions`**: `id UUID`, `user_id` RESTRICT, `token_hash`
(sha256 of the opaque token; the token itself is never stored),
`created_at`, `expires_at`, `revoked_at NULL` (the one mutable field,
one-shot). Lookup by token hash; sliding expiry NOT used (fixed TTL,
re-login).

**`human_decisions`** (append-only, the governance artifact):
`id UUID`, `work_item_id` RESTRICT, `reviewer_user_id → users`
RESTRICT, `decision` CHECK {approved, changes_requested, rejected,
approval_revoked}, `reason` (required), `qa_report_id` RESTRICT,
`content_draft_id` RESTRICT, `editorial_review_id` RESTRICT,
`content_hash` (the draft hash at decision time), `revokes_decision_id
NULL` (self-FK for approval_revoked), `request_id`, `created_at`.
No status/supersession — decisions are events, not stateful artifacts;
"the current approval" is derived: the latest `approved` decision not
referenced by a later `approval_revoked` AND with
`content_hash == ACTIVE draft hash` (the validity primitive).

**`editorial_workflow_events.actor_user_id`** (additive nullable column
+ index, new migration): the authenticated user behind OPERATOR-actor
transitions from now on; historical rows stay NULL (honest UNKNOWN).

## 4. Authentication mechanics

- Backend: `contentos.auth` module — password hashing (argon2id via
  `argon2-cffi`), session issue/verify/revoke service, FastAPI
  dependency `require_user(role=...)` applied to every
  `/internal/*` router (health stays open); typed 401/403; the
  current user id flows into commands (audit) exactly like
  `request_id` does today.
- Admin: `/login` page (server action → backend `/internal/auth/login`
  → sets the HttpOnly cookie), middleware-guarded routes, `/logout`;
  the admin's server-side fetch layer forwards the session token
  header on every backend call. No credentials or tokens ever reach
  browser JS beyond the HttpOnly cookie.
- Tests never weaken the boundary: the API test harness logs in
  through the real login flow with seeded users.

## 5. Read models and admin

- The AWAITING_HUMAN_REVIEW view becomes the DECISION view for
  reviewers: full pinned package (draft body, review findings, QA
  gates incl. waivers) + approve / request-changes(bounded choice) /
  reject forms with required reasons; operators without the reviewer
  role see the package read-only with an honest "you are not an
  authorized reviewer" note.
- `work-items/{id}/decisions` + decision detail read models (reviewer
  display name shown; password/token material never leaves the auth
  tables by construction).
- APPROVED items show the approval record, its validity
  (`current | stale`), and the revoke command.

## 6. Exit criteria

- [ ] every `/internal/*` route (except health) and every admin page
      (except login) requires an authenticated session; typed 401/403;
      no credential/token material in logs, responses, or durable
      rows beyond the designed hashes
- [ ] users are provisioned/rotated/deactivated only through audited
      commands; roles come from the frozen vocabulary
- [ ] AWAITING_HUMAN_REVIEW exits exist ONLY as reviewer commands
      producing append-only HumanDecision records pinning the exact
      package, with the WorkflowService transition gated on the durable
      record (artifact-gate pattern) and the decision id pinned in the
      event
- [ ] approve validates the ACTIVE ready QA report + hash match; a
      worker/AI identity cannot reach any decision command (no session,
      no decision — enforced by construction and tested)
- [ ] request-changes/revoke route through the responsible-state
      foundation with the new bounded vocabularies; REJECTED requires a
      reason; approval revocation references, never edits, the approval
- [ ] approval validity is derivable (`approval_is_current`) and
      hash-bound; APPROVAL_EXPIRED wiring exists for the publishing
      phase without being reachable yet
- [ ] workflow events record `actor_user_id` for authenticated actors;
      historical NULLs render as UNKNOWN
- [ ] read models/admin expose decisions and validity with leak tests;
      deterministic tests + real-PG verification; then a governance
      audit against these criteria

## 7. Implementation order (atomic, dependency-correct)

**Task G1 — auth foundation.** Migration (users/user_events/
auth_sessions + triggers); `contentos.auth` (hashing, session service,
provisioning commands via a management CLI entrypoint); FastAPI
dependency + router protection; login/logout endpoints; harness login
support; real-PG verification.

**Task G2 — admin authentication.** Login page, cookie/session
middleware, token forwarding in the server-side clients, logout,
role-aware chrome; admin tests updated to authenticate.

**Task G3 — decision records + workflow wiring.** Migration
(human_decisions + workflow-event `actor_user_id`); decision service
(approve/request-changes/reject/revoke with the full gates);
`PERMITTED_RESPONSIBLE_STATES` extensions; commands; real-PG
verification of the approve artifact gate and revocation.

**Task G4 — decision read models + admin decision surface.**

**Task G5 — approval validity primitives.** `approval_is_current`,
staleness surfacing in read models, APPROVAL_EXPIRED wiring (unreached
until publishing).

**Task G6 — governance audit** (docs-only, against §6), including
re-verifying that Phase 4's "no fake approval" invariant is now
correctly retired by real approvals.
