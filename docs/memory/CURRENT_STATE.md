# Konsepthane ContentOS - Current State

Last updated: 2026-09-01

## Current phase

PHASE 3 - Editorial Intelligence / Idea Engine - IN PROGRESS
(Task 1 architecture accepted; Task 2 workflow foundation COMPLETE —
the first Phase 3 runtime code)

Phase 3 design: docs/PHASE3_EDITORIAL_INTELLIGENCE.md (Accepted). Phase 3
takes eligible Phase 2 research to an auditable ContentBrief:
research intake -> EditorialWorkItem -> EditorialOpportunity -> Idea ->
EvidencePack -> SearchIntentAnalysis -> ContentBrief. Writer remains
Phase 4; Phase 3 ends at an ACCEPTED_FOR_DRAFTING brief version.

PHASE 2 - Research/Discovery foundation - COMPLETE (2026-09-01)

Tasks 1-20 complete. The formal closure decision is recorded in
docs/PHASE2_CLOSURE_AUDIT.md (final decision: PHASE 2 COMPLETE, zero
remaining Phase 2 blockers). Closure condition 2 (operator control surface)
was resolved by Task 19's implementation; closure condition 1 (vector
similarity) was resolved by ADR 0008, which formally defers the
vector-similarity duplicate signal — not implemented, not abandoned —
under frozen provider-neutral constraints and explicit re-entry triggers.

Phase 2 completion does NOT mean production readiness (the
production-readiness backlog in the closure audit §7 stands: deployment
access protection, secrets provisioning, backups/restore, monitoring,
source-allowlist governance, scheduled discovery, multi-worker crawl
limiting, raw-payload retention, runbooks, and the dispatch-gap/outbox
decision). Phase 3 design (Task 1) is accepted; Phase 3 runtime
implementation has not started.

Phase 1 foundation is complete and verified (first real CI run passed, both
local quality gates pass, fresh-clone bootstrap verified).

Tasks 1-12 delivered the research/discovery design, Source Registry, shared URL
canonicalization, DiscoveryItem admission, the safe FetchClient boundary,
defensive RSS/Atom plus sitemap discovery, and immutable FetchSnapshot
persistence. The immutable NormalizedDocument persistence boundary now exists;
the provider-neutral raw-payload contract supports bounded verified reads, and
the first executable HTML/text normalization pipeline and deterministic local
duplicate-decision boundary are complete. The durable PostgreSQL payload
backend and the idempotent Celery research-pipeline orchestration
(fetch -> normalize -> evaluate duplicates -> extract evidence) now exist;
PostgreSQL stays authoritative and queue progress never becomes domain state.
The single operator can now inspect the whole pipeline chain without psql
through a read-only internal API and read-only admin screens.

A minimal Python backend package, FastAPI application factory, typed settings,
structured logging, request-correlation, API error-envelope, SQLAlchemy
engine/session, Alembic migration, Redis/Celery queue, health-endpoint, local
Docker/Compose, and Next.js admin foundation are implemented. No editorial
business logic exists yet.

## Repository

Repository initialized locally at:

C:\Users\BURAK\Projects\konsepthane-contentos

Default branch:

main

## Completed

- Git repository initialized
- Codebase Memory MCP installed
- Codebase Memory auto_index enabled
- Codebase Memory auto_watch enabled
- project documentation directories created
- AGENTS.md memory protocol created
- persistent memory structure created
- product purpose, scope, and system boundaries documented
- architecture baseline and 21 bounded modules documented
- editorial state machine and publication gates documented
- editorial, sourcing, copyright, media, and human-review policy documented
- initial project glossary documented
- ADR 0001 accepted: ContentOS is a separate system
- ADR 0002 accepted: core technology stack
- ADR 0003 accepted: versioned authenticated Publishing API boundary
- ADR 0004 accepted: mandatory human review before any launch-time publishing
- Phase 1 repository hygiene and workspace configuration completed
- Python 3.12 runtime pin added
- Node.js 24 LTS and pnpm 11.15.1 pins added
- pnpm workspace prepared for `apps/admin` without scaffolding the application
- Python `contentos` package created with a src layout and generated `uv.lock`
- minimal `create_app()` FastAPI application factory implemented
- initial backend unit test, Ruff, and mypy configuration validated
- typed Pydantic settings added with the `CONTENTOS_` environment prefix
- local, test, and production environments are validated explicitly
- FastAPI metadata and API documentation exposure are settings-driven
- structured JSON/runtime and local console logging configured through the app factory
- deterministic sensitive-key redaction added for structured log fields
- request IDs are validated or generated, context-bound, returned, access-logged, and cleared
- stable JSON error envelope added with request_id and deterministic status-to-code mapping
- validation errors return sanitized 422 details that never echo rejected input
- unhandled exceptions return an opaque 500 envelope and are logged once with exception info
- SQLAlchemy 2.x + Psycopg 3 engine/session foundation added under `contentos.db`
- database settings added as validated `CONTENTOS_`-prefixed SecretStr URL with pool bounds
- lazy per-app engine, explicit-commit session scope, and replaceable FastAPI session dependency
- Alembic infrastructure added; env resolves the URL from settings and targets `Base.metadata`
- initial migration `0001` enables pgvector; downgrade intentionally never drops the extension
- migration `0001` verified against an ephemeral Dockerized pgvector PostgreSQL, then torn down
- Celery app factory added: Redis broker/result from secret settings, JSON-only, UTC, `contentos.default` queue
- tasks ignore results by default; results are short-expiry operational data, never workflow state
- worker entrypoint added with explicit settings/logging/signal setup and no import-time side effects
- worker signals bind task_id and propagated request_id to logs and clear context per task
- queue foundation verified end-to-end against an ephemeral Dockerized Redis, then torn down
- `/health/live` added: process liveness only, returning safe status/service/version
- `/health/ready` added: bounded postgres SELECT 1, pgvector-extension, and Redis PING checks
- readiness returns 200/ready or 503/not_ready with safe per-component states, outside the error envelope
- readiness failures log one safe structured event (component, error class, request_id); no URL/secret leaks
- health endpoints verified against ephemeral Dockerized pgvector PostgreSQL and Redis, then torn down
- multi-stage backend Dockerfile added: uv frozen install, no dev deps, non-root `contentos` user
- root `compose.yaml` added: postgres (pgvector), redis, one-shot migrate, api, worker, admin
- compose ordering: healthy postgres/redis -> migrate completes -> api/worker start
- all Compose host ports bind 127.0.0.1 only; postgres uses a named volume; Redis stays volatile
- `.env.example` documents safe development-only defaults with `CONTENTOS_` variables
- `scripts/bootstrap.ps1` and `scripts/smoke.ps1` added for local setup and stack verification
- full Compose stack verified (live/ready 200, pgvector, alembic head, worker connected), then removed
- Next.js 15 App Router admin scaffolded in `apps/admin` (TypeScript strict, plain CSS, pnpm workspace)
- admin runtime deps limited to next/react/react-dom/zod; ESLint, Prettier, Vitest, Testing Library for dev
- Zod server-only env module added; internal API URL never exposed via public build-time variables
- admin is noindex/nofollow with security headers; truthful static foundation page and safe error boundary
- pnpm build-script allowlist (esbuild, unrs-resolver) recorded in pnpm-workspace.yaml
- server-only Zod-validated backend client added; browser never calls FastAPI or sees its URL
- root page replaced with a truthful, per-request Foundation Status page (live/ready via server)
- unreachable/malformed backend renders Unavailable/Unknown; component failures are never invented
- admin-process-only `GET /api/health` added, independent of FastAPI/Postgres/Redis
- admin Dockerfile added: Node 24, corepack pnpm 11.15.1 frozen install, standalone output, non-root
- standalone output is opt-in via NEXT_OUTPUT_STANDALONE (Windows hosts cannot symlink-trace)
- `admin` Compose service added on 127.0.0.1:3000 with a Node-fetch /api/health healthcheck
- containerized admin reaches the API at http://api:8000 server-side; browser HTML verified leak-free
- smoke script now checks backend health, admin health, and truthful admin status rendering
- full six-service Compose stack verified end-to-end, then torn down
- `scripts/check.ps1` added as the canonical non-destructive local quality gate
- default gate runs toolchain, backend (uv frozen), admin (pnpm frozen), and repository checks
- `-Compose` additionally builds/starts the stack, runs smoke.ps1, and always tears down in finally
- GitHub Actions CI added (`.github/workflows/ci.yml`): backend, admin, infrastructure, compose-smoke jobs
- CI uses SHA-pinned first-party actions, frozen installs, contents:read only, and no secrets
- CI integration job migrates and readiness-checks against pgvector PostgreSQL and Redis service containers
- CI compose-smoke reuses scripts/smoke.ps1 via pwsh and always tears the stack down
- first real GitHub Actions run of `ci` on `main` completed successfully
- root README.md added documenting tools, bootstrap, stack, gates, migrations, CI, and boundaries
- fresh-clone verification passed: bootstrap, backend tests, and admin tests in a temporary clone
- Phase 1 foundation declared complete with no known blockers
- Phase 2 research/discovery design documented: Source Registry, DiscoveryItem, FetchSnapshot,
  NormalizedDocument, DuplicateDecision, ResearchEvidence with per-entity lifecycles
