# Phase 4 Editor Architecture (Task 9 — design only)

The Editor stage: the first governed consumer of a durable Writer
draft. It reviews ONE exact `ContentDraft` version against the accepted
brief contract and the projected evidence, produces a durable versioned
**EditorialReview** artifact with typed findings, and feeds the two
legal exits of `EDITING`: forward to `QA_REVIEW`, or rework to
`DRAFTING` through the named responsible-state routing foundation.
`REJECTED` remains an exclusively human decision and is NOT an Editor
output.

This document is design only (no runtime changes). It follows the
accepted Writer-stage discipline: deterministic gates fail closed,
model judgment is a policy signal and never Evidence, execution failure
is never an editorial verdict, workflow moves only through
`WorkflowService` behind artifact gates, and everything persisted is
append-only with provenance to exact versions.

## 1. Purpose and scope

**In scope**: semantic and editorial review of a draft — the checks the
Writer stage explicitly delegated (`PHASE4_WRITER_AUDIT.md`,
"deferred by design"):

- claim faithfulness: does the prose at each claim-bound block
  faithfully represent the bound claim (and only it), without
  overstating certainty;
- exclusion compliance: does any block violate the brief's exclusions
  (the Writer records `exclusions_mechanically_checked: False`; the
  Editor is where exclusions are actually reviewed);
- brief-objective fit: sections deliver the content objective, target
  audience, and intent summary of the accepted brief;
- editorial quality signals: tone/style consistency for the locale,
  redundancy, unclear instructions in how-to steps;
- uncertainty framing: caveats present (the Writer proved presence) are
  framed honestly where they appear.

**Out of scope**: media (QA-stage per `WORKFLOW.md` — the QA
architecture must handle the "eligible media set" gate honestly, since
no media pipeline exists yet); publication/approval/scheduling
anything; fact-checking against NEW sources (the evidence base is
frozen at the brief; missing evidence is a rework or human decision,
never a new research call from the Editor); producing content.

**Design decision — the Editor is evaluative, not generative.** The
Editor never writes or rewrites draft content. Revisions flow through
the existing rework loop back to the Writer (the single
content-producing engine), with the review's findings carried as
bounded structured input to the regeneration. Reasons: the draft
origin vocabulary stays frozen (`writer_engine|operator`); a second
content producer would need its own full validation/originality story
for no benefit; and "AI never adds external facts" is easiest to prove
when exactly one engine produces content under one set of gates. The
`WORKFLOW.md` `QA_REVIEW` entry condition "edited version exists" is
satisfied by the draft version that PASSED editorial review, pinned in
the review artifact.

**Design decision — humans advance the workflow out of EDITING.**
`DRAFTING → EDITING` is system-gated because its gate is mechanical (a
durable valid draft exists). The Editor's verdict, by contrast,
embodies model-assisted judgment; auto-advancing on it would hand the
model editorial authority. Therefore `EDITING → QA_REVIEW` and
`EDITING → CHANGES_REQUESTED` are explicit OPERATOR commands that
validate a durable review artifact for the exact active draft. The
review is the evidence; the human is the actor. (This mirrors
commissioning and brief acceptance, and keeps ADR 0004's
human-in-control posture ahead of the governance phase.)

## 2. Position in the canonical workflow

- Entry: the work item is in `EDITING` with the draft pinned in the
  validated entry event (`content_draft_id`, written by the Writer
  orchestration or the operator submit-draft command).
- Editor review generation is dispatched after the `EDITING`
  transition commits (implementation adds the downstream dispatch the
  Writer task deliberately omitted), and is also available as an
  explicit operator command (re-review, retry).
- Exits (all `WorkflowService`, all operator-actor):
  - `EDITING → QA_REVIEW` via a new `accept-review` command: requires
    an ACTIVE review, for the exact ACTIVE draft, whose verdict is
    `pass`; artifact refs pin `{editorial_review_id, content_draft_id,
    review_verdict, content_hash}`. Honesty note: `WORKFLOW.md` lists
    "eligible media set" in the QA_REVIEW entry condition, and no media
    pipeline exists yet — the QA architecture must define that gate
    truthfully (a QA that cannot evaluate media must report it as an
    explicit UNKNOWN/failing gate, never a silent pass); the Editor
    stage does not pretend to satisfy it.
  - `EDITING → CHANGES_REQUESTED(responsible=DRAFTING)` via the
    EXISTING `request-rework` command, extended to pin the ACTIVE
    review id when one exists (a `revise` verdict is the normal cause,
    but the operator may request rework regardless — human judgment
    outranks the signal in both directions only through explicit
    commands with reasons).
  - `EDITING → REJECTED`: existing human-only path; untouched.
