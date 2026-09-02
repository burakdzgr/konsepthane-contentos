# Phase 3 - Editorial Intelligence / Idea Engine Design

Status: Accepted design — Phase 3 Task 1. No Phase 3 runtime code exists
yet; nothing below is implemented unless CURRENT_STATE.md says so.

Scope: the middle of the pipeline —
eligible Phase 2 research → EditorialWorkItem → EditorialOpportunity →
Idea → EvidencePack → SearchIntentAnalysis → ContentBrief.
**Phase 3 stops at an accepted ContentBrief. Writer, Editor, QA, review,
scheduling, publishing, and distribution belong to Phase 4+.**

Governing rules carried forward unchanged: RESEARCH, DO NOT
TRANSLATE-AND-REPUBLISH (EDITORIAL_POLICY.md); non-bypassable evidence
provenance (ADR 0007); conservative duplicate handling while vector
similarity stays deferred (ADR 0008); human approval before publication
(ADR 0004, exercised in a later phase); no Konsepthane production access
(ADR 0001/0003); queue completion never advances workflow state
(WORKFLOW.md, ARCHITECTURE.md).

Phase 3 answers: *"What should Konsepthane create, why, on what evidence,
for which search/user need, and under exactly what writing contract?"*

---

## 1. The canonical workflow aggregate: EditorialWorkItem

### 1.1 Decision

The canonical WORKFLOW.md state machine becomes a real durable aggregate
named **EditorialWorkItem**, owned by a new foundational module
`contentos.workflow`. The name matches its meaning: one durable editorial
work identity that survives from research promotion through (in later
phases) drafting, review, publication, and refresh. Alternatives
("ContentCandidate", "EditorialItem") were considered and rejected: the
entity is not always content yet and not merely an item — it is the unit of
editorial *work* the whole organization tracks.

### 1.2 Fields (conceptual, implementation-ready)

| Field | Meaning |
| --- | --- |
| `id` | UUID — the stable editorial identity for all later phases |
| `locale` / `market` | Explicit (initially `tr-TR` / `TR`); never inferred, never part of any key |
| `origin` | `RESEARCH_INTAKE` (promoted from Phase 2) / `OPERATOR` (explicitly created, e.g. duplicate-reopen with distinct angle) |
| `current_state` | Canonical WORKFLOW.md state value (see §1.4 for the Phase 3 subset) |
| `current_state_entered_at` | Denormalized from the latest transition event |
| `title_working_label` | Short operator-facing label; NOT the content title (that lives on Idea/Brief) |
| `blocked_reason` / `rejected_reason` | Bounded operator-readable text, set only via transitions that enter `BLOCKED`/`REJECTED` |
| `created_at` / `updated_at` | Timestamps |

The aggregate deliberately carries **no** Phase 2 lifecycle state, no scores,
no evidence, and no content: those live on referenced artifacts. It is the
spine, not the body.

### 1.3 Workflow transition events (append-only)

`editorial_workflow_events` — the audit backbone required by WORKFLOW.md:

