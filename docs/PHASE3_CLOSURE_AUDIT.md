# Phase 3 Closure Audit — Editorial Intelligence / Idea Engine

Audit task: Phase 3 Task 15.
Audit date: 2026-09-02.
Auditor: implementation-independent closure review against the accepted
design (`docs/PHASE3_EDITORIAL_INTELLIGENCE.md`), the canonical workflow
(`docs/WORKFLOW.md`), the architecture and editorial policy documents, and
ADRs 0001–0009, performed on the repository as it actually exists at the
audited HEAD — not on task completion reports.

---

## 1. Purpose and scope

This document answers one question with evidence:

> Can ContentOS, from an eligible Phase 2 research signal, produce a fully
> auditable, human-inspectable, provenance-preserving
> `ACCEPTED_FOR_DRAFTING` ContentBrief through the accepted Phase 3
> workflow, while respecting all Phase 3 gates and without implementing
> Writer/publication behavior?

In scope: everything Phase 3 Tasks 1–14 delivered — workflow foundation,
opportunity intake/scoring, search signals, evidence packs, ideas, the AI
boundary and OpenAI adapter, search-intent analysis, content briefs and
acceptance, brief composition, Celery editorial orchestration, and the
operator visibility/command surface — audited as one composed system at
current HEAD, plus the four known closure questions and the security
boundaries.

Out of scope: Writer/Editor/QA, publication approval and everything after
it (ADR 0004 exercised in a later phase), Pinterest, analytics, and
production deployment readiness (tracked separately in §8; production
readiness is not phase completion).

## 2. Baseline

| Item | Value |
| --- | --- |
| Repository / branch | `konsepthane-contentos` / `main` |
| Audited HEAD | `20a6550f86f093fdff0d48b0a2642268563bc22b` (`feat: add editorial admin controls`, Task 14) |
| Parent | `4ff321f24f5fe3f050ff17db89a56072304e5441` (Task 13) |
| Alembic schema head | `0017` (verified with `alembic heads` during this audit) |
| Backend tests at HEAD | 1081 passed (canonical gate re-run during this audit) |
| Admin tests at HEAD | 135 passed; `tsc --noEmit`, eslint, prettier, `next build` clean |
| GitHub CI at HEAD | passed (backend quality, admin quality, migration/infrastructure integration, compose smoke) — per operator record for `20a6550f` |
| Accepted design | `docs/PHASE3_EDITORIAL_INTELLIGENCE.md` (Accepted, Phase 3 Task 1) |
| Tasks audited | Phase 3 Tasks 1–14 (Task 15 is this audit) |
| Dependencies | unchanged by this audit (`pyproject.toml`, `uv.lock`, `package.json`, `pnpm-lock.yaml` untouched) |

Codebase Memory graph state at audit time: 4,774 nodes / 26,292 edges,
status ready, indexed at content identical to `20a6550f` (the Task 14
worktree was committed unchanged); used for architecture recovery and
symbol location, with targeted source inspection wherever evidence was
required.

## 3. Design → implementation mapping