- `BLOCKED` is reserved for durable domain impossibility discovered at
  the boundary (e.g. the pinned draft was superseded while queued and
  no ACTIVE draft exists) — operator resolves; never used for
  transient failure.

## 3. Deterministic integrity gates (no model, run first)

Typed preconditions before any provider call (zero spend on failure):

1. work item in `EDITING`; the validated entry event's
   `content_draft_id` resolves to a draft of this work item;
2. the reviewed draft is the ACTIVE draft (reviewing a superseded
   version is a typed conflict — re-dispatch reviews the active one);
3. the draft's brief is still the exact ACCEPTED brief of the work
   item (a superseded brief is a typed conflict surfaced to the
   operator, candidate for `BLOCKED`);
4. drift guard: the draft still satisfies the persisted Writer
   validation policies (structure contract, claim-ref integrity,
   handling coverage) — recomputed deterministically from durable
   rows, catching schema/policy drift between stages;
5. idempotency/reuse checks (§7).

Failures 1–4 are typed `EditorPreconditionError` variants; no attempt
row, no review row.

## 4. Model-assisted semantic review (contentos.ai boundary)

One purpose, one schema, one template — reusing the existing boundary
exactly as the Writer does:

- `GenerationPurpose.EDITOR_REVIEW = "editor_review"` (vocabulary +
  CHECK widening in the Editor migration; downgrade refuses while
  editor_review attempt rows exist — same audit protection as 0018).
- Input projection (bounded, deterministic, leak-free): the draft body
  (validated content — it IS the artifact under review), its claim
  usages, the brief contract (sections, exclusions, objective,
  audience, intent summary, uncertainty notes), the claims with their
  evidence STATEMENTS (≤500 chars, identity-attached — the same flat
  `evidence_units` pattern as the Writer projection), and the
  required-handling manifest. Never: source bodies, clean_text, raw
  payloads, URLs, provider config.
- Output schema `editor-review/1` (strict, extra=forbid): a bounded
  list of findings only — the model NEVER outputs a verdict. Each
  finding: `finding_key` (slug), `dimension` (fixed vocabulary:
  `claim_faithfulness | exclusion_compliance | objective_fit |
  clarity_style | uncertainty_framing`), `severity`
  (`blocking | major | minor`), optional `block_id` anchor, optional
  `claim_ref` (claim UUID from the projection only), `description` and
  `recommendation` (bounded safe text: the same deterministic
  URL/HTML/script ban as draft blocks). An empty findings list is a
  valid output.
- Domain validation (same boundary contract as the Writer): unknown
  `block_id`/`claim_ref`, vocabulary violations, unsafe text, or
  bound-breaking output ⇒ durable `VALIDATION_FAILED` attempt
  (`error_class="domain_validation"`), ZERO review rows.
- The template instructs (Turkish, versioned, never persisted): judge
  ONLY against the projected brief/claims/evidence; never introduce
  external facts — a finding that depends on outside knowledge is
  forbidden; when uncertain whether prose overstates a claim, say so
  as a finding with honest severity rather than staying silent.

**Boundary invariants restated as binding**: findings are policy
signals. They are never `ResearchEvidence`, never claims, and never
enter the provenance chain as facts. They influence workflow ONLY
through the deterministic verdict policy (§5) plus explicit human
commands.

## 5. Verdict policy (deterministic, versioned: `editor-verdict/1`)

The verdict is COMPUTED from validated findings, never model-authored:

- any `blocking` or `major` finding ⇒ `revise`;
- otherwise (none, or only `minor`) ⇒ `pass` — minor findings persist
  on the review and travel to QA visibility rather than blocking.

The policy (severity thresholds, dimension weights if ever added) is a
versioned snapshot persisted per review, like every Writer policy.
There is no `reject` verdict and no verdict for execution failure.

## 6. Data model (implementation-ready; migration in the persistence task)

**`editorial_reviews`** (append-only; guarded like `content_drafts`)

