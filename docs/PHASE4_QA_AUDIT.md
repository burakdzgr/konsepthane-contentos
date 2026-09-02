# Phase 4 QA-Stage Closure Audit (Task 20)

Audit of the implemented QA stage (Phase 4 Tasks 16–19) against the
exit criteria of `PHASE4_QA_ARCHITECTURE.md` §7. Docs-only; no runtime
was changed by this audit.

Verification base: 1225 backend tests + 185 admin tests green through
`scripts/check.ps1`; schema head `0020`; real-infrastructure scripts run
against `pgvector/pgvector:pg16` (Task 16) and pg16 + `redis:7-alpine`
(Task 18 and the full-chain closure run); CI green on every QA-stage
commit.

## §7 exit-criteria matrix

| # | Criterion | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | QA validates the EXACT entry-pinned package; every gate yields an explicit result; absence is never a pass | **MET** | `QaService.resolve_package` requires the QA_REVIEW entry pins and refuses ambiguity (mismatched pins, forced revise pins, missing pins — all typed and unit-tested, incl. on real PG); every `qa-gates/1` gate emits `{result: ...}` with bounded detail; the read models render any malformed record as "UNKNOWN", never a pass. |
| 2 | Immutable versioned QaReport; append-only enforcement; idempotent re-runs; audited supersession; waivers append-only, audited, visible | **MET** | Migration `0020` (two-shape guarded trigger, single ACTIVE row, append-only waivers/events) verified on real PG incl. trigger negatives and the concurrent re-run race (exactly one ACTIVE); identical re-runs reuse by content_hash; changed re-runs supersede with an audited SYSTEM event; waivers require reasons, are QA_REVIEW-gated, and appear in every report listing. |
| 3 | The media gate is truthful (not_applicable / unsatisfied / waived_by_human) and blocking unless satisfied-by-vocabulary; link needs reported non-blocking | **MET** | `_media_needs` defaults to `unsatisfied` (blocking) whenever needs exist; a waiver produces `waived_by_human` with the needs count still visible and the waiver ids attached; `internal_link_needs` reports `none|pending` with `blocking: false`. Unit + real-PG + real-Redis verified (the terminal advance required the audited waiver). |
| 4 | Provenance re-proof (ADR 0007) and writer-envelope recheck run from durable rows; failures produce not_ready, never silence | **MET** | `_provenance_chain` requires ≥1 evidence link per used claim with broken claim ids reported (fail-closed unit test); `_writer_envelope` reuses `recompute_writer_envelope` verbatim; `_content_safety` re-runs the deterministic ban; `_review_currency` checks the review's recomputation flag and scope hashes — each failure is a `fail` result and a `not_ready` outcome. |
| 5 | QA_REVIEW → AWAITING_HUMAN_REVIEW only via the SYSTEM artifact gate on a ready report; rework via the routing foundation with a bounded choice; REJECTED human-only; BLOCKED untouched; execution failure never an outcome | **MET** | `run_qa_gates` TX B transitions ONLY on `ready_for_human_review` with `{qa_report_id, editorial_review_id, content_draft_id, content_hash}` pinned (real-PG+Redis verified incl. redelivery reuse via the pinned entry); `request-rework` from QA_REVIEW offers exactly `{drafting, editing}` through `PERMITTED_RESPONSIBLE_STATES` (arbitrary targets impossible — unit-tested); BLOCKED semantics unchanged; execution errors are task failures, and `QaOutcome` contains no failure or approval label (asserted). |
| 6 | No model involvement, no provider spend, no approval surface, no publication boundary; APPROVED unreachable by design | **MET** | The `contentos.qa` package imports no provider/AI-boundary module; no purpose widening exists in 0020 (asserted in the migration content test alongside the absence of 'approved'/'rejected' vocabulary); `TestNoGenericEndpoints` still bans approve/publish routes; the admin AWAITING_HUMAN_REVIEW view explicitly states the approval surface does not exist and renders no approve control (tested). |
| 7 | Operator inspects reports/gates/waivers via read models/admin with leak tests; deterministic tests; real-PG (+ broker) verification; then this audit and the Phase 4 closure audit | **MET** | `work-items/{id}/qa-reports` + `qa-reports/{id}` read models and the admin QA section/report page with leak tests on both sides; all QA tests are deterministic (no fake provider even needed); real-PG (Task 16) and real-PG+Redis (Task 18) verifications passed; this document is the Task 20 audit and `PHASE4_CLOSURE_AUDIT.md` is Task 21. |

**Result: 7/7 criteria MET. The QA stage is COMPLETE per §7.**

## Honest limitations

### Deferred by design (later phases — feature work)

- **The media gate cannot yet be satisfied, only waived.** A real media
  pipeline (asset intake, rights, eligibility) replaces the waiver path
  via a new gate-policy version — roadmap work, stated in the
  architecture.
- **Internal-link needs are non-blocking** until the Konsepthane
  Publishing API integration owns publish-time linking.
- **AWAITING_HUMAN_REVIEW has no exit surface.** Deliberate: APPROVED
  requires authenticated, authorized human reviewers (ADR 0004) — the
  governance phase; CHANGES_REQUESTED/REJECTED from that state also
  await that phase's command surface (the WorkflowService transitions
  exist; no API route exposes them from AWAITING_HUMAN_REVIEW yet).

### Production-readiness backlog (separate from feature completion)

- The Writer/Editor-stage backlog carries over unchanged (single-
  operator boundary; scripted per-task real-infrastructure verification
  rather than a CI lane; capped unpaged listings; no spend controls —
  though QA itself spends nothing).
- Waivers are work-item-scoped and permanent (no revocation command);
  a revocation would be a new audited append, not an edit — backlog.

## Disposition

The QA stage is closed. `PHASE4_CLOSURE_AUDIT.md` (Task 21) closes
Phase 4 itself.