| Accepted design section | Implementation (modules at HEAD) |
| --- | --- |
| §1 canonical workflow aggregate | `contentos.workflow` — `EditorialWorkItem`, append-only `EditorialWorkflowEvent`, `WorkflowService` (structural matrix from WORKFLOW.md, row-locked transitions, history-derived BLOCKED/CHANGES_REQUESTED exits, `resolve_block`/`reject_blocked`), migration 0009 lineage |
| §2 Phase 2 → Phase 3 intake | `contentos.opportunities.service.ResearchPromotionService` (`promote_research`, `promote_duplicate_override`), ADR 0008 gate (`ELIGIBLE_OUTCOMES`), promotion-root UNIQUE identity |
| §3 opportunity + scoring | `contentos.opportunities` — `EditorialOpportunity`, `OpportunityResearchInput`, `OpportunityScore`/`OpportunityScoreComponent`, `OpportunityScoringService` + pure `OpportunityScoringEngine` (v1 weights/thresholds snapshots), `OpportunityCommissioningService`, `OpportunityRejectionService` |
| §4 search-signal boundary | `contentos.signals` — `SearchSignal` observations (`record_manual_signal`), provider-neutral, observed_at/as_of semantics |
| §5 ideas | `contentos.ideas` — immutable versioned `Idea`, append-only `IdeaSelectionEvent`, `IdeaService` (operator create/select/deselect), originality guard with versioned policy |
| §6 AI boundary | `contentos.ai` — provider protocol/DTOs, validation pipeline, append-only `ai_generation_attempts` (metadata only), `FakeStructuredProvider`; `contentos.ai.providers.openai_provider` (ADR 0009 adapter, sole `openai` import site) |
| §7 evidence packs | `contentos.evidence_packs` — versioned `EvidencePack` + items + `EvidenceContradiction`, `EvidencePackService` (`assemble_pack`, `reassemble_pack`, `resolve_contradiction`, `list_eligible_evidence`), sufficiency policy snapshots |
| §8 search intent | `contentos.search_intent` — versioned `SearchIntentAnalysis`, deterministic composition + optional INTENT_SYNTHESIS, frozen `known_signal_refs`, missing_signals, cannibalization truth-states |
| §9 content brief | `contentos.briefs` — versioned `ContentBrief` + `BriefClaim`/`BriefClaimEvidence`/`BriefStatusEvent`, `BriefService` (14 acceptance gates, guarded status-only-forward trigger), `BriefCompositionEngine` |
| §10 versioning/idempotency | identity hashes + attempt-identity idempotent materialization across scoring/packs/ideas/intent/briefs; exact version pinning on every downstream artifact |
| §11 operator decisions / failure model | commissioning, rejection, selection, contradiction resolution, block resolution, brief acceptance, duplicate override — all explicit audited operator commands; BLOCKED/REJECTED semantics per WORKFLOW.md |
| §14 risk hooks | score `risk_flags`, pack licensing/staleness/locale cautions, brief mandatory exclusions/uncertainty notes |
| §15 evidence exposure to AI | bounded deterministic projections (idea generation context, brief evidence projection policy) — never raw payloads/bodies |
| §18 orchestration | `contentos.worker.editorial_tasks` (six frozen job names, Phase-2 delivery contract), `contentos.worker.runtime` provider seam, `contentos.worker.producer` (`CeleryEditorialControlDispatcher`, producer-only) |
| §19 operator controls | `contentos.api.read_models.editorial`, `contentos.api.routes.editorial` (+`editorial_control`), admin `apps/admin/src/app/editorial/**` + server-only clients |

The layers compose: the real-PostgreSQL + real-Redis verification recorded
under Task 14 (and re-relied on here because HEAD content is identical to
what it exercised) drove the entire chain through the REAL FastAPI app →
REAL broker messages → REAL registered worker tasks with no bypassed
domain rule.

## 4. Phase 3 exit-criteria matrix (design §23)

