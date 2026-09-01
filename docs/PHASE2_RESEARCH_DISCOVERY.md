# Phase 2 - Research / Discovery Foundation Design

Status: Accepted Phase 2 design (Phase 2 Task 1). Implementation closed on
2026-09-01: see docs/PHASE2_CLOSURE_AUDIT.md for the closure decision and
implementation deviations, and ADR 0008 for the formal deferral of the
vector-similarity signal (implementation-order item 11). The text below is
the original accepted design and is preserved as written; historical
statements such as "no runtime code exists yet" describe the state at design
time, not the current repository.

Scope: the left side of the pipeline only —
Source Registry → Discovery → Fetch → Normalize → Duplicate Detection →
Research/Evidence primitives. No idea scoring, briefs, writing, publishing, or
distribution.

Governing rule: RESEARCH, DO NOT TRANSLATE-AND-REPUBLISH. Everything in this
design exists to make evidence auditable and provenance non-bypassable
(EDITORIAL_POLICY.md; ADR 0005/0006/0007).

Relationship to WORKFLOW.md: the canonical editorial state machine in
WORKFLOW.md governs the future editorial work item (opportunity/content
candidate) from Phase 3 onward. Phase 2 entities deliberately do NOT reuse
those states. Each Phase 2 entity owns its own narrow lifecycle; the future
editorial item will *reference* these records when it enters `DISCOVERED` /
`RESEARCHING`, not absorb their states.

---

## 1. Source Registry

A **Source** is a configured, governed origin from which ContentOS may
discover research material. It is the sole admission gate: nothing is
discovered or fetched except on behalf of a registered, ACTIVE source
(ADR 0005).

### Fields (conceptual, implementation-ready)

| Field | Meaning |
| --- | --- |
| `id` | UUID primary identity |
| `slug` | Stable unique human-readable key (idempotency anchor) |
| `name` | Display name |
| `kind` | Enum, see below |
| `base_url` | Canonical origin (`scheme://host[:port]`, normalized lowercase host, no path unless meaningful) |
| `locale` | BCP-47 (initially `tr-TR` dominant) |
| `market` | ISO 3166-1 country (initially `TR`) |
| `lifecycle_state` | `ACTIVE` / `PAUSED` / `DISABLED` / `BLOCKED` |
| `state_reason` / `state_changed_at` | Why and when the state last changed (audited) |
| `trust_tier` | `OFFICIAL`, `EXPERT`, `REPUTABLE`, `GENERAL`, `REFERENCE_ONLY` |
| `discovery_strategy` | Enum + JSON config: how candidates are found for this source |
| `fetch_policy` | JSON: per-source overrides — min request interval, timeout, max body size |
| `robots_policy` | `OBEY` (the only Phase 2 value; field exists so the decision is explicit and auditable) |
| `terms_notes` | Free text: terms-of-use / licensing observations recorded by the operator |
| `metadata` | JSONB extension point (no schema promises) |
| `created_at` / `updated_at` | Timestamps |

`trust_tier` qualifies evidence weighting later; it never grants republication
rights. `REFERENCE_ONLY` sources may inform research but their expression must
never be reused.

### Source kinds

| Kind | Notes |
| --- | --- |
| `editorial_site` | Sites monitored for topical/evidence value |
| `competitor_site` | Inspiration/coverage comparison; expression is off-limits by policy |
| `rss_feed` | RSS/Atom feed endpoint |
| `sitemap` | XML sitemap endpoint |
| `manual` | Operator-registered candidates (no automated discovery) |
| `trend_provider` | Declared kind; **no integration exists or is implemented in Phase 2** |
| `search_provider` | Declared kind; **no integration exists or is implemented in Phase 2** |

Phase 2 implements discovery strategies only for `rss_feed`, `sitemap`, and
`manual`. `editorial_site`/`competitor_site` sources are discovered through
their feed or sitemap sub-sources in Phase 2. Provider kinds are enum
placeholders so the registry does not need schema changes later; registering
one does not make it functional.

### Lifecycle

