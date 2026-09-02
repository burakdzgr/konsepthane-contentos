# Phase 7 Publishing Audit (Task P5)

Phase 7 — Publishing (the ContentOS side) — is audited here against the
exit criteria of `PHASE7_PUBLISHING_ARCHITECTURE.md` §6, closing the
phase. The phase's goal: the exact approved package moves APPROVED →
SCHEDULED → PUBLISHING → PUBLISHED behind artifact gates and an
idempotent transport boundary — while the LIVE integration stays
explicitly blocked on the unresolved operator inputs.

Docs-only; no runtime was changed by this audit.

## What Phase 7 shipped

| Task | Content | Verified by |
| --- | --- | --- |
| P1 | Publication package foundation: migration `0025` (immutable hashed packages + append-only attempt facts), `PublicationAssembler` under the approval guard | 4 unit tests + `verify_pg_publishing.py` on real PG 16 |
| P2 | Scheduling + expiry resolution: `schedule_publication`, `resolve_approval_expired` (derived target), three operator routes, the evolved route-space pins | 6 unit tests |
| P3 | Transport + publish task: `PublishingTransport` protocol, deterministic fake, configuration-gated HTTP skeleton, the 11th editorial task, the governed publish command | 5 unit tests + `verify_pg_publish_task.py` on real PG 16 + Redis |
| P4 | Read models + admin publication surface with leak posture | 3 backend + 5 admin tests |

Schema head: `0025`. Suite at closure: 1291 backend + 232 admin tests;
CI green on every commit of the phase.

## §6 exit criteria — verdicts

1. **Packages assembled ONLY from the pinned approved artifacts under a
   current approval; deterministic, hashed, immutable, versioned; unmet
   unwaived media needs refuse assembly.** **MET.**
   `PublicationAssembler.assemble` runs `require_current_approval`
   FIRST (a stale approval raises typed and leaves zero rows), resolves
   the APPROVED package with ready-outcome and approved-hash equality
   re-checks, projects the draft structure VERBATIM plus the media
   manifest (waived unmet indexes LISTED, never hidden; unmet unwaived
   → typed refusal), canonical-JSON hashes it, and converges identical
   content on the existing row (per-work-item UNIQUE `package_hash`,
   append-only trigger — both PG-verified).

2. **APPROVED → SCHEDULED → PUBLISHING → PUBLISHED advance ONLY via
   WorkflowService behind artifact gates; humans schedule, machines
   execute; every pin resolvable.** **MET.** Scheduling is an OPERATOR
   command (named actor recorded) gated on the current approval AND an
   explicit package whose content hash equals the approved hash;
   PUBLISHING/PUBLISHED are SYSTEM transitions gated on the durable
   dispatch results, each pinning {publication_package_id,
   package_hash, remote_publication_ref}; redelivery guards demand the
   durable history pin the exact package
   (`WorkflowHistoryConflictError` otherwise).

3. **A stale approval at scheduling or publish time surfaces via
   APPROVAL_EXPIRED; the expired state has governed resolution with a
   deterministic target.** **MET.** `schedule_publication` refuses
   stale approvals with the truthful hash message; the publish task
   re-checks and fires `expire_stale_approval` INSTEAD of publishing
   (zero dispatches — tested); `resolve_approval_expired` DERIVES the
   target (AWAITING_HUMAN_REVIEW with full re-entry pins while the
   ACTIVE ready report covers the ACTIVE draft — proven by an
   immediate fresh approval over the carried pins — else QA_REVIEW
   with the review/draft pins), and the caller can never choose.

4. **Publishing failures are durable attempts with sanitized error
   classes; bounded retries then BLOCKED; REJECTED unreachable.**
   **MET.** Every dispatch outcome is committed as a
   `publication_attempt` BEFORE any transition; the status vocabulary
   is CHECK-bounded and contains no editorial words; transient kinds
   retry within the Celery bound; terminal kinds move SYSTEM →
   BLOCKED with the truthful reason (tested: `rejected_by_api` blocks
   with `rejected_reason` still None). No publishing code path can
   reach REJECTED.

5. **Dispatch is idempotent end to end.** **MET.** The idempotency key
   is derived from `(work_item_id, package_hash)` and stored on every
   attempt; per-package attempt numbers are UNIQUE; a successful
   attempt's remote reference is reused on redelivery with exactly one
   transport call (unit- and PG/Redis-verified); the key crosses the
   boundary so an idempotent Publishing API cannot double-publish
   either.