| # | Exit criterion | Evidence | Status | Notes |
| --- | --- | --- | --- | --- |
| 1 | Durable canonical EditorialWorkItem with audited transitions | `workflow/models.py` (work item + append-only event with from/to/actor/reason/artifact_refs/request_id); `WorkflowService.transition` validates under a row lock against the canonical matrix; audit-grep confirms `current_state` is assigned **only** in `workflow/service.py`; no admin/API/ORM bypass exists (read models are SELECT-only; control routes call services) | PASS | BLOCKED/CHANGES_REQUESTED exits derived from durable history, never caller-supplied |
| 2 | Versioned EditorialOpportunity with multi-source research inputs | `opportunities/models.py`: opportunity pinned to work item + UNIQUE promotion root document; `OpportunityResearchInput` rows (role, added_by, note, duplicate_decision_id) — multi-source proven in tests and the PG run (4 inputs); explicit audited disposition (reason/at/by) | PASS | |
| 3 | Explainable, component-level, UNKNOWN-honest scoring | `OpportunityScore` + per-component rows (availability KNOWN/UNKNOWN/NOT_APPLICABLE, value nullable, provenance_ref); weights/threshold/input snapshots persisted; UNKNOWN never coerced to 0 (engine tests pin it; read model + admin render "Unknown"); missing_signals durable; scoring **never** transitions or commissions (Task 13 tests: state stays IDEA_SCORING, disposition OPEN) | PASS | v1 emits UNKNOWN for 7 of 12 components honestly |
| 4 | Intake enforces ADR 0008 duplicate/normalization/provenance eligibility | `promote_research`: full chain resolution (document→snapshot→item→source), normalization must have SUCCEEDED, effective duplicate decision required (absence = hard stop), UNIQUE/RELATED/UPDATE_EXISTING distinct (UPDATE_EXISTING becomes update-signal role), DUPLICATE/REJECT hard stops; `promote_duplicate_override` operator-only with reason + distinct angle, decision never mutated, REJECT has **no** override; decision identity pinned in creation-event refs and research input | PASS | Verified live on real PG (real DUPLICATE decision reopened; decision row untouched) |
| 5 | Versioned Idea candidates with auditable explicit selection | immutable `Idea` versions (logical id + version), append-only `IdeaSelectionEvent` (reason, actor, request_id); deselection targets only the effective selection and never resurrects an older one (service rule + tests); generation attempt FK on model-assisted ideas; originality PASSED/FAILED/NOT_CHECKABLE truthful (NOT_CHECKABLE never passes acceptance) | PASS | |
| 6 | Provenance-preserving EvidencePack with roles/clusters | pack items reference exact `research_evidence.id` (FK) with role + claim_cluster + display note; no evidence text copied into a second source of truth (read model serves bounded statements FROM the evidence row, id stays canonical) | PASS | |
| 7 | Contradictions and gaps visible, explicit sufficiency gate | `EvidenceContradiction` rows (sides = exact evidence ids, severity, resolution state); sufficiency READY/INSUFFICIENT/CONFLICTED/BLOCKED persisted with detail (missing items, unresolved blocking contradictions); unresolved BLOCKING contradictions force CONFLICTED and the orchestration blocks the work item (Task 13 non-READY→BLOCKED path); resolution never retroactively edits a pack | PASS | See §7.2 for the continuation boundary |
| 8 | SearchIntentAnalysis with truthful missing-signal and cannibalization states | versioned analysis pins exact idea + exact signal ids (frozen snapshots; no implicit latest — service refuses unknown/mismatched signals); missing_signals durable data (UNKNOWN ≠ ZERO); cannibalization NOT_CHECKED/NO_KNOWN_CONFLICT/POTENTIAL/KNOWN with basis; KNOWN_CONFLICT refused for synthesis; UI/composition wording says "ContentOS-internal only; published inventory not accessible" — production inventory knowledge never claimed | PASS | |
| 9 | Versioned ContentBrief with deterministic claim/evidence map | versioned brief pins exact idea/pack/analysis ids; `BriefClaim` + `BriefClaimEvidence` link claims to exact evidence ids; factual/source-assertion claims require eligible evidence FROM the pinned pack (gate + composition validation); writing contract only — no article prose fields exist; uncertainty notes/exclusions system-merged and model-undeletable; structure/copyright guard versioned and recorded; content hash whole-version integrity; guarded PG trigger permits status-only forward changes (accepted versions immutable) | PASS | |
| 10 | No path bypasses ResearchEvidence provenance (ADR 0007) | FK chain resolvable end-to-end: `content_briefs → evidence_packs → evidence_pack_items → research_evidence → normalized_documents → fetch_snapshots → discovery_items → sources` (RESTRICT FKs on every link except the Phase 2 `discovery_items.source_id` CASCADE, which downstream RESTRICT FKs neutralize for any item with fetched history — and no delete surface exists); `ResearchEvidence(` constructed in exactly one place (`research/service.py`); AI attempts table deliberately has no output columns and no path writes evidence from attempts; no bare-URL or copied-text evidence root exists | PASS | Grep + model audit, not documentation |
| 11 | Provider-neutral AI boundary with attempt provenance and fake provider | `contentos.ai` protocol + DTOs; `ai_generation_attempts` persist provider/model/schema/template identities, input refs/hash, status, retry_number, usage — never prompts/raw output (module contract states it; no such columns exist); `FakeStructuredProvider` used by every automated test; `openai` imported ONLY in `contentos/ai/providers/openai_provider.py` (repo-wide grep); strict validated structured outputs; failures are typed statuses, never editorial decisions; read models expose safe metadata only (leak tests pin absence of prompts/keys/raw output) | PASS | ADR 0009 governs the adapter |
| 12 | Idempotent Celery orchestration with explicit workflow transitions | six frozen `contentos.editorial.*` tasks; at-least-once absorbed by durable artifact identities (redelivery tests: no duplicate events/artifacts, single provider call on reuse); every transition via `WorkflowService` with artifact refs; queue completion alone never advances state; commit-before-enqueue proven with an independent-session dispatcher on real PG; DOMAIN vs DISPATCH retry separation; API process contains no WorkerRuntime/provider machinery (grep: zero references under `contentos/api`) | PASS | Dispatch-gap disposition in §7.1 |
| 13 | Operator visibility and command surface for the whole chain | `/internal/editorial` reads (queue, detail explainability projection, eligible evidence) + 16 explicit business POST commands; admin `/editorial` + `/editorial/[id]` server-rendered over the server-only client (internal URL never in browser output — test-pinned); reads are read-only (row-count test); no `/action`/`/execute`/`/state`/`/transition`/`/command` and no publish/schedule/approve path (pinned over OpenAPI paths); operator reasons required for every judgment command; absent/unknown values render truthfully | PASS | |
| 14 | BRIEFING→DRAFTING contract enforced | Only `BriefService.accept_for_drafting` performs DRAFT→ACCEPTED_FOR_DRAFTING + BRIEFING→DRAFTING, atomically, after re-validating the full pinned upstream chain (14 gates: stage, commissioned opportunity, duplicate gate, current selection, originality PASSED, claim/evidence map, blocking contradictions, …); exposed only as the explicit operator command (API + admin "Accept for drafting" with the explicit does-NOT-publish wording); no Celery task ever accepts; SUPERSEDED can never be accepted; acceptance ≠ published/approved/scheduled/released — no such state or command exists in Phase 3 | PASS | Proven live on real PG through the API |