```text
ACTIVE  <->  PAUSED        (temporary operator hold; resumable freely)
ACTIVE/PAUSED -> DISABLED  (long-term off; re-enable is an explicit operator act)
any     ->  BLOCKED        (policy/robots/legal/terms decision)
BLOCKED ->  ACTIVE         (only via explicit operator decision with reason)
```

Only `ACTIVE` sources are eligible for discovery and fetching. `BLOCKED`
differs from `DISABLED` by meaning "must not be used for a policy reason", not
"currently unwanted". Every transition records actor, reason, timestamp.

---

## 2. Discovery Item

A **DiscoveryItem** is a candidate resource (URL) found through a source's
discovery strategy. It is NOT downloaded content and carries no body.

### Fields

| Field | Meaning |
| --- | --- |
| `id` | UUID |
| `source_id` | FK → sources (the source it was discovered through) |
| `discovered_url` | URL exactly as found |
| `canonical_url` | Output of the URL canonicalization boundary (§9) |
| `url_hash` | SHA-256 of `canonical_url` (uniqueness/index key) |
| `title` / `snippet` | If offered by the feed/sitemap/operator; untrusted hint, not evidence |
| `discovery_method` | `FEED_ENTRY` / `SITEMAP_ENTRY` / `MANUAL` (provider methods reserved) |
| `discovered_at` | When ContentOS first recorded it |
| `external_published_at` | Publication timestamp claimed by the source, if any (untrusted) |
| `locale` | Inherited from source, overridable |
| `state` | See lifecycle |
| `rejection_reason` | Coded enum + optional note when `REJECTED` |
| `metadata` | JSONB |
| timestamps | created/updated |

### Lifecycle (admission only — fetch progress is not editorial state)

```text
DISCOVERED -> ACCEPTED      (passed admission checks; eligible for fetching)
DISCOVERED -> REJECTED      (terminal; coded reason)
ACCEPTED   -> FETCHED       (at least one successful immutable snapshot exists)
ACCEPTED   -> FETCH_FAILED  (bounded attempts exhausted; operator-visible)
FETCH_FAILED -> ACCEPTED    (explicit operator/system re-queue with reason)
```

Rejection reason codes (initial): `OUT_OF_SCOPE`, `DUPLICATE_URL`,
`SOURCE_NOT_ACTIVE`, `POLICY`, `INVALID_URL`, `UNSUPPORTED_SCHEME`.

Deliberate exclusions:

- No `QUEUED` state. Being enqueued in Celery is transient transport fact, not
  a durable domain fact; PostgreSQL remains authoritative (ARCHITECTURE.md).
- `FETCHED`/`FETCH_FAILED` are convenience projections; the authoritative fetch
  record is the FetchSnapshot. No editorial states (`RESEARCHING`, etc.) here.

---

## 3. Fetch Snapshot

A **FetchSnapshot** is the immutable record of one fetch attempt. Snapshots
are append-only: a later fetch of the same URL creates a new snapshot and
never overwrites earlier evidence (ADR 0006).

### Fields

| Field | Meaning |
| --- | --- |
| `id` | UUID |
| `discovery_item_id` | FK → discovery_items |
| `source_id` | FK → sources (denormalized for policy/rate queries) |
| `requested_url` | URL the fetcher was asked to fetch (canonical URL) |
| `final_url` | URL after redirects |
| `redirect_count` | Number of redirects followed |
| `http_status` | Integer, null when no response |
| `fetched_at` | Request start (UTC) |
| `fetch_duration_ms` | Total duration |
| `content_type` | Parsed media type of response |
| `content_length` | Bytes actually stored |
| `body_sha256` | Hash of the raw payload |
| `raw_payload_ref` | Opaque storage locator: `storage_backend` + key. Phase 2 initial backend is the ContentOS PostgreSQL (size-capped); object storage is a future backend behind the same reference shape. Blob storage itself is NOT implemented in this task. |
| `response_headers` | Allowlisted subset only (`content-type`, `content-language`, `last-modified`, `etag`, `cache-control`) — never cookies or auth material |
| `outcome` | `SUCCESS`, `HTTP_ERROR`, `NETWORK_ERROR`, `TIMEOUT`, `TOO_LARGE`, `DISALLOWED_MIME`, `ROBOTS_DISALLOWED`, `SSRF_BLOCKED`, `REDIRECT_LIMIT_EXCEEDED`, `INVALID_URL` |
| `robots_decision` | `ALLOWED` / `DISALLOWED` / `ROBOTS_UNAVAILABLE` (see §8 for fail behavior) |
| `fetcher_version` | Version of the fetch implementation |
| `metadata` | JSONB |
| `created_at` | Insert time |