- ADR 0005 accepted: Source Registry is the sole admission gate for research intake
- ADR 0006 accepted: fetch snapshots are immutable and append-only
- ADR 0007 accepted: research evidence carries non-bypassable provenance
- crawler safety boundary, idempotency keys, module dependency model, future table and
  Celery job plans, and the atomic Phase 2 implementation order are documented
- `contentos.sources` package added: string-valued enums, Source + SourceLifecycleEvent models
- migration `0002_create_sources` added (uniqueness on slug and kind+base_url; safe downgrade)
- `register_source` is idempotent with typed conflicts and DB-race recovery; no silent overwrite
- lifecycle transitions validated per design (BLOCKED exits only to ACTIVE) with append-only
  audit events ordered by a monotonic bigint identity
- source base-URL normalization implemented for registration identity only (no network I/O)
- Source Registry verified against ephemeral pgvector PostgreSQL including a
  downgrade-to-0001/re-upgrade cycle; pgvector survived throughout
- shared URL canonicalization boundary added at `contentos.core.urls` (network-free,
  stdlib-only) with frozen v1 rules and `URL_CANONICALIZATION_VERSION = 1`
- v1 tracking-parameter policy: `utm_` prefix plus gclid/fbclid/msclkid, case-insensitive
- `canonical_url_hash` added: unsalted SHA-256 lowercase hex of the canonical URL's UTF-8
- canonical URL != safe-to-fetch URL: no DNS/SSRF/robots here; that stays in the future
  fetch boundary
- `contentos.sources.urls` registration identity semantics intentionally unchanged and
  kept independent of the shared canonicalizer
- `contentos.discovery` package added: DiscoveryItem model, enums, repository, service
- migration `0003_create_discovery_items` added; uniqueness on (source_id, url_hash)
- discovery rows persist discovered_url, canonical_url, url_hash, and canonicalization
  version 1 via `contentos.core.urls`; hints are stored as untrusted, never overwritten
- manual admission requires an ACTIVE source (PAUSED/DISABLED/BLOCKED all refuse)
- rediscovery is idempotent: returns the existing row and touches only `last_seen_at`;
  lifecycle, rejection, fetch state, and hints are preserved; REJECTED is terminal
- discovery lifecycle: DISCOVERED->ACCEPTED/REJECTED, ACCEPTED->FETCHED/FETCH_FAILED,
  FETCH_FAILED->ACCEPTED only via explicit reasoned re-queue; no audit table by design
- shared persistence helpers promoted to `contentos.db.types` (string_enum, JSON_DICT)
- discovery verified against ephemeral pgvector PostgreSQL including a
  downgrade-to-0002/re-upgrade cycle; sources rows and pgvector survived
- `contentos.fetching` safe HTTP client added (httpx promoted to a runtime dependency)
- SSRF guard: resolve-then-validate every address via stdlib ipaddress; one unsafe
  answer fails the host closed; the SSRF gate runs before robots per hop
- DNS rebinding protection: connections target the validated pinned IP while the Host
  header and HTTPS `sni_hostname` extension keep TLS verification on the real hostname
- redirects followed manually with full per-hop revalidation and a bounded hop limit
- robots.txt evaluated per origin (4xx=allowed, else fail closed as retryable), fetched
  through the same protections with a bounded TTL in-memory cache
- streamed bodies with hard byte caps (Content-Length is advisory only), conservative
  MIME allowlist, allowlisted response headers only, no cookies, trust_env off, TLS never
  weakened, identified Konsepthane-ContentOS user agent
- process-local per-host limiter (concurrency 1 + min interval); distributed enforcement
  deferred to Celery orchestration
- stable FetchOutcome/RetryClassification contract; typed fetch settings added
- no FetchSnapshot persistence, Phase 2 Celery orchestration, or sitemap parsing yet
- `contentos.discovery.feed` added as the first automated discovery strategy
- only ACTIVE `rss_feed` sources with `discovery_strategy=feed` are eligible
- feed retrieval uses the existing safe FetchClient; retryable and terminal outcomes remain distinct
- stdlib ElementTree is used after rejecting DTD/entity declarations, with byte, element,
  entry, URL, title, and snippet limits; no XML dependency was added
- RSS 2.x and namespace-aware Atom entries resolve against the final fetched feed URL
- feed hints are markup-stripped/truncated and dates become timezone-aware UTC or null
- feed candidates use `DiscoveryMethod.FEED` and the shared DiscoveryService admission path
- repeated feeds and canonical URL variants are idempotent; lifecycle and stored hints are preserved
- Task 6 verified offline: 302 backend tests and the full root quality gate passed
- `contentos.discovery.sitemap` added with bounded URL-set and recursive sitemap-index traversal
- only ACTIVE `sitemap` sources with `discovery_strategy=sitemap` are eligible
- every root/child document uses FetchClient; XML parsing accepts application/xml or text/xml only
- DTD/entity declarations are rejected; byte, element, per-document URL (5,000),
  index-entry (50), depth (3), document (50), total URL (5,000), and URL-length
  limits are centralized and enforced