**Result: 14 / 14 PASS, 0 BLOCKED, 0 NOT_APPLICABLE.**

Writer implementation is explicitly not an exit requirement and was not
needed to demonstrate any criterion (§6.N below).

## 5. End-to-end chain audit

The complete operator story was demonstrated on real ephemeral pgvector
PostgreSQL (schema `0017`) + real Redis, through the REAL FastAPI app
publishing with the REAL producer to the REAL broker, each message
verified (stable task name, JSON payload, request-id header, no secrets)
and then executed by the REAL registered worker tasks (fake AI provider
through the runtime seam — no live model calls):

1. **Phase 2 research**: governed sources → discovery → fetch snapshot
   (durable payload store) → normalized document → real duplicate
   decisions.
2. **Promotion** (`POST .../research/{id}/promote` → worker): WorkItem +
   Opportunity + creation event at IDEA_SCORING; scoring dispatched by the
   worker after commit; redelivery reused the durable promotion.
3. **Score** (`POST .../evaluate` → worker): a REAL `strong` /
   `commissionable` evaluation from the real deterministic engine with 12
   component rows (UNKNOWN components honest); no transition, no
   commissioning.
4. **Commissioning** (`POST .../commission`): OPEN→COMMISSIONED +
   OPERATOR IDEA_SCORING→EVIDENCE_BUILDING with score identity pinned in
   the event; idempotent repeat added nothing. (Race behavior — one
   winner, loser idempotent — proven on real PG in Task 13.)
5. **Ideas** (`POST .../generate-ideas` → worker): three immutable
   candidates with generation-attempt provenance and originality results.
6. **Selection** (`POST .../ideas/{id}/select`): append-only event; no
   workflow movement.