| Aspect | Decision |
| --- | --- |
| PK / FKs | `id UUID`; `work_item_id → editorial_work_items` RESTRICT; `content_draft_id → content_drafts` RESTRICT (exact version reviewed); `content_brief_id → content_briefs` RESTRICT; `generation_attempt_id → ai_generation_attempts` RESTRICT NULL |
| Uniqueness | `UNIQUE(work_item_id, version)`; `UNIQUE(generation_attempt_id)` (one review per SUCCEEDED attempt); partial unique `(work_item_id) WHERE status='active'` |
| Columns | version ≥1; verdict (`pass|revise` via string_enum CHECK); integrity_gate_result JSONB (the §3 recomputation, persisted); verdict_policy_snapshot JSONB; review_scope JSONB (what was projected: claim ids, handling ids, brief content_hash, draft content_hash); engine_name/engine_version (`editor`/`1`); status (`active|superseded`); superseded_by_review_id NULL; content_hash; created_at |
| Immutability | UPDATE only `active→superseded` + one-shot pointer (the proven two-shape trigger from 0018); DELETE forbidden |
| Supersession | a NEW review for the same work item (new draft version, or explicit re-review) supersedes the ACTIVE one with an audited status event and required reason |

**`editorial_review_findings`** (append-only rows of one review)

`id`, `review_id` RESTRICT, `finding_key` (unique per review),
`dimension` (CHECK vocabulary), `severity` (CHECK), `origin`
(`model_signal | deterministic` — the drift guard may emit
deterministic findings), `block_id` NULL, `brief_claim_id` RESTRICT
NULL, `description`, `recommendation` NULL, `created_at`. No UPDATE, no
DELETE.

**`editorial_review_status_events`** — the exact draft-status-event
pattern (BigInteger id with SQLite variant, from/to status, actor
origin, required reason, request_id, replacement_review_id,
occurred_at; append-only trigger).

No change to `content_drafts`, briefs, or workflow tables. The purpose
CHECK on `ai_generation_attempts` is widened for `editor_review` with
the audit-protecting downgrade guard.

## 7. Idempotency, reuse, retries, failure taxonomy

Identical to the proven Writer semantics:

- attempt identity = purpose + schema/template + input_hash +
  retry_number; the same identity reuses the durable attempt AND its
  review with zero provider calls;
- SUCCEEDED attempt without a review row ⇒ typed
  `IncompleteReviewMaterializationError`; recovery ONLY by explicit
  `retry_number+1`;
- deterministic persistence rejection of valid output ⇒
  `ReviewGenerationMaterializationError`, attempt keeps its real
  status (committed before the terminal task failure);
- TIMEOUT / PROVIDER_ERROR: bounded DOMAIN retries with failed
  attempts committed first; VALIDATION_FAILED / CANCELLED terminal per
  attempt; the work item STAYS in `EDITING` in every failure case —
  visible, truthful, resumable by explicit re-command; never
  `REJECTED`, never `CHANGES_REQUESTED`, never silent.

## 8. Orchestration and commands

New Celery task `contentos.editorial.generate_editor_review`
(kwargs `{work_item_id, retry_number=0, supersede_reason=None}`,
JSON-safe, inherited delivery contract):

- TX A: integrity gates → engine → durable review (or durable failed
  attempt) → commit;
- NO workflow transition on success (the human advances; §1) and no
  downstream dispatch (QA does not exist yet — its architecture will
  hook `QA_REVIEW` entry);
- redelivery guard: an ACTIVE review already covering the ACTIVE draft
  ⇒ `reused`, no provider call.

Dispatch wiring: `generate_writer_draft` TX B and the operator
`submit-draft` command gain the post-commit dispatch of the Editor
task (the artifact-gate pattern's "downstream dispatch" step that was
deliberately omitted while the Editor did not exist). Dispatch failure
after commit is logged and non-fatal — the explicit operator command
covers the gap; state was already truthfully advanced by the draft
artifact gate.

Operator commands (`/internal/editorial`, POST-only, thin, no generic
endpoints):

- `work-items/{id}/generate-editor-review` — queued; regeneration =
  same command with `retry_number+1` (+ supersede reason when an
  ACTIVE review exists);
- `work-items/{id}/accept-review` — direct: validates work item in
  `EDITING` + ACTIVE review + review pins the ACTIVE draft + verdict
  `pass`, then `WorkflowService` OPERATOR transition to `QA_REVIEW`
  with the review pinned; required reason;
- `request-rework` (existing) — extended to include
  `editorial_review_id` in artifact refs when an ACTIVE review exists;
  no behavioral change otherwise;