- child sitemap locations and redirect final URLs must be same-origin with the final root
  sitemap URL; locations must be absolute, and cycles/duplicates are skipped before fetching
- sitemap `lastmod` is validated for warnings but is not stored as `external_published_at`
  because modification time is not publication time
- explicit gzip sitemap representations are unsupported; no XML/compression dependency was added
- sitemap candidates use `DiscoveryMethod.SITEMAP` and shared idempotent DiscoveryService admission
- Task 7 verified offline: 352 backend tests and the full root quality gate passed
- `contentos.fetching` now owns immutable `FetchSnapshot` persistence via model,
  append/read-only repository, and transactional recording service
- migration `0004_create_fetch_snapshots` adds frozen FetchOutcome,
  RetryClassification, and RobotsDecision CHECK values plus useful history/outcome indexes
- snapshot rows retain requested/final URLs, status/MIME, fetched time, safe selected
  headers, redirect chain, duration, retry metadata, stable failure detail, and created time
- exact FetchResult body bytes are SHA-256 hashed with byte size; PostgreSQL stores only
  an opaque caller-supplied `raw_payload_ref`, never response bodies
- any present body, including an empty successful body, requires a non-empty payload reference;
  body-less failures store null hash, size, and payload reference
- recording locks an ACCEPTED DiscoveryItem and atomically maps SUCCESS to FETCHED or any
  non-success outcome to FETCH_FAILED; retries require the existing explicit requeue transition
- multiple attempts per DiscoveryItem are retained in deterministic history order
- FetchSnapshot uses `ON DELETE RESTRICT`; a PostgreSQL trigger rejects UPDATE and DELETE,
  while repository/service APIs expose no mutation or deletion path
- real ephemeral pgvector PostgreSQL verification passed: empty upgrade to 0004, metadata and
  service flows, append-only trigger, downgrade to 0003, survival checks, and re-upgrade
- no payload-store backend, Celery orchestration, feed/sitemap retrofit, normalization,
  endpoint, or admin work was added
- Task 8 verified: 380 backend tests and the full root quality gate passed
- `contentos.normalization` now owns immutable `NormalizedDocument` persistence,
  an append/read-only repository, and explicit `record_success`/`record_failure` services
- migration `0005_create_normalized_documents` adds the FetchSnapshot `ON DELETE RESTRICT`
  provenance link, frozen status/failure checks, extractor identity uniqueness, JSONB
  derived structures, fingerprint fields, indexes, and append-only trigger
- extractor identity is (`fetch_snapshot_id`, `extractor_name`, `extractor_version`):
  exact identical retries return the existing row; conflicting retries raise a typed
  conflict; new extractor names or versions append and coexist
- success requires non-empty exact extractor output and SHA-256 fingerprint v1 over its
  exact UTF-8 bytes; the persistence layer performs no case, punctuation, or language
  transformation; failure rows require a broad stable failure code and contain no fake content
- both successful and failed normalization records require a successful FetchSnapshot with
  `raw_payload_ref`, body hash, and body size; fetch failures remain at the snapshot layer
- real ephemeral pgvector PostgreSQL verification passed: empty upgrade to 0005, successful
  and failed recording, retry/conflict/versioning behavior, raw UPDATE/DELETE rejection,
  downgrade to 0004 with source/discovery/fetch/pgvector survival, and re-upgrade
- Task 9 verified: 409 backend tests and the full root quality gate passed; no extraction,
  raw-payload reader/backend, duplicate engine, endpoint, worker task, or UI was added
- `contentos.payloads` now defines frozen opaque `RawPayloadRef` and `StoredPayload`
  value objects plus separate synchronous `RawPayloadStore`/`RawPayloadReader` protocols
- payload writes are byte-exact and content-addressed: SHA-256 and size are computed before
  storage, optional expected provenance is verified first, identical puts are idempotent,
  and conflicting bytes cannot overwrite an existing reference
- `read_verified_payload` requires a caller-supplied maximum, counts and hashes actual
  streamed bytes, and returns bytes only after exact expected size and SHA-256 verification
- stable payload errors cover invalid references/metadata, missing objects, size limits,
  integrity failures, immutable conflicts, and sanitized backend failures
- `InMemoryRawPayloadStore` is explicitly process-local DEV/TEST infrastructure only;
  it uses deterministic `memory:sha256:<hex>` references and is not a production default
- the existing `CONTENTOS_FETCH_MAX_BODY_BYTES` setting remains the composition-time read
  limit, avoiding a second drifting configuration value; no configuration change was needed
- Task 10 added no schema, migration, dependency, FetchSnapshot, normalization, endpoint,
  Celery, frontend, production storage, or extraction changes
- Task 10 verified: 456 backend tests and the full root quality gate passed
- `contentos.normalization.pipeline` now executes the verified FetchSnapshot ->
  RawPayloadReader -> extractor -> immutable NormalizedDocument path without committing
- payload bytes are read only through `read_verified_payload`; hash/size violations raise
  typed pipeline integrity errors and persist no misleading normalization record
- frozen versioned extractor contracts added with stable `html-basic/1` and `text-basic/1`
  identities; media selection supports text/html, application/xhtml+xml, and text/plain
- the stdlib HTML parser provides bounded visible text, heading/section, safe-link,
  explicit author/language/date, selected meta/OpenGraph, and summarized JSON-LD extraction
  without scripts, resources, external entities, browser execution, or network access
- charset policy is deterministic: response charset, then HTML meta charset for HTML,
  then strict UTF-8; supported legacy codecs are allowlisted and machine locale is unused
- clean text preserves case, Turkish characters, punctuation, and meaningful block breaks;
  extraction never rewrites, summarizes, transliterates, or applies NLP
- parser, clean-text, heading, section, link, anchor, metadata, and JSON-LD limits are
  centralized; expected failures map to the existing Task 9 failure-code vocabulary
- extraction success/failure persists only through `NormalizationService`, preserving
  exact retry idempotency and typed conflicts for changed output under the same version
- no parser dependency was added; `pyproject.toml` and `uv.lock` remain unchanged
- synthetic end-to-end coverage proves Source -> DiscoveryItem -> stored payload ->
  FetchSnapshot -> verified extraction -> NormalizedDocument provenance without network I/O
- Task 11 verified: 487 backend tests and the full root quality gate passed
- `contentos.duplicates` now owns immutable `DuplicateDecision` persistence,
  bounded local candidate queries, deterministic similarity signals, engine v1,
  and the caller-committed `evaluate_and_record` service
- migration `0006_create_duplicate_decisions` adds the NormalizedDocument
  `ON DELETE RESTRICT` provenance link, frozen decision CHECK values, unique
  (`normalized_document_id`, `engine_name`, `engine_version`) identity, bounded
  JSONB result fields, decision/evaluation-time indexes, and append-only trigger
- engine identity is `duplicate-engine/1`; exact retries return the stored decision
  before rescanning the evolving corpus, concurrent differing winners raise a typed
  conflict, and a new engine version may append and coexist
- v1 compares successful local ContentOS NormalizedDocuments only; it excludes the
  target and alternate normalizations of the same FetchSnapshot, prioritizes exact
  fingerprint/raw/canonical/final-URL candidates, then fills from recent rows, with
  at most 200 comparisons and 10 persisted matches