7. **Evidence pack** (`GET eligible-evidence`, then
   `POST .../evidence-packs/build` → worker): explicit operator
   selections + a declared material contradiction; READY pack; SYSTEM
   EVIDENCE_BUILDING→SEO_RESEARCH with pack identity in refs; analysis
   dispatched only after commit.
8. **Search intent** (`POST .../analyze-search-intent` → worker): exact
   signal observation pinned (no implicit latest); versioned analysis with
   honest missing signals and NOT_CHECKED cannibalization; SYSTEM
   SEO_RESEARCH→BRIEFING.
9. **Content brief** (`POST .../compose-brief` → worker): DRAFT brief with
   deterministic claim→evidence map, system-owned uncertainty notes and
   exclusions, structure guard `passed`; work item stayed BRIEFING.
10. **Acceptance** (`POST .../briefs/{id}/accept`):
    ACCEPTED_FOR_DRAFTING + BRIEFING→DRAFTING, one brief status event,
    one workflow event. The chain stops there — nothing downstream
    exists.

Side paths also demonstrated live: opportunity rejection on a second
eligible item; BLOCKED→history-derived-state resolution on a third;
duplicate reopen over a real DUPLICATE decision (decision untouched);
contradiction resolution + pack reassembly (old version immutable); GET
endpoints changing nothing; every read response free of raw
content/secrets.

Provenance held at every step: the accepted brief's claims resolve to
exact `research_evidence` ids, which resolve through their normalized
document and fetch snapshot to the registered source.

## 6. Invariant / security audit

Confirmed by targeted code inspection and greps at HEAD (not inferred
from documentation):

| Invariant | Evidence | Result |
| --- | --- | --- |
| No Konsepthane production DB/site/Publishing API access | no client/integration exists; `core/config.py` documents the DB URL must never point at a Konsepthane database; ADR 0001/0003 untouched | HELD |
| No publication/scheduling/Pinterest/analytics/release surface | zero such endpoints (OpenAPI-path test); "publish" matches in code are broker-publish vocabulary and truthful "not accessible" wording; canonical post-DRAFTING states exist only as reserved workflow vocabulary with no Phase 3 writer | HELD |
| No Writer/Editor/QA engine | no such module/class exists (grep); no article prose fields on any artifact | HELD |
| No auth/RBAC introduced | no login/users/roles/sessions/JWT anywhere; single-operator boundary documented | HELD |
| No arbitrary internet research beyond governed Phase 2 intake | fetch remains ADR 0005/0006-governed; the editorial control API accepts only entity UUIDs, never URLs to fetch | HELD |
| No browser-side AI/provider calls; no keys in admin output | admin has no provider client; internal URL and secrets absent from rendered HTML/JS (test-pinned); OpenAI adapter confined to `contentos.ai.providers` | HELD |
| No raw payload / clean_text / response body / prompt / raw model output exposure | read models never select those columns; serialized-response leak tests (backend + PG run) assert absence; AI attempt table has no such columns | HELD |
| AI output never ResearchEvidence | single evidence construction site in `research/service.py`; attempts table stores metadata only | HELD |
| No generic state mutation endpoint / raw ORM selector | route audit + test pins; only `WorkflowService` writes `current_state` | HELD |
| No fabricated search-demand/competition/CPC/traffic data | signals are recorded observations only; scoring emits UNKNOWN where no durable signal exists; no estimation code | HELD |
| Queue completion never advances workflow state | every transition is an explicit `WorkflowService` call with artifact refs; task completion alone changes nothing (Task 13 tests) | HELD |

## 7. Known limitation disposition (the four closure questions)

### 7.1 DB commit ↔ broker dispatch gap — `PRODUCTION_READINESS_BACKLOG`

**Affected operations**: worker-internal next-stage dispatch
(promotion→scoring, READY-pack→analysis) and API queue commands. The
pattern everywhere is commit-durable-result-first, then enqueue; there is
no transactional outbox.

