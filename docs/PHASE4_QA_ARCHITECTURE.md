# Phase 4 QA Architecture (design only)

The QA stage: the final DETERMINISTIC gatekeeper between the editorial
loop and the human decision. It validates the EXACT package pinned at
`QA_REVIEW` entry — the reviewed draft, its pass review, and the full
provenance chain — through hard publication gates where the absence of
a result is never a pass, produces a durable versioned **QaReport**,
and advances `QA_REVIEW → AWAITING_HUMAN_REVIEW` only behind that
artifact. Phase 4 ENDS there: `APPROVED` belongs to the later
governance phase (ADR 0004 — a named authorized human, which requires
authentication that deliberately does not exist yet).

This document is design only (no runtime changes). It inherits every
binding rule of the Writer/Editor stages: WorkflowService-only
transitions behind artifact gates; append-only persistence pinned to
exact versions; execution failure never an editorial verdict;
truthful UNKNOWN; no publication boundary crossed.

## 1. Purpose and design decisions

**Decision — QA v1 is fully deterministic: no model involvement.** The
Editor stage already provides the governed model-assisted semantic
signal, and a human holds both of its exits. QA re-proves what machines
can prove (integrity, provenance, envelope, safety) and states honestly
what they cannot (media, semantic truth) — adding a second model
opinion here would add spend and noise, not proof. Consequences: no
`GenerationPurpose` widening, no AI attempts, no provider seam in QA;
a future governed model-assisted QA signal would follow the Editor
pattern (findings-only schema, deterministic verdict policy) as a NEW
versioned gate, never a silent change.

**Decision — the ready advance is SYSTEM-gated; the not-ready exits are
human.** The QA outcome is computed deterministically from durable
rows, so a `ready_for_human_review` report is a mechanical artifact
gate exactly like a durable draft: the QA task advances
`QA_REVIEW → AWAITING_HUMAN_REVIEW` itself (SYSTEM actor, report
pinned). Anything else — rework, waivers, rejection — is an explicit
human command with a reason. This is consistent with `WORKFLOW.md`
("AWAITING_HUMAN_REVIEW entry: QA passes all hard publication gates")
and keeps humans in charge of every judgment call.

**Decision — the media gate is truthful, human-waivable, and never a
silent pass.** No media pipeline exists. The gate reports:
`not_applicable` (the brief has no media needs), `unsatisfied` (needs
exist, nothing can evaluate them — the DEFAULT, and it blocks), or
`waived_by_human` (an explicit audited operator waiver with a reason).
The waiver is honest scope-limiting, not fabricated satisfaction: the
report keeps the need list visible either way. When a media pipeline
exists (roadmap), a real evaluation replaces the waiver path via a new
gate-policy version. Internal-link needs are REPORTED the same way but
are non-blocking in v1 (internal linking is a publish-time concern the
Konsepthane Publishing API integration will own); the report shows
them so the human decides informed.

## 2. Position in the canonical workflow

- Entry: `QA_REVIEW`, entered ONLY by accept-review with
  `{editorial_review_id, content_draft_id, review_verdict,
  content_hash}` pinned in the validated entry event.
- On entry the QA run is dispatched (from the accept-review command,
  post-commit best-effort — the established pattern) and is always
  available as an explicit operator command.
- Exits (all `WorkflowService`):
  - `QA_REVIEW → AWAITING_HUMAN_REVIEW`: SYSTEM, by the QA task, ONLY
    when a durable ACTIVE QaReport has outcome
    `ready_for_human_review`; artifact refs pin `{qa_report_id,
    editorial_review_id, content_draft_id, content_hash}`.
  - `QA_REVIEW → CHANGES_REQUESTED`: the existing `request-rework`
    command generalized — the QA_REVIEW context's permitted
    responsible states are `{DRAFTING, EDITING}` (a new entry in the
    Task 6 `PERMITTED_RESPONSIBLE_STATES` map; the operator chooses
    from THAT vocabulary only, defaulting to DRAFTING); the ACTIVE
    report/review/draft are pinned.
  - `QA_REVIEW → BLOCKED`: unchanged semantics — durable domain
    impossibility (e.g. the pinned package cannot resolve), never a
    failed gate and never transient failure.