- signal priority is exact normalized fingerprint/raw body -> DUPLICATE; same
  canonical/final resource with changed content -> UPDATE_EXISTING; title >= 0.92
  plus lexical >= 0.85 -> DUPLICATE; lexical >= 0.45 or title >= 0.65 with lexical
  >= 0.25 -> RELATED; otherwise UNIQUE
- title similarity uses bounded Unicode casefold/whitespace normalization plus
  stdlib SequenceMatcher; lexical similarity is bounded Unicode token-set Jaccard
  with no stemming, stopwords, transliteration, dependency, embedding, or AI
- every decision persists the complete frozen threshold snapshot, aggregate signals,
  bounded safe provenance matches, and rationale codes; it never stores clean text
- REJECT remains approved durable vocabulary but v1 never infers it from an eligible
  low-similarity document; unusable normalization is rejected at service eligibility
- real ephemeral pgvector PostgreSQL verification passed: empty upgrade to `0006`,
  local DUPLICATE/UPDATE_EXISTING/RELATED/UNIQUE outcomes, retry/v2 coexistence,
  catalog objects, raw UPDATE/DELETE rejection, downgrade to `0005` with prior data
  and pgvector survival, and successful re-upgrade; temporary resources were removed
- no production Konsepthane inventory lookup exists; future comparison requires an
  explicit boundary and never direct production database access
- Task 12 added no dependency, embedding/vector column, AI, Celery task, endpoint,
  frontend, evidence extraction, publishing integration, or production access
- Task 12 verified: 512 backend tests and the full root quality gate passed
- `contentos.research` now owns the immutable `ResearchEvidence` primitive with an
  append/read-only repository, centralized validation, and the caller-committed
  `record_evidence` service (started by Codex, audited and verified unchanged)
- migration `0007_create_research_evidence` adds RESTRICT provenance FKs to
  normalized_documents, fetch_snapshots, and sources, frozen enum CHECKs, evidence-key
  format/version checks, excerpt-consistency checks, unique
  (`normalized_document_id`, `extractor_name`, `extractor_version`, `evidence_key`)
  identity, JSONB metadata bounds, useful indexes, and the append-only trigger
- provenance is derived internally through NormalizedDocument -> FetchSnapshot ->
  DiscoveryItem -> Source; callers cannot supply source_url/fetched_at/snapshot/source
- excerpt contract frozen: offset version 1, zero-based start-inclusive end-exclusive
  Python code-point offsets into exact clean_text; the persisted excerpt must equal the
  exact slice with no fuzzy/whitespace/case fallback (Turkish/emoji/multiline verified)
- VERIFIED means exact structural excerpt grounding only, never semantic entailment;
  quotes and VERIFIED status require an excerpt; excerpt-less structured-metadata
  evidence requires a bounded non-executable source_locator and stays UNVERIFIED
- evidence identity is deterministic: evidence_key v1 = SHA-256 over the canonical
  UTF-8 JSON tuple (type, statement, excerpt_start, excerpt_end); no timestamps or
  randomness; exact retries return the stored row, changed content under the same
  identity raises a typed conflict, and extractor versions coexist
- copyright bounds centralized: excerpt <= 750 chars, statement <= 2000, bounded
  extractor/locator/licensing/confidence fields, bounded metadata depth/items; full
  clean_text and raw payloads are never copied into evidence
- optional confidence is Decimal 0..1 with a mandatory recorded basis; licensing is
  never inferred (operator note only); extraction methods are machine/human, no AI
- SAVEPOINT-based race recovery keeps the caller's outer transaction intact on
  uniqueness races; raw SQLAlchemy errors never escape the service contract
- real ephemeral pgvector PostgreSQL verification passed: empty upgrade to `0007`,
  full chain creation, derived provenance/evidence-key checks, exact-retry idempotency,
  wrong-excerpt rejection, extractor v2 coexistence, catalog FK/check/unique/index/
  trigger objects, raw UPDATE/DELETE rejection, downgrade to `0006` with prior data and
  pgvector survival, and successful re-upgrade; temporary resources were removed
- Task 13 added no AI, embeddings, Evidence Pack, Celery task, endpoint, frontend,
  dependency, or lockfile change
- Task 13 verified: 542 backend tests and the full root quality gate passed
- `contentos.research.extractor` adds the deterministic v1 evidence extractor: the first
  executable producer of ResearchEvidence, persisting only through ResearchEvidenceService
- extractor identity is the existing `deterministic-evidence/1`; behavior changes require
  a version bump; extraction method is MACHINE
- v1 emits at most one author and one publication-date OBSERVATION per document, all
  excerpt-less and UNVERIFIED, with no confidence score and no inferred licensing
- v1 deliberately produces no exact-excerpt candidates (`MAX_EXACT_EXCERPT_CANDIDATES = 0`):
  no metadata fact has a structurally certain clean-text span, and weak evidence is not
  invented to raise counts
- statements are frozen deterministic Turkish templates; no generative variation
- structured-metadata allowlist is author/date only: `article:author`,
  `article:published_time`, and the first JSON-LD `author`/`datePublished` string; unknown
  keys (description/OpenGraph/canonical/tracking) are ignored, malformed shapes produce
  warnings and skips rather than failures
- dedupe priority is the normalized top-level field first (`normalized.author_name`,
  `normalized.external_published_at`), then article meta, then JSON-LD; exactly one
  evidence row per fact
- source_locator values follow the Task 13 bounded non-executable path contract
  (e.g. `structured_metadata.article:published_time`)
- reruns are idempotent through the Task 13 evidence key: second runs create zero rows and
  return the existing evidence; created/existing/skipped/warnings are reported in an
  immutable extraction result; runs themselves are not persisted
- extractor limits (candidates per document, metadata value length, JSON-LD summaries
  inspected) are centralized and within Task 13 persistence limits
- Task 14 added no migration (head stays `0007`), no AI, no Celery, no EvidencePack,
  no endpoint, no dependency change
- Task 14 verified: 565 backend tests and the full root quality gate passed
- Task 15 sequencing corrected: the durable payload backend was implemented BEFORE Celery
  orchestration because cross-process fetch->normalize requires retrievable raw bytes;
  Celery orchestration moves to Task 16
- `contentos.payloads.postgres` adds the durable, immutable, content-addressed PostgreSQL
  provider (`RawPayloadBlob` model + `PostgresRawPayloadStore`) satisfying the unchanged
  Task 10 `RawPayloadStore`/`RawPayloadReader` protocols
- migration `0008_create_raw_payload_blobs`: sha256 CHAR(64) primary identity, BIGINT size,
  BYTEA payload, timestamptz created_at, format/size/octet-length CHECKs, the append-only
  UPDATE/DELETE trigger, and a symmetric downgrade
- frozen reference format `postgres:sha256:<64 lowercase hex>`; identity is SHA-256 of the
  exact bytes only; same bytes share one row and reference, expected hash/size mismatches
  are rejected before persistence
- put() refuses payloads above the configured cap (default matches the fetch body cap;
  DB CHECK enforces the absolute 50 MiB settings ceiling); readers still require explicit
  max_bytes and yield bounded chunks