6. **The transport boundary holds.** **MET.** No Konsepthane
   DB/filesystem access exists anywhere; `publishing_api_url`/`_key`
   default to None with NO default endpoint; the HTTP adapter raises a
   typed `TransportConfigurationError` unconfigured, and the publish
   task resolves the transport BEFORE any state moves so an
   unconfigured boundary is a truthful no-op with the item still
   SCHEDULED (tested); the key lives only in server settings
   (SecretStr); media bytes cross only through the bounded reader;
   the success⇔remote-ref invariant is enforced in the DTO AND the DB
   CHECK.

7. **Read models/admin expose packages and attempts with leak
   tests.** **MET.** The publication page carries summaries (the
   approved body never ships to the admin — asserted by content),
   pins, hashes, sanitized attempt classes and remote refs, and the
   tri-state approval currency (honest null with no package); tests
   assert no `publishing_api`/key material and no backend URL in any
   response or page.

8. **Migration `0025` verified on real PostgreSQL; deterministic tests
   with the fake transport; the LIVE integration remains blocked.**
   **MET.** `verify_pg_publishing.py` (0025 cycle over a populated
   approved chain, real assembly + idempotent reuse, all trigger/CHECK
   negatives) and `verify_pg_publish_task.py` (schedule + publish over
   the REAL broker with envelope inspection, durable attempt → SYSTEM
   PUBLISHED, redelivery reuse) both passed. The three open inputs —
   the Publishing API contract, the service auth method, the
   production owner — remain explicitly unresolved in
   `docs/memory/CURRENT_STATE.md`, and nothing can dispatch anywhere
   real without them.

9. **A publishing closure audit against these criteria.** **MET** —
   this document.

## The no-publication invariant — retired the intended way

From Phase 3 on, `test_no_publication_command` banned every
publish/schedule-shaped route. Phase 7 retires the ban exactly as the
approval ban was retired in Phase 5: the test now PINS the route space
— scheduling exists only as
`/work-items/{id}/schedule-publication` (approval- and
package-gated), publication execution only as
`/work-items/{id}/publish` (whose worker re-checks the approval), and
`pinterest`/`release` shapes stay banned. Publication is now a
governed capability, not a gap.

## Production-readiness backlog additions (NOT feature gaps)

1. **A real scheduler**: SCHEDULED → publish is operator-triggered in
   v1; time-based scheduling (publish-at) needs a durable schedule
   field + a beat/cron trigger — deliberately deferred until the
   Publishing API contract lands.
2. **Publication attempt paging** in the read model (unbounded listing
   today; bounded by the retry cap in practice).
3. Carried forward unchanged: real-infra CI lane (now incl. the two
   publishing verification scripts), session hygiene, spend controls,
   capped listings, secrets management, production media store.

## Addendum (2026-09-02, post-closure): contract accepted, client live-ready

The operator supplied and accepted the **Publishing API v1 contract**
(`docs/PUBLISHING_API_CONTRACT.md`), resolving the contract, the auth
method (Bearer service token) and the ownership declaration
(Konsepthane main backend). `HttpPublishingTransport` was upgraded
from skeleton to contract-complete — content-addressed
`PUT /v1/media/{sha256}` before the idempotent
`POST /v1/publications` with the correlation header, 429 treated as
transient per the contract note — and proven two ways: a
contract-faithful in-process double (unit suite) and a REAL socket
HTTP server on real PG + Redis driven by the real publish task
(media PUT with server-side SHA recomputation → PUBLISHED →
wire-level idempotent redelivery). What remains before production
publishing: the Konsepthane backend implements the receiving side in
its own repository, and the operator supplies the deployed
`CONTENTOS_PUBLISHING_API_URL` + `CONTENTOS_PUBLISHING_API_KEY`.

## Verdict

Phase 7 — Publishing (ContentOS side) — is **CLOSED**: 9/9 exit
criteria MET, both real-infrastructure verifications passed, and the
full loop now runs research → … → APPROVED → SCHEDULED → PUBLISHING →
PUBLISHED against a fake transport. The LIVE integration is blocked
on three operator inputs (Publishing API contract, service auth,
production owner). Next per the roadmap: Scheduling/Distribution
(Pinterest) and Analytics — both blocked on their own external inputs
— or the production-readiness backlog, which needs none.