| Field | Meaning |
| --- | --- |
| `id` | BIGINT monotonic identity (append order = audit order, as in Task 2's audit table) |
| `work_item_id` | FK → editorial_work_items |
| `from_state` | Nullable (null only for the creation event) |
| `to_state` | Canonical state |
| `actor_origin` | `OPERATOR` / `SYSTEM` (a Celery job acting after a durable result) |
| `reason` | Required bounded text |
| `artifact_refs` | JSONB: the exact artifact identities/versions relevant to this transition (e.g. `{"opportunity_score_id": …, "evidence_pack_id": …}`) |
| `request_id` | Correlation identifier (existing request-context contract) |
| `occurred_at` | Timestamp |

Rules (all inherited from WORKFLOW.md and made concrete):

- Only `WorkflowService` (application service in `contentos.workflow`) may
  transition state; it validates the canonical transition matrix, writes the
  event and the denormalized `current_state` atomically, and flushes —
  callers own commit (the established Phase 2 service pattern).
- No admin/ORM direct state edits; the admin calls command endpoints that
  call the service.
- Queue/job completion NEVER advances state: a job persists its durable
  result, commits, and then *explicitly* requests a transition through the
  service, which re-checks preconditions against durable rows.
- Events are append-only (PG trigger, as with every Phase 2 audit surface).

### 1.4 Canonical-state ownership in Phase 3

WORKFLOW.md's early states are conceptually realized by Phase 2 entities;
Phase 3 owns the middle:

| Canonical state | Realized by |
| --- | --- |
| `DISCOVERED` / `RESEARCHING` / `NORMALIZED` / `DUPLICATE_CHECK` / `DUPLICATE` | Phase 2 entity lifecycles (DiscoveryItem, FetchSnapshot/NormalizedDocument, DuplicateDecision). No EditorialWorkItem exists yet in these conceptual states. |
| `IDEA_SCORING` | Phase 3: EditorialWorkItem exists; EditorialOpportunity evaluated |
| `EVIDENCE_BUILDING` | Phase 3: EvidencePack assembly + sufficiency gate |
| `SEO_RESEARCH` | Phase 3: SearchIntentAnalysis |
| `BRIEFING` | Phase 3: ContentBrief composition and acceptance |
| `DRAFTING` and beyond | Phase 4+ (the BRIEFING→DRAFTING gate is *defined* in §10.4 but exercised later) |
| `BLOCKED` / `REJECTED` / `CHANGES_REQUESTED` | Cross-cutting, Phase 3 uses them per §11 |

**Intake decision (explicit, single recommendation): promotion, not
replay.** An EditorialWorkItem is created by a defined *promotion* directly
into `IDEA_SCORING`, with a single creation event
(`from_state = NULL → IDEA_SCORING`, reason = promotion, `artifact_refs`
pinning the exact Phase 2 chain: discovery_item_id, normalized_document_id,
duplicate_decision_id, and the initial research-input set). Replaying
DISCOVERED→…→DUPLICATE_CHECK as synthetic workflow events is rejected: it
would fabricate event history that duplicates — and could drift from — the
already-authoritative Phase 2 records. The Phase 2 artifacts ARE the audit
trail for those conceptual states; the promotion event references them
instead of imitating them. This is honest state history.

---

## 2. Phase 2 → Phase 3 intake

### 2.1 Eligibility (deterministic, ADR 0008-binding)

A NormalizedDocument-rooted research signal is intake-eligible only when ALL
hold:

1. The NormalizedDocument's `normalization_status` is `SUCCEEDED`.
2. Its effective DuplicateDecision (latest per the Task 17 ordering
   contract) exists — **no decision ⇒ not eligible for automatic
   commissioning** (absence of a result is not a pass).
3. The decision outcome gates as follows:
   - `DUPLICATE` — hard stop. No automatic work item. An operator MAY
     explicitly create an `origin=OPERATOR` work item for a demonstrably
     distinct angle; that override is its own audited event carrying the
     duplicate decision reference and a mandatory reason (this realizes
     WORKFLOW.md's `DUPLICATE → RESEARCHING if a distinct angle is
     proposed` without hiding the duplicate).
   - `REJECT` — hard stop, no override path in Phase 3.
   - `UNIQUE` — eligible.
   - `RELATED` — eligible; the relationship stays attached to the
     opportunity inputs and remains visible through scoring, pack, and brief.
   - `UPDATE_EXISTING` — eligible **as an update/refresh signal**; the
     opportunity records this disposition; it is never treated as a
     new-topic guarantee.
4. Full provenance chain intact (guaranteed by Phase 2 FKs; intake
   revalidates existence, never trusts absence).

Duplicate decisions are advisory-but-gating, never infallible (ADR 0008):
every Phase 3 record retains the exact `duplicate_decision_id` used, so
later observed misses become re-entry-trigger evidence rather than silent
loss.

### 2.2 Multi-source research inputs

One opportunity aggregates many research signals.
`opportunity_research_inputs`:

| Field | Meaning |
| --- | --- |
| `opportunity_id` | FK |
| `normalized_document_id` | FK, NOT NULL, RESTRICT |
| `duplicate_decision_id` | FK, NOT NULL — the exact decision that admitted this input |
| `role` | `PRIMARY_SIGNAL` / `SUPPORTING` / `CONTRADICTING` / `CONTEXT` / `UPDATE_SIGNAL` |
| `added_by` | `SYSTEM` (intake) / `OPERATOR` |
| `note` | Bounded optional |
| `added_at` | Timestamp |

Uniqueness: (`opportunity_id`, `normalized_document_id`). Whole article
bodies are never copied into Phase 3; inputs are references. Source
diversity (distinct `source_id` count via the Phase 2 join) is computed
deterministically from this set and feeds scoring, sufficiency, and the
copyright guard: **substantive content must not be built from one competitor
article** — a single-input opportunity can exist (e.g. an official
announcement) but is flagged, and per-content-type policy (§7.3) decides
whether it may proceed.

---

## 3. EditorialOpportunity

### 3.1 Entity

An Opportunity answers "is there a worthwhile content opportunity here?" —
it is not yet the article.

| Field | Meaning |
| --- | --- |
| `id` | UUID |
| `work_item_id` | FK, UNIQUE — 1:1 logical identity with the work item's research-side question |
| `topic_summary` | Bounded operator/engine-readable description of the opportunity |
| `update_of_reference` | Optional bounded reference when `UPDATE_EXISTING` disposition applies (free note now; future inventory reference later) |
| `disposition` | `OPEN` / `COMMISSIONED` / `REJECTED` (operator decisions; see §11) |
| `disposition_reason` / `disposition_at` / `disposition_by` | Audit of the commissioning decision |
| `created_at` / `updated_at` | Timestamps |

Inputs live in `opportunity_research_inputs` (§2.2); scores are append-only
(§3.2). The opportunity row itself is a small relational anchor — not a
mutable JSON bag.

> *Implementation note (Phase 3 Task 3):* the §10.3 promotion identity is
> realized physically as `editorial_opportunities.promotion_root_document_id`
> — a NOT NULL, UNIQUE, RESTRICT FK to `normalized_documents`. This gives the
> one-root→one-work-item invariant database backing while keeping promotion
> identity fully separate from research-input roles (the same document can
> still be attached as supporting/context input to another opportunity).

### 3.2 OpportunityScore (append-only, explainable)

`opportunity_scores`:

| Field | Meaning |
| --- | --- |
| `id` | UUID |
| `opportunity_id` | FK |
| `engine_name` / `engine_version` | e.g. `opportunity-engine` / `1` (deterministic v1) |
| `overall_band` | `STRONG` / `MODERATE` / `WEAK` / `INELIGIBLE` — bands, not a bare number |
| `overall_value` | Nullable numeric alongside the band (engines may compute one; the band is the contract) |
| `eligibility` | `COMMISSIONABLE` / `NOT_COMMISSIONABLE` / `NEEDS_OPERATOR_REVIEW` |
| `weights_snapshot` | JSONB — the exact weight/config version used |
| `threshold_snapshot` | JSONB — the exact eligibility thresholds used (versioned config; **no numeric thresholds are frozen in this design**) |
| `missing_signals` | JSONB list of component names with status UNKNOWN |
| `risk_flags` | JSONB list (see §14) |
| `input_snapshot` | JSONB — exact input identities: research-input ids, duplicate_decision ids, search_signal observation ids, policy/config versions |
| `input_snapshot_hash` | SHA-256 over the canonical input snapshot (idempotency key part) |
| `evaluated_at` / `created_at` | Timestamps |

`opportunity_score_components` (relational — queryable, reportable):

| Field | Meaning |
| --- | --- |
| `score_id` | FK |
| `component` | e.g. `recency`, `audience_fit`, `evidence_availability`, `source_diversity`, `source_trust`, `competition`, `search_demand`, `editorial_value`, `seasonality`, `duplicate_overlap_risk`, `policy_risk`, `production_cost_estimate` |
| `availability` | **`KNOWN` / `UNKNOWN` / `NOT_APPLICABLE`** |
| `value` | Nullable numeric — null whenever availability ≠ KNOWN |
| `confidence` | Nullable 0..1 where meaningful |
| `provider` | Signal origin (`DERIVED_PHASE2`, `MANUAL_OPERATOR`, future provider names) |
| `observed_at` | As-of time of the underlying signal |
| `provenance_ref` | JSONB reference to the underlying rows/signal ids |

**UNKNOWN ≠ ZERO is a hard rule**: an engine must never coerce a missing
signal to 0. The v1 deterministic engine computes only from signals that
exist today (recency from `external_published_at`/`fetched_at`, source
diversity and trust from Phase 2 joins, duplicate-overlap disposition,
evidence availability from ResearchEvidence counts), renormalizes weights
over KNOWN components, records everything else UNKNOWN, and lists them in
`missing_signals`. Search demand, competition, CPC, trends, and analytics do
not exist and are **never invented**. Uniqueness/idempotency:
(`opportunity_id`, `engine_name`, `engine_version`, `input_snapshot_hash`) —
identical reruns return the stored score; changed inputs or engine version
append a new score; the effective score is the latest by
(`evaluated_at`, `id`), the same deterministic-latest pattern as Phase 2.

---

## 4. Search-signal boundary (provider-neutral)

`search_signals` is the single governed store for external/manual search and
demand observations — no provider objects in domain records:

| Field | Meaning |
| --- | --- |
| `id` | UUID |
| `signal_type` | Stable vocabulary: `SEARCH_VOLUME`, `TREND`, `SERP_OBSERVATION`, `QUERY_SET`, `MANUAL_INTENT_NOTE`, … (extensible enum) |
| `subject` | Normalized topic/query concept the signal is about |
| `locale` / `market` | Explicit |
| `provider` | `MANUAL_OPERATOR` first; future: `SEARCH_CONSOLE`, `KEYWORD_PROVIDER_<x>`, `ANALYTICS` — a governed vocabulary, not SDK types |
| `value` | JSONB typed per signal_type (bounded) |
| `confidence` | Nullable |
| `observed_at` / `as_of` | When the value was true, not when it was stored |
| `recorded_at` | Insert time |

Task 1 selects **no** provider; the only Phase 3 implementation commitment
is manual operator entry plus this storage shape. Consumers (scores, intent
analyses) reference signal ids in their input snapshots so historical
evaluations stay reconstructible. Signal age is always displayable
(`observed_at` mandatory).

---

## 5. Idea

### 5.1 Entity and versioning

An Idea is the Konsepthane-specific content concept derived from an eligible
opportunity. Multiple candidates per opportunity are expected; every
candidate and every version is immutable.

`ideas` (each row = one immutable idea version):

| Field | Meaning |
| --- | --- |
| `id` | UUID — the version identity downstream artifacts pin |
| `logical_idea_id` | UUID — stable candidate identity across versions |
| `opportunity_id` | FK |
| `version` | Integer; UNIQUE (`logical_idea_id`, `version`) |
| `working_title` | Proposed, not final |
| `angle` | The original angle — why this is not the sources' framing |
| `audience` | Who it serves |
| `value_proposition` | What problem/question it answers |
| `content_type` | Controlled vocabulary (§13) |
| `locale` / `market` | Explicit |
| `rationale` | Why meaningfully different from existing/related work (references related opportunities where known) |
| `exclusions` | JSONB list of things this content must NOT do/claim |
| `planning_dimensions` | JSONB optional structured Konsepthane dimensions (§13.2) |
| `origin` | `OPERATOR` / `MODEL_ASSISTED` |
| `generation_attempt_id` | FK → ai_generation_attempts, nullable (NOT NULL when origin is MODEL_ASSISTED) |
| `created_at` | Timestamp |

Idempotency (model-assisted generation): one generation attempt per
(`opportunity_id`, input snapshot hash, generator name+version, retry
number) — reruns with identical inputs and version are no-ops that return
existing candidates.

### 5.2 Selection (explicit, auditable, append-only)

`idea_selection_events`: `opportunity_id`, `idea_id` (exact version),
`action` (`SELECTED` / `DESELECTED`), `actor_origin` (OPERATOR only in
Phase 3), `reason`, `request_id`, `occurred_at`. The effective selected idea
is the latest `SELECTED` not followed by `DESELECTED`. Rejected/unselected
candidates are never overwritten or deleted; selection is an operator
editorial decision, distinct from any later human publication approval
(ADR 0004 untouched).

### 5.3 Originality boundary (deterministic guards)

An Idea must never be: a translation of one source title, a paraphrase of
one competitor article, a copied source outline, a fabricated user
experience/trend/statistic, or an unsupported factual claim. Architecture
support (not just prompts):

- deterministic check: for substantive content types, the parent
  opportunity's input set must span multiple distinct sources (policy
  minimum per content type/risk class, configurable, versioned — no
  universal number frozen here); failures flag the idea and block
  commissioning of the brief, not silently pass;
- deterministic check: normalized working_title similarity against each
  input document title (the existing bounded title-similarity utility) —
  a near-copy is recorded as a failed originality check on the idea;
- `angle` and `rationale` are mandatory non-empty fields — an idea without a
  stated original angle is invalid at the domain layer;
- fake-UGC guard: idea text fields are validated against a policy list of
  UGC-implying claims ("gerçek yorumlar", "annelerden tavsiyeler", ratings,
  testimonials) unless a real UGC evidence type exists — Phase 3 has no UGC
  ingestion, so such ideas are rejected deterministically;
- AI-generated ideas are proposals with recorded generation provenance —
  never evidence, never a provenance root (ADR 0007).

---

## 6. AI / model boundary (`contentos.ai`)

### 6.1 Provider-neutral protocol

Task 1 defines boundaries only — no OpenAI SDK, no adapter, no calls.

```text
engine (ideas/search_intent/briefs)
  → GenerationRequest (provider-neutral DTO: purpose, schema name+version,
    template name+version, input projection, bounds)
  → StructuredGenerationProvider protocol (contentos.ai)
  → [future adapter: OpenAI first, per ARCHITECTURE.md]
  → GenerationOutcome (provider-neutral DTO: status, validated payload OR
    failure class, provider/model/version identity, usage metadata)
```

Required adapter-exposed metadata (frozen now): provider name, model name,
model version/stable identity where available, request/template/schema
version, latency, token/usage metadata, cost metadata where available,
finish/status/error class. Provider SDK objects never cross into domain
code or storage. A **fake deterministic provider** for tests is mandatory
before any real adapter (the ADR 0008 pattern, reused).

### 6.2 Structured output only

Every AI call flows: provider → provider-neutral DTO → schema validation
(versioned Pydantic schema) → domain validation → persisted versioned
artifact. A response failing validation is recorded as a **failed attempt**
(`VALIDATION_FAILED`) — it is never coerced, never partially persisted, and
never mutates workflow state. No model response ever directly transitions an
EditorialWorkItem.

### 6.3 Attempt provenance — concrete recommendation: one generic record

**Recommendation: a single reusable `ai_generation_attempts` table**, not
per-engine attempt tables. Rationale: every Phase 3 purpose (idea
candidates, intent synthesis, brief wording, evidence organization) needs
identical provenance and cost hooks; per-engine tables would triplicate an
identical shape, and Cost/Budget Controls (module 19) later needs one place
to aggregate. Per-engine *result* artifacts stay in their own tables; only
the attempt/execution record is generic.

| Field | Meaning |
| --- | --- |
| `id` | UUID |
| `purpose` | `IDEA_CANDIDATES` / `INTENT_SYNTHESIS` / `BRIEF_COMPOSITION` / `EVIDENCE_ORGANIZATION` (extensible vocabulary) |
| `provider` / `model_name` / `model_version` | Identity, recorded not assumed |
| `schema_name` / `schema_version` / `template_version` | Exact contract used |
| `input_refs` | JSONB — exact input artifact ids/versions (opportunity score id, evidence ids projected, signal ids, policy versions) |
| `input_hash` | SHA-256 of the canonical input projection (idempotency) |
| `status` | `SUCCEEDED` / `VALIDATION_FAILED` / `PROVIDER_ERROR` / `TIMEOUT` / `CANCELLED` |
| `error_class` | Bounded, sanitized; never raw provider payloads with secrets |
| `retry_number` | N of the logical operation (one logical operation id across retries, per WORKFLOW.md) |
| `usage` | JSONB — tokens/latency; cost fields attachable later without redesign (Cost/Budget hook) |
| `created_at` | Timestamp |

This answers, permanently: which provider/model produced this suggestion,
under which schema/template version, from which exact inputs, when, at what
usage, did validation pass, and which retry it was.

> **Implementation note (Task 8).** Physical attempt identity is a
> DB-UNIQUE `attempt_identity_hash` (schema-versioned canonical-JSON
> SHA-256 over purpose, input hash, provider/model identity — an
> unavailable `model_version` participates explicitly as null, never a
> fabricated value — schema/template name+version, retry number), because a
> nullable-column UNIQUE tuple cannot give exact idempotency.
> `template_name` is persisted alongside `template_version`. The mandatory
> deterministic test provider is `fake` /
> `deterministic-structured-test-model` / `1`. Retry convention: the first
> provider attempt of a logical operation is `retry_number = 0`.
> Idea `generation_attempt_id` and EvidencePack `organization_attempt_id`
> were realized as staged nullable FKs (runtime idea creation stays
> operator-only; deterministic pack assembly writes NULL). Sequential
> identical retries never invoke the provider twice; under truly concurrent
> identical execution both callers may invoke the provider while the DB
> identity still guarantees exactly one durable attempt row — serializing
> the provider call itself would need a mutable reservation model that
> conflicts with the append-only completed-outcome design and remains a
> future orchestration boundary.

---

## 7. EvidencePack

### 7.1 Entity (immutable, versioned)

An EvidencePack is a first-class assembled research artifact — never copied
article text, a source dump, a URL list, or AI-invented research.

`evidence_packs`:

| Field | Meaning |
| --- | --- |
| `id` | UUID (version identity) |
| `opportunity_id` | FK |
| `idea_id` | FK nullable — packs may be (re)built after idea selection to focus on the selected angle |
| `version` | Integer; UNIQUE (`opportunity_id`, `version`) |
| `assembler_name` / `assembler_version` | Deterministic assembler identity; model assistance recorded via `organization_attempt_id` |
| `organization_attempt_id` | FK → ai_generation_attempts, nullable (AI may help ORGANIZE; membership and provenance stay deterministic) |
| `sufficiency` | `READY` / `INSUFFICIENT` / `CONFLICTED` / `BLOCKED` (§7.3) |
| `sufficiency_detail` | JSONB — missing areas, diversity counts, unresolved contradiction refs, policy version applied |
| `source_diversity` | JSONB summary — distinct source count, trust-tier distribution, `REFERENCE_ONLY` presence |
| `staleness_notes` | JSONB — time-sensitive/stale evidence flags with observed_at context |
| `locale_limitations` | JSONB — geographic/locale caveats |
| `licensing_cautions` | JSONB — aggregated from evidence `licensing_notes` and `REFERENCE_ONLY` tiers (travel with the pack, per ADR 0007) |
| `created_at` | Timestamp |

Packs are append-only: a changed evidence set or assembler version creates a
new version; downstream briefs pin exact pack versions. Idempotency:
(`opportunity_id`, canonical selected-evidence identity set + assembler
name/version) — identical assembly is a no-op returning the existing
version.

### 7.2 Items and provenance (ADR 0007, non-bypassable)

`evidence_pack_items`: `pack_id`, `research_evidence_id` (FK NOT NULL
RESTRICT), `role` (`KEY_FACT` / `SUPPORTING` / `CONTRADICTING` / `CONTEXT` /
`CAUTION`), `claim_cluster` (bounded key grouping evidence into
factual/claim clusters), `display_note` (bounded synthesis text, OPTIONAL
and never a substitute). UNIQUE (`pack_id`, `research_evidence_id`).

There is **no** `evidence_text` field that strips provenance. Every
consumer traces: ContentBrief → EvidencePack → ResearchEvidence →
NormalizedDocument → FetchSnapshot → Source. Bounded display/synthesis
fields are allowed only because the ResearchEvidence reference on the same
row is mandatory.

### 7.3 Evidence-sufficiency gate (explicit)

Sufficiency is a computed, recorded result — never implied:

- `READY` — cluster coverage, source diversity per content-type/risk policy
  (configurable minimums, versioned; no universal number frozen in Task 1),
  and no blocking contradictions;
- `INSUFFICIENT` — named missing clusters/diversity gaps recorded;
- `CONFLICTED` — unresolved blocking contradictions (§7.4);
- `BLOCKED` — policy/licensing/risk block independent of quantity.

**Absence of evidence is not a pass.** The gate result and the policy
version that produced it are stored on the pack; the EVIDENCE_BUILDING →
SEO_RESEARCH transition requires a `READY` pack version (WORKFLOW.md's
"evidence pack meets minimum sourcing requirements", made concrete).

### 7.4 Contradictions

`evidence_contradictions`: `pack_id`, `claim_key` (subject),
`evidence_side_a` / `evidence_side_b` (JSONB arrays of research_evidence
ids), `nature` (bounded description/classification), `severity` (`LOW` /
`MATERIAL` / `BLOCKING`), `resolution_status` (`UNRESOLVED` /
`RESOLVED_CAUTIOUS_WORDING` / `RESOLVED_NEEDS_RESEARCH` /
`RESOLVED_EDITORIAL_JUDGMENT`), `handling_recommendation` (bounded),
`created_at`. Conflicting evidence is never flattened into false certainty;
AI must never silently pick the convenient source — contradiction rows are
deterministic domain records that the brief's claim map must respect: an
UNRESOLVED BLOCKING contradiction blocks the affected claim (and, per
severity, the pack). Resolution is an operator/editorial act with a recorded
status, not a model output.

---

## 8. SearchIntentAnalysis

**Decision: a first-class versioned artifact (option A).** WORKFLOW.md gives
SEO_RESEARCH its own canonical state; ARCHITECTURE.md gives it its own
module (8); its inputs (search signals) and provenance (provider/as-of
times) differ from the brief's. Folding it into the brief would collapse a
canonical state and blur signal provenance.

`search_intent_analyses`:

| Field | Meaning |
| --- | --- |
| `id` | UUID (version identity) |
| `opportunity_id` | FK |
| `idea_id` | FK — the exact selected idea version analyzed |
| `version` | Integer; UNIQUE (`opportunity_id`, `version`) |
| `primary_intent` / `secondary_intents` | Intent model (bounded; JSONB for secondary) |
| `target_audience` | Bounded |
| `query_concepts` | JSONB — Turkish query/topic concepts (no invented volumes) |
| `page_purpose` / `likely_format` | What the target page is for; expected content shape |
| `known_signal_refs` | JSONB — search_signal ids + a frozen snapshot of their values/as-of times |
| `missing_signals` | JSONB — explicitly named unknowns (volume, SERP, trends…) |
| `cannibalization_status` | §8.1 |
| `cannibalization_basis` | JSONB — what was actually checked (internal refs) |
| `related_references` | JSONB — related opportunities/work items where known |
| `locale` / `market` | Explicit |
| `engine_name` / `engine_version` / `synthesis_attempt_id` | Deterministic composition identity + optional AI-assist attempt FK |
| `created_at` | Timestamp |

No live Google/Semrush/Search Console integration exists or is selected in
Task 1; the analysis truthfully lists `missing_signals` instead.

### 8.1 Cannibalization truth-states

`NOT_CHECKED` / `NO_KNOWN_CONFLICT` / `POTENTIAL_CONFLICT` /
`KNOWN_CONFLICT` — a durable recorded input, not a prompt hint. Until the
Konsepthane published-inventory read contract exists (a separate future
boundary; no production DB access, ADR 0001/0003), the maximum honest claims
are `NOT_CHECKED` or, when ContentOS-internal overlap was actually examined
(related opportunities/briefs), `POTENTIAL_CONFLICT` / `NO_KNOWN_CONFLICT`
**scoped explicitly to ContentOS-internal data** in
`cannibalization_basis`. The system never claims "no cannibalization"
against an inventory it cannot see; the missing integration stays visible.

> **Implementation note (Task 10).** Physical analysis identity is a
> DB-UNIQUE `input_snapshot` + `input_snapshot_hash` (schema-versioned
> canonical-JSON SHA-256 over opportunity/exact idea/composition mode,
> the deterministic semantic composition OR the synthesis attempt
> identity hash, frozen signal snapshots, missing signals, cannibalization
> status+basis, related references). Deterministic semantic fields arrive
> through the typed `IntentComposition` DTO (no inferred-intent
> heuristic). `cannibalization_basis` uses a versioned bounded schema
> (schema_version 1, `scope: contentos_internal`, exact checked
> references, `published_inventory: unavailable_not_checked`);
> KNOWN_CONFLICT is refused until an inventory contract exists. AI
> synthesis reuses the Task 8/9 artifact-idempotency semantics: a reused
> SUCCEEDED attempt returns its already-materialized analysis, and a
> reused attempt with no artifact is a typed incomplete-materialization
> error recovered via retry_number + 1. The artifact has no evidence-pack
> FK — the READY-pack gate stays with §18 orchestration.

---

## 9. ContentBrief

### 9.1 Entity (versioned; accepted versions immutable)

The ContentBrief is the final Phase 3 artifact and the future Writer's whole
contract.

`content_briefs`:

| Field | Meaning |
| --- | --- |
| `id` | UUID (version identity) |
| `work_item_id` | FK |
| `version` | Integer; UNIQUE (`work_item_id`, `version`) |
| `idea_id` | FK — exact idea version |
| `evidence_pack_id` | FK — exact pack version |
| `search_intent_analysis_id` | FK — exact analysis version |
| `locale` / `market` | Explicit |
| `target_audience` / `intent_summary` / `original_angle` | From upstream artifacts, restated as the writing contract |
| `title_guidance` | Working title + constraints (not a frozen headline) |
| `content_objective` | What the piece must achieve for the reader |
| `required_sections` / `optional_sections` | JSONB ordered structures — subject to the copyright guard (§9.2) |
| `practical_requirements` | JSONB — Konsepthane planning dimensions required for this piece (§13.2) |
| `exclusions` | JSONB — prohibited claims/topics/framings (includes fake-UGC prohibitions) |
| `uncertainty_notes` | JSONB — what the writer must hedge or omit |
| `internal_link_needs` / `media_needs` | JSONB — needs, not assets (media provenance is module 14, later) |
| `faq_questions` | JSONB optional, only where justified by intent |
| `acceptance_criteria` | JSONB — measurable done-conditions for the future draft |
| `status` | `DRAFT` / `ACCEPTED_FOR_DRAFTING` / `SUPERSEDED` |
| `composition_attempt_id` | FK → ai_generation_attempts nullable (deterministic assembly + optional model-assisted wording) |
| `engine_name` / `engine_version` | Brief-composer identity |
| `created_at` | Timestamp |

No generated article text lives in a brief. A new version supersedes the
old (`SUPERSEDED`), never edits it; an `ACCEPTED_FOR_DRAFTING` version is
immutable and is the only thing Phase 4's Writer may receive.

### 9.2 Claim/evidence map

`brief_claims`: `brief_id`, `claim_key`, `claim_text` (bounded),
`claim_kind` (`FACTUAL` / `SOURCE_ASSERTION` / `OBSERVATION` / `INFERENCE` /
`EDITORIAL_JUDGMENT` / `INSTRUCTION`), `handling` (bounded guidance, e.g.
cautious wording from a contradiction). `brief_claim_evidence`:
(`claim_id`, `research_evidence_id` FK NOT NULL RESTRICT).

Deterministic gates: every `FACTUAL`/`SOURCE_ASSERTION`/`STATISTIC`-bearing
claim must link ≥1 eligible ResearchEvidence row (a source URL alone is
never verification — EDITORIAL_POLICY.md); `INFERENCE` and
`EDITORIAL_JUDGMENT` need no evidence but MUST be marked as such; a claim
whose evidence sits in an UNRESOLVED BLOCKING contradiction cannot be
`FACTUAL` in an acceptable brief.

Copyright guard (structural, not prompt-based): the brief composer must
record a deterministic structure-similarity check between
`required_sections` and each single input document's heading structure
(Phase 2 stores `headings`); a near-match to any single source fails brief
acceptance. Cross-source synthesis for substantive topics is enforced by the
pack's source-diversity gate; `REFERENCE_ONLY`/licensing cautions surface in
`exclusions`/`uncertainty_notes` automatically from the pack.

### 9.3 BRIEFING → DRAFTING acceptance boundary (defined now, exercised in Phase 4)

A brief version may be `ACCEPTED_FOR_DRAFTING` only when ALL hold:

1. The opportunity is `COMMISSIONED` and not superseded by a rejection.
2. The pinned duplicate gate is resolved and not a hard stop.
3. The pinned EvidencePack version is `READY`.
4. No UNRESOLVED BLOCKING contradiction affects any FACTUAL claim.
5. A SearchIntentAnalysis version is pinned (missing signals allowed —
   missing analysis not).
6. The claim/evidence map passes its deterministic gates (§9.2).
7. The full provenance chain resolves (revalidated, not assumed).
8. No policy/risk block is open on the work item.
9. Acceptance is an explicit operator command, recorded as a workflow event
   pinning the exact brief version.

Acceptance for drafting is an editorial decision; it is NOT human
publication approval — ADR 0004's approval gate remains untouched and later.

> **Implementation note (Task 11).** Physical brief identity is the
> relational UNIQUE (work_item, exact idea, exact pack, exact analysis,
> engine name+version); a schema-versioned `content_hash` (canonical-JSON
> SHA-256 over ALL brief content + the complete claim map with evidence
> links + the structure-guard result/policy) makes same-identity retries
> idempotent, different wording a typed conflict, and out-of-band child
> inserts an acceptance-time integrity failure. The manual/deterministic
> persistence path uses composer identity `manual-brief-input/1`
> (`composition_attempt_id` NULL); Task 12 freezes the real composer. The
> §9.2 copyright guard is `BriefStructurePolicy` `default/1` (ordered
> normalized SequenceMatcher over section guidance vs each source's
> headings, threshold 0.8, min 2 checkable headings), snapshot-persisted;
> NOT_CHECKABLE fails acceptance closed. FACTUAL/SOURCE_ASSERTION claims
> require pack-member evidence at draft creation already; RETRACTED
> evidence never satisfies the gate, DISPUTED-only support requires
> recorded handling, and idea originality NOT_CHECKABLE fails acceptance
> closed. The duplicate gate reuses Task-3 admission semantics: current
> effective REJECT is always a hard stop; effective DUPLICATE passes only
> with the audited `duplicate_override` creation-event marker. STATISTIC
> remains an evidence type only — no claim kind and no statistical-text
> detection regex is pretended.

---

## 10. Versioning, reproducibility, idempotency

### 10.1 Version semantics (uniform rules)

- **Immutable**: workflow events, scores, idea versions, selection events,
  evidence packs + items + contradictions, intent analyses, brief versions,
  AI attempts. All append-only (PG triggers, the Phase 2 pattern).
- **Mutable anchors**: `editorial_work_items` (current_state +
  denormalizations), `editorial_opportunities` (disposition), brief `status`
  (`DRAFT→ACCEPTED_FOR_DRAFTING→SUPERSEDED` transitions only) — each
  mutation audited via events.
- **Logical vs version identity**: logical ids (`work_item_id`,
  `logical_idea_id`, (`opportunity_id`, artifact family)) group versions;
  every downstream pin uses the *version* id (UUID of the exact row).
  "Current/effective" is always deterministic-latest by
  (business timestamp, created_at, id) or by explicit status — never
  ambiguous, mirroring the Task 17 projection contract.
- **Downstream pinning**: briefs pin exact idea/pack/analysis versions;
  packs pin exact evidence ids; scores pin exact input snapshots; workflow
  events pin the versions relevant to each transition.

### 10.2 Input snapshots / reproducibility

"Why did ContentOS recommend this article on this date?" is answerable from
immutable rows alone: score `input_snapshot` (+hash), pack membership,
signal snapshots with as-of times, attempt `input_refs`, engine/model and
policy/config versions on every artifact, and the workflow event trail.
Historical explanation never depends on mutable current rows.

### 10.3 Idempotency identities (at-least-once safe)

| Operation | Identity |
| --- | --- |
| Promotion/intake | (`normalized_document_id`) — one work item per promoted document root; re-delivery returns the existing item |
| Opportunity evaluation | (`opportunity_id`, engine name+version, `input_snapshot_hash`) |
| Idea generation | (`opportunity_id`, generator name+version, `input_hash`, retry) via attempt records; resulting candidates keyed by content identity |
| Evidence Pack assembly | (`opportunity_id`, canonical evidence-id set, assembler name+version) |
| SearchIntentAnalysis | (`opportunity_id`, `idea_id`, analyzer name+version, signal-snapshot hash) |
| ContentBrief | (`work_item_id`, pinned upstream version triple, composer name+version) |

Same identity ⇒ return existing artifact; changed identity ⇒ append new
version. Celery redelivery therefore cannot create uncontrolled duplicates
(the Phase 2/Task 16 contract, extended).

---

## 11. Rejection, blocking, and the failure model

**Domain decisions** (workflow/disposition facts):
`REJECTED` — opportunity not worth commissioning, hard duplicate, explicit
out-of-scope (reason + actor recorded; reopening is an explicit audited
event per WORKFLOW.md).
`BLOCKED` — insufficient evidence, unresolved blocking contradiction,
required provider unavailable *as an editorial dependency*, mandatory search
signal unavailable where policy requires one, budget/policy dependency.
Resume is an explicit resolution event back to the prior state.

**Execution failures** (attempt facts, never workflow states): provider
timeout, malformed model output (VALIDATION_FAILED), transient outages,
worker crashes. These live on `ai_generation_attempts`/job records with
bounded retries; the work item stays in its state. Only exhausted,
operator-relevant failure escalates to `BLOCKED` via an explicit SYSTEM
transition with reason — a provider timeout never becomes editorial
`REJECTED`.

**Operator decisions in Phase 3** (all audited commands, none of them
publication approval): commission/reject an opportunity, select/deselect an
idea, resolve a contradiction/block, accept a brief for drafting, request
regeneration, explicitly reopen a duplicate with a distinct angle.

---

## 12. Deterministic / model-assisted / human split

| Responsibility | Class |
| --- | --- |
| Intake eligibility, provenance validation, duplicate gating | DETERMINISTIC |
| Source diversity, missing-evidence detection, sufficiency gate | DETERMINISTIC |
| Version resolution, idempotency, threshold gates, claim-link gates | DETERMINISTIC |
| Structure-similarity copyright guard, fake-UGC guard | DETERMINISTIC |
| Opportunity scoring v1 (known-signal components) | DETERMINISTIC |
| Angle/idea candidates, topic synthesis | MODEL_ASSISTED (validated, attempt-recorded) |
| Contradiction summarization, intent synthesis, brief wording, pack organization | MODEL_ASSISTED (membership/provenance stays deterministic) |
| Commissioning, idea selection, block resolution, brief acceptance, duplicate reopen | HUMAN/OPERATOR |

Phase 3 is not "everything is an LLM task": every gate that protects policy,
provenance, or money is deterministic; models propose, humans decide,
deterministic code verifies.

---

## 13. Content type and Konsepthane product fit

### 13.1 ContentType

Controlled extensible vocabulary (initial): `GUIDE`, `IDEA_LIST`,
`CHECKLIST`, `PLANNING_GUIDE`, `COMPARISON`, `FAQ`, `HOW_TO`,
`INSPIRATION`. Stored as stable lowercase values via the existing
`string_enum` pattern; extension is a migration-time vocabulary addition,
not free text. Content type parameterizes scoring weights, evidence/source
minimums, brief shape, and future QA — and is never inferred from a single
source article alone (it is an idea-level editorial choice validated against
the input set).

### 13.2 Planning dimensions

Konsepthane content is practical celebration/event planning. Ideas and
briefs may carry structured optional `planning_dimensions` /
`practical_requirements` (JSONB with a versioned bounded schema): theme,
color palette, decorations, cake, menu, shopping list, budget band, space,
preparation time, DIY level, age/event suitability, practical steps. These
are optional per content type — no type requires all — and live in bounded
versioned JSONB precisely so the relational core stays generic and future
locales/products do not require key changes.

---

## 14. Risk model hooks

A minimal risk vocabulary — not a policy engine: `MEDICAL`, `LEGAL`,
`FINANCIAL`, `SAFETY`, `PERSON_OR_ORG_CLAIMS`, `TIME_SENSITIVE`. Risk flags
attach to opportunity scores (`risk_flags`), evidence-pack sufficiency
policy (higher diversity/verification minimums per flag), and brief
exclusions/acceptance criteria. Flags originate deterministically (content
type, operator marking, evidence types) and raise gates; they never
auto-adjudicate — heightened human attention is the response, consistent
with EDITORIAL_POLICY.md.

---

## 15. Evidence exposure to AI

Future AI input builders receive only a controlled evidence projection —
never raw HTML, raw payloads, whole competitor articles, or unrelated
database content. The conceptual DTO per evidence unit: evidence id,
evidence type, bounded statement/excerpt where policy permits, source
slug + trust tier, captured/fetched-at freshness, provenance identity,
uncertainty/licensing caution. Projections are built by
`contentos.ai`-adjacent builder code from ResearchEvidence via its service
(the ADR 0007 "no text-only accessor" rule holds: the projection carries
provenance identity through to the attempt's `input_refs`).

---

## 16. Database plan (conceptual — NO migrations in Task 1)

| Table | Identity | Key FKs | Uniqueness | Mutability |
| --- | --- | --- | --- | --- |
| `editorial_work_items` | UUID | — | — | State-mutable via service; audited |
| `editorial_workflow_events` | BIGINT | work_item | — | **Append-only** |
| `editorial_opportunities` | UUID | work_item | `work_item_id` | Disposition-mutable; audited |
| `opportunity_research_inputs` | UUID | opportunity, normalized_document, duplicate_decision | (opportunity, document) | Append-only |
| `opportunity_scores` | UUID | opportunity | (opportunity, engine, version, input_hash) | **Append-only** |
| `opportunity_score_components` | UUID | score | (score, component) | **Append-only** |
| `search_signals` | UUID | — | — | **Append-only** |
| `ideas` | UUID | opportunity, generation_attempt | (logical_idea_id, version) | **Append-only** |
| `idea_selection_events` | BIGINT | opportunity, idea | — | **Append-only** |
| `evidence_packs` | UUID | opportunity, idea?, organization_attempt? | (opportunity, version) | **Append-only** |
| `evidence_pack_items` | UUID | pack, research_evidence (RESTRICT) | (pack, evidence) | **Append-only** |
| `evidence_contradictions` | UUID | pack | — | Resolution-status mutable via service, audited; otherwise immutable |
| `search_intent_analyses` | UUID | opportunity, idea, synthesis_attempt? | (opportunity, version) | **Append-only** |
| `content_briefs` | UUID | work_item, idea, evidence_pack, search_intent_analysis, composition_attempt? | (work_item, version) | Status-mutable via service; content immutable |
| `brief_claims` | UUID | brief | (brief, claim_key) | **Append-only** (per brief version) |
| `brief_claim_evidence` | UUID | claim, research_evidence (RESTRICT) | (claim, evidence) | **Append-only** |
| `ai_generation_attempts` | UUID | — (referenced BY artifacts) | (purpose, input_hash, provider, model, schema_version, retry) | **Append-only** |

Conventions carried from Phase 2: UUID PKs; `string_enum` VARCHAR+CHECK
(never PG enums); timestamptz; append-only enforced by triggers; RESTRICT
on all provenance FKs (evidence/pack/brief chains can never be hollowed
out); deterministic-latest ordering indexes ((parent_id, business_ts DESC)
style); indexes on workflow `current_state`, opportunity `disposition`,
attempt `purpose`/`status`.

**Relational vs JSONB discipline**: relational for everything joined,
filtered, gated, versioned, or audited (identities, FKs, versions, states,
claim links, component rows); JSONB for bounded engine/config snapshots,
signal values typed per signal_type, planning dimensions, provider-neutral
usage metadata, and pinned input snapshots. Nothing whose absence or value
gates a workflow transition may live only in JSONB.

Delete behavior: nothing in Phase 3 is deleted; RESTRICT FKs plus
append-only triggers make provenance structurally permanent (retention is a
future governed policy, unchanged from ADR 0006).

---

## 17. Module boundaries (downward-only, no cycles)

```text
contentos.workflow        EditorialWorkItem, events, WorkflowService,
                          canonical state matrix (foundational; imports only
                          core/db)
contentos.signals         search_signals store (foundational; core/db only)
contentos.ai              provider protocol, DTOs, attempt records, fake
                          provider (foundational; core/db only)
      ↓
contentos.opportunities   Opportunity, inputs, scoring engine
                          (reads Phase 2: normalization, duplicates,
                          research, sources — read-only; uses workflow,
                          signals)
      ↓
contentos.ideas           Idea versions, candidates, selection
                          (uses opportunities, ai, workflow)
contentos.evidence_packs  Packs, items, contradictions, sufficiency
                          (uses opportunities, research read-only, ai,
                          workflow)
      ↓
contentos.search_intent   SearchIntentAnalysis
                          (uses opportunities, ideas, signals, ai, workflow)
      ↓
contentos.briefs          ContentBrief, claims, acceptance
                          (uses ideas, evidence_packs, search_intent,
                          workflow, ai)
```

Hard rules: Phase 2 modules never import Phase 3 (verified direction:
Phase 3 → Phase 2 read-only through existing repositories/services); `ai`
never imports domain modules; `workflow` imports no Phase 3 stage module;
no provider SDK anywhere until the adapter task, and then only inside
`contentos.ai.providers.*`. Worker/API layers sit above all of it, exactly
as in Phase 2.

---

## 18. Jobs / orchestration plan (design only)

Phase 3 is punctuated by operator decisions; the chain is deliberately NOT
one automatic cascade like Phase 2's fetch chain.

| Job (stable name reserved) | Trigger | Persists / transition |
| --- | --- | --- |
| `contentos.editorial.promote_research` | Operator command (or future policy) | Work item + opportunity + inputs; creation event → IDEA_SCORING |
| `contentos.editorial.evaluate_opportunity` | After promotion; re-runnable | Score (append); no state change by itself |
| `contentos.editorial.generate_idea_candidates` | Operator command on commissioned opportunity | Attempt + idea versions; no state change |
| `contentos.editorial.build_evidence_pack` | After commissioning/idea selection | Pack version; on READY, SYSTEM transition EVIDENCE_BUILDING → SEO_RESEARCH; on not-READY, → BLOCKED with reason |
| `contentos.editorial.analyze_search_intent` | After READY pack | Analysis version; SYSTEM transition → BRIEFING |
| `contentos.editorial.compose_content_brief` | Operator command in BRIEFING | Brief DRAFT version; acceptance stays an operator command |

Contracts inherited verbatim from Task 16: PostgreSQL authoritative;
commit-before-enqueue; at-least-once absorbed by the §10.3 identities;
UUID-string-only payloads with request_id headers; DOMAIN vs DISPATCH retry
separation; bounded deterministic backoff; terminal policy failures never
retried; explicit `WorkflowService` transitions only after durable commits
(queue completion alone advances nothing). Operator commissioning
(IDEA_SCORING → EVIDENCE_BUILDING) and brief acceptance remain human
commands, never job side effects.

Realized in Phase 3 Task 13: the six job names above are registered in
`contentos.worker.editorial_tasks` (research and editorial pipelines share
one `WorkerRuntime`, which gained a lazy structured-generation provider
factory seam — fake in tests, configured OpenAI in production, typed
terminal failure when unconfigured). `build_evidence_pack` is the explicit
evidence-selection command: its payload carries bounded JSON selection
entries mapped onto the EXISTING `EvidenceSelection` contract (never an
invented heuristic). AI-task retry classification: TIMEOUT/PROVIDER_ERROR
retry within the Celery bound with each provider retry a distinct durable
attempt (`retry_number = base + task retries`, failed attempts committed
before the DOMAIN retry); VALIDATION_FAILED/CANCELLED are terminal.
Commissioning landed as `OpportunityCommissioningService.
commission_opportunity` in `contentos.opportunities` — a transport-neutral
operator command, not a Celery job.

---

## 19. Operator controls and admin plan (design only)

Future admin (extending the Task 17/19 patterns — server-only, explicit
POST commands, no generic endpoints): an editorial work queue by state;
per-item view showing opportunity score + components + missing signals,
research inputs with duplicate decisions, idea candidates + selection,
evidence pack (members, roles, contradictions, gaps, sufficiency), search
intent (+ signal ages), brief versions + claim map, full workflow event
history, blocked reasons, and AI attempt metadata (provider/model/schema/
usage/status — never raw provider payloads).

Future commands (business-explicit, mirrors §11): commission/reject
opportunity, select idea, request regeneration, resolve
contradiction/block, accept brief for drafting, reopen duplicate with
distinct angle. **No publication approval anywhere in Phase 3.**

Future internal API shape: reads under `/internal/editorial/...`
(work-items list/detail projections mirroring the Task 17 read-model
approach); commands as explicit POSTs
(`/internal/editorial/opportunities/{id}/commission`, `.../ideas/{id}/select`,
`.../briefs/{id}/accept`, …). No `/action`, `/execute`, `/state`.

Observability requirement (binding): a recommendation that cannot explain
itself is invalid — every surfaced score/idea/pack/brief must render its
engine versions, inputs, missing signals, and decision trail from the
immutable records of §10.

Realized in Phase 3 Task 14: read models in
`contentos.api.read_models.editorial`; reads
`GET /internal/editorial/work-items`, `.../work-items/{id}`,
`.../opportunities/{id}/eligible-evidence`; explicit POST commands under
`/internal/editorial/...` — `research/{id}/promote`,
`research/{id}/reopen-duplicate`, `opportunities/{id}/evaluate`,
`/commission`, `/reject`, `/generate-ideas`, `/evidence-packs/build`,
`/analyze-search-intent`, `ideas/{id}/select`, `/deselect`,
`contradictions/{id}/resolve`, `evidence-packs/{id}/reassemble`,
`work-items/{id}/resolve-block`, `/reject-blocked`, `/compose-brief`,
`briefs/{id}/accept` (thin adapters over existing domain services and a
producer-only `CeleryEditorialControlDispatcher` publishing the six
frozen §18 job names). Private admin routes `/editorial` and
`/editorial/[id]` extend the Task-17/19 server-only pattern.
Acknowledged recovery limitation (for the closure audit): a READY pack
produced by `reassemble` does not advance workflow or dispatch analysis
by itself — continuing with it is the operator's next explicit command,
because no accepted Task-13 orchestration semantics cover automatic
continuation from reassembly.

---

## 20. Security (unchanged boundaries)

Phase 3 introduces: no arbitrary internet fetching (all research enters via
the Phase 2 governed pipeline); no Konsepthane production DB access
(cannibalization stays truthfully `NOT_CHECKED`-capable, §8.1); no
browser-to-provider calls and no provider keys in admin/browser (AI runs
server-side behind `contentos.ai`, keys in backend settings only); no
raw-payload or clean-text exposure through admin (Task 17 rules extend);
AI is never an evidence root (ADR 0007); no auth redesign — the
single-operator/private-infrastructure boundary stands; no users/RBAC/login
in Phase 3 Task 1 planning.

---

## 21. Testing strategy

The Phase 2 testing machinery extends directly: offline unit tests with
real SQLite-backed sessions and real services; the fake deterministic AI
provider for every model-assisted engine (no network, reproducible
outputs); eager-Celery orchestration tests through real registered task
boundaries with fake dispatchers; real ephemeral pgvector PostgreSQL
verification per persistence task (migrations up/down, append-only
triggers, catalog checks); admin tests with mocked server-only clients.
Mandatory cross-cutting suites: provenance-chain integrity (brief → …
→ source resolvable for every artifact), gate tests (sufficiency,
claim-evidence, acceptance boundary, UNKNOWN≠0), idempotency tests per
§10.3 identity, and failure-model tests (VALIDATION_FAILED never persists
artifacts or advances state).

---

## 22. Phase 3 implementation order (atomic, dependency-correct)

1. **Workflow foundation** — `contentos.workflow`: EditorialWorkItem +
   append-only events + WorkflowService with the canonical matrix;
   migration 0009; no intake yet.
2. **Opportunity persistence + intake** — `contentos.opportunities`:
   Opportunity + research inputs + deterministic eligibility; the
   `promote_research` service path (operator-triggered promotion from
   eligible Phase 2 chains, incl. the duplicate-override event); migration.
3. **Deterministic opportunity scoring v1** — engine + scores + components
   (+ UNKNOWN handling, risk flags), versioned config snapshots.
4. **Search-signal store** — `contentos.signals` + manual operator entry
   surface (API-level, minimal); migration.
5. **EvidencePack foundation** — packs/items/contradictions + sufficiency
   gate + policy config versioning; migration.
6. **Idea persistence + selection** — versions, candidates, selection
   events, deterministic originality guards; operator-authored ideas first
   (no AI yet); migration.
7. **Provider-neutral AI boundary** — `contentos.ai`: protocol, DTOs,
   schema validation pipeline, `ai_generation_attempts`, fake deterministic
   provider; migration. (No real adapter.)
8. **First real adapter + idea generation engine** — OpenAI adapter behind
   the protocol (first per ARCHITECTURE.md; requires its own dependency/ADR
   checkpoint), model-assisted idea candidates end-to-end with validation
   and attempt provenance.
9. **SearchIntentAnalysis** — artifact + deterministic composition +
   optional model-assisted synthesis + cannibalization truth-states;
   migration.
10. **ContentBrief persistence + claim map + acceptance gate** — briefs,
    claims, claim-evidence links, §9.3 boundary; migration.
11. **Brief composition engine** — deterministic assembly from pinned
    artifacts + model-assisted wording + copyright/structure guard.
12. **Celery orchestration** — the §18 jobs with Task 16 contracts;
    workflow-service transitions wired.
13. **Admin/operator visibility + commands** — the §19 read projections and
    explicit commands (may split read/command into two tasks if size
    demands).
14. **Phase 3 closure audit** — design-vs-implementation, deferrals,
    Phase 4 entry criteria (the Task 18 pattern).

---

## 23. Phase 3 exit criteria

Phase 3 is complete when ContentOS can take eligible Phase 2 research and
produce a fully auditable, human-inspectable ContentBrief ready for a future
Writer — concretely:

- [ ] Durable canonical EditorialWorkItem with audited transitions exists
- [ ] Versioned EditorialOpportunity with multi-source research inputs exists
- [ ] Explainable, component-level, UNKNOWN-honest opportunity scoring exists
- [ ] Intake enforces duplicate/normalization/provenance eligibility (ADR 0008 semantics)
- [ ] Versioned Idea candidates with auditable explicit selection exist
- [ ] Provenance-preserving EvidencePack with roles/clusters exists
- [ ] Contradictions and evidence gaps are visible, with an explicit sufficiency gate
- [ ] SearchIntentAnalysis exists with truthful missing-signal and cannibalization states
- [ ] Versioned ContentBrief with a deterministic claim/evidence map exists
- [ ] No path bypasses ResearchEvidence provenance (ADR 0007 verified end-to-end)
- [ ] Provider-neutral AI boundary with attempt provenance and a fake test provider exists
- [ ] Idempotent Celery orchestration with explicit workflow transitions exists
- [ ] Operator visibility and command surface for the whole chain exists
- [ ] The BRIEFING→DRAFTING contract is enforced: Phase 4's Writer can receive only an `ACCEPTED_FOR_DRAFTING` brief version and its pinned evidence contract

Writer implementation is explicitly NOT a Phase 3 exit requirement.

---

## Explicitly NOT in Phase 3

Writer/Editor/QA engines, human publication review/approval flows,
scheduling, publishing, the Konsepthane Publishing API/inventory contract,
Pinterest, analytics ingestion, media provenance, cost/budget enforcement
(hooks only), UGC ingestion, vector similarity (ADR 0008 re-entry triggers
govern), authentication/RBAC, and any Konsepthane production access.