### Immutability and retention

- Application code never updates or deletes snapshot rows; there is no update
  path in the repository layer.
- Failed attempts are also snapshots (without payload) — failures are evidence
  about source behavior.
- Retention (conceptual only in Phase 2): any snapshot referenced by research
  evidence is retained indefinitely; unreferenced raw payloads may later be
  pruned by an explicit, logged retention job honoring EDITORIAL_POLICY
  ("store only the source material necessary for research, verification, and
  audit"). No retention job is implemented in Phase 2.

---

## 4. Normalized Document

A **NormalizedDocument** is the extraction result derived from exactly one
FetchSnapshot. Raw HTML is never the normalized document. Reruns with a newer
extractor append a new row; they never mutate old rows.

### Responsibilities / fields

| Field | Meaning |
| --- | --- |
| `id` | UUID |
| `fetch_snapshot_id` | FK → fetch_snapshots (exactly one) |
| `status` | `SUCCEEDED` / `FAILED` / `EMPTY` / `UNSUPPORTED_CONTENT` |
| `failure_reason` | Coded reason when not `SUCCEEDED` |
| `canonical_title` | Extracted title |
| `clean_text` | Boilerplate-free body text (the excerpt-offset reference text for evidence) |
| `sections` | Ordered headings/section structure (JSONB) |
| `extracted_links` | Outbound links with anchor context (JSONB) |
| `language_detected` | Detected language + confidence |
| `publication_date_extracted` | If recoverable from markup/metadata (untrusted claim, recorded as such) |
| `author_attribution` | If present |
| `structured_metadata` | Selected OpenGraph/JSON-LD subset (JSONB) |
| `content_fingerprint` | SHA-256 of normalized text + a locality-sensitive fingerprint (e.g. simhash/minhash) for near-duplicate comparison |
| `extractor_name` / `extractor_version` / `parser_version` | Exact tooling provenance |
| `created_at` | Insert time |

Uniqueness: one row per (`fetch_snapshot_id`, `extractor_name`,
`extractor_version`) — reruns are idempotent per version and auditable across
versions.

### Extraction failure

A failed extraction is recorded as a NormalizedDocument row with `FAILED` /
`EMPTY` / `UNSUPPORTED_CONTENT` status. The raw snapshot remains untouched and
re-extraction with a newer extractor version is always possible. Failures are
operator-visible; they never silently discard the discovery item.

---

## 5. Duplicate / Similarity Decision

Duplicate detection is the pre-AI boundary that decides whether a normalized
document adds anything before any idea/AI spend. A decision is a durable,
auditable record — never just a boolean on the document.

### Outcomes

| Outcome | Meaning |
| --- | --- |
| `UNIQUE` | No material overlap found; eligible for downstream research |
| `RELATED` | Overlapping topic; still potentially valuable with a distinct angle |
| `UPDATE_EXISTING` | Same subject as existing ContentOS research/inventory; treat as update signal |
| `DUPLICATE` | Materially the same content; do not commission |
| `REJECT` | Not duplicate-related disqualification (spam/garbage/unusable extraction) |

### Signals (all recorded per decision)

1. Exact URL match (same `canonical_url` seen before)
2. Canonical URL match after redirects (`final_url` comparison)
3. Raw body hash match (`body_sha256`)
4. Normalized content hash match (fingerprint exact part)
5. Normalized title similarity
6. Lexical similarity (shingle/minhash over `clean_text`)
7. Vector similarity (pgvector embedding; model + version recorded per decision)
   *(deferred by ADR 0008 after the Phase 2 closure audit; re-entry triggers recorded there)*
8. Comparison universe: existing ContentOS normalized documents and research;
   **future**: published Konsepthane inventory via an explicit read-only
   contract (does not exist yet; no Konsepthane access is implied now)

No fixed thresholds are chosen in this design. Thresholds are configuration,
and every DuplicateDecision records the exact thresholds and engine version it
used (`thresholds_snapshot`), so historical decisions remain interpretable
after tuning.

### DuplicateDecision record

`id`, `normalized_document_id` (subject), `decision`, `decided_at`,
`engine_version`, `embedding_model` (+version) when vector similarity is used,
`thresholds_snapshot` (JSONB), `signals` (JSONB: each computed signal and its
value), `matched_references` (JSONB list: {kind, id, score} of the nearest
existing records), `decided_by` (`MACHINE` or `HUMAN` override + actor),
`note`, `created_at`. Append-only; re-evaluation appends a new decision and
the latest one is effective.

---

## 6. Research Evidence Primitive

The smallest auditable research unit, designed so a future Evidence Pack can
be assembled without re-deriving provenance (ADR 0007). Evidence Pack itself
is NOT part of Phase 2.

### Fields

| Field | Meaning |
| --- | --- |
| `id` | UUID |
| `statement` | The extracted fact/observation/claim as recorded |
| `evidence_type` | `SOURCE_ASSERTION`, `OBSERVATION`, `STATISTIC`, `QUOTE`, `INSTRUCTION` |
| `normalized_document_id` | FK, NOT NULL — exact document the statement came from |
| `fetch_snapshot_id` | FK, NOT NULL — exact immutable capture |
| `source_id` | FK, NOT NULL |
| `source_url` | Denormalized `final_url` for fast display |
| `excerpt_start` / `excerpt_end` | Offsets into the normalized `clean_text` |
| `excerpt_text` | The bounded excerpt itself (limited length by policy) |
| `extracted_at` | Timestamp |
| `extraction_method` | `MACHINE` (with model/tool + version) or `HUMAN` (actor) |
| `confidence` | 0..1 with a recorded basis |
| `licensing_note` | Copyright/usage caution for this excerpt where relevant |
| `verification_status` | `UNVERIFIED` → `VERIFIED` / `DISPUTED` / `RETRACTED` |
| `verified_by` / `verified_at` | When status changes |
| `metadata` | JSONB |

Provenance fields (`normalized_document_id`, `fetch_snapshot_id`, `source_id`,
excerpt boundaries, `extracted_at`, `extraction_method`) are immutable after
creation. `verification_status` is the only intentionally mutable dimension,
and its changes are audited. AI output is never a source (EDITORIAL_POLICY):
evidence must always point at a fetched snapshot, so a model cannot be a
provenance root by construction.

---

## 7. Copyright / Provenance Rules (binding for all later phases)

Research material MAY be:

- used as evidence with exact provenance;
- summarized and synthesized **across multiple sources**;
- transformed into original editorial planning (angles, outlines, briefs);
- compared against other evidence, including contradictions.

ContentOS MUST NOT:

- publish copied source text;
- rewrite a single article paragraph-by-paragraph (single-source paraphrase);
- reproduce protected images, tables, or distinctive structures;
- treat unknown-license media as reusable;
- fabricate quotes, statistics, or user-generated content;
- strip or detach provenance from any research artifact.

Non-bypassable enforcement (design commitments, per ADR 0007):

1. Evidence rows cannot exist without snapshot + document references
   (NOT NULL foreign keys, no "orphan evidence" API).
2. Excerpts are bounded (offset-limited); there is no evidence primitive that
   stores a whole article as "the evidence".
3. Future Writer/Editor stages receive evidence only through the evidence
   service, which always returns provenance with each unit — there is no
   "text-only" accessor to bypass it.
4. Snapshot immutability (ADR 0006) guarantees the provenance chain cannot be
   rewritten after the fact.
5. `REFERENCE_ONLY` trust tier and `licensing_note` travel with evidence; a
   later publication gate can therefore always see the caution.

---

## 8. Fetch / Crawl Policy Boundary (design; crawler NOT implemented yet)

| Rule | Policy |
| --- | --- |
| Schemes | `http`/`https` only; everything else rejected at canonicalization |
| Robots | robots.txt honored per host; explicit disallow → `ROBOTS_DISALLOWED` outcome (permanent for that URL until policy change). Robots endpoint unavailable → treat as retryable fetch failure, do NOT fail open on repeated unavailability without operator decision |
| Identification | Dedicated user agent, e.g. `KonsepthaneContentOSBot/<version> (+contact URL)`; never impersonate a browser |
| Concurrency | Bounded global worker concurrency; **per-host concurrency 1** initially |
| Rate limits | Per-host minimum request interval, per-source overrides via `fetch_policy` |
| Timeouts | Bounded connect + read timeouts |
| Body size | Hard maximum stored body size (e.g. single-digit MiB default, configurable); larger responses → `TOO_LARGE`, truncated bodies are not stored as success |
| Redirects | Bounded redirect count (e.g. 5); each hop re-validated against all rules below |
| MIME | Content-type allowlist (`text/html`, `application/xhtml+xml`, feed/XML types, `text/plain`); others → `DISALLOWED_MIME` |
| SSRF | Resolve DNS first, reject targets resolving to loopback, private (RFC 1918), link-local, ULA, or cloud-metadata ranges; verify **every** resolved address |
| DNS rebinding | Connect to the validated resolved IP (pinned) with the original Host/SNI, so a second resolution cannot swap targets mid-request |
| Credentials | No credentialed crawling by default; no cookies persisted |
| Execution | No browser automation and no JavaScript execution in the initial crawler; adding either later requires explicit approval (likely an ADR) |
| Retries | Classified: `TIMEOUT`/`NETWORK_ERROR`/5xx are retryable with bounded backoff; `ROBOTS_DISALLOWED`/`SSRF_BLOCKED`/`DISALLOWED_MIME`/4xx (except 429) are not |

---

## 9. Idempotency Boundaries

URL canonicalization is a single shared boundary (one function/module) used by
discovery and fetch alike: lowercase scheme/host, strip fragments, strip known
tracking parameters, normalize ports/trailing slashes, sort remaining query
parameters. Its version is recorded in metadata when it materially changes.

| Operation | Idempotency key / uniqueness boundary |
| --- | --- |
| Register source | `slug` unique; also (`kind`, `base_url`) unique — re-registration returns the existing source |
| Record discovery | (`source_id`, `url_hash`) unique — rediscovery touches "last seen" metadata, never duplicates rows |
| Fetch execution | Job keyed by `discovery_item_id`; a repeated job run may create a new snapshot (append-only is safe), but a bounded "recent successful snapshot exists" check prevents pointless refetch storms |
| Normalization | (`fetch_snapshot_id`, `extractor_name`, `extractor_version`) unique — reruns are no-ops per version |
| Duplicate decision | Append-only; rerun appends a decision with a newer `engine_version`/thresholds; effective decision = latest |
| Evidence extraction | (`normalized_document_id`, extractor identity, excerpt boundaries) unique to avoid duplicate machine evidence |

Celery delivery is at-least-once; these database-level boundaries — not queue
semantics — are what make repeated execution safe.

---

## 10. Module Ownership and Dependencies

New backend packages (modular monolith, same repo/database as Phase 1):

| Module (package) | Owns |
| --- | --- |
| `contentos.sources` | Source model, lifecycle, policies, registration service |
| `contentos.discovery` | DiscoveryItem, admission rules, discovery strategies (feed/sitemap/manual) |
| `contentos.fetching` | Safe HTTP client, crawl policy enforcement, FetchSnapshot |
| `contentos.normalization` | Extraction pipeline, NormalizedDocument, fingerprinting |
| `contentos.duplicates` | DuplicateDecision engine and records |
| `contentos.research` | ResearchEvidence primitives and evidence service |

Dependency direction (downward only; all may use `contentos.core` and
`contentos.db`):

```text
sources
  ↓
discovery        (reads source policy/state)
  ↓
fetching         (reads discovery items + source fetch/robots policy)
  ↓
normalization    (reads fetch snapshots only)
  ↓
duplicates       (reads normalized documents; queries research + normalized
  ↓               corpus READ-ONLY for comparison; future Konsepthane inventory
  ↓               via an explicit interface — no direct DB access, per ADR 0001)
research         (reads normalized documents + snapshots; owns evidence)
```

Cross-check rule: `duplicates` needs to look at `research`/`normalization`
data. That is a read-only query dependency expressed through repository
interfaces, not a reverse ownership dependency — `research` never calls
`duplicates`. No module imports upward; no cycles.

---

## 11. State Machine Summary (per entity, no global enum)

| Entity | States | Owner |
| --- | --- | --- |
| Source | `ACTIVE` / `PAUSED` / `DISABLED` / `BLOCKED` | `contentos.sources` |
| DiscoveryItem | `DISCOVERED` / `ACCEPTED` / `REJECTED` / `FETCHED` / `FETCH_FAILED` | `contentos.discovery` |
| FetchSnapshot | none — immutable record with an `outcome` classification | `contentos.fetching` |
| NormalizedDocument | none — immutable per extractor version with a `status` | `contentos.normalization` |
| DuplicateDecision | none — append-only decisions | `contentos.duplicates` |
| ResearchEvidence | `verification_status` only: `UNVERIFIED` / `VERIFIED` / `DISPUTED` / `RETRACTED` | `contentos.research` |

No Phase 2 entity uses editorial states (`DRAFT`, `PUBLISHED`,
`AWAITING_HUMAN_REVIEW`, …). Those belong to the future editorial work item
defined in WORKFLOW.md.

---

## 12. Database Plan (future migrations; NOT created in this task)

| Table | Purpose | Identity | Key FKs | Uniqueness | Mutability | Likely indexes |
| --- | --- | --- | --- | --- | --- | --- |
| `sources` | Governed origin registry | UUID | — | `slug`; (`kind`, `base_url`) | Mutable with audited lifecycle | `lifecycle_state`, `kind` |
| `discovery_items` | Candidate URLs | UUID | `source_id` | (`source_id`, `url_hash`) | State-mutable, provenance-immutable | `state`, `url_hash`, `discovered_at` |
| `fetch_snapshots` | Immutable fetch attempts | UUID | `discovery_item_id`, `source_id` | none (append-only history) | **Append-only** | `discovery_item_id`, `body_sha256`, `fetched_at`, `outcome` |
| `normalized_documents` | Extraction results | UUID | `fetch_snapshot_id` | (`fetch_snapshot_id`, `extractor_name`, `extractor_version`) | **Append-only** per version | `content_fingerprint`, `language_detected`, `status` |
| `duplicate_decisions` | Auditable duplicate outcomes | UUID | `normalized_document_id` | none (append-only) | **Append-only** | (`normalized_document_id`, `decided_at`), `decision` |
| `research_evidence` | Evidence primitives | UUID | `normalized_document_id`, `fetch_snapshot_id`, `source_id` | (`normalized_document_id`, extractor identity, excerpt bounds) | Provenance-immutable; `verification_status` mutable | `verification_status`, `evidence_type`, `source_id` |

Vector columns (pgvector) attach to `normalized_documents` (document
embedding) when the duplicate engine lands; embedding model/version is stored
alongside, never assumed. Full column DDL is deliberately deferred to each
implementation task.

---

## 13. Job / Queue Plan (future Celery jobs; NOT implemented in this task)

PostgreSQL is authoritative; a job may perform work for a state but queue
completion never advances domain state by itself.

| Job | Input identity | Idempotency | Retryable failures | Persists |
| --- | --- | --- | --- | --- |
| `discover_source` | `source_id` (+ optional window) | (`source_id`, `url_hash`) uniqueness absorbs re-runs | Network/feed timeouts; malformed feed entries are recorded, not retried | Before: source `ACTIVE`. After: new/touched discovery_items |
| `fetch_discovery_item` | `discovery_item_id` | Recent-snapshot check + append-only snapshots | `TIMEOUT`/`NETWORK_ERROR`/5xx/429 with backoff; policy outcomes are terminal | Before: item `ACCEPTED`. After: snapshot row + item `FETCHED`/`FETCH_FAILED` |
| `normalize_fetch` | `fetch_snapshot_id` | Unique per (snapshot, extractor version) | Transient parser/resource errors; deterministic failures recorded as `FAILED` rows | After: normalized_documents row (any status) |
| `evaluate_duplicate` | `normalized_document_id` | Append-only decisions; latest wins | Embedding-provider transient errors (when vector signal exists) | After: duplicate_decisions row |
| `extract_research_evidence` | `normalized_document_id` | Unique per (document, extractor, excerpt) | Model/provider transient errors | After: research_evidence rows (`UNVERIFIED`) |

Job chaining is explicit (a job schedules the next one only after its
database write commits). No business state lives only inside Celery/Redis.

---

## 14. Phase 2 Implementation Order (atomic tasks)

1. **Source Registry persistence** — Source model + enums + migration `0002`
   + repository/service with idempotent registration + tests. *(= Task 2, below)*
2. Source lifecycle service (audited transitions) + minimal API endpoints for
   source listing/registration (single-operator, no auth by design).
3. URL canonicalization boundary (pure module + exhaustive unit tests).
4. DiscoveryItem model + migration + admission service (uniqueness,
   rejection codes); manual discovery method first.
5. Feed (RSS/Atom) discovery strategy; then sitemap strategy.
6. Safe HTTP fetch client (policy boundary of §8: SSRF guard, robots, limits)
   as a pure, worker-independent component with tests.
7. FetchSnapshot model + migration + append-only repository; wire client to
   persistence.
8. Normalization pipeline v1 (extractor + NormalizedDocument + migration),
   including failure statuses.
9. Content fingerprinting (hashes + lexical fingerprint) on normalized docs.
10. DuplicateDecision model + engine v1 using URL/hash/lexical signals only
    (no embeddings yet); configurable thresholds recorded per decision.
11. pgvector embedding column + vector similarity signal in the duplicate
    engine (provider-neutral embedding interface).
    *Deferred by ADR 0008 after the Phase 2 closure audit.*
12. ResearchEvidence model + migration + evidence service (provenance
    enforcement).
13. Celery orchestration: `discover_source` → `fetch_discovery_item` →
    `normalize_fetch` → `evaluate_duplicate` chain with idempotency.
14. Minimal admin visibility: read-only sources + discovery/fetch status page
    (server-side, same boundary rules as the Foundation Status page).

### Recommended Task 2 (exact)

Implement the **Source Registry persistence foundation** only:

- `Source` SQLAlchemy model on the existing `contentos.db.base.Base` in a new
  `contentos/sources` package, with `SourceKind`, `SourceLifecycleState`, and
  `TrustTier` enums;
- Alembic migration `0002_create_sources` (upgrade + safe downgrade);
- uniqueness on `slug` and (`kind`, `base_url`);
- a repository/service with idempotent `register_source` (re-registering the
  same identity returns the existing record) and audited lifecycle-state
  transition (`ACTIVE`/`PAUSED`/`DISABLED`/`BLOCKED` with reason);
- unit tests with fakes plus migration verification against an ephemeral
  Dockerized PostgreSQL (same pattern as Phase 1), keeping the default test
  suite Postgres-free;
- no API endpoints, no admin UI, no Celery, no discovery logic.

---

## Explicitly NOT in Phase 2

Idea scoring, evidence packs, SEO/intent research, briefs, writing, editing,
QA, human review flows, scheduling, publishing, Pinterest, analytics, media
handling, trend/search provider integrations, browser-based crawling,
authentication (single-operator model unchanged), and any Konsepthane access.