- the store is session-scoped, flushes only, never commits; identical concurrent puts are
  absorbed with the SAVEPOINT race pattern and the outer transaction stays usable;
  hash-conflicting or inconsistent stored rows raise typed conflict/integrity errors
- FetchSnapshot integration verified: body -> postgres put -> record_fetch_result stores
  the ref with matching body_sha256/body_size_bytes; NormalizationPipeline succeeded
  through the PostgreSQL reader with zero pipeline code changes (provider neutrality held)
- `InMemoryRawPayloadStore` remains DEV/TEST only and unchanged
- real ephemeral pgvector PostgreSQL verification passed all 25 steps: empty upgrade to
  `0008`, BYTEA/constraint/trigger catalog checks, exact Turkish/UTF-8 byte round-trip,
  hashlib-equal digests, idempotent re-put, chunked reconstruction, max_bytes rejection,
  snapshot + pipeline integration, raw UPDATE/DELETE rejection, downgrade to `0007` with
  prior data and pgvector survival, and re-upgrade
- Task 15 added no Celery task, endpoint, UI, object storage, AI, or dependency change
- Task 15 verified: 595 backend tests and the full root quality gate passed
- `contentos.worker.research_tasks` adds the five idempotent research-pipeline Celery
  jobs with frozen names `contentos.research.discover_source`, `.fetch_discovery_item`,
  `.normalize_fetch`, `.evaluate_duplicate`, and `.extract_research_evidence`
- tasks are registered explicitly via `register_research_pipeline_tasks(app, runtime)`
  with `shared=False` (no shared-task registry replay); `create_worker_app` wires a
  process-safe lazy `WorkerRuntime` (engine/session factory created on first use,
  never at import or registration time)
- delivery contract: at-least-once (`acks_late` + `reject_on_worker_lost`) absorbed by
  PostgreSQL uniqueness/idempotency; task arguments are JSON UUID strings only; no
  payload bytes, bodies, or URLs cross the broker
- TRANSACTION RULE enforced: every stage commits its durable output first and only
  then enqueues the next stage; a post-commit broker publish failure triggers a
  bounded DISPATCH retry whose rerun detects the durable output and only reschedules
  the next stage (proven by dispatch-failure recovery and failed-commit tests)
- discovery admission boundary preserved: `discover_source` runs feed/sitemap
  strategies for eligible ACTIVE sources only and leaves new candidates DISCOVERED;
  it never auto-accepts or enqueues fetches; the automatic chain starts at ACCEPTED
- fetch redelivery in FETCHED state reuses the latest successful snapshot via the new
  bounded `FetchSnapshotRepository.get_latest_successful_for_discovery_item` and
  re-dispatches normalize without network I/O
- retryable fetch failures record the failed snapshot, requeue with an explicit
  reason, commit, then `self.retry`; SSRF/robots/policy failures and exhausted
  retries stay terminal (FETCH_FAILED) and are never retried
- centralized retry policy: max 3 retries, deterministic exponential backoff
  30s..600s, HTTP Retry-After respected within the cap, no jitter
- duplicate gate: UNIQUE/RELATED/UPDATE_EXISTING dispatch evidence extraction;
  DUPLICATE/REJECT stop the chain; evidence extraction is the terminal stage
- `request_id` propagates through task headers when valid; logs carry only IDs,
  statuses, outcomes, and counts (no URLs, payloads, titles, or evidence statements)
- eager-mode tests exercise the real registered task boundary on a PostgreSQL-faithful
  SQLite harness (working SAVEPOINTs + timezone-aware reloads), including full-chain,
  duplicate-stop, redelivery-idempotency, and session-lifecycle coverage
- real ephemeral pgvector PostgreSQL verification passed: migrate to `0008`, eager
  full chain (1 blob, 1 snapshot, 1 SUCCEEDED document, 1 UNIQUE decision, 2 evidence
  rows, linked provenance), redelivery reuse with zero HTTP calls and zero new rows,
  duplicate-stop for a second source with identical content (2 snapshots share 1
  content-addressed blob, no extra evidence), schema stayed `0008`, pgvector survived
- Task 16 added no Beat scheduling, endpoint, UI, AI, Evidence Pack, schema change
  (head stays `0008`), or dependency change
- Task 16 verified: 627 backend tests and the full root quality gate passed
- `contentos.api.read_models.research` adds the read-only research visibility
  layer: immutable frozen Pydantic DTOs plus bounded query functions that never
  write, never commit, and never return ORM entities
- `/internal/research` GET-only router registered in `create_app` (three
  endpoints: `/sources`, `/discovery-items`, `/discovery-items/{id}`); health
  routes, request-context middleware, error envelope, and lazy DB connection
  are unchanged; POST/PUT/PATCH/DELETE return 405
- source list: id/slug/name/kind/locale/market/lifecycle/trust/strategy/
  base_url/timestamps plus aggregate discovery counts (total + per lifecycle
  state) computed in one grouped SQL subquery — never N+1
- pipeline list answers "what happened to this URL": discovery fields plus
  deterministic latest-stage projections (latest FetchSnapshot by fetched_at/
  created_at/id desc; latest NormalizedDocument by normalized_at/created_at/id
  desc; latest DuplicateDecision scoped to that latest document only; evidence
  count + newest timestamp for that document) — a decision or evidence from an
  older normalization version is never shown as belonging to the latest one
- list endpoints are one window-function SELECT plus one COUNT over the same
  filtered join (query count independent of page size); filters cover source,
  lifecycle state, method, fetch outcome, normalization status, duplicate
  outcome, has_evidence, and bounded URL/text substring search (escaped, no
  regex); pagination is mandatory (default 50, max 100, bounded offset) with a
  frozen `{items,total,limit,offset}` envelope and deterministic ordering
  (sources: updated/created desc then id; pipeline: last_seen/discovered desc
  then id) pinned by tests
- detail endpoint returns bounded histories (max 20 each, newest first, with
  totals and truncated flags) for fetch attempts, normalization attempts, and
  duplicate decisions, plus an evidence SUMMARY only (counts by verification
  status and type, newest timestamp)
- deliberately never exposed by the read API: raw payload bytes/refs,
  clean_text, excerpts, evidence statements, wholesale structured/metadata
  JSON, selected headers, redirect chains, duplicate signals/thresholds/match
  payloads, secrets/URLs; a recursive JSON scan test and the real-PG
  verification both enforce this
- invalid UUIDs return the 422 validation envelope; missing items return the
  404 envelope; no DB or SQL details leak
- admin gains read-only routes `/sources`, `/research`, `/research/[id]` plus
  header navigation (Status / Sources / Research Pipeline with aria-current);
  all pages are force-dynamic React Server Components fetching server-side
  only — the backend URL never reaches browser JavaScript
- admin filters/pagination live in URL search params via GET forms (shareable,
  no JS required); the only buttons are filter submits — no mutation controls
  anywhere; per-stage badges keep explicit text (color is never the sole
  carrier); backend unavailable/malformed/empty states render truthfully
- admin responses are zod-validated against exact backend enum vocabularies
  (unknown values are malformed, never rendered); timestamps render
  deterministically server-side as `YYYY-MM-DD HH:mm UTC` with no timezone
  dependency