- `AWAITING_HUMAN_REVIEW` is the Phase 4 terminal for this effort. Its
  own exits (`APPROVED`, `CHANGES_REQUESTED`, `REJECTED`) stay in the
  matrix but no APPROVED-producing surface is built (no fake approval
  before authentication + reviewer authorization exist — ADR 0004).

## 3. Hard gates (`qa-gates/1`, versioned policy snapshot per report)

Every gate produces an explicit result; UNKNOWN/absent is never a pass.

1. **package_integrity** — the QA_REVIEW entry pins resolve; the pinned
   draft is the ACTIVE draft with a matching `content_hash`; the pinned
   review is the ACTIVE review, verdict `pass`, covering exactly that
   draft; the brief is still the ACCEPTED writing contract.
2. **provenance_chain** — ADR 0007 re-proof from durable rows: every
   `DraftClaimUsage` resolves `BriefClaim → BriefClaimEvidence →
   ResearchEvidence` with at least one evidence link per used claim;
   counts and any broken links reported.
3. **writer_envelope** — the Task 11 recomputation
   (`recompute_writer_envelope`) reused verbatim: structure contract,
   claim-ref integrity, handling coverage against CURRENT rows.
4. **content_safety** — the deterministic URL/HTML/script ban re-run
   over the durable body and title (defense in depth against any
   future persistence-path regression).
5. **editorial_review_currency** — the pass review's own integrity
   record was computed with `writer_envelope_recomputed: True` and its
   `review_scope` hashes still match the draft/brief rows.
6. **media_needs** — `not_applicable` | `unsatisfied` (default when
   needs exist) | `waived_by_human` (audited waiver). Blocking unless
   not_applicable or waived.
7. **internal_link_needs** — reported (`none` | `pending`), NON-blocking
   in v1 (publish-time concern; visible to the human).

Outcome (deterministic): `ready_for_human_review` when every blocking
gate is `pass`/`not_applicable`/`waived_by_human`; else `not_ready`.
There is no reject outcome and no verdict for execution failure.

## 4. Data model (implementation-ready; migration in the persistence task)

**`qa_reports`** (append-only; the proven two-shape guarded trigger)

| Aspect | Decision |
| --- | --- |
| PK / FKs | `id UUID`; `work_item_id` RESTRICT; `content_draft_id` RESTRICT; `editorial_review_id` RESTRICT; `content_brief_id` RESTRICT |
| Uniqueness | `UNIQUE(work_item_id, version)`; partial unique `(work_item_id) WHERE status='active'` |
| Columns | version ≥1; outcome (`ready_for_human_review|not_ready` CHECK); gate_results JSONB (per-gate result + bounded detail, e.g. broken-link ids, need lists); gate_policy_snapshot JSONB (`qa-gates/1`); status (`active|superseded`) + superseded_by_report_id NULL (one-shot); engine_name/version (`qa`/`1`); content_hash; created_at |
| Immutability | UPDATE only the two supersession shapes; DELETE forbidden |
| Supersession | any re-run producing a DIFFERENT content_hash supersedes the ACTIVE report (SYSTEM actor, reason = what changed); identical re-runs reuse idempotently |

**`qa_gate_waivers`** (append-only): `id`, `work_item_id` RESTRICT,
`gate_key` (CHECK vocabulary — v1: `media_needs` only), `reason`
(required), `request_id` NULL, `created_at`. A waiver belongs to the
WORK ITEM (it survives report supersession) and is consumed by the
next report run; it is always visible in read models. Waivers are
created only by the explicit operator command.

**`qa_report_status_events`** — the established status-event pattern
(append-only trigger).

No AI attempt rows, no purpose widening. Migration 0020.

## 5. Orchestration and commands

Celery task `contentos.editorial.run_qa_gates` (9th editorial task;
kwargs `{work_item_id}` — no retry_number: the run is deterministic and
free, and redelivery is absorbed by report idempotency):

- gates run from durable rows in TX A → durable QaReport (idempotent:
  identical content_hash reuses the ACTIVE report) → commit;
- when the outcome is `ready_for_human_review` and the work item is
  still in QA_REVIEW: TX B SYSTEM transition to AWAITING_HUMAN_REVIEW
  with the report pinned → commit; redelivery validates the pinned
  entry (`_require_compatible_entry`) — queue completion never state;
