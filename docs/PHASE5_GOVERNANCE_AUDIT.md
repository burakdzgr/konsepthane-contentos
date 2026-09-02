# Phase 5 Governance Audit (Task G6)

Phase 5 — Governance (authentication, authorization, named human
decisions) — is audited here against the exit criteria of
`PHASE5_GOVERNANCE_ARCHITECTURE.md` §6, closing the phase. The phase's
goal: `APPROVED` becomes real — reachable only through a named,
authenticated, authorized human whose decision is an append-only,
package-pinned record.

Docs-only; no runtime was changed by this audit.

## What Phase 5 shipped

| Task | Content | Verified by |
| --- | --- | --- |
| G1 | Auth foundation: migration `0021` (users / user_events / auth_sessions + triggers), `contentos.auth` (argon2id, opaque hashed sessions, audited management CLI), `require_user/require_operator/require_reviewer`, login/logout/me, operator guard on every pipeline router, real-login test harnesses | 13 unit tests + `verify_pg_auth.py` on real PG 16 |
| G2 | Admin authentication: `/login` (the only open page, carrying Foundation Status), edge middleware, HttpOnly SameSite=Lax cookie, Bearer forwarding + 401→expired redirect, sign-out; smoke does a REAL CLI-provision → login → me round trip | 12 admin tests + upgraded `scripts/smoke.ps1` |
| G3 | Decision records + workflow wiring: migration `0022` (`human_decisions` append-only events + `editorial_workflow_events.actor_user_id`), DecisionService gates, the four reviewer routes, named actors on operator transitions | 10 unit tests + `verify_pg_decisions.py` on real PG 16 + Redis |
| G4 | Decision read models + admin decision surface: decisions read model with reviewer names + hash-bound status, actor names in event views (NULL → UNKNOWN), the admin decision surface with role gating and validity badges, identity chrome | 3 backend + 17 admin tests |
| G5 | Approval validity primitives: `approval_is_current`, the `require_current_approval` guard (`StaleApprovalError`), `expire_stale_approval` SCHEDULED → APPROVAL_EXPIRED wiring | 4 unit tests |

Schema head: `0022`. Suite at closure: 1256 backend + 216 admin tests;
CI green on every commit of the phase.

## §6 exit criteria — verdicts

1. **Every `/internal/*` route (except health) and every admin page
   (except login) requires an authenticated session; typed 401/403; no
   credential/token material beyond the designed hashes.** **MET.**
   `api/app.py` applies `require_operator` to all four pipeline routers
   and `require_reviewer` to the decisions router; only health and
   `/internal/auth/login` are open (asserted in `test_auth.py`:
   unauthenticated 401 with `WWW-Authenticate`, open health, typed
   403). Admin: edge middleware redirects every cookie-less page except
   `/login`, `/api/health`, static assets. Leak posture: the raw
   session token exists exactly once (login response → HttpOnly
   cookie); at rest only `token_hash` (sha256) and argon2id
   `password_hash` exist (`test_auth.py` asserts the raw token is
   never stored); the decisions read model joins `users` for names
   only, and `test_decisions.py` asserts no "password"/"token"
   substring in the read output; admin tests assert the internal
   backend URL never renders.

2. **Users provisioned/rotated/deactivated only through audited
   commands; frozen role vocabulary.** **MET.** No self-registration;
   `python -m contentos.auth.cli` (create-user / set-password /
   set-roles / set-active) writes a `user_events` audit row with a
   required reason for every change (passwords via env/prompt, never
   argv); roles are CHECK-constrained to {operator, reviewer}; identity
   fields are immutable and DELETE forbidden by trigger (negative-tested
   on real PG in `verify_pg_auth.py`).

3. **AWAITING_HUMAN_REVIEW exits exist ONLY as reviewer commands with
   append-only pinned HumanDecision records, artifact-gated
   transitions, decision id pinned.** **MET.** The three exits
   (approve / request-changes / reject-package) plus revoke-approval
   are the reviewer-guarded router's only routes, each following
   record → commit → WorkflowService transition (with
   `decision_artifact_refs` pins + `actor_user_id`) → commit.
   `human_decisions` is append-only by trigger (PG-verified);
   `test_no_publication_command` pins the complete approval surface to
   exactly the two governed routes and still bans
   publish/schedule/pinterest/release shapes.

4. **Approve validates the ACTIVE ready QA report + hash match; a
   worker/AI identity cannot reach any decision command.** **MET.**
   `DecisionService.record_approval` requires the ACTIVE
   `ready_for_human_review` report covering the ACTIVE draft AND the
   entry-pinned content hash to still equal the ACTIVE draft hash
   ("a changed package cannot ride an old QA pass" — tested with a 409
   and zero decision rows). Decisions require an authenticated session
   holding the REVIEWER role; workers and AI calls have no session by
   construction, and `_record` re-checks active-reviewer status so a
   decision row can never carry a non-reviewer identity
   (`test_operator_only_user_cannot_decide`).

