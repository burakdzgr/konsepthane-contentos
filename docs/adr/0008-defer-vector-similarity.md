# ADR 0008: Defer the Vector-Similarity Duplicate Signal Until Justified

Status: Accepted
Date: 2026-09-01

## Context

The accepted Phase 2 design (docs/PHASE2_RESEARCH_DISCOVERY.md) promised
vector similarity as a first-class commitment, not merely an idea: duplicate
signal 7 in §5 ("Vector similarity (pgvector embedding; model + version
recorded per decision)"), the §12 database plan ("Vector columns (pgvector)
attach to `normalized_documents` … when the duplicate engine lands"), and
implementation-order item 11 ("pgvector embedding column + vector similarity
signal in the duplicate engine (provider-neutral embedding interface)").
This ADR is therefore a **formal scope amendment**, required by the Phase 2
closure audit (docs/PHASE2_CLOSURE_AUDIT.md, closure condition 1), which
refused to relabel the item "future" without a recorded decision.

What is actually implemented (Tasks 10/12, verified): the deterministic
engine `duplicate-engine/1` evaluates canonical/final-URL identity, raw-body
hash, exact normalized-content SHA-256 fingerprint, normalized title
similarity (bounded Unicode normalization + stdlib SequenceMatcher), and
bounded lexical token-set similarity over a candidate set capped at 200
comparisons. Every DuplicateDecision durably records engine name+version, a
frozen thresholds snapshot, computed signals, bounded matched references
(≤10), and rationale codes, in an append-only, trigger-protected,
idempotent-per-engine-version table. No semantic/vector similarity exists;
no embedding code exists anywhere in the codebase. This baseline is
conservative and explainable — it is not claimed to be perfect: it cannot see
paraphrased or cross-language semantic duplicates.

The system also has, today: an empty production corpus (no source allowlist
is seeded), no selected embedding provider or model, no AI integration of any
kind (Phase 2 forbids it), and a live pgvector extension installed since
migration `0001` and checked by `/health/ready`.

## Decision

Defer implementation-order item 11 — the pgvector embedding column and the
vector-similarity duplicate signal — out of Phase 2. Vector similarity is
**deferred until justified** by the re-entry triggers below; it is not
abandoned, and it is not declared unnecessary.

Rationale:

1. **Corpus scale.** The normalized corpus is currently empty and will stay
   small during early supervised operation; nothing yet demonstrates that
   vector search is necessary for Phase 2 correctness, and the bounded
   deterministic candidate scan is comfortably sufficient at this scale.
2. **A conservative pre-AI gate exists.** URL/hash/title/lexical signals
   provide an explainable duplicate gate whose every decision is fully
   auditable (thresholds + signals + matches persisted per decision).
3. **No provider contract exists.** No embedding provider/model has been
   selected, and Phase 2 permits no AI providers. Implementing the signal now
   would force a provider-shaped design with zero real selection criteria.
4. **Premature freezing.** Adding vector storage today would prematurely fix
   provider/model identity, embedding dimensionality, vector
   lifecycle/versioning, re-embedding policy, cost policy, and similarity
   calibration — all before any data exists to calibrate against.
5. **Calibration needs Phase 3 data.** Responsible vector thresholds require
   real corpus, retrieval, and quality observations that only Phase 3
   research/idea operation will produce.
6. **Nothing is foreclosed.** pgvector is already installed and
   health-checked; the decision record schema already versions engines and
   freezes thresholds per decision, so a future `duplicate-engine/2` (or a
   separate vector signal version) appends new decisions without touching or
   reinterpreting historical ones.
7. **Not a provenance/security prerequisite.** Vector similarity improves
   candidate *classification quality*; it plays no role in the admission
   gate (ADR 0005), snapshot immutability (ADR 0006), or evidence provenance
   (ADR 0007). Deferring it weakens no security or provenance invariant.

### Phase 3 safety conditions (binding while the signal is deferred)

Phase 3 may begin without vector similarity only under conservative duplicate
handling:

- `DUPLICATE` and `REJECT` remain hard stops for downstream spend.
- `RELATED` and `UPDATE_EXISTING` remain downstream-eligible signals — they
  are inputs to editorial judgment, never silent deletion.
- Uncertain similarity must not be auto-rejected merely because lexical
  similarity is imperfect; when in doubt, the engine's existing thresholds
  classify conservatively toward `UNIQUE`/`RELATED` and downstream review
  bears the cost, not the corpus.
- The Phase 3 Idea Engine must not treat duplicate decisions as infallible;
  materially overlapping ideas are still possible and must be tolerable.
- Phase 3 artifacts must preserve references to the underlying
  DuplicateDecision ids/outcomes/signals they relied on, so misses become
  observable evidence (see re-entry trigger 2/3) instead of silent loss.

### Constraints frozen for the eventual implementation

When vector similarity is implemented, it MUST:

- sit behind a provider-neutral embedding protocol (no provider SDK types in
  domain code; a fake deterministic provider must exist for tests);
- record embedding model name + model version as provenance on every
  decision that used the signal, never assumed;
- record and validate embedding dimensionality; reject dimension mismatches;
- give embeddings a deterministic identity (document/content fingerprint +
  model identity) and an explicit vector-version lifecycle with a safe,
  bounded re-embedding strategy (append/version, never silent overwrite);
- avoid provider-specific columns where avoidable;
- generate embeddings in bounded batches with explicit cost policy;
- have no runtime dependency on any Writer/LLM provider;
- record the vector similarity threshold and signal version in the
  DuplicateDecision thresholds/signals snapshots, exactly as the
  deterministic signals do today.

### What this deferral does NOT allow

- removing pgvector or the future vector plans from the architecture;
- claiming lexical similarity is universally sufficient;
- introducing OpenAI (or any) embeddings ad hoc in Phase 3 outside the
  provider-neutral boundary above;
- individual agents/features generating embeddings independently;
- bypassing DuplicateDecision as the durable duplicate record;
- bypassing or weakening provenance/evidence constraints (ADR 0005/0006/0007).

## Re-entry Triggers

Vector-similarity work MUST be reopened (as a designed task, starting from
the frozen constraints above) when any of the following is observed:

1. **Corpus scale**: the normalized research corpus grows to where the
   bounded lexical candidate comparison becomes expensive or noisy — the
   numeric threshold is to be established from observed corpus/query
   behavior, not invented in advance.
2. **Duplicate miss evidence**: operator review repeatedly identifies
   semantic duplicates (paraphrases, restructured coverage) that the
   URL/hash/title/lexical signals classified `UNIQUE`.
3. **Phase 3 quality evidence**: the Idea Engine generates materially
   overlapping ideas from documents classified `UNIQUE`/`RELATED`.
4. **Performance**: deterministic candidate selection no longer meets a
   documented latency or candidate-bound target (to be documented when such
   a target first exists).
5. **Multilingual expansion**: cross-language or translated-topic similarity
   becomes a requirement (e.g., non-Turkish sources enter the registry with
   comparison intent).
6. **Provider decision**: an embedding provider/model abstraction is
   selected on explicit cost/privacy/reliability criteria — at that point
   the deferral loses its "no provider contract" leg and the work should be
   scheduled deliberately.

## Consequences

- Phase 2 closes with the deterministic duplicate baseline as the
  authoritative pre-AI gate; the closure audit's last open condition is
  resolved as DEFERRED_ACCEPTED.
- Historical documents keep describing vector similarity as part of the
  original accepted design; this ADR amends scope going forward without
  rewriting that history.
- The duplicate gate knowingly accepts a class of semantic false negatives
  for now; the Phase 3 safety conditions convert those from silent loss into
  observable evidence that feeds the re-entry triggers.
- A future vector signal lands as a new engine/signal version appending new
  decisions; no historical decision is reinterpreted, preserving the Task 12
  auditability contract.

## Alternatives Considered

- **Implement item 11 now with a placeholder/fake embedding provider**:
  rejected; it would freeze dimensionality, storage, and calibration around
  a provider that does not exist, produce untested-in-anger thresholds, and
  violate the Phase 2 no-AI boundary in spirit while adding no real
  duplicate-detection quality.
- **Drop vector similarity from the architecture entirely**: rejected; the
  design's reasons for the signal (semantic/paraphrase duplicates, future
  scale) remain valid, pgvector is already provisioned, and abandoning it
  would invite ad-hoc embedding use later without frozen constraints.
- **Keep Phase 2 open until vector similarity is built**: rejected; every
  other Phase 2 commitment is delivered and verified, the signal is not a
  provenance/security prerequisite, and blocking research operation on an
  uncalibratable feature would invert the quality-over-quantity principle.
- **Silently relabel item 11 as "future" without a decision record**:
  rejected explicitly by the closure audit; scope changes to an accepted
  design require a recorded, reviewable amendment — this document.
