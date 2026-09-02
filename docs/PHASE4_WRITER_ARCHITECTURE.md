# Phase 4 - Writer Architecture / Drafting Boundary Design

Status: Accepted — Phase 4 Task 1. Written before any Phase 4 runtime
code exists; nothing below is implemented unless
`docs/memory/CURRENT_STATE.md` says so. Implementation status is tracked
by `CURRENT_STATE.md`; Writer-stage closure will be recorded by a
Writer-stage audit (§21).

Scope: the Writer / Drafting boundary only — how an exact
`ACCEPTED_FOR_DRAFTING` ContentBrief becomes an original, durable,
provenance-preserving **draft artifact**, and nothing more. Editor, QA,
human review, media provenance, scheduling, publishing, and distribution
are NOT designed here (§20 fixes where they live).

Governing rules carried forward unchanged: RESEARCH, DO NOT
TRANSLATE-AND-REPUBLISH (EDITORIAL_POLICY.md); non-bypassable evidence
provenance (ADR 0007); human approval before publication (ADR 0004,
exercised in a later stage); no Konsepthane production access (ADR
0001/0003); provider-neutral AI with attempt provenance (Phase 3 §6, ADR
0009); queue completion never advances workflow state (WORKFLOW.md,
ARCHITECTURE.md); Phase 3 artifacts are immutable version-pinned inputs
(PHASE3_CLOSURE_AUDIT.md §10).

Phase 4 begins answering: *"How does ContentOS transform an exact
accepted writing contract into original draft content without losing
provenance, uncertainty, auditability, or human-control boundaries?"*

---

## 1. The entry contract (immutable)

Writer consumes exactly one thing: an exact, immutable
`ContentBrief(status = ACCEPTED_FOR_DRAFTING)` version, identified by its
id, whose work item is in `DRAFTING`. Every permissible upstream input is
derived through that brief's pins (idea version, evidence pack version,
search-intent analysis version, claim/evidence map, exclusions,
uncertainty notes, acceptance criteria, structure-guard result, policy
snapshots).

Writer MUST NOT consume: an unaccepted DRAFT brief; "latest brief"
without exact identity; arbitrary opportunity state as its contract;
arbitrary URLs, search results, or source bodies; raw crawler payloads or
`clean_text`; provider-generated facts; Konsepthane production
pages/database; undocumented external context.

The accepted brief is the sole authority for audience, intent, angle,
required/optional sections, exclusions, uncertainty, claims, exact
eligible evidence, media needs, internal-link needs, and acceptance
criteria. Writer may not silently expand that contract. **Absence of
information is never permission to invent it.**

## 2. Module boundary

Decision: a new bounded domain package **`contentos.drafts`**, following
the exact layering the briefs package proved in Phase 3:

- **Domain artifact** (`contentos.drafts.models` / `values` /
  `repository` / `service`): what a persisted draft *is* — the
  `ContentDraft` aggregate, its claim-usage provenance rows, its status
  events, and `DraftService`, the single validated persistence path for
  BOTH machine-generated and operator-authored drafts.
- **Writer engine** (`contentos.drafts.generation` +
  `generation_schemas`): how a draft is *produced* — deterministic input
  projection, provider invocation through the existing AI boundary,
  strict output validation, idempotent materialization. Engine identity:
  `writer/1` (manual path: `manual-draft-input/1`).
- **AI provider boundary**: unchanged — `contentos.ai` (protocol, DTOs,
  validation pipeline, `ai_generation_attempts`, fake provider, OpenAI
  adapter per ADR 0009). No Writer-specific provider abstraction is
  created; the existing boundary already covers it.
- **Workflow orchestration**: unchanged home — a new job in
  `contentos.worker.editorial_tasks` (§15) under the same Phase-2/3
  delivery contract.
- **Editor**: a future downstream consumer (`contentos.editing`,
  architecture in a later task). Not part of Writer implementation; §17
  fixes only the handoff contract.

The module is named for the persisted domain (`drafts`), not the engine
(`writer`), so orchestration/provider concerns never leak into the
artifact's identity — the same reasoning that named `contentos.briefs`
rather than `contentos.composer`.

## 3. The draft artifact

Decision: **`ContentDraft` — immutable, versioned rows; identity
`work_item_id + version`; no separate logical-draft id.**

- One draft lineage exists per work item (exactly as `ContentBrief`
  versions do); `logical_draft_id` would duplicate `work_item_id` with no
  additional meaning. `UNIQUE(work_item_id, version)` with a
  service-allocated monotonically increasing version.
- Every generated draft is immutable: a changed draft is a NEW version;
  historical content is never mutated in place (§14 fixes the DB-level
  enforcement). The single mutable projection is `status`
  (`active` → `superseded`, §11), guarded status-only-forward.
- Multiple drafts from the same accepted brief are legitimate
  (regeneration, rework after a CHANGES_REQUESTED return); §10's identity
  semantics prevent uncontrolled duplication.

Core fields (conceptual; exact DDL in §14): id (UUID PK), work_item_id,
content_brief_id (the EXACT accepted brief version), version, locale,
market (copied from the brief at creation — explicit, never implicit
Turkish), origin (`writer_engine` | `operator`), generation_attempt_id
(NULL exactly when origin is `operator`), manual_input_hash (NOT NULL
exactly when origin is `operator` — the manual-path idempotency identity,
§10), engine_name/engine_version,
title_proposal (nullable — a proposal, never a final headline),
body (structured content, §4), body_schema_version, claim-usage rows
(§5), uncertainty_coverage (validator result, §7), validation and
originality policy snapshots + originality_result (§6), status,
superseded_by_draft_id, content_hash (SHA-256 over the canonical-JSON
whole version), created_at.

