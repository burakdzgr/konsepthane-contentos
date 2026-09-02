# Phase 4 Editor-Stage Closure Audit (Task 15)

Audit of the implemented Editor stage (Phase 4 Tasks 10–14) against the
exit criteria of `PHASE4_EDITOR_ARCHITECTURE.md` §11. Docs-only; no
runtime was changed by this audit. Evidence cites actual code, tests,
and real-infrastructure verification runs at the audited HEAD.

Verification base: 1192 backend tests + 171 admin tests green through
`scripts/check.ps1`; schema head `0019`; real-infrastructure scripts run
against `pgvector/pgvector:pg16` (Task 10) and pg16 + `redis:7-alpine`
(Task 13); CI green on every Editor-stage commit.

## §11 exit-criteria matrix

| # | Criterion | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Review generation requires the exact EDITING entry pin and an ACTIVE draft over the exact ACCEPTED brief (typed failures, zero provider spend) | **MET** | `ReviewService.resolve_reviewable_draft` + the locked gates in `create_review`: EDITING required, the validated EDITING entry event must PIN a draft, the pin must equal the ACTIVE draft (mismatch is a typed conflict — never a guess), and the brief must still be ACCEPTED_FOR_DRAFTING. `test_editor_generation.py::test_preconditions_cost_zero_provider_calls` asserts zero invocations; `test_reviews.py::TestPreconditions` covers the missing-pin and wrong-state paths; the not-in-EDITING Celery delivery is a terminal FAILURE with zero invocations. (The superseded-brief branch is enforced in code but has no dedicated unit test — recorded under limitations.) |
| 2 | Immutable versioned EditorialReview; append-only enforcement; one review per SUCCEEDED attempt; audited supersession | **MET** | Migration `0019`: the proven two-shape guarded trigger (content immutable; `active→superseded` then one-shot replacement pointer; DELETE forbidden), append-only findings/status-event triggers, `UNIQUE(generation_attempt_id)`, `UNIQUE(work_item_id, version)`, partial-unique ACTIVE row. Real-PG verification passed the migration cycle over populated data, all trigger negatives, the concurrent supersession race (exactly one ACTIVE), and the audit-protecting downgrade refusal. |
| 3 | Deterministic integrity gates recompute the Writer envelope and fail closed; drift emits deterministic findings or typed errors | **MET** | `reviews/integrity.py::recompute_writer_envelope` re-proves structure contract, claim-reference integrity (body ↔ relational usages ↔ brief claims), and handling coverage against the manifest REBUILT from current rows; each failed check is one BLOCKING finding with origin `deterministic` under the service-reserved `drift-` prefix (forgery rejected on both the service and engine paths). `integrity_gate_result` records `writer_envelope_recomputed: True` with per-check outcomes — confirmed on real PG. Hard impossibilities (missing pin, ambiguous state) stay typed errors. |
| 4 | Model output is findings-only in a strict schema; verdict computed by the versioned deterministic policy; findings are policy signals, never Evidence, never new facts | **MET** | `editor-review/1` (`extra=forbid`) has NO verdict field — smuggling is schema-rejected (`test_verdict_smuggling_is_schema_rejected`); `editor-verdict/1` computes pass/revise from validated severities with the snapshot persisted per review; findings live in their own tables, never touch the ADR 0007 chain, and the template forbids external-knowledge findings. There is no `reject` verdict anywhere in the vocabulary. |
| 5 | Execution failure is never a verdict; the item stays EDITING; VALIDATION_FAILED terminal with zero review rows | **MET** | Unknown anchors/reserved keys ⇒ durable `VALIDATION_FAILED` attempt (`domain_validation`) with ZERO review rows; timeouts retry within the bounded DOMAIN policy with failed attempts committed first, then terminal — the work item remains EDITING in every case (unit + real-PG failure-truthfulness step). REJECTED remains an exclusively human transition. |
| 6 | Idempotent generation; explicit retry_number+1 regeneration; redelivery-safe reuse; typed incomplete-materialization recovery | **MET** | Same identity reuses the durable attempt+review with zero provider calls; the Celery redelivery guard returns `reused` when the ACTIVE review already covers the ACTIVE draft (real-Redis verified with a sentinel provider at zero invocations); regeneration is the same command with `retry_number+1` and a REQUIRED supersede reason over an active review, fully audited; `IncompleteReviewMaterializationError` recovery only via explicit `retry_number+1`; `ReviewGenerationMaterializationError` keeps the attempt's real SUCCEEDED status. |
| 7 | EDITING → QA_REVIEW only via the operator accept-review command gated on a durable pass review pinning the ACTIVE draft; CHANGES_REQUESTED routing kept; REJECTED human-only | **MET** | `accept-review` validates ACTIVE review + ACTIVE draft + pin equality + verdict `pass`, then performs the OPERATOR WorkflowService transition with `{editorial_review_id, content_draft_id, review_verdict, content_hash}` pinned (revise/missing ⇒ truthful 409; verified on real PG). `request-rework` keeps the Task 6 responsible-state routing and now pins the ACTIVE review. The Editor task itself NEVER transitions workflow. |
| 8 | Writer regeneration after review-driven rework receives the bounded findings input | **MET** | The rework CHANGES_REQUESTED entry pins the review; when the DRAFTING cycle was entered from CHANGES_REQUESTED, `WriterEngine` projects the pinned review's findings as bounded `editorial_findings` (ids + bounded safe text only) with `rework_review_id` in input_refs, and template `writer-draft/2` carries the binding rework rule ("findings are instructions, never a fact source"). `test_rework_regeneration_receives_review_findings` closes the loop end-to-end. |
| 9 | Operator inspects reviews, findings, integrity results, attempts, failures via read models/admin with leak tests | **MET** | `work-items/{id}/reviews` + `reviews/{id}` read models (findings with block AND claim anchors resolved, integrity per-check record, policy snapshots, supersession audit, editor attempt metadata incl. failed attempts); admin Reviews section (state-gated commands, honest revise helper) + read-only review detail page cross-linked to the exact reviewed draft; UNKNOWN rendered as UNKNOWN; leak tests on both sides (FORBIDDEN_STRINGS scan, internal-URL assertions). |
| 10 | Deterministic fake-provider tests; no live calls in gates; real-PG (+ broker) verification; then this audit | **MET** | All Editor tests run on `FakeStructuredProvider`; gates/CI make no live provider calls; `verify_pg_reviews.py` (Task 10) and `verify_pg_editor.py` (Task 13: dispatch-after-commit, failure truthfulness, broker message inspection, redelivery reuse, accept-review gate) both fully passed on real containers. This document is the Task 15 audit. |

