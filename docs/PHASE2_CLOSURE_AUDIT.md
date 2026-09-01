# Phase 2 Closure Audit — Research / Discovery Foundation

Status: Audit complete (Phase 2 Task 18). This document is the formal Phase 2
closure decision record.

Audited at HEAD: `ea9e9ac feat: add read-only research pipeline visibility`
Audit date: 2026-09-01
Schema head at audit: `0008` (verified via `alembic heads`)
Verified baseline at audit: backend 652 tests passed, admin 60 tests passed,
`scripts/check.ps1` all stages passed, `git diff --check` clean, lockfiles
unchanged.

> **Task 19 follow-up (2026-09-01): closure condition 2 RESOLVED BY
> IMPLEMENTATION.** The minimal operator control surface now exists — see the
> note in §11. The only remaining closure condition is the vector-similarity
> formal disposition (condition 1, to be resolved by the Task 20 scope
> decision). The executive decision remains **PHASE 2 CONDITIONALLY
> COMPLETE** until Task 20 records that decision. Verified baseline after
> Task 19: backend 687 tests, admin 96 tests, `scripts/check.ps1` green,
> schema head still `0008`, lockfiles unchanged.

---

## 1. Executive decision

**B. PHASE 2 CONDITIONALLY COMPLETE.**

The entire runtime foundation promised by the accepted Phase 2 design is
implemented, verified against real PostgreSQL, and protected by the security,
immutability, and provenance invariants of ADRs 0005/0006/0007. No
implemented behavior violates the accepted design.

Closure is conditional because two explicit design commitments are neither
implemented nor formally amended out of scope:

1. **Vector similarity duplicate signal** — design §5 signal 7, §12 vector
   column plan, and implementation-order item 11. Not implemented; never
   formally removed from Phase 2 scope in any accepted repository record.
2. **Minimal source registration endpoints / operator mutation surface** —
   implementation-order item 2 promised "minimal API endpoints for source
   listing/registration". Listing exists (Task 17); registration and every
   other operator mutation (accept/reject/requeue, lifecycle transitions)
   remain programmatic-only.

Phase 2 may be declared COMPLETE as soon as each condition is resolved by
either implementation or a formally recorded scope amendment (§11, §12).
Nothing else blocks closure.

---

## 2. Scope audited

- Authoritative design: `docs/PHASE2_RESEARCH_DISCOVERY.md` (accepted, Task 1),
  read in full, including the field tables (§1–§6), copyright/provenance rules
  (§7), crawl policy (§8), idempotency boundaries (§9), module dependencies
  (§10), database plan (§12), job plan (§13), implementation order (§14), and
  the "Explicitly NOT in Phase 2" list.
- Governing records: ADR 0005 (admission gate), ADR 0006 (immutable
  snapshots), ADR 0007 (evidence provenance), `docs/ARCHITECTURE.md`,
  `docs/WORKFLOW.md`, `docs/EDITORIAL_POLICY.md`, and the Task 2–17 history in
  `docs/memory/CURRENT_STATE.md`.
- Implementation: the `contentos.sources/discovery/fetching/normalization/
  duplicates/research/payloads/worker` packages, migrations `0002`–`0008`,
  the `contentos.api` read surface, and `apps/admin`. Claims below were
  verified by targeted code/graph search, not assumed from memory.
- Out of audit scope: Phase 1 foundation (closed earlier), Phase 3 features.

---

## 3. Accepted Phase 2 commitments

From the design's implementation order (§14), the accepted Phase 2 work was:

1. Source Registry persistence
2. Source lifecycle service + **minimal API endpoints for source
   listing/registration**
3. URL canonicalization boundary
4. DiscoveryItem model + admission service (manual first)
5. Feed (RSS/Atom) then sitemap discovery strategies
6. Safe HTTP fetch client (crawl policy §8)
7. FetchSnapshot model + append-only persistence
8. Normalization pipeline v1 incl. failure statuses
9. Content fingerprinting on normalized documents
10. DuplicateDecision model + engine v1 "using URL/hash/lexical signals only
    (no embeddings yet)"
11. **pgvector embedding column + vector similarity signal in the duplicate
    engine**
12. ResearchEvidence model + evidence service (provenance enforcement)
13. Celery orchestration chain with idempotency
14. Minimal admin visibility: read-only sources + discovery/fetch status page

Plus the binding cross-cutting commitments: admission gate (ADR 0005),
snapshot immutability (ADR 0006), non-bypassable evidence provenance
(ADR 0007), the crawl policy table (§8), the idempotency table (§9), the
module dependency direction (§10), and "PostgreSQL authoritative; queue
completion never advances domain state" (§13).

---

## 4. Implementation evidence matrix

Status vocabulary: COMPLETE, COMPLETE_DIFFERENT_IMPLEMENTATION,
DEFERRED_ACCEPTED, BLOCKER, OUT_OF_SCOPE, DOC_DRIFT.