## 4. Draft content representation

Decision: **bounded structured JSON body with inline-Markdown text
fields** (`writer-draft-body/1`), plus relational claim-usage rows. Not a
free Markdown blob, not a free-form JSON blob, not a relational
block-per-row explosion.

Shape (validated, `extra=forbid` semantics, all lengths/counts bounded):

- `sections`: ordered list. Each: `key` (must satisfy the accepted
  brief's section contract — every brief required-section key present
  exactly once; optional-section keys allowed; unknown keys rejected),
  `heading` (plain text), ordered `blocks`.
- `blocks`: each has `block_id` (unique within the draft, stable anchor),
  `kind` ∈ {`paragraph`, `list`, `how_to_step`, `callout`, `faq_item`,
  `internal_link_need`, `media_need`}, `text` (bounded; inline Markdown
  only — emphasis/lists; **no HTML, no scripts, no URLs, no images**),
  `claim_refs` (list of BriefClaim UUIDs used in this block),
  `uncertainty_refs` (ids from the required-handling manifest this block
  discharges, §7), and kind-specific bounded fields
  (`internal_link_need.link_need_ref` → an entry of the brief's
  `internal_link_needs`; `media_need.media_need_ref` → an entry of the
  brief's `media_needs`).

Why this choice: deterministic persistence and hashing (canonical JSON);
machine validation (every gate in §6–§8 operates on typed blocks, not
prose scraping); auditability (claims and caveats anchor to block ids);
future Editor revisions (block-level diffs between immutable versions);
originality checks (structure is explicit); safe publication
transformation later (Markdown-per-block renders without an HTML
sanitizer in the editorial store). Plain Markdown alone was rejected
because claim/caveat anchoring and structural validation would depend on
fragile text parsing; block-per-row relational storage was rejected as
heavy for content that is always read/written as one immutable version —
the relational needs (claim provenance queries) are served by
`draft_claim_usages` instead. The representation is versioned
(`body_schema_version`), so this decision is evolvable, not irreversible.

## 5. Draft-level claim provenance

Decision: **`Draft → DraftClaimUsage → exact BriefClaim →
BriefClaimEvidence → exact ResearchEvidence`.** The Phase 3 chain is
extended, never replaced.

- Every block's `claim_refs` are mirrored 1:1 into relational
  `draft_claim_usages` rows at persistence (draft_id, brief_claim_id,
  section_key, block_id) — validated to match the body exactly, so the
  indexed relational view and the content can never disagree.
- Evidence identities are NOT duplicated at draft level: the brief claim
  already pins its exact evidence rows, and duplicating links would
  create a second source of truth. The question *"why was this factual
  statement allowed into this draft?"* resolves as: block anchor →
  DraftClaimUsage → BriefClaim (kind, handling) → BriefClaimEvidence →
  ResearchEvidence → NormalizedDocument → FetchSnapshot → Source.
- A bare end-of-article citation list, a source URL, or raw AI output is
  never provenance; none of those forms exist in the body schema.

Per claim kind (Phase 3 vocabulary), the Writer rules are:

| Claim kind | Writer may | Validator enforces |
| --- | --- | --- |
| FACTUAL | state it, phrased originally | every block containing factual content carries `claim_refs`; the claim must be a pinned brief claim (which Phase 3 already forced to carry eligible evidence) |
| SOURCE_ASSERTION | relay it AS an attributed assertion | block must reference the claim AND keep attribution wording (source-says framing); never restated as bare fact |
| OBSERVATION | describe it | claim_ref required, as factual |
| INFERENCE | present it as inference | inference framing must survive (§7 marker); never hardened into fact |
| EDITORIAL_JUDGMENT | use freely as stance/guidance | claim_ref recommended for traceability; no evidence demanded |
| INSTRUCTION | expand into steps | steps must derive from the claim/brief practical requirements; no new external facts inside steps |

A kind is never silently converted (an inference presented as a fact is a
validation failure, not a style issue).

## 6. Fact-creation rule (binding invariant)

> Writer may transform, organize, explain, and phrase the accepted brief
> claims; it may NOT introduce a new external factual assertion unless
> that assertion flows through a pinned brief claim's claim/evidence
> path. The model's pretraining knowledge is never a source.

Harmless generation that requires no new evidence: connective prose,
phrasing, transitions, rhetorical framing, editorial guidance, clearly
marked inference, instructions derived from the accepted contract.
Content that ALWAYS requires provenance: dates, prices, counts,
statistics, historical assertions, legal/regulatory statements,
medical/safety claims, product specifications, named factual
comparisons — any externally verifiable factual statement.

Prompt instructions state this rule but are NEVER the enforcement.
Deterministic post-generation validation (versioned policy
`writer-validation/1`, applied by `DraftService` before ANY draft row is
created — for machine and operator drafts alike):

1. **Claim-reference validity**: every `claim_refs` entry must be a claim
   of the EXACT pinned brief; unknown/foreign ids fail closed.
2. **Numeric-assertion gate**: any block text containing numeric factual
   tokens (digits, percentages, currency, year-like tokens) outside an
   allowlisted pattern set (list positions, step numbers, quantities
   explicitly present in a referenced claim's text) must carry
   `claim_refs`; otherwise validation fails. This is a deliberately
   conservative lexical gate — deterministic, honest about its limits.
3. **Kind rules** of §5 (attribution framing for SOURCE_ASSERTION,
   inference framing for INFERENCE).
4. **Exclusion compliance**: brief exclusions are checked as bounded
   deterministic text rules where mechanically checkable (e.g. forbidden
   topics/terms recorded by the brief); non-mechanical exclusions remain
   visible contract for Editor/QA.
5. **URL/HTML ban**: no URLs, no HTML/script in any text field (§18/§19
   handle links and media as placeholders).

**What is deterministic and what is not — the truthful boundary.** The
gates above (known claim refs only, required claim refs present, the
numeric/date/statistic-like assertion gate per versioned policy,
SOURCE_ASSERTION attribution and inference/editorial-judgment framing
requirements, structurally detectable exclusion enforcement, required
uncertainty/caution references, the URL/HTML/script prohibition,
schema/body structural validation, no unknown claim or evidence
identifiers, no raw source material) ARE deterministic hard gates and
fail closed at persistence.

What NO deterministic syntax check can prove is semantic claim
faithfulness: that every natural-language sentence is actually entailed
by its referenced BriefClaim. This architecture does not claim that
certainty. The semantic layer is placed explicitly:

- Writer persistence keeps the conservative deterministic fail-closed
  envelope above, plus the architectural guarantee that the model never
  receives source bodies to copy facts from (§9).
- A future governed **semantic claim-faithfulness check** may be
  model-assisted — provider-neutral through `contentos.ai`, auditable as
  attempts, versioned as policy. Its output is a POLICY/QA *signal*,
  never Evidence, and never a substitute for provenance.
- Editor and especially QA perform factual-consistency and
  unsupported-claim review against the exact `DraftClaimUsage →
  BriefClaim → ResearchEvidence` chain — that chain exists precisely so
  the semantic question is checkable later.
- The system never claims semantic certainty it did not actually prove;
  read models and audits describe the Writer gates as the deterministic
  envelope they are.

## 7. Uncertainty and contradiction propagation

Uncertainty is contract, not decoration. The Writer input carries a
deterministic **required-handling manifest** computed from the pinned
artifacts: each entry has a stable `handling_id`, a kind
(`uncertainty_note` | `licensing_caution` | `staleness` |
`locale_limitation` | `contradiction_cautious_wording` |
`claim_handling`), the source identity (brief note index, pack caution,
contradiction id, claim id), and the required behavior.

Sources: brief `uncertainty_notes` (all mandatory notes from Phase 3,
including missing-signal and inventory-not-verified notes), pack
licensing cautions / staleness notes / locale limitations, unresolved
non-blocking contradictions and resolved-cautious-wording contradictions
from the pinned pack, and per-claim `handling` strings.

Rules:

- The model must discharge every manifest entry: either a block carries
  the corresponding `uncertainty_refs` entry with compliant wording, or —
  for document-level caveats — a dedicated callout block does.
- The validator fails the output when any mandatory handling id is
  undischarged (a disappeared caveat is a validation failure).
- Deterministic wording checks where mechanical: a
  `contradiction_cautious_wording` entry requires hedged framing in the
  discharging block; certainty-hardening ("may" → "does") of a manifest
  entry's subject is Editor/QA territory beyond the mechanical envelope,
  but *removal* is caught here.
- The full coverage result (`uncertainty_coverage`: manifest → block ids)
  is persisted on the draft, so the future Editor/QA and the operator can
  inspect exactly how each caution survived.
- A model may never silently choose one side of a conflict: conflicting
  claims arrive only with their contradiction handling entries attached.

## 8. Writer output contract

The provider never returns a raw string as the contract. Strict typed
schema **`WriterDraftV1`** (`extra="forbid"`, all bounds explicit),
validated through the existing `contentos.ai` structured-output pipeline:

- `title_proposal` (bounded, optional).
- `sections[]` → `blocks[]` exactly as §4 (the model emits the same shape
  the body stores, minus system-owned fields).
- per-block `claim_refs` (UUIDs from the projected claim set only),
  `uncertainty_refs` (handling ids from the manifest only).
- `generation_notes` (bounded, non-persisted-as-content; recorded only in
  validation diagnostics if needed).

Validation rules: bounded section/block counts and lengths; section keys
limited to the brief contract; identifiers valid and unique
(`block_id`); claim refs ⊆ projected claims; handling refs ⊆ manifest; no
unknown evidence ids anywhere (evidence ids are not even part of the
output vocabulary — the model references claims, never evidence
directly); no URLs/HTML/script; no secrets/provider objects. System-owned
fields (ids, versions, hashes, policy snapshots, coverage results, status,
engine identity) are NOT in the model schema — smuggling is schema-
rejected, following the Phase 3 pattern.

Invalid output ⇒ the generation attempt persists with
`VALIDATION_FAILED`, **no draft row exists, no workflow state changes.**

## 9. Writer input projection

`WriterInputProjection` is built deterministically from the exact
accepted brief and its pins; its canonical-JSON hash is the attempt input
hash. Contents (all bounded):

- **ContentBrief**: intent summary, content objective, original angle,
  target audience, locale/market, required/optional sections (key,
  heading guidance, purpose), exclusions, uncertainty notes, internal
  link needs, media needs, FAQ questions, acceptance criteria, title
  guidance, practical requirements.
- **Brief claims**: id, key, text, kind, handling, and for each claim the
  bounded statements of its EXACT pinned evidence (id, bounded statement
  ≤500 chars, verification status, source slug + trust tier, freshness) —
  reusing the Phase 3 bounded-evidence-projection discipline
  (`brief-evidence-projection` precedent).
- **EvidencePack**: sufficiency + relevant cautions (licensing,
  staleness, locale) and contradiction entries with resolution states.
- **SearchIntentAnalysis**: primary/secondary intents, page purpose,
  likely format, query concepts, missing signals.
- **Idea**: working title, angle, audience, value proposition, validated
  planning dimensions, exclusions.
- **WorkItem**: locale, market, working title label.
- **Required-handling manifest** (§7).

Explicitly forbidden — Writer never receives: raw payloads, HTML bodies,
`clean_text` or any whole normalized article body, crawler
headers/cookies/credentials, database or broker URLs, provider secrets,
arbitrary source documents, evidence of other opportunities, raw provider
responses from prior attempts, source URLs. Every evidence-derived datum
stays attached to its `ResearchEvidence` id inside the claim projection.
Minimal-necessary projection is the rule; it is also the strongest
anti-copy control: **the model cannot mirror text it never receives.**

## 10. Attempt semantics and idempotency

The Phase 3 AI boundary is reused verbatim; purpose vocabulary gains
**`WRITER_DRAFT`** (a `string_enum` CHECK-constraint extension —
migration work in the implementing task, no new attempt table).

Attempt records (existing columns): purpose, provider/model/version,
schema `writer-draft/1`, template `writer-draft/1`, input refs (exact
brief id + work item id + engine/policy identities + schema marker),
input snapshot hash, retry_number, status, usage, error class,
timestamps. No raw prompt/output persistence — the existing explicit
policy stands and Writer adds no exception.

Identities (mirroring Tasks 9/10/12 exactly):

- **Generation identity** = attempt identity hash over (purpose, provider
  identity, schema/template versions, input snapshot hash, retry_number).
  Same inputs + same retry_number ⇒ the same durable attempt, reused
  without a provider call.
- **Draft artifact identity (machine path)** = `generation_attempt_id
  UNIQUE` on `content_drafts`: one successful attempt materializes
  exactly one draft. Reused SUCCEEDED attempt ⇒ its existing draft is
  returned.
- **Draft artifact identity (manual path)**: `UNIQUE(generation_attempt_id)`
  cannot protect operator-authored drafts (their attempt id is NULL), so
  the manual path gets its own durable identity: **`manual_input_hash`**
  = SHA-256 over the canonical JSON of {exact accepted brief id, body
  schema version, canonical structured body, canonical DraftClaimUsage
  mapping, required-handling coverage, Writer validation policy version}.
  Persisted on the row; enforced by a partial unique index
  `(work_item_id, manual_input_hash) WHERE origin='operator'`. The SAME
  exact operator submission (or its redelivery) converges on the SAME
  durable draft — the service pre-checks by identity and returns the
  existing row (`created=False`) regardless of its later status; a
  substantively changed body/mapping/coverage/policy hashes differently
  and creates a new version. `request_id` remains correlation metadata
  only and never participates in business identity. Race recovery follows
  the established ContentOS pattern: insert under `begin_nested()`, and on
  the unique-violation IntegrityError re-read by identity and return the
  concurrent winner — never a duplicate version, never a client error for
  an honest retry.
- **Dangerous case** (attempt SUCCEEDED, materialization failed): the
  committed SUCCEEDED attempt has no draft; since raw output is never
  persisted it cannot be re-materialized — typed
  `IncompleteDraftMaterializationError`; recovery is an explicit new
  provider invocation with `retry_number + 1` (distinct durable attempt).
  A persistence rejection of validated output keeps the attempt's real
  status (never relabeled).

Distinct operations, never conflated: **Celery redelivery** re-executes
and converges on the same attempt/draft (no duplicates); **provider
retry** (timeout/provider-error) is a DOMAIN retry with a distinct
retry_number per attempt; **operator regeneration** (§12) is a new
explicit command producing a new version; **future Editor revision** is a
different artifact family entirely and never touches Writer rows.

## 11. Draft status model

Decision: minimal two-value status on the artifact — **`active` |
`superseded`** — plus append-only `draft_status_events`.

- Validity is a precondition of existence: invalid output never becomes a
  draft, so no GENERATED/VALIDATED split exists.
- FAILED belongs to attempts, not drafts.
- Editorial rejection belongs to workflow/Editor decisions, not to
  historical draft content.
- Supersession: the previous `active` draft becomes `superseded` (with
  `superseded_by_draft_id`) in the same transaction that creates its
  replacement; enforced status-only-forward by a guarded trigger (the
  `content_briefs` pattern). Historical drafts never disappear.
- At most one `active` draft per work item (partial unique index).

## 12. Regeneration

Explicit business command only — no generic `/regenerate` architecture.
Conceptual command: **regenerate draft from the exact accepted brief**,
operator-triggered under the single-operator boundary, with a required
reason (editorial judgment is being recorded).

- Allowed only while the work item is in `DRAFTING` — before the
  automatic advance of §13 (e.g. after failed generation attempts), or
  after a rework return to DRAFTING once the named CHANGES_REQUESTED
  responsible-state routing foundation (§13, §22 Task 6) exists. Outside
  DRAFTING the command is a typed conflict; no rework-from-EDITING flow
  is exposed before that foundation ships.
- The previous draft remains immutable; the new version supersedes it
  (§11) with the reason on the status event.
- Mechanically: a new generation with `retry_number + 1` (or a fresh
  input hash if the brief was legitimately superseded and re-accepted —
  a different brief id is a different contract).
- If a future Editor version exists for the draft lineage, regeneration
  is refused — that rule is enforced when Editor architecture lands, and
  Writer's design leaves the seam (the command validates downstream
  artifact absence).

## 13. Workflow semantics

`WORKFLOW.md` fixes the entry condition for `EDITING` as **"Draft version
exists"** — an artifact gate, not a judgment gate. The accepted design's
human gates are commissioning, brief acceptance, and publication
approval; nothing mandates a human gate between Writer and Editor, and
the Editor stage is itself where quality review begins.

Decision: **automatic SYSTEM transition after a valid durable Writer
draft** — the pack-READY precedent, not a new operator gate:

1. durable validated `ContentDraft` (+ claim usages, coverage, status
   rows) is committed — TX A;
2. explicit `WorkflowService.transition(work_item, EDITING,
   actor_origin=SYSTEM, artifact_refs={draft id, version, content hash,
   brief id})` — TX B, committed;
3. downstream Editor dispatch happens only after that commit — and is
   **absent until Editor exists** (the handoff boundary of §17); items
   rest truthfully in `EDITING`.

Queue completion itself is never the state change — the transition is an
explicit service call gated on the durable artifact, with the exact draft
identity pinned in the event. Redelivery after the transition follows the
Phase 3 `_require_compatible_entry` pattern (history must pin the same
draft; incompatible history is a typed conflict, never repaired).

**Rework path — a declared Phase 4 dependency, NOT currently
operational.** The desired canonical behavior is `EDITING →
CHANGES_REQUESTED → DRAFTING`. The CURRENT runtime `WorkflowService`
cannot do this: its documented Task-2 limitation is that
`CHANGES_REQUESTED` may return only to the state it was entered FROM
(derived from durable history), so entering from `EDITING` permits a
return only to `EDITING`. This design does not claim a transition the
runtime cannot perform. Instead, Phase 4 adds a dedicated prerequisite —
the **named CHANGES_REQUESTED responsible-state routing foundation**
(§22 Task 6) — which must exist BEFORE any Writer rework/regeneration
flow that returns from `EDITING` to `DRAFTING` is exposed. Its binding
requirements:

- routing remains controlled by `WorkflowService`; a caller can NEVER
  supply an arbitrary target state (this must not become a generic state
  setter);
- the responsible state is recorded durably and auditably WHEN
  `CHANGES_REQUESTED` is entered (in the entry event's validated
  `artifact_refs`/metadata), with a required reason;
- the responsible target is validated against what is permitted for the
  current review context (from `EDITING`, the permitted responsible
  states are the canonical upstream production stages — initially
  `DRAFTING` — never an arbitrary state);
- the exit transition is derived from that durable record/history, and
  falls back to the existing return-to-origin behavior when no
  responsible state was recorded (full backward compatibility);
- existing `BLOCKED` semantics are untouched;
- normal append-only workflow audit events are written throughout.

Until that foundation ships, initial Writer generation and
`DRAFTING → EDITING` are fully operational, but Writer rework from
`EDITING` is explicitly NOT claimed operational. Regeneration (§12) is
correspondingly available only while the work item is genuinely in
`DRAFTING` (e.g. after failed generation attempts), and additionally
after a rework return once the routing foundation exists.

Failure behavior (see §16 taxonomy): provider failures retry within the
existing bounded DOMAIN policy; validation/policy failures are terminal
per attempt with the durable failed attempt as the operator-visible
record; the work item **stays in DRAFTING** — truthful and resumable via
explicit re-command. Execution failure NEVER becomes `REJECTED` (that is
an editorial decision reserved to humans) and never fabricates a draft or
a transition. `BLOCKED` is reserved for durable domain impossibility
discovered at the boundary (e.g. the pinned brief was superseded while
the item sat in DRAFTING — a state requiring operator resolution), never
for transient execution failure; the existing resolve-block command is
the recovery path.

## 14. Data model plan (implementation-ready; NO migration in Task 1)

**`content_drafts`**

| Aspect | Decision |
| --- | --- |
| PK | `id UUID` |
| FKs | `work_item_id → editorial_work_items.id` RESTRICT; `content_brief_id → content_briefs.id` RESTRICT; `generation_attempt_id → ai_generation_attempts.id` RESTRICT NULL; `superseded_by_draft_id → content_drafts.id` RESTRICT NULL |
| Uniqueness | `UNIQUE(work_item_id, version)`; `UNIQUE(generation_attempt_id)` (one draft per successful attempt — machine path); partial unique `(work_item_id, manual_input_hash) WHERE origin='operator'` (manual-path idempotency, §10); partial unique `(work_item_id) WHERE status='active'` |
| Columns | version INT ≥1; locale; market; origin (`writer_engine`\|`operator` via string_enum CHECK); manual_input_hash CHAR(64) NULL; engine_name; engine_version; title_proposal NULL; body JSONB (`writer-draft-body/1`); body_schema_version; uncertainty_coverage JSONB; validation_policy_snapshot JSONB; originality_policy_snapshot JSONB; originality_result JSONB; status (`active`\|`superseded`); content_hash CHAR(64); created_at |
| CHECKs | `(origin='operator') = (generation_attempt_id IS NULL)`; `(origin='operator') = (manual_input_hash IS NOT NULL)`; version ≥ 1; status vocabulary |
| Immutability | append-only guarded trigger: UPDATE may change ONLY `status` (forward `active→superseded`) and `superseded_by_draft_id` (NULL→value, once); DELETE forbidden; no repository update/delete surface for content fields |
| Indexes | (work_item_id, version DESC); content_brief_id; generation_attempt_id; (status, work_item_id) |
| Audit | content_hash = SHA-256 canonical JSON over the whole immutable version; policy snapshots persisted per row |

**`draft_claim_usages`** (append-only)

| Aspect | Decision |
| --- | --- |
| PK | `id UUID` |
| FKs | `draft_id → content_drafts.id` RESTRICT; `brief_claim_id → brief_claims.id` RESTRICT |
| Columns | section_key; block_id; created_at |
| Uniqueness | `UNIQUE(draft_id, brief_claim_id, block_id)` |
| Behavior | written only at draft creation, validated 1:1 against body `claim_refs`; no update/delete |
| Indexes | draft_id; brief_claim_id |

**`draft_status_events`** (append-only)

| Aspect | Decision |
| --- | --- |
| PK | `id BIGINT` identity (monotonic) |
| FKs | `draft_id → content_drafts.id` RESTRICT; `replacement_draft_id` RESTRICT NULL |
| Columns | from_status; to_status; actor_origin (`operator`\|`system`); reason; request_id NULL; occurred_at |
| Behavior | one event per status change, same transaction; no update/delete |

**`ai_generation_attempts`**: unchanged table; the `purpose` CHECK
constraint gains `writer_draft` (constraint replacement in the same
migration). No draft-side evidence link tables exist by design (§5).

Expected migration: **0018** in the first implementation task — verify
the actual next revision id at implementation time; never assume.

## 15. Celery plan (design only)

- Task name: **`contentos.editorial.generate_writer_draft`** — the
  editorial namespace continues (same pipeline family, same queue, same
  delivery contract); a new namespace would add operational surface
  without meaning.
- Input DTO (JSON-safe kwargs): `{content_brief_id, retry_number=0,
  supersede_reason=None}` — the exact brief id is the pin; work item and
  all upstream artifacts derive from it. No URLs, no free JSON.
- Guards inside the task: brief exists, status ACCEPTED_FOR_DRAFTING,
  its work item is in DRAFTING (redelivery-compatible-entry check when
  already advanced), regeneration semantics per §12.
- Execution: TX A — engine runs (attempt + validated draft materialized,
  or failed attempt committed); TX B — SYSTEM transition to EDITING with
  draft refs; commit; **no downstream dispatch** until Editor exists.
- Retry classes: existing DOMAIN vs DISPATCH separation; TIMEOUT /
  transient PROVIDER_ERROR retry within the bounded no-jitter policy with
  a distinct durable attempt per retry (`retry_number = base + task
  retries`); VALIDATION_FAILED / CANCELLED terminal; failed attempts
  committed before any DOMAIN retry.
- Idempotency: redelivery converges on the same attempt/draft/transition
  (identities of §10); no uncontrolled duplicates possible
  (`UNIQUE(generation_attempt_id)` is the DB backstop).
- Commit↔broker gap: Writer inherits the accepted Phase 3 delivery
  semantics unchanged. Nothing here is qualitatively different — a lost
  enqueue loses only the enqueue, the operator re-command is idempotent,
  and the outbox decision stays exactly where the Phase 3 closure audit
  placed it: production-readiness backlog. Writer must not make it worse
  (single commit-before-enqueue discipline, no fire-before-commit).

## 16. Failure model

| Class | Examples | Behavior |
| --- | --- | --- |
| Input/domain | brief not accepted; brief superseded/incompatible; work item in the wrong state; provenance chain unresolved; claim/evidence map invalid | typed terminal error BEFORE any provider call (zero AI spend); no attempt row where no generation was attempted; work item state unchanged |
| Provider/execution | timeout; provider error | durable failed attempt; bounded DOMAIN retry with distinct retry_number; terminal `ai_failed` after the bound; stays DRAFTING |
| Model output | schema-invalid output; unknown claim ref; unsupported factual assertion (numeric gate); missing required section; undischarged mandatory handling; policy violation; unsafe structural similarity | attempt persists `VALIDATION_FAILED` (terminal per attempt); NO draft row; explicit re-command (retry_number+1) is the retry path |
| Infrastructure | DB failure; broker failure | transaction rolls back whole (no partial artifacts); DISPATCH retries for enqueue-only failures; redelivery converges |

Invariants: a failure never becomes editorial `REJECTED`; never creates a
fake successful draft; never silently transitions to EDITING. Everything
is operator-visible through durable attempts and (future) read models.
`BLOCKED` only for durable domain impossibility (§13), set through
`WorkflowService` with the exact reason.

## 17. Editor handoff contract (boundary only — Editor NOT designed here)

What Writer guarantees at the moment `EDITING` is entered: an immutable
`active` ContentDraft version whose body passed every §6–§8 gate; the
exact accepted brief pinned; claim usages resolvable to brief claims and
evidence; the uncertainty-coverage record; validation/originality policy
snapshots; the workflow event pinning the draft identity.

The future Editor receives exactly: the draft version id (+ hash), the
accepted brief id, the claim-usage provenance, the required-handling
manifest and its coverage, and the relevant policy snapshots. Editor may
conceptually change prose, organization, and wording — but future Editor
architecture MUST produce its own versioned artifacts, preserve claim
provenance, keep discharged handling discharged, and can never mutate
historical Writer draft rows. Nothing more is fixed here.

## 18. Links

- Internal links: `internal_link_need` placeholder blocks referencing the
  brief's `internal_link_needs` entries only. ContentOS has no production
  inventory integration; Writer never invents an existing Konsepthane
  URL and never queries production. Resolution to real URLs is a
  publishing-era concern.
- External citations: user-facing attribution happens as source-name
  attribution wording tied to SOURCE_ASSERTION claims (whose provenance
  already pins the source). **No URLs appear in draft body text at all**
  (deterministic validator rule); user-facing citation *rendering* is a
  later transformation with access to evidence provenance. Internal
  evidence provenance (§5) and user-facing citation are distinct layers
  and never conflated.

## 19. Media

Writer receives the brief's `media_needs` and may emit `media_need`
placeholder blocks (concept description, position). Writer has no
authority over assets: nothing it outputs is licensed, cleared, or
approved; media provenance (ARCHITECTURE.md module 14) is a later
module. The body schema contains no image/asset embedding.

## 20. Phase 4 scope decision

**Phase 4 = Content Production: `Writer → Editor → QA`, ending when an
exact, validated content package reaches `AWAITING_HUMAN_REVIEW`.**
Phase 4 exit means *the content is ready for an authorized human review
decision* — it does NOT mean an authorized human has approved
publication. **`APPROVED` is outside Phase 4** and belongs to the next
governance/review phase: ADR 0004 requires an *authorized human* to
approve the exact content, evidence, QA, and media versions, and the
current runtime deliberately has no authentication/RBAC/
authorized-reviewer identity architecture — that identity/approval
boundary must be designed by the next phase before `APPROVED` can be
implemented, and is NOT pulled into the production phase. Scheduler,
Publishing, Pinterest, and Analytics remain later still (ADR 0003/0004
keep publication integration a separate boundary).

The next-phase handoff therefore begins from `AWAITING_HUMAN_REVIEW`:
Phase 4 delivers the package and the workflow position; the follow-on
phase designs authorized-human identity and the approval decision
surface.

Three acknowledged Phase 4 dependencies fixed now: (a) `QA_REVIEW` entry
requires "edited version and eligible media set exist" (WORKFLOW.md), so
a minimal media-eligibility slice must be scoped by the QA-stage
architecture task — NOT by Writer; (b) the named CHANGES_REQUESTED
responsible-state routing foundation (§13) must exist before Writer
rework from EDITING is exposed (§22 Task 6); (c) richer review-loop
routing beyond that foundation belongs to the Editor/QA stage designs.

This Task 1 governs the **Writer stage only**; §21 defines when the
Writer stage is complete. Phase 4 as a whole closes only after Editor
and QA, under its own eventual closure audit.

## 21. Writer-stage exit criteria

The Writer stage is complete when:

- [ ] generation requires an exact `ACCEPTED_FOR_DRAFTING` brief (typed
      failure otherwise, no provider spend)
- [ ] immutable, versioned `ContentDraft` exists with append-only DB
      enforcement and status-only-forward supersession
- [ ] draft claim provenance resolves: block anchor → DraftClaimUsage →
      BriefClaim → ResearchEvidence (ADR 0007 chain intact end-to-end)
- [ ] the deterministic Writer-stage envelope fails closed (known claim
      refs only, numeric-assertion gate, kind/framing rules, required
      handling, URL/HTML ban — §6); no draft row from invalid output;
      semantic claim-faithfulness is explicitly delegated to Editor/QA
      (and any future governed model-assisted check is a policy signal,
      never Evidence) — the system claims no semantic certainty it did
      not prove
- [ ] uncertainty/contradiction required handling survives, with a
      persisted coverage record; disappeared caveats fail validation
- [ ] originality/copyright guard exists (no source bodies in the
      projection; verbatim-overlap and structure-conformance gates as
      versioned policy)
- [ ] provider-neutral AI boundary reused; purpose `WRITER_DRAFT`
      attempts carry full identity/provenance metadata; no raw
      prompt/output persisted
- [ ] deterministic fake-provider Writer tests exist; automated gates
      never call a live provider
- [ ] idempotent generation and explicit regeneration exist (one draft
      per successful attempt; redelivery/duplicate-safe; supersession
      audited); rework from EDITING is exposed only once the named
      CHANGES_REQUESTED responsible-state routing foundation exists
- [ ] the SUCCEEDED-attempt/failed-materialization case has a typed error
      and a defined retry_number+1 recovery
- [ ] `DRAFTING → EDITING` happens only via `WorkflowService` after a
      valid durable draft commits, SYSTEM actor, draft identity pinned in
      the event; queue completion alone never advances state
- [ ] operator-authored drafts (origin `operator`) pass the identical
      validation path with no fake AI attempt, and carry the durable
      `manual_input_hash` idempotency identity (identical resubmission
      reuses the same draft; a changed submission is a new version)
- [ ] operator can inspect drafts, provenance, coverage, attempts, and
      failures through read models/admin; no raw provider data, secrets,
      or source bodies exposed
- [ ] no publication/approval/scheduling boundary crossed; no Konsepthane
      production access; failures are visible, truthful, and never become
      editorial rejection
- [ ] real-PostgreSQL (and broker, where orchestration is in scope)
      verification of the full DRAFTING story, then a Writer-stage audit
      against these criteria

## 22. Phase 4 implementation order (atomic, dependency-correct)

Task 1 — this architecture (docs only). Then:

**Task 2 — Draft persistence + provenance foundation.**
Scope: `contentos.drafts` models/values/repository + migration (expected
`0018`: `content_drafts`, `draft_claim_usages`, `draft_status_events`,
purpose CHECK gains `writer_draft`); body schema `writer-draft-body/1`
structural validation; `DraftService.create_draft` covering BOTH origins
with §6.1/§6.5 structural gates (claim-ref validity, URL/HTML ban,
section-contract conformance, claim-usage mirroring), supersession, and
immutability triggers. Dependencies: none beyond Phase 3. Migration: YES.
Runtime: yes + tests (SQLite + real-PG incl. trigger/downgrade cycles).
Acceptance: immutable versioned drafts with resolvable provenance and
operator-authored path. Non-goals: AI generation, policies of Task 3,
workflow transition, API/admin.

**Task 3 — Writer validation & originality policies.**
Scope: versioned `writer-validation/1` (numeric-assertion gate, kind
rules, exclusion checks) and `writer-originality/1` (evidence-statement
verbatim-overlap cap, brief-structure conformance, heading-similarity
reuse of the Phase 3 structure-guard mechanics) + required-handling
manifest builder and coverage validation, all enforced inside
`DraftService`. Dependencies: Task 2. Migration: none. Acceptance:
unsupported facts/undischarged handling/structure mirroring fail closed
with typed reasons; policy snapshots persisted. Non-goals: provider
calls, thresholds beyond versioned policy config.

**Task 4 — Writer input projection, output schema, and engine.**
Scope: `WriterInputProjection` (deterministic, bounded, hashed),
`WriterDraftV1` + template/schema `writer-draft/1`, `WriterEngine`
(`writer/1`) through `contentos.ai` with the fake provider: attempt
identity, pre-provider short-circuits, idempotent materialization,
`IncompleteDraftMaterializationError` + retry_number+1 recovery. The
existing OpenAI adapter works unchanged through the boundary — no
adapter task exists. Dependencies: Tasks 2–3. Migration: none (purpose
value shipped in Task 2). Acceptance: same-identity reuse without
provider calls; validation failures leave zero draft rows; no live
provider in gates. Non-goals: Celery, workflow transition, API.

**Task 5 — Writer orchestration + DRAFTING→EDITING wiring (initial
generation only).**
Scope: `contentos.editorial.generate_writer_draft` under the Phase 2/3
delivery contract (WorkerRuntime provider seam, DOMAIN/DISPATCH retries,
redelivery guards), TX A/TX B with the SYSTEM transition and pinned draft
refs. Initial generation does NOT require Editor implementation and does
NOT expose any rework/regeneration-from-EDITING flow. Dependencies:
Task 4. Migration: none. Acceptance: real-PG + real-Redis verification of
generate → durable draft → EDITING, failure truthfulness, redelivery
idempotency. Non-goals: rework routing, regeneration commands, Editor
dispatch, admin.

**Task 6 — Named CHANGES_REQUESTED responsible-state routing
foundation.**
Scope: the `WorkflowService` enhancement of §13 — durably record a
validated responsible state (with required reason) when
CHANGES_REQUESTED is entered, derive the exit from that durable record,
validate targets per review context (EDITING → DRAFTING initially),
preserve return-to-origin fallback and BLOCKED semantics, normal audit
events; never a caller-supplied arbitrary transition, never a generic
state setter. Dependencies: none on Tasks 2–5 (workflow core), but
sequenced here because nothing needs it earlier. Migration: none
expected (the durable record lives in the validated entry-event
`artifact_refs`); verify at implementation time. Acceptance: EDITING →
CHANGES_REQUESTED(responsible=DRAFTING) → DRAFTING works under
WorkflowService with full audit; arbitrary targets impossible; legacy
entries still resolve return-to-origin. Non-goals: Editor/QA review-loop
semantics beyond the foundation.

**Task 7 — Writer rework + regeneration command surface, read models,
and admin.**
Scope: explicit operator commands (generate, regenerate with reason,
operator-authored draft submission with manual-idempotency semantics,
rework-return EDITING→CHANGES_REQUESTED(responsible=DRAFTING)→DRAFTING);
`/internal/editorial` draft read projections (versions, body,
claim→evidence chain, coverage, attempts, history) + private admin draft
screens, following the Task 14 patterns (server-only boundary, reasons
required, truthful unknowns, no raw provider data). Dependencies: Tasks
5 AND 6 (rework depends on the routing foundation — the dependency is
explicit, not hidden). Migration: none. Acceptance: operator story
inspectable and drivable end-to-end incl. rework/regeneration; leak
tests. Non-goals: Editor UI, publication anything.

**Task 8 — Writer-stage audit.**
Scope: docs-only audit against §21; disposition of Writer-stage
limitations; go/no-go for the Editor stage. Migration: none.

**Task 9 — Editor architecture (design only)** — opens the next stage
under §17's handoff contract, only after Writer-stage closure.
Subsequent Editor/QA implementation ordering (through the package
reaching `AWAITING_HUMAN_REVIEW`, §20) is fixed by that and later design
tasks, not here.

## 23. ADR disposition

No new ADR. Every decision above lives in this accepted design:
provenance and publication boundaries are already governed by ADR 0004 /
0007 (extended, not changed); the provider boundary by ADR 0009; no
Konsepthane access by ADR 0001/0003. The draft body representation —
the closest candidate — is explicitly versioned
(`body_schema_version` + `writer-draft-body/1`), making it an evolvable
design decision rather than a cross-phase irreversible commitment; the
ADR directory (0001–0009 at the time of writing) therefore gains
nothing.