- no Celery/queue/worker introspection appears anywhere: the screens reflect
  durable PostgreSQL state only; no auto-refresh/websocket/SSE/polling
- real ephemeral pgvector PostgreSQL verification passed: migrate to `0008`,
  service-seeded realistic rows (full chain with evidence, duplicate stop,
  retry history, discovered-only, rejected, failed normalization), all three
  endpoints via the real FastAPI app — aggregates, projections, filters,
  pagination, detail histories, 404/422, forbidden-field scan; schema stayed
  `0008`, pgvector intact, teardown complete
- Task 17 added no auth/RBAC, no mutations, no migration (head stays `0008`),
  no backend or frontend dependency (lockfiles unchanged), no Celery control,
  no AI
- Task 17 verified: 652 backend tests, 60 admin tests, and the full root
  quality gate passed
- Task 18 (Phase 2 closure audit) complete: `docs/PHASE2_CLOSURE_AUDIT.md` is
  the formal closure decision record, audited at HEAD `ea9e9ac` against the
  accepted design, ADRs 0005-0007, and the actual code
- closure decision at Task 18 (historical; superseded by Task 20's PHASE 2
  COMPLETE): **PHASE 2 CONDITIONALLY COMPLETE** — the entire runtime
  foundation is implemented and verified; no implemented behavior violates
  the accepted design; all security/copyright/provenance invariants verified
  intact at audit time
- open closure condition 1: vector-similarity duplicate signal (design §5
  signal 7, §12 vector column, implementation-order item 11) is an explicit
  unimplemented Phase 2 commitment with no formal scope amendment on record;
  resolution = implement item 11 OR record a formal deferral ADR with a
  re-entry trigger (audit recommends the ADR)
- open closure condition 2: implementation-order item 2's "minimal API
  endpoints for source listing/registration" is half-delivered (listing only);
  no operator-facing mechanism exists for source registration, lifecycle
  transitions, DISCOVERED->ACCEPTED admission, rejection, requeue, or job
  triggering — the pipeline is currently operable only programmatically;
  resolution = minimal operator control surface (audit recommends) OR formal
  amendment
- audit dispositions recorded: retention job and Konsepthane inventory
  comparison OUT_OF_SCOPE by explicit design wording; Celery Beat never a
  Phase 2 commitment (executable jobs only were promised); human duplicate
  override (decided_by) and evidence verification workflow
  (verified_by/verified_at) DEFERRED_ACCEPTED with human review flows;
  duplicate record shape, evidence append-only strengthening, evidence_key
  identity, FetchSnapshot field naming/redirect_chain, normalization
  status/failure-code split, and explicit-markup-only language all
  COMPLETE_DIFFERENT_IMPLEMENTATION with rationale; missing
  fetcher_version/metadata snapshot columns accepted as minor doc drift;
  SHA-256 + engine-time lexical similarity confirmed sufficient for the
  Phase 2 baseline (stored LSH is a later scaling optimization); distributed
  per-host rate limiting DEFERRED (holds exactly with one fetch worker;
  required before multi-worker production); commit-vs-publish gap documented
  with recovery strategy, residual stall window, and outbox trigger criteria
- production-readiness matrix recorded separately from phase completion
  (deployment access protection, secrets, backups, retention, scheduling,
  monitoring, runbooks, DR, source-allowlist governance = before production;
  none of these block Phase 2)
- Phase 3 entry criteria defined: closure recorded, no provenance blockers,
  frozen duplicate-eligibility semantics, evidence-service-only retrieval,
  end-to-end auditability (no clean_text bypass), no Konsepthane access, AI
  never a provenance root, no Writer before Idea/Evidence-Pack/Brief design
- Task 18 changed no runtime code, schema (head stays `0008`), or
  dependencies; gates re-run and green at audit (backend 652, admin 60,
  check.ps1, git diff --check)
- Task 19 (minimal operator control surface) complete: closure condition 2 is
  RESOLVED BY IMPLEMENTATION; the pipeline is now operator-usable end to end
  without repo access
- POST-only control endpoints under `/internal/research` (router
  `contentos.api.routes.research_control`): source registration, source
  lifecycle transition, source discovery trigger, discovery-item
  accept/reject/requeue, discovery-item fetch trigger; GET on control paths
  is 405; no PUT/PATCH/DELETE, no generic action endpoint (OpenAPI-pinned)
- registration is idempotent through `SourceRegistryService` (identical ->
  "existing", conflicting -> 409, invalid -> 422); control policy restricts
  registrable kinds to rss_feed/sitemap/manual; discovery strategy derives
  from kind; no metadata/discovery_config/fetch_policy JSON accepted
  (extra="forbid"); registration performs no network I/O
- lifecycle transitions call `transition_source_state` with origin fixed
  server-side to OPERATOR (request cannot supply origin); domain matrix and
  `SourceLifecycleEvent` audit remain authoritative; blank reasons rejected
- admission stays two explicit operator decisions: accept never enqueues
  fetch; requeue (FETCH_FAILED -> ACCEPTED, reason required) never starts
  fetch; REJECTED is terminal (accept/requeue/fetch all 409)
- task triggers validate durable eligibility only (source ACTIVE +
  feed/sitemap strategy; item ACCEPTED + parent ACTIVE), mutate nothing, then
  publish the frozen Task 16 entry-point names via
  `contentos.worker.producer.CeleryResearchControlDispatcher`
  (`send_task`, lazy Celery app — creating the FastAPI app touches neither
  Redis nor PostgreSQL); dispatcher is injectable via
  `app.state.research_control_dispatcher`
- the control API never accepts a URL to fetch: triggers take entity UUIDs
  only, so registered durable entities alone determine what the crawler may
  touch; task messages carry one UUID arg plus only a validated request_id
  header; broker publish failure returns a safe 503 and is never reported as
  queued; Celery task IDs are never exposed
- domain mutations commit before responding; commit failure returns the
  opaque 500 envelope with full rollback (transition + audit event atomic)