- rework regeneration feedback: when the Writer regenerates after a
  review-driven rework, the writer projection gains a bounded
  `editorial_findings` input (finding_key, dimension, severity,
  block_id, claim id, description) taken from the review pinned in the
  CHANGES_REQUESTED entry event — ids and bounded text only, so the
  Writer addresses findings without any new fact channel.

## 9. Read models and admin

- `work-items/{id}/reviews` — all review versions (verdict, engine,
  draft pinned, finding counts by severity, truthful UNKNOWN for
  absent verdicts is impossible by construction — a review row always
  has a computed verdict — but integrity-gate UNKNOWNs render as
  UNKNOWN);
- `reviews/{id}` — full detail: findings with anchors resolved
  (section/block, claim key/kind), integrity gate result, policy
  snapshots, status events, safe attempt metadata (failures visible);
- admin: Reviews section on the editorial detail page (state-gated
  generate/accept-review/request-rework commands with required
  reasons) + read-only review detail page; the same leak rules and
  tests as drafts (no raw provider data, broker URLs, or source
  bodies).

## 10. Security and truthfulness rules (inherited, binding)

No provider keys outside worker config; no raw prompts/outputs
persisted or shown; findings text is bounded safe text; no Konsepthane
production access; UNKNOWN never rendered as 0/PASS; failed attempts
never hidden; single-operator boundary until the governance phase.

## 11. Editor-stage exit criteria

- [ ] review generation requires the exact EDITING entry pin and an
      ACTIVE draft over the exact ACCEPTED brief (typed failures, zero
      provider spend)
- [ ] immutable versioned EditorialReview with append-only enforcement,
      one review per SUCCEEDED attempt, audited supersession
- [ ] deterministic integrity gates recompute the Writer envelope and
      fail closed; drift emits deterministic findings or typed errors
- [ ] model output is findings-only in a strict schema; verdict derived
      by the versioned deterministic policy; findings are policy
      signals, never Evidence, never new facts
- [ ] execution failure is never a verdict; the item stays EDITING;
      VALIDATION_FAILED terminal per attempt with zero review rows
- [ ] idempotent generation, explicit retry_number+1 regeneration,
      redelivery-safe reuse, typed incomplete-materialization recovery
- [ ] EDITING → QA_REVIEW only via the operator accept-review command
      gated on a durable pass review pinning the ACTIVE draft;
      EDITING → CHANGES_REQUESTED keeps the responsible-state routing;
      REJECTED stays human-only
- [ ] writer regeneration after review-driven rework receives the
      bounded findings input (ids + bounded text only)
- [ ] operator inspects reviews, findings, integrity results, attempts,
      failures via read models/admin with leak tests
- [ ] deterministic fake-provider tests; no live calls in gates;
      real-PG (+ broker for orchestration) verification; then an
      Editor-stage audit against these criteria

## 12. Implementation order (atomic, dependency-correct)

**Task 10 — Review persistence + provenance foundation.** Migration
(0019): three tables + purpose CHECK widening + guards; enums/errors/
values; repository; `ReviewService` create/supersede with the full
gate set (integrity gates deterministic-only at this task, no engine);
unit tests + real-PG verification (migration cycle, triggers, race,
downgrade guard). No API/admin/Celery.

**Task 11 — Verdict policy + integrity gate recomputation.** The
versioned `editor-verdict/1` policy, deterministic drift-guard
recomputation against durable rows, deterministic findings; truthful
snapshots persisted per review; unit tests. No provider involvement.

**Task 12 — Projection + output schema + engine.** `editor-review/1`
pydantic schema, bounded leak-free projection, `EditorEngine` through
`StructuredGenerationService` with purpose `EDITOR_REVIEW`, domain
validator, materialization + reuse + incomplete-recovery semantics;
fake-provider tests (projection leak test pinned).

**Task 13 — Orchestration + commands.** `generate_editor_review`
Celery task (8th editorial task) + dispatch from the two draft paths;
`generate-editor-review`, `accept-review` commands;
`request-rework` review pinning; writer rework findings input;
real-PG + real-Redis verification (dispatch on draft success, failure
truthfulness, redelivery reuse, accept-review artifact gate). 

**Task 14 — Read models + admin.** Review list/detail projections and
admin screens with leak tests.

**Task 15 — Editor-stage audit** against §11 (docs-only), then the QA
architecture (design only) follows.