**Result: 10/10 criteria MET. The Editor stage is COMPLETE per §11.**

## Honest limitations

### Deferred by design (QA stage / later phases — feature work)

- **QA does not exist yet.** `accept-review` moves items into
  `QA_REVIEW`, where nothing runs; the QA architecture (next task)
  must define the stage — including the `WORKFLOW.md` "eligible media
  set" entry gate truthfully (no media pipeline exists: an explicit
  UNKNOWN/failing gate, never a silent pass) — and the artifact-gated
  advance to `AWAITING_HUMAN_REVIEW` that closes Phase 4.
- **The semantic QUALITY of model findings is a signal, not a proof.**
  The system proves the findings' structure, anchors, and safety, and
  computes the verdict deterministically from them — it does not prove
  the model judged well. That is exactly why humans hold both exits of
  EDITING; QA adds an independent second gate.
- **Reviews cover the ACTIVE draft only** (a superseded draft cannot be
  re-reviewed) — deliberate: reviews inform live decisions; history
  stays immutable and inspectable.
- **No operator-authored reviews.** Human judgment acts through the
  explicit accept-review / request-rework commands (with reasons)
  rather than by writing findings — deliberate for now; an operator
  finding channel would need its own bounded input surface.

### Production-readiness backlog (separate from feature completion)

- The Writer-stage audit's backlog carries over unchanged
  (single-operator boundary without auth/RBAC until governance;
  real-PG/Redis verification as a scripted per-task ritual rather than
  a CI lane; no provider spend controls; capped unpaged listings).
- **Evidence gap**: the superseded-brief review precondition
  (`ReviewPreconditionError` when the reviewed draft's brief is no
  longer ACCEPTED) is enforced in `create_review` and
  `resolve_reviewable_draft` but has no dedicated unit test — the
  construction requires a brief supersession mid-EDITING; add one when
  a cheap harness path exists.

## Disposition

The Editor stage is closed. Next per the accepted order and the
autonomous mandate: **QA architecture (design only)** — QA_REVIEW hard
gates over the exact reviewed package, the truthful media gate, and the
QA_REVIEW → AWAITING_HUMAN_REVIEW artifact-gated advance — then QA
implementation and the Phase 4 closure audit.