- admin gains server-only mutation flows via Server Actions (browser never
  learns the backend URL; failures become bounded notice codes in redirect
  query params): `/sources/new` registration form ("registering does not
  automatically crawl"), per-source lifecycle controls + Run discovery
  (shown only for eligible ACTIVE feed/sitemap sources) on `/sources`, and
  state-appropriate actions on `/research/[id]` (DISCOVERED: Accept/Reject
  with real coded reasons; ACCEPTED: Start fetch; FETCH_FAILED: Requeue with
  reason; FETCHED/REJECTED: no actions)
- no manual normalize/duplicate/evidence triggers (Task 16 owns the chain
  after fetch), no Celery control panel, no deletes, no source editing, no
  manual discovery-item creation, no auth/RBAC
- real ephemeral pgvector PostgreSQL verification passed: HTTP registration
  (idempotent, single row), audited lifecycle round-trip, both triggers
  dispatching the frozen task names with request_id headers and
  UUID-only payloads, accept/requeue via HTTP, rejected-terminal enforcement,
  schema stayed `0008`, pgvector intact, teardown complete; no Redis needed
  (fake dispatcher — producer behavior is the unit under test)
- Task 19 added no migration (head stays `0008`) and no dependency changes
- Task 19 verified: 687 backend tests, 96 admin tests, and the full root
  quality gate passed
- Task 20 (documentation/ADR only) complete: ADR 0008 "Defer the
  Vector-Similarity Duplicate Signal Until Justified" accepted; it
  acknowledges the original Phase 2 promise (design §5 signal 7, §12 vector
  column plan, implementation-order item 11) and amends scope formally
  rather than rewriting history
- deferral rationale recorded: empty/small corpus, conservative explainable
  deterministic gate exists, no embedding provider contract selected,
  premature freezing of model/dimension/lifecycle/cost/calibration, Phase 3
  data needed for responsible thresholds, pgvector infrastructure already
  live so nothing is foreclosed, and vector similarity is a classification
  quality enhancement — not a provenance/security prerequisite
- the deterministic duplicate baseline (`duplicate-engine/1`: URL/raw-hash/
  fingerprint/title/lexical signals with persisted thresholds, signals,
  bounded matches, append-only idempotent decisions) remains authoritative
  for the current phase
- ADR 0008 freezes provider-neutral constraints for the eventual vector
  implementation (embedding protocol, model+version provenance, dimension
  validation, deterministic embedding identity, vector-version lifecycle,
  safe re-embedding, fake deterministic test provider, bounded batches, no
  Writer/LLM runtime dependency, threshold+version recorded per decision)
  and defines measurable re-entry triggers (corpus scale, observed duplicate
  misses, Phase 3 overlap evidence, performance targets, multilingual
  expansion, provider selection)
- binding Phase 3 safety conditions while deferred: DUPLICATE/REJECT remain
  hard stops; RELATED/UPDATE_EXISTING stay downstream-eligible signals;
  uncertain similarity is never auto-rejected; the Idea Engine must not
  treat duplicate decisions as infallible and must preserve references to
  the underlying decisions/signals
- Phase 2 design doc status updated (implementation closed, item 11 and
  signal 7 annotated as deferred by ADR 0008) without deleting or rewriting
  the original design; closure audit updated (K2 -> DEFERRED_ACCEPTED, all
  exit criteria resolved, final decision PHASE 2 COMPLETE)
- Task 20 changed no runtime code, schema (head stays `0008`), or
  dependencies; gates re-run and green (backend 687, admin 96, check.ps1,
  git diff --check)
- PHASE 3 Task 1 complete: `docs/PHASE3_EDITORIAL_INTELLIGENCE.md` accepted
  (design only; zero runtime changes, schema stays `0008`, no dependencies)
- canonical workflow aggregate chosen: `EditorialWorkItem` in a new
  foundational `contentos.workflow` module, carrying the WORKFLOW.md
  canonical states with append-only transition events (actor/reason/
  artifact-version pins/request_id); only WorkflowService transitions; queue
  completion never advances state
- intake decision: promotion, not replay — work items are created directly
  into IDEA_SCORING with a creation event pinning the exact Phase 2 chain
  (discovery item, normalized document, duplicate decision); the early
  canonical states are realized by Phase 2 entity lifecycles, never
  fabricated as synthetic event history
- intake eligibility is deterministic and ADR 0008-binding: SUCCEEDED
  normalization + effective DuplicateDecision required (absence is not a
  pass); DUPLICATE = hard stop with explicit audited operator override for
  a distinct angle only; REJECT = hard stop; UNIQUE/RELATED eligible
  (relationship stays visible); UPDATE_EXISTING = update signal only
- major entities designed: EditorialOpportunity (+multi-source
  opportunity_research_inputs with roles), append-only explainable
  OpportunityScore (+relational components with KNOWN/UNKNOWN/NOT_APPLICABLE
  availability — UNKNOWN != ZERO, no invented search/competition data),
  provider-neutral search_signals store, versioned Idea candidates with
  append-only selection events and deterministic originality/fake-UGC
  guards, immutable versioned EvidencePack (+items with mandatory
  ResearchEvidence FKs, contradictions, explicit
  READY/INSUFFICIENT/CONFLICTED/BLOCKED sufficiency gate), first-class
  versioned SearchIntentAnalysis with truthful cannibalization states
  (NOT_CHECKED default — no production inventory access), versioned
  ContentBrief with deterministic claim/evidence map and the
  BRIEFING->DRAFTING acceptance boundary defined now for Phase 4
- provider-neutral AI boundary designed (`contentos.ai`): structured-output
  pipeline (provider -> neutral DTO -> schema validation -> domain
  validation -> artifact), one generic append-only ai_generation_attempts
  provenance record (provider/model/version, schema/template version, input
  refs+hash, status, retry, usage with future cost hooks), fake
  deterministic test provider mandatory before any real adapter; failed
  validation is a recorded failed attempt, never coerced, never a state
  change; AI can propose artifacts but can NEVER create source provenance
- EvidencePack provenance rule: packs reference ResearchEvidence rows
  (NOT NULL RESTRICT); no evidence_text that strips provenance; full chain
  ContentBrief -> EvidencePack -> ResearchEvidence -> NormalizedDocument ->
  FetchSnapshot -> Source stays resolvable
- versioning/idempotency/reproducibility contracts documented per artifact
  (input snapshots + hashes, deterministic-latest selection, downstream
  version pinning); execution failure vs domain decision separated (a
  provider timeout never becomes editorial REJECTED)
- module boundaries: workflow/signals/ai foundational; opportunities ->
  ideas/evidence_packs -> search_intent -> briefs; Phase 3 reads Phase 2
  read-only; Phase 2 never imports Phase 3; conceptual DB plan (17 tables)
  and job plan (6 jobs with Task 16 contracts) recorded — no migrations
  created, head stays `0008`
- Phase 3 implementation order defined: 14 atomic tasks (workflow
  foundation -> opportunity+intake -> scoring v1 -> signals -> evidence
  packs -> ideas -> AI boundary -> first adapter+idea engine -> search
  intent -> briefs+claim map -> brief composition -> orchestration ->
  admin -> closure audit); exit criteria enumerated (Writer explicitly not
  required for Phase 3 closure)
- ARCHITECTURE.md status line minimally corrected (stale "no application
  components exist yet") to point at the per-phase records; no historical
  architecture rewritten; no new ADR needed (design conforms to 0001-0008)
- PHASE 3 Task 2 (workflow foundation) complete: `contentos.workflow` added
  with `EditorialWorkItem`, append-only `EditorialWorkflowEvent`,
  `WorkflowRepository` (insert/append/get/get-for-update/list-history only;
  no update/delete surface), and `WorkflowService` as the sole transition
  boundary (validates, flushes; caller commits; typed transport-neutral
  errors)
- the full canonical WORKFLOW.md state vocabulary is persisted as one frozen
  lowercase enum (26 states) so later phases never migrate it; Phase 3
  exercises only its subset
- creation is fixed at IDEA_SCORING (promotion, not replay): no caller can
  choose an initial state; the creation event is from_state NULL ->
  idea_scoring with actor origin, required reason, bounded artifact_refs
  snapshot (identifiers only: depth/items/string-length limits, no payloads
  or secrets, never interpreted as FKs), and validated optional request_id;
  work item + creation event are written atomically in one transaction
- structural transition matrix implemented exactly from WORKFLOW.md
  including the MEASURING self-loop and explicit REJECTED/ARCHIVED ->
  RESEARCHING reopen paths; STRUCTURAL validity is deliberately separate
  from artifact eligibility (no opportunity/evidence/brief gates exist yet)
- BLOCKED and CHANGES_REQUESTED exits are derived from durable history
  (the from_state of the latest entry event), never from a caller-supplied
  target; BLOCKED may also go to REJECTED; documented Task 2 limitation:
  CHANGES_REQUESTED supports return-to-origin only — the richer
  named-responsible-state mechanism belongs to the phase implementing
  review loops
- entering BLOCKED/REJECTED requires a non-empty bounded reason mirrored to
  blocked_reason/rejected_reason (DB CHECKs enforce presence in those
  states); leaving clears the current-row projection while the immutable
  event history preserves the original reason; execution failures are never
  REJECTED (that separation stays with the failure model)
- transitions run under a row lock (get_by_id_for_update) and validate
  against the actually observed state, so stale/duplicate deliveries fail
  with a typed error instead of appending impossible history; promotion
  idempotency (one work item per promoted research root) is deliberately
  Task 3's identity — Task 2 defines no fake external key
- migration `0009_create_editorial_workflow`: both tables, frozen literal
  enum CHECKs, blocked/rejected-reason CHECKs, jsonb object CHECK on
  artifact_refs, BIGINT identity event PK, ON DELETE RESTRICT, indexes,
  and the established append-only trigger
  (`trg_editorial_workflow_events_append_only`); symmetric downgrade
  removes only Task 2 objects; work items are effectively permanent (no
  deletion API anywhere)
- real ephemeral pgvector PostgreSQL verification passed: 0008 -> 0009,
  service round-trip (create + valid transition + typed invalid transition),
  event UPDATE/DELETE rejected by trigger, work-item RESTRICT, state/event
  consistency, downgrade to 0008 with Phase 2 rows and pgvector surviving
  and only workflow objects removed, re-upgrade to 0009; teardown complete
- Task 2 added no intake, no opportunities/scoring, no AI, no Celery jobs,
  no API endpoints, no admin changes, and no dependency changes
- Task 2 verified: 713 backend tests (687 + 26 new), 96 admin tests, and
  the full root quality gate passed; schema head `0009`

## Current documentation structure

- AGENTS.md
- docs/PROJECT.md
- docs/ARCHITECTURE.md
- docs/WORKFLOW.md
- docs/EDITORIAL_POLICY.md
- docs/PHASE2_RESEARCH_DISCOVERY.md
- docs/PHASE2_CLOSURE_AUDIT.md
- docs/PHASE3_EDITORIAL_INTELLIGENCE.md
- docs/memory/PROJECT_MEMORY.md
- docs/memory/CURRENT_STATE.md
- docs/memory/GLOSSARY.md
- docs/adr/README.md (ADRs 0001-0008)

## Current implementation status

Repository foundation: complete

Backend: application factory, typed settings, structured logging, request context, API error contract, database engine/session foundation, liveness/readiness endpoints, the GET-only `/internal/research` visibility API (sources, discovery-items list, discovery-item detail), and the POST-only operator control surface (registration, lifecycle, admission, requeue, discovery/fetch triggers) complete

Frontend/control panel: Next.js foundation with server-side backend client, truthful Foundation Status page, Docker/Compose integration, the Sources / Research Pipeline / pipeline-detail screens with header navigation, and server-action operator controls (source registration/lifecycle/discovery trigger, item accept/reject/requeue/fetch); the browser never calls FastAPI or learns its URL

Database: engine/session, Alembic + pgvector, Source Registry, DiscoveryItem,
immutable FetchSnapshot, immutable NormalizedDocument, immutable
DuplicateDecision, immutable ResearchEvidence, and immutable content-addressed
raw_payload_blobs tables complete; Phase 3 editorial_work_items and
append-only editorial_workflow_events tables complete; schema head `0009`

Queue/workers: Redis/Celery foundation, worker entrypoint, and the five idempotent
research-pipeline domain tasks complete (commit-before-enqueue, at-least-once,
PostgreSQL authoritative); no Beat scheduling yet

Research discovery: Source Registry, manual/feed/sitemap admission, safe FetchClient,
bounded sitemap-index traversal, immutable FetchSnapshot persistence, and the
NormalizedDocument persistence, provider-neutral raw-payload contracts, and executable
bounded HTML/text normalization plus deterministic local duplicate decisions complete;
the immutable ResearchEvidence primitive with exact excerpt provenance, the
deterministic v1 evidence extractor (author/date metadata evidence), the durable
PostgreSQL raw-payload backend, the idempotent Celery research-pipeline
orchestration, and read-only operator visibility (internal API + admin screens)
are complete; no production inventory comparison exists

AI integration: not started

Publishing integration: not started

Pinterest integration: not started

Analytics integration: not started

## Important current constraint

Phase 2 implementation is authorized only one atomic task at a time.

No Evidence Pack, Celery Beat scheduling, pre-commit configuration, or
editorial business logic exists yet. The admin exposes exactly the minimal
Task 19 operator controls (registration, lifecycle, admission, requeue,
discovery/fetch triggers); there are no normalize/duplicate/evidence stage
triggers, no Celery control panel, no deletes, no source editing, and no
manual discovery-item creation. Backend
unit tests remain offline and require no running PostgreSQL or Redis. Docker Compose
covers local development only; production deployment does not exist. The admin app
has no login, authentication, users, roles, or RBAC by design.

ContentOS is a private single-operator control panel. Application-level users,
authentication, authorization, roles, and RBAC are outside the Phase 1 design;
access protection belongs to future deployment infrastructure.

## Next immediate task

PHASE 3 TASK 3 (awaiting explicit authorization) — Opportunity persistence +
intake, per the accepted design's implementation order item 2:
`contentos.opportunities` with the EditorialOpportunity anchor and
multi-source `opportunity_research_inputs` (roles, each pinning the exact
normalized_document_id + duplicate_decision_id), plus deterministic Phase 2
eligibility and the `promote_research` service path — operator-triggered
promotion of eligible Phase 2 chains into the workflow foundation
(SUCCEEDED normalization + effective DuplicateDecision required; DUPLICATE
hard stop with the explicit audited operator-override event for a distinct
angle; REJECT hard stop; UNIQUE/RELATED eligible; UPDATE_EXISTING as update
signal), promotion idempotency (one work item per promoted
normalized-document root), and a migration. No scoring engine yet (that is
design item 3), no AI, no Celery, no API/admin.

Before implementing the affected integrations, resolve:

- Publishing API contract, service authentication method, and production owner
- initial source allowlist, crawl permissions, and retention rules
- scoring, QA, cost, and budget thresholds
- Pinterest account/API access and distribution policy
- analytics data sources and content-identity mapping
- owner approval audit semantics for the future editorial workflow

## Known blockers

No known blockers. Phase 1 closed cleanly.

The integration and governance inputs listed above are intentionally unresolved
and will block their respective implementation or launch work, not this phase.