| Design commitment | Design source | Implementation | Verification | Status | Disposition |
| --- | --- | --- | --- | --- | --- |
| A. Source Registry (model, enums, uniqueness, audited lifecycle, idempotent registration) | §1, §14 item 1, ADR 0005 | `contentos.sources` (models/enums/repository/service), migration `0002`; slug + (kind, base_url) unique; `SourceLifecycleEvent` audit with monotonic id; BLOCKED→ACTIVE-only | `tests/unit/test_sources.py`; Task 2 real-PG run incl. downgrade cycle | COMPLETE | Closed |
| A2. Source lifecycle **endpoints** (registration) | §14 item 2 | Service exists (`SourceRegistryService.register_source`, `transition_source_state`); listing endpoint exists (Task 17); **no registration/mutation endpoint** | Task 17 surface is GET-only by accepted task scope | **BLOCKER** (until implemented or formally amended) | Closure condition 2 — see §11/§12 |
| B. DiscoveryItem (admission, uniqueness, rejection codes, lifecycle, conservative rediscovery) | §2, §14 item 4 | `contentos.discovery` (model/enums/repository/service), migration `0003`; (source_id, url_hash) unique; all six rejection codes; DISCOVERED/ACCEPTED/REJECTED/FETCHED/FETCH_FAILED with explicit reasoned requeue | `tests/unit/test_discovery.py`; Task 4 real-PG run | COMPLETE | Closed |
| B2. No QUEUED state; fetch progress is projection, not editorial state | §2 exclusions | No queue-state columns anywhere; PostgreSQL authoritative | Task 16 design + tests | COMPLETE | Closed |
| C. Safe fetch/crawl policy (§8 table: schemes, robots, UA, per-host concurrency 1, rate interval, timeouts, body cap, bounded redirects w/ per-hop revalidation, MIME allowlist, SSRF resolve-all + pinned-IP/SNI anti-rebinding, no cookies/credentials, no browser/JS, classified retries) | §8, §14 item 6 | `contentos.fetching.client` + `policy`: `trust_env=False`, `verify=True`, `sni_hostname` pinning, cookie clearing, syntax→SSRF→robots per hop, streamed caps, allowlists, process-local per-host limiter (concurrency 1 + min interval) | `tests/unit/test_fetching.py` (exhaustive offline); code lines cited verified this audit | COMPLETE | Closed. Distributed (cross-worker) limiting: see §14-item in deviations |
| D. RSS/Atom discovery | §14 item 5 | `contentos.discovery.feed`: DTD/entity rejection, bounded parsing, ACTIVE `rss_feed`+`feed` eligibility, shared admission | `tests/unit/test_feed_discovery.py` (Task 6: offline) | COMPLETE | Closed |
| E. Sitemap discovery | §14 item 5 | `contentos.discovery.sitemap`: bounded URL-set + recursive index traversal, same-origin child rule, centralized limits | `tests/unit/test_sitemap_discovery.py` (Task 7) | COMPLETE | Closed |
| F. FetchSnapshot (immutable, append-only, failures are snapshots, opaque payload ref) | §3, §14 item 7, ADR 0006 | `contentos.fetching.snapshots` + repository/service, migration `0004` with append-only trigger; failures recorded without payload; `raw_payload_ref` opaque | `tests/unit/test_fetch_snapshots.py`; Task 8 real-PG raw UPDATE/DELETE rejection | COMPLETE (field-level drift in §5 below) | Closed |
| G. Raw payload persistence (Postgres-backed, size-capped, opaque ref shape) | §3 `raw_payload_ref` row, ADR 0006 | Task 10 provider-neutral contracts (`contentos.payloads`) + Task 15 durable `PostgresRawPayloadStore` (`postgres:sha256:<hex>`, BYTEA, content-addressed, append-only trigger), migration `0008` | `test_payloads.py`, `test_payloads_postgres.py`; Task 15 real-PG 25-step run | COMPLETE | Closed |
| H. NormalizedDocument (immutable per extractor version, failure rows, uniqueness) | §4, §14 item 8 | `contentos.normalization` models/service, migration `0005`; (snapshot, extractor_name, extractor_version) unique; typed retry/conflict | `test_normalization.py`; Task 9 real-PG run | COMPLETE (field-level drift in §5) | Closed |
| I. Normalization pipeline v1 (extractor, charset policy, bounded extraction, failure statuses) | §4, §14 item 8 | `contentos.normalization.pipeline` + `html-basic/1`, `text-basic/1`; verified payload reads only; stdlib parser, no NLP | `test_normalization_pipeline.py` (Task 11 incl. synthetic E2E) | COMPLETE | Closed |
| J. Content fingerprinting | §14 item 9 | SHA-256 fingerprint v1 over exact clean-text bytes on every succeeded document | Task 11 tests | COMPLETE_DIFFERENT_IMPLEMENTATION (no stored LSH; see §5) | Closed for Phase 2 baseline |
| K. DuplicateDecision + engine v1 (URL/hash/lexical signals, thresholds snapshot, matches, append-only) | §5, §14 item 10 | `contentos.duplicates`, migration `0006`; `duplicate-engine/1`; signals 1–6 of §5 implemented; frozen thresholds + signals + bounded matches + rationale codes persisted per decision | `test_duplicates.py`; Task 12 real-PG run | COMPLETE (record-shape drift in §5) | Closed |
| K2. Vector similarity signal (+ embedding model/version provenance, pgvector column) | §5 signal 7, §12, **§14 item 11** | **Not implemented.** No vector column, no embedding interface, no vector code outside health checks (verified by repo-wide search) | — | **BLOCKER** (until implemented or formally amended) | Closure condition 1 — see §11/§12 |
| L. ResearchEvidence (NOT NULL provenance FKs, bounded excerpts, exact offsets, evidence identity, no orphan API) | §6, §7, §14 item 12, ADR 0007 | `contentos.research` models/validation/repository/service, migration `0007`; derived provenance (callers cannot supply it); exact-slice excerpt contract v1; evidence_key v1 SHA-256 identity | `test_research_evidence.py`; Task 13 real-PG 24-step run | COMPLETE (intentional strengthening in §5) | Closed |
| M. Evidence extraction (machine, deterministic, idempotent) | §13 `extract_research_evidence` row, §9 | `contentos.research.extractor` `deterministic-evidence/1` (author/date metadata evidence, excerpt-less UNVERIFIED, no invention) | `test_evidence_extractor.py` (Task 14) | COMPLETE | Closed. (Design's "model/provider" wording anticipated AI extractors — those are Phase 3; deterministic machine extraction satisfies the Phase 2 primitive.) |
| N. Celery orchestration (five jobs, idempotent, commit-before-enqueue, PostgreSQL authoritative, classified retries) | §13, §14 item 13 | `contentos.worker.research_tasks` + `runtime`: frozen task names, acks_late at-least-once, commit-before-enqueue, bounded dispatch retry, admission boundary preserved, 30s→600s backoff, terminal policy failures never retried | `test_research_tasks.py` (32 tests); Task 16 real-PG eager full-chain run | COMPLETE | Closed |
| O. Read-only admin observability | §14 item 14 | `/internal/research/*` GET-only API + `/sources`, `/research`, `/research/[id]` admin pages; server-only boundary; no payload/excerpt/statement exposure | `test_research_read_api.py` (25), admin suites (60); Task 17 real-PG run | COMPLETE (exceeds item 14: adds pipeline detail + evidence summaries) | Closed |
| P. PostgreSQL/pgvector foundation | §12, Phase 1 | Migrations `0001`–`0008`; pgvector extension installed and health-checked; every append-only table trigger-protected (verified: triggers in `0004`–`0008`) | Phase 1/2 real-PG runs; readiness endpoint | COMPLETE | Closed |
| Q. Security/copyright/provenance invariants | §7, §8, ADRs 0005–0007 | See §8 of this audit | See §8 | COMPLETE | Closed |
| R. Module dependency direction (downward only, no cycles) | §10 | sources→discovery→fetching→normalization→duplicates→research holds; `duplicates` reads normalization/research read-only; worker/api sit above domain modules | import structure; mypy strict build | COMPLETE | Closed |
| S. Idempotency boundaries (§9 table) | §9 | All six rows implemented: slug/(kind,base_url); (source_id,url_hash); recent-successful-snapshot reuse (Task 16); (snapshot,extractor,version); append-only decisions; evidence identity (strengthened to evidence_key) | Tasks 2–16 tests | COMPLETE | Closed |
| T. URL canonicalization boundary (shared, versioned) | §9, §14 item 3 | `contentos.core.urls` v1, `URL_CANONICALIZATION_VERSION = 1`, version persisted on discovery rows | `test_core_urls.py` (Task 3) | COMPLETE | Closed |

---

## 5. Design-vs-implementation deviations

Each deviation was audited individually. None violates an ADR. "Design"
refers to the conceptual field tables of `PHASE2_RESEARCH_DISCOVERY.md`, which
that document itself qualifies as "conceptual, implementation-ready" — exact
DDL was "deliberately deferred to each implementation task" (§12).

### 5.1 DuplicateDecision record (design §5 vs Task 12)

| Design concept | Implementation | Classification |
| --- | --- | --- |
| `engine_version` | `engine_name` + `engine_version` (richer identity) | COMPLETE_DIFFERENT_IMPLEMENTATION |
| `thresholds_snapshot` | `thresholds` JSONB (frozen snapshot per decision) | COMPLETE (name only) |
| `signals` per decision | `signals` JSONB (aggregates of signals 1–6) | COMPLETE |
| `matched_references` | `matches` JSONB (bounded ≤10, safe provenance) | COMPLETE (name only) |
| `decided_at` | `evaluated_at` | COMPLETE (name only) |
| `embedding_model` (+version) | Absent — meaningful only with signal 7 | Travels with closure condition 1 (vector signal) |
| `decided_by` (MACHINE / HUMAN override + actor), `note` | Absent — engine is machine-only; no override path | DEFERRED_ACCEPTED: "human review flows" are in the design's "Explicitly NOT in Phase 2" list; a human-override decision belongs to that future review surface |
| Append-only, "re-evaluation appends, latest is effective" | Append-only enforced by PG trigger; identity unique per (document, engine_name, engine_version): exact retries return the stored row, changed output under the same version is a typed conflict, new versions append and coexist; "latest effective" is deterministic ordering (used by Task 17 projections) | COMPLETE_DIFFERENT_IMPLEMENTATION — strengthened: same-version silent re-decision is impossible, which is stricter than the design and better for audit |

### 5.2 ResearchEvidence (design §6 vs Tasks 13–14)

| Design concept | Implementation | Classification |
| --- | --- | --- |
| Provenance fields immutable; `verification_status` "the only intentionally mutable dimension… changes audited" (also ADR 0007) | Entire row append-only (PG trigger); `verification_status` is stored but **no mutation path exists at all** | COMPLETE_DIFFERENT_IMPLEMENTATION — implementation is strictly stronger than required. The permitted mutability was an allowance for a future verification workflow, not an obligation; that workflow belongs with human review flows (explicitly not Phase 2). When it lands, the audited status change must be designed then (new columns + audit, or an append-only verification-events table — the latter preserves the current trigger). |
| `verified_by` / `verified_at` | Absent (no verification workflow exists to populate them) | DEFERRED_ACCEPTED (Phase 3, with review flows) |
| `confidence` 0..1 "with a recorded basis" | `confidence` Decimal 0..1 + mandatory `confidence_basis` (DB CHECK) | COMPLETE |
| `licensing_note` | `licensing_notes`, operator note only, never inferred | COMPLETE |
| `excerpt_text` + offsets | `excerpt` + `excerpt_start/end` + `offset_version` (frozen v1 code-point offsets, exact-slice DB CHECK, VERIFIED-requires-excerpt CHECK) | COMPLETE_DIFFERENT_IMPLEMENTATION — strengthened |
| Uniqueness "(document, extractor identity, excerpt boundaries)" | `evidence_key` v1 = SHA-256 over (type, statement, excerpt bounds), unique per (document, extractor identity, key) | COMPLETE_DIFFERENT_IMPLEMENTATION — strengthened: identity also covers statement content, so a changed statement under identical offsets cannot silently collide |
| Extraction method MACHINE "(with model/tool + version)" | `extraction_method` + `extractor_name`/`extractor_version` (deterministic tool; no AI models exist) | COMPLETE |

### 5.3 FetchSnapshot (design §3 vs Task 8)

| Design concept | Implementation | Classification |
| --- | --- | --- |
| `source_id` denormalized FK "for policy/rate queries" | Absent; source reached via `discovery_item_id` join (Task 17 read models do exactly this) | COMPLETE_DIFFERENT_IMPLEMENTATION — semantic equivalent; no rate/policy query needs the denormalization today. May be added additively if per-source snapshot queries become hot. |
| `redirect_count` | `redirect_chain` (full ordered list; count derivable) | COMPLETE_DIFFERENT_IMPLEMENTATION — strictly more information |
| `http_status` / `content_length` / `fetch_duration_ms` / `response_headers` | `status_code` / `body_size_bytes` / `duration_ms` / `selected_headers` (same allowlist semantics) | COMPLETE (names only) |
| `outcome` vocabulary | Superset: adds `ROBOTS_UNAVAILABLE`; `robots_decision` adds `NOT_EVALUATED`; plus `retry_classification` and `retry_after_seconds` (beyond design) | COMPLETE_DIFFERENT_IMPLEMENTATION — strengthened |
| `fetcher_version` | Absent | DOC_DRIFT / accepted minor gap: fetch behavior provenance lives in code history; the capture itself (bytes, hashes, outcomes, headers) is fully recorded. Add additively only if a fetch-behavior dispute ever requires it. Not a closure condition. |
| `metadata` JSONB extension point | Absent | DOC_DRIFT / accepted minor gap: additive when first needed; append-only rows argue against speculative columns. Not a closure condition. |

### 5.4 NormalizedDocument (design §4 vs Tasks 9/11)

| Design concept | Implementation | Classification |
| --- | --- | --- |
| `status` SUCCEEDED/FAILED/EMPTY/UNSUPPORTED_CONTENT | `SUCCEEDED`/`FAILED` + `failure_code` (`empty_content`, `unsupported_content`, `decode_error`, `parse_error`, `extractor_error`, `policy_rejected`) | COMPLETE_DIFFERENT_IMPLEMENTATION — same information, cleaner status/reason split |
| `canonical_title` / `author_attribution` / `publication_date_extracted` | `title` / `author_name` / `external_published_at` (recorded as untrusted claims) | COMPLETE (names only) |
| `language_detected` + confidence | `language` from explicit markup declaration only; no statistical detection, no confidence | COMPLETE_DIFFERENT_IMPLEMENTATION — deliberate: the pipeline never invents metadata (no NLP by accepted Task 11 scope). Statistical detection, if ever wanted, is a new extractor version. |
| `sections` / `extracted_links` / `structured_metadata` | `headings` + `sections` / `links` / `structured_metadata` (bounded, curated) | COMPLETE |
| `content_fingerprint` = "SHA-256 **+ a locality-sensitive fingerprint** (e.g. simhash/minhash)" | SHA-256 fingerprint v1 stored; near-duplicate capability provided at decision time by the engine's bounded lexical token-set similarity (Task 12), not by a stored LSH column | COMPLETE_DIFFERENT_IMPLEMENTATION for the Phase 2 baseline — see verdict below |
| Extractor/parser identity | `extractor_name`/`extractor_version`/`parser_version` | COMPLETE |

**Fingerprint sufficiency verdict (audit item 9):** implementation-order item
10 required engine v1 to use "URL/hash/lexical signals only" — satisfied: the
engine computes exact fingerprint/raw-hash/URL signals plus lexical and title
similarity over a bounded candidate set (≤200 comparisons, exact-signal
candidates prioritized). At the current corpus scale this is a correct and
sufficient pre-AI duplicate gate. A *stored* LSH fingerprint is a scaling
optimization for candidate selection, not a Phase 2 exit requirement; it
becomes worth revisiting together with the vector signal (both change
candidate retrieval). This is intentionally NOT conflated with vector
similarity (closure condition 1), which is a separate promised signal.

### 5.5 Distributed fetch rate limiting (audit item 14)

Design §8 requires "bounded global worker concurrency; per-host concurrency 1
initially" and per-host minimum intervals. The implemented limiter is
process-local (Task 5, recorded then as "distributed enforcement deferred to
Celery orchestration"). Task 16 added **no** distributed enforcement — with a
single worker process (the current Compose deployment) the §8 guarantee holds
exactly; with multiple workers the per-host bound becomes per-process.

Classification: DEFERRED_ACCEPTED for Phase 2 (the design says "initially" and
never promised cross-worker enforcement); REQUIRED_BEFORE_PRODUCTION for any
deployment with more than one fetch-capable worker (§7 matrix). Until then,
worker concurrency must stay at one process for fetch workloads.

### 5.6 DB-commit / broker-publish gap (audit item 15)

Task 16 deliberately ships without a transactional outbox. Current strategy:
commit durable output first, then enqueue; a post-commit publish failure
triggers a bounded DISPATCH retry whose rerun finds the durable output and
only reschedules. `acks_late` + `reject_on_worker_lost` mean a crash between
commit and enqueue redelivers the original message, which recovers the chain.

Residual failure window: broker message loss (Redis restart with volatile
broker) or dispatch-retry exhaustion leaves a chain *stalled* with fully
consistent durable state — never corrupted, never duplicated. Recovery is
re-enqueueing the stalled stage (idempotent by construction); the Task 17
screens make stalls visible (e.g. FETCHED item with no NormalizedDocument).

Verdict: acceptable for Phase 2 (single-operator, restartable, observable).
Outbox trigger criteria: recurring stalled chains in production, a durable
broker requirement, or any workflow where a lost hand-off has editorial cost.
Revisit via ADR before Phase 4/production hardening.

---

## 6. Intentional deferrals (accepted by design wording — no amendment needed)

| Item | Design evidence | Disposition |
| --- | --- | --- |
| Raw payload retention/pruning | §3: "Retention (conceptual only in Phase 2)… No retention job is implemented in Phase 2"; ADR 0006 "Retention is a future, explicit, logged pruning process" | OUT_OF_SCOPE for Phase 2 by explicit wording; REQUIRED_BEFORE_PRODUCTION (long-run storage growth), see §7 |
| Celery Beat / periodic discovery scheduling (audit item 10) | The design nowhere requires scheduling: §13 defines *executable* jobs; §14 item 13 requires the orchestration chain only; "scheduling" in "Explicitly NOT in Phase 2" refers to editorial scheduling. `discover_source` exists and runs; nothing enqueues it periodically | OUT_OF_SCOPE for Phase 2 (never promised); REQUIRED_BEFORE_PRODUCTION for hands-off operation |
| Evidence Pack, idea scoring, briefs, Writer/Editor/QA, human review flows, publishing, Pinterest, analytics, media, trend/search providers, browser crawling, authentication, Konsepthane access | "Explicitly NOT in Phase 2" list | OUT_OF_SCOPE (Phase 3+) |
| Konsepthane inventory comparison in the duplicate universe | §5 signal 8: "**future**… does not exist yet; no Konsepthane access is implied now" | OUT_OF_SCOPE by explicit wording |
| Human duplicate override (`decided_by`), evidence verification workflow (`verified_by`/`verified_at`) | §5/§6 concepts vs "human review flows" exclusion | DEFERRED_ACCEPTED to the Phase 3 review surface (see §5.1/§5.2) |
| AI/model-based evidence extractors and embedding providers | §13 retry wording anticipates them; no AI is permitted in Phase 2 tasks | OUT_OF_SCOPE (Phase 3), subject to ADR 0007 invariants |

---

## 7. Production-readiness considerations (separate from phase completion)

Phase completion measures delivery of the accepted design. Production
readiness measures safe unattended operation. They are not the same; nothing
below except the two named closure conditions blocks Phase 2.

| Concern | Classification |
| --- | --- |
| Operator mutation surface (source registration, admission, requeue) | REQUIRED_FOR_PHASE2 — closure condition 2 (design item 2), unless formally amended |
| Vector similarity signal disposition | REQUIRED_FOR_PHASE2 — closure condition 1 (implement or amend) |
| Deployment infrastructure access protection (admin/API are unauthenticated by design) | REQUIRED_BEFORE_PRODUCTION — never expose beyond a trusted network boundary |
| Secrets provisioning (`.env` is local-only today) | REQUIRED_BEFORE_PRODUCTION |
| PostgreSQL backups / restore drill | REQUIRED_BEFORE_PRODUCTION |
| Raw payload retention job (append-only growth) | REQUIRED_BEFORE_PRODUCTION (long-run); bounded near-term by body caps + MIME allowlist |
| Distributed per-host rate limiting | REQUIRED_BEFORE_PRODUCTION if >1 fetch worker; until then pin fetch workers to one process |
| Periodic discovery scheduling (Beat or equivalent) | REQUIRED_BEFORE_PRODUCTION for hands-off operation; manual triggering suffices for supervised use |
| Monitoring/alerts (stalled chains, fetch failure rates, queue depth) | REQUIRED_BEFORE_PRODUCTION; Task 17 screens are the interim manual monitor |
| Operator runbooks (requeue, stalled-chain recovery, source blocking) | REQUIRED_BEFORE_PRODUCTION |
| Worker process sizing / concurrency policy | REQUIRED_BEFORE_PRODUCTION |
| Disaster recovery / broker durability decision (see §5.6) | REQUIRED_BEFORE_PRODUCTION |
| Source allowlist governance execution (see §8.3) | REQUIRED_BEFORE_PRODUCTION |
| Stored LSH fingerprint / candidate-retrieval scaling | POST_LAUNCH / OPTIONAL |
| Transactional outbox | OPTIONAL until §5.6 trigger criteria met |
| Object-storage payload backend | OPTIONAL (opaque ref shape keeps the path open, ADR 0006) |

---

## 8. Security / provenance invariants (audit items 16–17)

All verified against code at HEAD; none violated. Any violation would have
been a BLOCKER.

### 8.1 Crawler / system security

| Invariant | Evidence |
| --- | --- |
| Registered ACTIVE source required for automated discovery/fetch | `discover_source`/`fetch_discovery_item` skip non-ACTIVE sources without network I/O; admission services refuse non-ACTIVE sources (Tasks 4/6/7/16 tests) |
| SSRF protections, every resolved address validated | `contentos.fetching.client`: resolve-then-validate, one unsafe answer fails closed; gate ordering syntax→SSRF→robots per hop (Task 5 fix) |
| DNS-rebinding defense | Pinned-IP connect + Host header + `sni_hostname` extension (client.py) |
| Redirect revalidation | Manual redirect following, full per-hop revalidation, bounded hops |
| Robots fail-closed | Disallow → terminal `ROBOTS_DISALLOWED`; robots endpoint unavailable → retryable `ROBOTS_UNAVAILABLE`, never fail-open |
| Bounded bodies / MIME allowlist | Streamed byte caps (Content-Length advisory only); conservative MIME allowlist |
| No cookie replay / no env credential adoption / TLS never weakened | `trust_env=False`, `verify=True`, `cookies.clear()` per request (client.py:101–102, 253–254) |
| Raw bytes never exposed by admin | Task 17 read models exclude payload refs/bytes/clean_text; enforced by a recursive forbidden-key/content scan test and the real-PG verification |
| Raw payloads + snapshots + documents + decisions + evidence immutable | Append-only PG triggers in migrations `0004`–`0008` (verified present); repository layers expose no mutation |
| No production Konsepthane access | Repo-wide search: Konsepthane appears only in naming/user-agent/config comments; config comment explicitly forbids pointing at a Konsepthane DB |
| Admin internal/single-operator, no app RBAC | By design (Phase 2 scope); ARCHITECTURE.md's authenticated control panel with roles is future architecture, deferred with deployment protection |
| No payload bytes/URLs on the broker | Task 16: UUID-string-only task args; header carries request_id only |

### 8.2 Copyright / editorial ("RESEARCH, DO NOT TRANSLATE-AND-REPUBLISH")

| Invariant | Evidence |
| --- | --- |
| Provenance retained end-to-end | Evidence FKs (document/snapshot/source, NOT NULL, RESTRICT) are derived internally — callers cannot supply provenance (Task 13) |
| Evidence bounded; no whole-article evidence | Excerpt ≤750 chars with exact-slice CHECK; statement ≤2000; full clean_text never copied into evidence |
| Raw source expression not exposed toward publication | No publication path exists; the only read surface (Task 17) withholds clean_text, excerpts, and statements entirely |
| No fake users/quotes/statistics | Deterministic extractor invents nothing (`MAX_EXACT_EXCERPT_CANDIDATES = 0`; metadata-allowlist evidence only, UNVERIFIED) |
| AI output can never be a provenance root | No AI exists in the system; the evidence service requires an eligible fetched-and-normalized document, so the invariant holds by construction (ADR 0007) |
| Evidence Pack / Writer not implemented | Verified absent; Phase 3 must consume evidence only through the evidence service (entry criterion, §10) |

No Phase 3 safety guarantee is claimed here: the gates above protect research
intake; publication-side gates (QA, review, licensing states) do not exist yet
and are Phase 3+ obligations.

### 8.3 Initial source governance (audit item 23)

No production source allowlist is seeded (verified: no seed migrations/
fixtures; registry is empty at deploy). Before production use, each source
must be admitted by the operator through the governed registration path with,
at minimum: a review of the site's terms (recorded in `terms_notes`), an
explicit `trust_tier` decision, correct `kind` and `discovery_strategy`,
`robots_policy=OBEY` (the only permitted value), any per-source `fetch_policy`
overrides (crawl etiquette), and a conscious ACTIVE/BLOCKED decision.
`competitor_site` sources must never be registered casually: policy allows
coverage comparison only, never expression reuse, and `REFERENCE_ONLY` tier
exists for exactly that caution. This is a documented governance procedure,
not code; it becomes executable through the operator mutation surface
(closure condition 2).

### 8.4 Operational admission gap (audit item 12 — stated plainly)

Automated discovery (feed/sitemap) creates items in DISCOVERED. The Celery
chain begins only at ACCEPTED. **No operator-facing mechanism exists today to
perform DISCOVERED→ACCEPTED** (or reject, or requeue, or register a source,
or enqueue a pipeline job): the only paths are the Python services
(`DiscoveryService.accept_item` etc.) invoked programmatically. Task 17
provides observation only, by its accepted scope. Consequently the pipeline
is currently operable end-to-end only by a developer-operator with repo
access. This is exactly the gap named as closure condition 2 and is not
hidden behind "read-only by design".

---

## 9. Phase 2 exit criteria

- [x] Source admission boundary exists and is sole intake gate (ADR 0005)
- [x] URL canonicalization is a single shared versioned boundary
- [x] DiscoveryItem admission with coded rejections and conservative rediscovery
- [x] Safe crawler boundary exists (SSRF/robots/TLS/limits per design §8)
- [x] Feed and sitemap discovery strategies exist (defensive parsing)
- [x] Immutable append-only FetchSnapshots exist (ADR 0006, trigger-enforced)
- [x] Durable content-addressed raw payload storage exists (opaque ref shape)
- [x] Deterministic normalization with failure states exists
- [x] Content fingerprinting exists (SHA-256 v1; lexical similarity at engine)
- [x] Duplicate boundary exists: durable, auditable, thresholds+signals frozen per decision
- [ ] **Vector similarity signal disposition formally resolved** (implement item 11 or record scope amendment)
- [x] Evidence primitive with non-bypassable provenance exists (ADR 0007)
- [x] Deterministic machine evidence extraction exists (idempotent, no invention)
- [x] Worker orchestration exists (idempotent, commit-before-enqueue, PostgreSQL authoritative)
- [x] Operator read visibility exists (no payload/excerpt/statement exposure)
- [x] **Operator mutation surface disposition formally resolved** — RESOLVED BY IMPLEMENTATION in Task 19 (registration/lifecycle/admission/requeue/trigger endpoints + admin controls; see §11)
- [x] All security/copyright/provenance invariants verified intact (§8)
- [x] Quality baseline green at audit HEAD (backend 652, admin 60, root gate, schema `0008`)

Phase 2 closes when the two unchecked boxes are resolved. No other work is
required for closure. *(Task 19 update: the operator-mutation-surface box is
now checked; the vector-similarity disposition is the single remaining
unchecked criterion.)*

---

## 10. Phase 3 entry criteria

Phase 3 (Idea Engine / editorial intelligence) may begin only when:

1. The Phase 2 closure decision is recorded as COMPLETE (this audit's two
   conditions resolved and CURRENT_STATE updated).
2. No unresolved provenance blocker exists: ADR 0005/0006/0007 invariants
   verified at the closing HEAD (done in §8; re-verify only if code changed).
3. Duplicate eligibility semantics are frozen: Phase 3 consumes
   UNIQUE/RELATED/UPDATE_EXISTING as the only evidence-eligible outcomes and
   treats the latest decision per (document, engine identity ordering) as
   effective — exactly the Task 16/17 semantics.
4. The evidence retrieval contract is stable: Phase 3 obtains evidence
   exclusively through `contentos.research` services/repositories, which
   always return provenance with each unit; no text-only accessor may be
   added.
5. Research inputs are auditable end-to-end: every Phase 3 idea/brief must be
   traceable to ResearchEvidence rows, thus to snapshots and sources; Phase 3
   must NOT bypass ResearchEvidence to consume NormalizedDocument.clean_text
   directly as "research".
6. Production/source boundaries are clear: no Konsepthane production access
   (ADR 0001/0003 boundaries unchanged); any future inventory comparison goes
   through an explicit read-only contract that does not exist yet.
7. AI usage in Phase 3 respects ADR 0007: AI may propose (extract, score,
   draft plans) but can never be a provenance root; AI-extracted evidence
   still terminates in a fetched snapshot and starts UNVERIFIED.
8. No Writer exists before the Idea/Evidence-Pack/Brief design is accepted
   (ADR 0004's human-review gate remains binding for anything
   publication-shaped).
9. The vector-similarity decision made for closure condition 1 is reflected
   in Phase 3 planning: if deferred, its re-entry trigger (embedding
   infrastructure arriving with Phase 3 AI providers) is an explicit Phase 3
   design input, not a forgotten promise.

---

## 11. Final closure decision

**B. PHASE 2 CONDITIONALLY COMPLETE.**

All fourteen implementation-order items are delivered and verified except:

- **Item 11 (vector similarity signal)** — not implemented. The design lists
  it as a first-class Phase 2 item and as duplicate signal 7 with recorded
  embedding-model provenance; no accepted repository record removes it from
  scope. Deferral has so far existed only in task-instruction wording
  ("remains a later, independent task"), which is operator intent but not a
  formal amendment. Honest status: open Phase 2 commitment.
  Resolution options: (a) implement item 11, or (b) record a formal scope
  amendment (recommended: a short ADR) deferring the vector signal — with the
  stored-LSH fingerprint note from §5.4 — to the phase that introduces
  embedding providers, including an explicit re-entry trigger. The audit
  recommends (b): the deterministic engine satisfies the pre-AI gate at
  current corpus scale, and a vector signal built before any embedding
  provider exists would freeze provider choices prematurely.

- **Item 2, endpoint half (operator mutation surface)** — the promised
  "minimal API endpoints for source listing/registration" are half-delivered
  (listing only), and §8.4 documents that the pipeline is currently operable
  only programmatically. Resolution options: (a) implement a minimal operator
  control surface (recommended — it is small, uses only existing services,
  and makes Phase 2 actually usable by its operator), or (b) formally amend
  the scope to accept programmatic operation for Phase 2 and move the
  mutation surface to Phase 3/production-readiness.

  > **RESOLVED BY IMPLEMENTATION (Task 19, 2026-09-01).** Option (a) was
  > implemented. The control surface is POST-only, adapter-thin over the
  > existing domain services, and single-operator/no-auth as before:
  >
  > - `POST /internal/research/sources` — idempotent governed registration
  >   (functional kinds `rss_feed`/`sitemap`/`manual` only; no free-form
  >   JSON fields; no network I/O)
  > - `POST /internal/research/sources/{source_id}/lifecycle` — audited
  >   transition via `SourceRegistryService` (origin fixed to OPERATOR)
  > - `POST /internal/research/sources/{source_id}/discover` — enqueues the
  >   frozen `contentos.research.discover_source` job for eligible ACTIVE
  >   feed/sitemap sources; new discoveries stay DISCOVERED
  > - `POST /internal/research/discovery-items/{id}/accept` — DISCOVERED→
  >   ACCEPTED (never enqueues fetch; accept and fetch stay separate)
  > - `POST /internal/research/discovery-items/{id}/reject` — coded terminal
  >   rejection
  > - `POST /internal/research/discovery-items/{id}/requeue` — FETCH_FAILED→
  >   ACCEPTED with required reason (never starts fetch)
  > - `POST /internal/research/discovery-items/{id}/fetch` — enqueues the
  >   frozen `contentos.research.fetch_discovery_item` job for an ACCEPTED
  >   item of an ACTIVE source; the API accepts entity UUIDs only, never a
  >   URL to fetch
  >
  > Admin gains server-only mutation flows (`/sources/new` registration,
  > per-source lifecycle + Run discovery controls, per-item state actions on
  > `/research/[id]`). No normalize/duplicate/evidence stage triggers, no
  > Celery control panel, no deletes, no source editing, no schema change.
  > §8.4's operational admission gap is thereby closed.

No other deviation, deferral, or gap blocks closure: every remaining
difference is a verified semantic equivalent, a documented strengthening, an
explicitly future item by the design's own wording, or accepted minor doc
drift (§5.3).

---

## 12. Exact next task

**Recommended Task 19 — Minimal operator control surface (resolves closure
condition 2):** internal write API + admin forms strictly over existing
domain services: register source, audited lifecycle transitions
(pause/resume/disable/block/unblock with reason), accept/reject DiscoveryItem
(coded reason), requeue failed fetch (reason), and explicit "run discovery" /
"run fetch" job enqueueing for a source/item. Same single-operator/no-auth
boundary, full audit trail, no new schema expected (head stays `0008`), no
new dependencies. *(DONE — Task 19, 2026-09-01; see the resolution note in
§11.)*

**Then Task 20 — Phase 2 scope amendment + formal closure (resolves closure
condition 1):** record the vector-similarity deferral decision as a short ADR
(0008) with re-entry trigger, amend the Phase 2 design/status notes
accordingly, flip this audit's two open exit-criteria boxes, declare
**PHASE 2 COMPLETE** in this document and CURRENT_STATE, and define the first
Phase 3 task.

(If the operator prefers the fastest closure instead: a single amendment task
may defer both conditions formally — at the documented cost that the pipeline
remains developer-operated until the control surface exists.)