**What can happen**: a crash or broker outage exactly between commit and
enqueue loses only the *enqueue* — never the durable domain result and
never a workflow transition (transitions commit before their dependent
dispatch). The reverse hazard (broker message representing uncommitted
state) cannot occur for domain results because publication strictly
follows commit; a redelivered message for already-durable work re-executes
idempotently.

**Recovery paths that exist today**: (a) DISPATCH-classified Celery retry
inside the task re-runs, reuses the durable result idempotently, and
re-enqueues; (b) at-least-once broker redelivery re-runs the task with
the same convergence; (c) the Task 14 command surface gives the operator
an explicit, idempotent re-trigger for **every** stage (evaluate,
generate-ideas, evidence-packs/build, analyze-search-intent,
compose-brief), each converging on the durable artifact identity —
redelivery/re-trigger tests prove no duplicate artifacts or events result.
The Task 14 queue detail projection makes a stalled stage visible.

**Disposition**: the exit criterion is *"idempotent Celery orchestration
with explicit workflow transitions exists"* — it is satisfied: semantics
remain correct under loss (nothing false is ever recorded; every durable
state is visible and resumable through a defined operator path), and
idempotency guarantees convergence rather than duplication. What the gap
costs is unattended delivery *reliability*, which is a deployment
concern. The outbox/transactional-dispatch decision therefore stays where
the Phase 2 closure audit already placed it: the production-readiness
backlog (§8), with the same trigger criteria. Not a Phase 3 blocker.

### 7.2 READY reassembled EvidencePack continuation — `ACCEPTED_PHASE_3_BOUNDARY`

**Behavior**: `reassemble_pack` (API: `POST /evidence-packs/{id}/reassemble`)
produces a new immutable pack version carrying frozen contradiction
resolutions; it performs no workflow transition and dispatches nothing.

**Audit**: this is the *correct* side of two binding rules, not a missing
path. First, "queue completion never advances workflow state" and the
design's own framing — "the chain is deliberately NOT one automatic
cascade… punctuated by operator decisions" (§18) — mean a durable
artifact appearing is never, by itself, a state change; the only accepted
automatic advance is the `build_evidence_pack` job's own READY transition,
which Task 13 defines for the pack *that job assembled*. Second, the
end-to-end workflow remains fully operational through explicit commands
in every recovery shape that exists:

- work item in **SEO_RESEARCH** (pack went READY earlier, contradiction
  resolved later): the operator may immediately queue
  `analyze-search-intent` pinned to the reassembled READY version — the
  analysis command accepts any READY pack of the opportunity; nothing is
  stuck.
- work item **BLOCKED** from a non-READY pack: resolve the contradiction,
  reassemble, `resolve-block` back to EVIDENCE_BUILDING (history-derived
  target), then queue `evidence-packs/build` — the worker job transitions
  on its READY result exactly as accepted, and analysis/brief may pin
  whichever READY version the operator chooses. Every step is an existing
  explicit command; each was exercised live in the Task 14 PG run
  (resolution, reassembly, block resolution) and the Task 13 run (READY
  transition, blocking path).

**Disposition**: intentionally manual, explicit-command recovery boundary
consistent with the accepted invariants; recorded in the design's §19
realization note. A convenience "continue with pack X" orchestration could
be Phase 3-adjacent UX polish, but no accepted contract requires it. Not
a blocker.

### 7.3 Minimal contradiction declaration UI — `ACCEPTED_PHASE_3_BOUNDARY`

**State at HEAD**: contradiction *visibility* (read model + admin cards
with sides/severity/resolution), *safe handling* (CONFLICTED sufficiency
blocks progression; unresolved stays unresolved), *resolution* (typed
domain command + API + admin form with required reason), and *typed
declaration* (the `build` API command accepts full bounded contradiction
declarations) all exist. Only a rich declaration-authoring form in the
admin pack builder was kept minimal.

**Disposition**: design §19's accepted command list is "commission/reject
opportunity, select idea, request regeneration, resolve
contradiction/block, accept brief for drafting, reopen duplicate" — it
requires contradictions to be *visible with their trail* and *resolvable*,
which they are; it does not require a declaration-authoring UX. The
operator story (declare at pack build) remains possible through the typed
internal API command. Classified as an accepted boundary with a small UX
backlog note (admin declaration inputs), not a blocker.