5. **Request-changes/revoke route through the responsible-state
   foundation; REJECTED requires a reason; revocation references,
   never edits.** **MET.** `PERMITTED_RESPONSIBLE_STATES` gained
   AWAITING_HUMAN_REVIEW and APPROVED contexts ({DRAFTING, EDITING,
   QA_REVIEW}, bounded three-way choice, default DRAFTING — bounded in
   the admin form too); every decision requires a reason (schema +
   service); `approval_revoked` is a NEW record with a self-FK
   `revokes_decision_id` under the CHECK
   `(decision='approval_revoked') = (revokes_decision_id IS NOT NULL)`
   (tested; the approval row is untouched).

6. **Approval validity derivable and hash-bound; APPROVAL_EXPIRED
   wiring exists without being reachable.** **MET.**
   `approval_is_current` / `approval_status` derive the latest
   unrevoked approval and bind it to the ACTIVE draft hash;
   `require_current_approval` is the typed guard
   (`StaleApprovalError`) every future consumer must pass;
   `expire_stale_approval` wires SCHEDULED → APPROVAL_EXPIRED as a
   SYSTEM detection (actor_user_id honestly NULL, hashes pinned),
   refuses to run outside SCHEDULED, and NEVER expires a still-current
   approval. No route or task exposes it: SCHEDULED stays unreachable
   until the publishing phase (`APPROVED → SCHEDULED` is in the
   canonical matrix but no code path invokes it).

7. **Workflow events record `actor_user_id`; historical NULLs render
   UNKNOWN.** **MET.** All human-driven transitions (decisions,
   submit-draft, accept-review, request-rework, resolve) thread the
   authenticated user id into the event; the read model resolves it to
   a display name; NULL stays NULL through the API and the admin
   renders `operator · UNKNOWN` for pre-governance operator events
   (system events stay `system`) — tested at both layers.

8. **Read models/admin expose decisions and validity with leak tests;
   deterministic tests + real-PG verification.** **MET.** GET
   `work-items/{id}/decisions` (events exactly as recorded + derived
   status); the admin "Human decisions" section shows the history with
   pins, the approval record with an honest `current | stale` badge,
   reviewer-gated decision forms and a truthful non-reviewer note.
   Real-infrastructure proof: `verify_pg_decisions.py` drove the FULL
   chain (research → … → AWAITING_HUMAN_REVIEW) on pgvector/pg16 +
   redis:7 through migration `0022`, then a named approval → APPROVED
   with pins + actor, revocation → CHANGES_REQUESTED via qa_review,
   and the append-only trigger negatives. G4/G5 added no migrations;
   their SQLite drift simulations (direct hash mutation) are documented
   test-only knobs for what PG immutability triggers make impossible —
   on real PG staleness can only arise from a NEW ACTIVE draft version,
   which the same `approval_status` derivation covers.

## Phase 4's "no fake approval" invariant — correctly retired

Phase 4 closed with "no approval surface exists" as a binding
invariant. Phase 5 retires it the intended way: approval now exists
ONLY as the two governed reviewer routes producing named, append-only,
hash-pinned decision records behind the authentication boundary — the
Phase 4 ban test evolved into an exact-surface pin
(`test_no_publication_command` asserts the approval path set equals
exactly those two routes). ADR 0004 is now mechanically enforced: an
AI/worker identity cannot hold a session, cannot hold the reviewer
role, and cannot produce a decision row (defense in depth at the API
guard AND inside `DecisionService._record`).

## Consolidated production-readiness backlog (NOT feature gaps)

Carried forward, deduplicated with the Phase 4 backlog:

1. **Real-infrastructure CI lane** for the per-task PG/Redis
   verification scripts (incl. `verify_pg_full_chain.py` and
   `verify_pg_decisions.py` as end-to-end smokes).
2. **Session hygiene**: no server-side session cleanup job (expired
   rows accumulate); consider a pruning command. Login has no
   rate-limiting/lockout (single-tenant internal tool — accepted for
   now, required before any exposure).
3. **Provider spend controls** (quotas/budgets) beyond bounded retries.
4. **Unpaged capped listings** in draft/review/report/decision read
   models.
5. **Admin manual-draft JSON textarea** → structured editor (UX only).
6. **Secrets management** for production deployment (compose env vars
   today; a real secret store before production).

## Verdict

Phase 5 — Governance — is **CLOSED**: 8/8 exit criteria MET, the
Phase 4 approval invariant correctly retired, real-PG verification on
every migration of the phase. The next phase per the roadmap is Media
(QA `media_needs` already blocks honestly awaiting it), then
Publishing — which must consume `require_current_approval` and the
Publishing API contract (versioned + authenticated + idempotent; the
open integration questions in `docs/memory/CURRENT_STATE.md`).