- `not_ready` ⇒ no transition, truthful report; execution errors are
  task failures, never reports.

Dispatch: `accept-review` dispatches `run_qa_gates` post-commit
(best-effort, logged — the established API pattern). Operator commands
(`/internal/editorial`, POST-only):

- `work-items/{id}/run-qa` — queued explicit (re-)run;
- `work-items/{id}/waive-qa-gate` — direct: `{gate_key, reason}` with
  gate_key bounded to the waivable vocabulary (v1: `media_needs`);
  appends the audited waiver; does NOT re-run gates by itself (the
  operator re-runs explicitly, or the next run consumes it);
- `request-rework` (existing) — gains the QA_REVIEW context with a
  bounded `responsible_state` choice (`drafting` default, `editing`
  allowed); pins report/review/draft.

No generic endpoints; no approval/publication surface of any kind.

## 6. Read models and admin

- `work-items/{id}/qa-reports` — report versions (outcome, per-gate
  summary, waiver presence, pins); `qa-reports/{id}` — full detail
  (gate_results with bounded details, policy snapshot, waivers,
  status events);
- admin: QA section on the editorial detail page (report table with
  per-gate badges — `unsatisfied`/`unknown` never rendered as pass —
  run-qa / waive-media / request-rework forms with required reasons
  and an explicit waiver warning) + read-only report detail page;
  AWAITING_HUMAN_REVIEW items show the full pinned package with a
  clear "human decision pending; approval surface does not exist yet"
  statement;
- leak rules and tests as before.

## 7. Exit criteria (QA stage + Phase 4 closure)

- [ ] QA validates the EXACT entry-pinned package; every gate yields an
      explicit result; absence is never a pass
- [ ] immutable versioned QaReport with append-only enforcement,
      idempotent re-runs, audited supersession; waivers append-only,
      audited, always visible
- [ ] the media gate is truthful (not_applicable / unsatisfied /
      waived_by_human) and blocking unless satisfied-by-vocabulary;
      internal-link needs reported non-blocking
- [ ] provenance re-proof (ADR 0007) and writer-envelope recheck run
      from durable rows; failures produce not_ready, never silence
- [ ] QA_REVIEW → AWAITING_HUMAN_REVIEW only via the SYSTEM artifact
      gate on a ready report; rework via the routing foundation with a
      bounded responsible-state choice; REJECTED human-only; BLOCKED
      untouched; execution failure never an outcome
- [ ] no model involvement, no provider spend, no approval surface, no
      publication boundary; APPROVED remains unreachable by design
- [ ] operator inspects reports/gates/waivers via read models/admin
      with leak tests; deterministic tests; real-PG (+ broker for
      orchestration) verification; then a QA-stage audit and the
      PHASE 4 CLOSURE AUDIT (research → AWAITING_HUMAN_REVIEW
      end-to-end on real infrastructure)

## 8. Implementation order (atomic, dependency-correct)

**Task 16 — QA report persistence foundation.** Migration 0020
(qa_reports + qa_gate_waivers + qa_report_status_events, triggers);
enums/errors/values/repository; `QaService` with package-resolution
gates and idempotent report persistence (gate ENGINE separate); unit
tests + real-PG verification (cycle, triggers, race).

**Task 17 — QA gate engine.** `qa-gates/1`: the seven gates computed
from durable rows (reusing `recompute_writer_envelope` and the safety
ban), deterministic outcome, waiver consumption; unit tests over
ready/not_ready/waived/broken-provenance states.

**Task 18 — QA orchestration + commands + routing extension.**
`run_qa_gates` task + TX B SYSTEM advance; accept-review post-commit
dispatch; `run-qa`, `waive-qa-gate` commands; QA_REVIEW entry in
`PERMITTED_RESPONSIBLE_STATES` + bounded rework choice; real-PG +
real-Redis verification (ready advance with pins, not_ready
truthfulness, waiver flow, redelivery idempotency).

**Task 19 — QA read models + admin.**

**Task 20 — QA-stage audit** (docs-only, against §7).

**Task 21 — PHASE 4 CLOSURE AUDIT** (docs-only): the complete
Research → … → AWAITING_HUMAN_REVIEW story audited end-to-end against
the phase's binding invariants, with a real-infrastructure full-chain
verification run and the production-readiness backlog consolidated.