### 7.4 Stale documentation — resolved in this task (was: documentation debt)

Findings and corrections (all documentation-only, applied by Task 15):

| Stale statement | Location | Correction |
| --- | --- | --- |
| "No Phase 3 runtime code exists yet; nothing below is implemented…" | `PHASE3_EDITORIAL_INTELLIGENCE.md` header | Header now states the design is Accepted and realized; implementation status tracked by `CURRENT_STATE.md`, closure by this audit. The historical design body is untouched. |
| "No editorial business logic exists yet." | `CURRENT_STATE.md` foundation summary | Scoped historically; Phase 3 delivery stated. |
| "Phase 2 implementation is authorized only one atomic task at a time." | `CURRENT_STATE.md` constraint section | Generalized: implementation proceeds one authorized atomic task at a time (phase-agnostic rule). |
| "The admin exposes exactly the minimal Task 19 operator controls…" | `CURRENT_STATE.md` constraint section | Scoped to the *research* admin surface; the editorial surface is described separately. |
| `PHASE 3 … IN PROGRESS` header + Task 15 "awaiting authorization" next-task block | `CURRENT_STATE.md` | Updated per the closure decision below. |

Historical per-task records (Tasks 2–14 entries, Phase 1/2 blocks) are
preserved untouched — they are clearly task-scoped history.

## 8. Deferrals and non-Phase-3 backlog

### 8.1 Phase 4+ backlog

- Writer engine consuming exactly one `ACCEPTED_FOR_DRAFTING` brief
  version (Phase 4).
- Editor/QA engines, review loops, CHANGES_REQUESTED richer routing
  (named-responsible-state mechanism — documented Task 2 limitation,
  owned by the phase implementing review loops).
- Human publication approval flow (ADR 0004), scheduling, publishing,
  Konsepthane Publishing API/inventory contract (ADR 0003), Pinterest,
  analytics ingestion, media provenance.
- Real search-signal provider integrations (the boundary is
  provider-neutral; only manual observations exist today) and
  cannibalization checks against real published inventory.
- Cost/budget enforcement (hooks exist: usage metadata, "Not reported"
  cost honesty; no billing calculation).

### 8.2 Production-readiness backlog (carried forward + Phase 3 additions)

Inherited from the Phase 2 closure audit §7, still applicable, still not
phase blockers: deployment access protection (unauthenticated by design —
never expose beyond a trusted boundary), secrets provisioning, backups /
restore drill, monitoring/alerting, source allowlist governance
execution, periodic discovery scheduling, distributed per-host crawl
limiting (pin fetch workers to one process until then), raw payload
retention, operator runbooks, worker sizing, broker durability.

Phase 3 updates to that list:

- **DB commit ↔ broker dispatch / outbox decision** — now also covers the
  six editorial jobs (§7.1); same trigger criteria as Phase 2 §5.6;
  interim mitigation: idempotent re-trigger commands + queue visibility.
- **OpenAI production configuration** — key provisioning, model pinning
  review, spend monitoring before any unattended AI generation
  (`openai_*` settings exist; no live call has ever been made by gates).
- **Editorial runbooks** — BLOCKED triage, contradiction resolution +
  reassembly + continuation, duplicate-override policy.
- Admin contradiction-declaration UX polish (§7.3) — optional.

### 8.3 Intentionally deferred architecture (unchanged)

Vector similarity stays governed by ADR 0008 (deferred with re-entry
triggers); INELIGIBLE score band stays reserved vocabulary; the
object-storage payload backend option stays open (ADR 0006).

## 9. Documentation consistency findings

See §7.4 for the findings-and-corrections table. Scan method: targeted
greps for current-tense falsehoods ("exists yet", "not started",
"IN PROGRESS", "awaiting", stale schema heads, stale admin-scope claims)
across `docs/` plus a read of the constraint/next-task/blockers sections
of `CURRENT_STATE.md` and both design-doc headers. No contradictory
architecture status lines remain after the corrections; schema-head
references all state `0017`, which matches `alembic heads`.

## 10. Phase 4 entry criteria

Phase 4 (Writer) may begin only under these inherited, immutable
assumptions:

1. Writer receives only an exact `ACCEPTED_FOR_DRAFTING` ContentBrief
   version — never a DRAFT, never a mutable reference.
2. Writer consumes the brief's pinned evidence contract (claims → exact
   `ResearchEvidence` ids through the pinned pack); it never re-researches
   from arbitrary URLs.
3. Writer cannot weaken or bypass ResearchEvidence provenance (ADR 0007
   remains non-bypassable).
4. Writer cannot silently resolve contradictions or uncertainty — the
   brief's uncertainty notes and handling instructions are binding
   contract, not suggestions.
5. Writer output (AI output generally) is never evidence and never enters
   `research_evidence`.
6. Draft creation is not publication approval; DRAFTING and every later
   state remain gated by their own explicit decisions.
7. ADR 0004 human publication approval remains later and untouched.
8. No Konsepthane production DB access is introduced (ADR 0001/0003).
9. The provider-neutral AI boundary remains — Writer generation goes
   through `contentos.ai` attempts with full identity metadata, fake
   provider in tests, no live calls in gates.
10. Phase 3 artifacts remain immutable, version-pinned inputs; no Writer
    task may mutate historical Phase 3 artifacts.
11. A Writer failure is an execution failure (typed, retryable/terminal),
    never an editorial rejection of the brief.
12. The BRIEFING→DRAFTING acceptance stays the only doorway into Writer
    work; queue completion still never advances workflow state.

**Exact next task**: `PHASE 4 TASK 1 — Writer Architecture / Drafting
Boundary Design` (design only; no implementation). The Phase 3 design
names no more specific title for the Phase 4 opener, so this direction
stands.

## 11. Verification performed

- Preflight: clean worktree at `20a6550f` on `main`; parent `4ff321f`.
- `alembic heads` → `0017`; no migration added by this audit.
- Codebase Memory graph confirmed fresh relative to HEAD (indexed at
  identical content) and used for architecture/symbol recovery; targeted
  source inspection and greps performed for every invariant claim above.
- Boundary greps at HEAD: publication/Pinterest/scheduling/analytics
  surfaces (none beyond reserved workflow vocabulary), Konsepthane
  production references (none in code; config comment forbids), `openai`
  import isolation (adapter only), raw-content exposure in API layers
  (none), evidence construction sites (one), `current_state` writers
  (WorkflowService only), generic mutation endpoints (zero).
- Canonical `.\scripts\check.ps1` re-run after the documentation edits:
  backend ruff/mypy/pytest (1081 passed), admin
  prettier/eslint/tsc/vitest (135 passed)/`next build`, repository
  checks — all green; `git diff --check` clean; dependency files
  untouched.
- Prior runtime evidence relied on (content-identical HEAD): Task 13 real
  PG editorial-orchestration run (redeliveries, commissioning race,
  commit-before-enqueue) and real Redis transport run; Task 14 real
  PG + real Redis full operator story through the real API, broker, and
  worker; GitHub CI green at `20a6550f`. No new infrastructure was spun
  up: the audit exposed no uncertainty requiring fresh runtime
  verification.

## 12. FINAL DECISION

Every §23 exit criterion passes with evidence; the full accepted chain is
demonstrated end-to-end on real infrastructure at this exact content; all
four known closure questions are dispositioned without a blocker; no
security or provenance boundary was crossed; Writer/publication remain
unimplemented and were not needed for closure.

# PHASE 3 COMPLETE

Zero remaining Phase 3 blockers. Phase 3 closes at HEAD
`20a6550f86f093fdff0d48b0a2642268563bc22b`, schema head `0017`.

Production readiness remains a separate, open concern tracked in §8.2 —
Phase 3 completeness is a statement about the accepted editorial
functional contract, not about safe unattended deployment.

Exact next task: **PHASE 4 TASK 1 — Writer Architecture / Drafting
Boundary Design** (design only).
