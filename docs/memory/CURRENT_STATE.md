# Konsepthane ContentOS - Current State

Last updated: 2026-09-01

## Current phase

PHASE 3 - Editorial Intelligence / Idea Engine - IN PROGRESS
(Task 1 architecture accepted; Task 2 workflow foundation COMPLETE;
Task 3 opportunity persistence + promotion COMPLETE; Task 4 deterministic
opportunity scoring v1 COMPLETE; Task 5 provider-neutral search-signal
foundation COMPLETE; Task 6 EvidencePack foundation COMPLETE; Task 7 Idea
persistence + operator selection COMPLETE; Task 8 provider-neutral AI
boundary COMPLETE; Task 9 OpenAI adapter + model-assisted idea generation
engine COMPLETE; Task 10 SearchIntentAnalysis COMPLETE; Task 11
ContentBrief persistence + claim map + acceptance gate COMPLETE; Task 12
Brief Composition Engine COMPLETE)

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
decision). Phase 3 implementation is in progress; see the Phase 3 entries
below for what actually exists.

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
- PHASE 3 Task 3 (opportunity persistence + Phase 2 -> Phase 3 promotion)
  complete: `contentos.opportunities` added (enums/models/errors/repository/
  service); reads Phase 2 primitives, calls WorkflowService; Phase 2 never
  imports Phase 3 and workflow never imports opportunities
- `EditorialOpportunity`: 1:1 with its work item (UNIQUE work_item_id,
  RESTRICT), topic_summary, update_of_reference, disposition
  OPEN/COMMISSIONED/REJECTED with a DB consistency CHECK (non-open requires
  reason/at/by); promotion creates OPEN — no commissioning commands yet
- promotion identity is DATABASE-BACKED:
  `editorial_opportunities.promotion_root_document_id` (NOT NULL, UNIQUE,
  RESTRICT FK to normalized_documents) realizes the design §10.3 identity
  "one work item per promoted document root"; input roles stay a separate
  concept, so a promoted document can still be supporting/context input on
  another opportunity (implementation note added to the Phase 3 design doc)
- `OpportunityResearchInput`: references only (opportunity, document,
  duplicate decision — all RESTRICT), role
  primary_signal/supporting/contradicting/context/update_signal, added_by
  system/operator (OpportunityActor — distinct from workflow actor/origin
  vocabularies), bounded note; UNIQUE (opportunity, document); append-only
  PG trigger; never payloads/clean text/evidence text
- `ResearchPromotionService.promote_research` (ADR 0008-binding): requires
  document exists + SUCCEEDED + an effective DuplicateDecision (absence is a
  hard stop, never an implicit UNIQUE) + resolvable provenance chain
  (snapshot/item/source); UNIQUE/RELATED eligible with the exact decision
  pinned forever; UPDATE_EXISTING eligible only as an update signal (role
  update_signal + truthful update_of_reference naming the decision — no
  production inventory lookup, no fake article id); DUPLICATE/REJECT are
  hard stops
- effective-decision semantics reused, not reinvented: new
  `DuplicateDecisionRepository.get_effective_for_document` centralizes the
  deterministic (evaluated_at, created_at, id DESC) latest-is-effective
  contract the Task 17 projections already used
- one atomic caller-owned transaction creates work item (via
  WorkflowService, IDEA_SCORING, origin research_intake, locale from
  discovery item, market from source) + creation event (artifact_refs pin
  promotion kind, document, decision+outcome, snapshot, item, source) +
  opportunity + initial input; SAVEPOINT race recovery: a concurrent winner
  is recovered idempotently, otherwise typed PromotionConflictError; forced
  mid-promotion failure leaves zero orphans (tested)
- idempotent retry returns the existing work_item/opportunity ids
  (created=False) with no second event/opportunity/input; incompatible
  re-claim (e.g. override after a research-intake promotion when a newer
  engine version flips the outcome) raises PromotionConflictError without
  overwriting
- `promote_duplicate_override` (operator-only, narrow): applies only to an
  effective DUPLICATE decision (eligible outcomes are redirected to
  promote_research; REJECT has no override); mandatory bounded reason +
  distinct angle; work item origin OPERATOR, event actor OPERATOR, event
  reason = override reason, refs record promotion=duplicate_override with
  the pinned DUPLICATE decision; input note records the override; the
  DuplicateDecision is never mutated and never claimed wrong
- migration `0010_create_editorial_opportunities`: both tables, frozen
  literal vocabularies, uniques (work_item, promotion_root,
  opportunity+document), disposition-consistency CHECK, five RESTRICT FKs,
  indexes, append-only trigger on research inputs; symmetric downgrade
  removes only Task 3 objects
- real ephemeral pgvector PostgreSQL verification passed: migrate to
  `0010`, full REAL chain (payload store + snapshots + normalization + real
  duplicate engine producing unique/duplicate), promotion end-to-end,
  idempotent retry, DUPLICATE hard stop, operator override, input
  UPDATE/DELETE rejected by trigger, opportunity RESTRICT, promotion-root
  uniqueness enforced by PG, downgrade to `0009` with workflow/Phase 2
  rows and pgvector surviving, re-upgrade; teardown complete
- Task 3 added no scoring, search signals, ideas, evidence packs, AI,
  Celery jobs, API endpoints, admin changes, or dependency changes
- Task 3 verified: 735 backend tests (713 + 22 new), 96 admin tests, and
  the full root quality gate passed; schema head `0010`
- PHASE 3 Task 4 (deterministic opportunity scoring v1) complete: pure
  `OpportunityScoringEngine` (`opportunity-engine`/`1`) in
  `contentos.opportunities.scoring` strictly separated from the
  persistence-orchestrating `OpportunityScoringService`
  (`scoring_service.py`); the engine does no I/O and the service flushes
  while the caller commits
- append-only `opportunity_scores` (band strong/moderate/weak/ineligible +
  nullable normalized 0..1 overall_value, eligibility
  commissionable/not_commissionable/needs_operator_review, weights/threshold
  snapshots, missing_signals, risk_flags, input_snapshot + SHA-256 hash,
  evaluated_at) and relational `opportunity_score_components` (UNIQUE
  (score, component); availability known/unknown/not_applicable; the DB
  CHECK enforces KNOWN <-> value present, so UNKNOWN can never be smuggled
  in as zero); both tables trigger-protected append-only, RESTRICT FKs
- full 12-component vocabulary frozen now (recency, audience_fit,
  evidence_availability, source_diversity, source_trust, competition,
  search_demand, editorial_value, seasonality, duplicate_overlap_risk,
  policy_risk, production_cost_estimate); v1 computes exactly the five with
  durable deterministic sources and persists explicit UNKNOWN rows (NULL
  values) for the other seven — never fabricated, and a missing row is not
  the same thing as UNKNOWN
- UNKNOWN != ZERO enforced end to end: only KNOWN components enter the
  weighted score and the denominator renormalizes over KNOWN weights;
  known-signal coverage rule (>=3 known core components AND >=0.5 known
  weight fraction, else eligibility = needs_operator_review) prevents one
  lonely signal from fabricating an excellent score
- frozen v1 policy (all persisted per score in weights/threshold snapshots,
  test-pinned, described as initial operational policy, never statistical
  truth): weights summing to 1.0; recency buckets 7/30/90/365 days ->
  1.0/0.8/0.6/0.4 with 0.2 floor (external_published_at precedence, then
  fetched_at; no timestamp -> UNKNOWN, never "old"); diversity by distinct
  sources 1/2/3/4+ -> 0.3/0.6/0.8/1.0 (same-source documents count once);
  trust tier map official/expert/reputable/general/reference_only ->
  1.0/0.9/0.75/0.5/0.25 aggregated by MEAN over distinct sources; duplicate
  overlap as inverted-risk contribution unique/related/update_existing/
  duplicate/reject -> 1.0/0.7/0.5/0.2/0.0 aggregated by MIN (operator
  override stays visibly high-risk; decisions never rewritten; no vector
  claim); evidence buckets 0/1-2/3-5/6+ -> 0.0/0.4/0.7/1.0 with zero
  evidence a KNOWN 0.0 fact (availability signal only — explicitly not the
  future EvidencePack sufficiency gate); bands strong>=0.75, moderate>=0.55;
  eligibility strong->commissionable, moderate->needs review,
  weak->not commissionable; INELIGIBLE band reserved and never emitted by
  v1 (intake already owns hard stops); risk_flags empty in v1 (no governed
  deterministic classifier exists; nothing inferred)
- reproducible input snapshot (schema v1): pins research-input ids,
  document/decision ids + outcomes, roles, source ids + trust tiers,
  recency timestamps, the evidence-set identity (sorted ids up to 200, else
  count + set-hash + query basis), and the evaluation DAY; hash = SHA-256
  over canonical sorted JSON (order-independent, never Python repr)
- idempotency: DB-unique (opportunity, engine, version, input_snapshot_hash);
  same-day identical retry returns the existing score with no duplicate
  rows; changed evidence/inputs, a later evaluation day (recency
  legitimately moved), or a new engine version append a new score; old
  scores immutable; SAVEPOINT race recovery returns the concurrent winner
- effective score = `get_effective_score` (evaluated_at DESC, id DESC);
  history remains fully queryable; scoring never mutates
  EditorialOpportunity.disposition and never transitions the work item
  (tested: disposition stays open, no new workflow events)
- migration `0011_create_opportunity_scores`: both tables, frozen literal
  vocabularies, identity unique, value-presence/range CHECKs, hash-format
  CHECK, JSONB shape CHECKs, indexes, two append-only triggers; symmetric
  downgrade removes only Task 4 objects
- real ephemeral pgvector PostgreSQL verification passed: migrate to
  `0011`, real chain (payload store + snapshot + normalization + real
  duplicate engine + promotion), full evaluation (12 components, 5 KNOWN,
  UNKNOWN NULLs, snapshots present), idempotent retry, evidence-change
  append + effective-is-latest, no disposition/workflow side effects, all
  four UPDATE/DELETE mutations rejected by triggers, DB rejecting
  KNOWN-without-value, downgrade to `0010` with opportunities and pgvector
  surviving, re-upgrade; teardown complete
- Task 4 added no search-signal store, no external providers, no AI, no
  Celery, no API/admin changes, no automatic commissioning, and no
  dependency changes
- Task 4 verified: 778 backend tests (735 + 43 new), 96 admin tests, and
  the full root quality gate passed; schema head `0011`
- PHASE 3 Task 5 (provider-neutral search-signal foundation) complete:
  `contentos.signals` added (enums/errors/values/models/repository/service);
  signals are OBSERVATIONS, never current truth — multiple observations for
  one subject coexist, no "effective/current signal" helper exists, and
  later consumers (scoring engine v2+, SearchIntentAnalysis, briefs) will
  explicitly choose and pin exact signal IDs
- `search_signals` table: signal_type vocabulary frozen (search_volume,
  trend, serp_observation, query_set, manual_intent_note — WHAT was
  observed, never which provider), subject (bounded, conservative
  whitespace normalization only — no slugs, no NLP, Turkish casing
  untouched), explicit locale/market, provider as a bounded governed STRING
  vocabulary (no enum-CHECK migration churn for future governed
  connectors; no vendor SDK concepts in the domain), bounded typed JSONB
  value, nullable confidence (never defaulted to 1.0 for human entry),
  observed_at (mandatory, aware) distinct from recorded_at, nullable as_of
  for the represented period, and a SHA-256 observation_hash
- exactly ONE operational provider: `manual_operator` — the service exposes
  `record_manual_signal` with NO provider parameter, so unavailable
  providers cannot be spoofed; future connectors get their own explicit
  admission paths
- v1 value schemas (strict allowlists in `contentos/signals/values.py`,
  bounded, provider-neutral, no raw API responses/SERP HTML/secrets):
  SEARCH_VOLUME requires value+unit+basis (naked numbers rejected; zero is
  a legitimate observation; optional period); TREND requires
  observation+scale+basis (no fake universal 0-100 scale); SERP_OBSERVATION
  is bounded manual facts (features/notes/intent_pattern/ranking_notes, at
  least one, no fetching/scraping); QUERY_SET trims blanks, deduplicates
  keeping first occurrence, and PRESERVES operator order (semantically
  meaningful — identity hash is order-sensitive by design);
  and MANUAL_INTENT_NOTE is a bounded operator note that is editorial research
  input and never ResearchEvidence (model has zero FKs — no opportunity or
  evidence binding, verified by test)
- append-only history: PG trigger rejects UPDATE/DELETE; corrections append
  a new observation; no supersession/retraction model yet (documented:
  consumers select exact observations; old observations remain historical
  and visible)
- exact-retry idempotency: observation identity = SHA-256 over canonical
  sorted JSON (schema v1) of type+subject+locale+market+provider+canonical
  value+confidence+observed_at+as_of; DB-UNIQUE on the hash; identical
  retry returns the existing row (created=False); any changed
  observed_at/as_of/value/type/subject appends; SAVEPOINT race recovery
  returns the concurrent winner; "same subject" alone is never deduped
- recording a signal has zero side effects: no work item, no opportunity,
  no score, no workflow transition (tested against a real promoted+scored
  opportunity); opportunity-engine/1 untouched — SEARCH_DEMAND/COMPETITION
  remain UNKNOWN and Task 4 score history stays exactly reproducible
- migration `0012_create_search_signals`: table + frozen vocabulary CHECK +
  subject/locale/market/provider/confidence/hash-format/jsonb-object CHECKs
  + unique hash index + subject/type indexes + append-only trigger;
  symmetric downgrade removes only Task 5 objects
- real ephemeral pgvector PostgreSQL verification passed: migrate to
  `0012`, survivor seed (promoted+scored opportunity), record note/query
  set/search volume, idempotent exact retry, changed-observation append,
  4-observation deterministic history, PG-enforced hash uniqueness,
  UPDATE/DELETE rejected by trigger, zero scoring/workflow side effects,
  downgrade to `0011` with scores/opportunities/documents/pgvector
  surviving and only search_signals removed, re-upgrade; teardown complete
- Task 5 explicitly added NO external providers (no Semrush/Google/Search
  Console/analytics/scraping/API keys/OAuth/network), no AI, no Celery, no
  API/admin surfaces, and no dependency changes
- Task 5 verified: 805 backend tests (778 + 27 new), 96 admin tests, and
  the full root quality gate passed; schema head `0012`
- PHASE 3 Task 6 (EvidencePack foundation, including the reproducibility
  correction pass) complete: `contentos.evidence_packs` added
  (enums/errors/policy/models/repository/service); assembler identity
  `evidence-pack-assembler`/`1`; membership and provenance fully
  deterministic — a pack is assembled from explicitly selected
  ResearchEvidence units and is never copied text, a source dump, raw HTML,
  a URL list, or an AI summary
- assembly identity covers the WHOLE semantic assembly input: each pack
  stores a canonical `assembly_input_snapshot` (schema v1: assembler
  name+version, the EXACT policy snapshot, sorted selection triples
  (evidence id, role, claim_cluster), sorted contradiction states
  (claim_key, sides, nature, severity, resolution_status)) plus its SHA-256
  `assembly_input_hash` over canonical sorted JSON (never Python repr);
  DB-backed UNIQUE (opportunity, assembler name+version,
  assembly_input_hash) alongside UNIQUE (opportunity, version); display
  notes and handling recommendations are excluded ONLY as formally cosmetic/
  advisory (documented + tested: a notes-only retry returns the existing
  pack; they never affect sufficiency)
- sufficiency policy is an EXPLICIT caller input: frozen
  `EvidenceSufficiencyPolicy` dataclass (name, version, min_evidence_items,
  min_distinct_sources, min_key_facts, staleness_days) with
  snapshot()/from_snapshot(); `DEFAULT_EVIDENCE_POLICY` = default/1
  (3 items, 2 distinct sources, 1 key fact, 180 staleness days) is a named,
  versioned initial operational policy — fully persisted per pack in
  policy_snapshot AND inside the assembly snapshot, never invisible
  universal truth; the 180-day staleness caution belongs to the versioned
  policy; changing ONLY a policy version/threshold yields a NEW pack
  version with a different hash while the old pack is untouched, and an
  exact retry with the original policy returns the original pack
  (DB-uniqueness-protected, tested on SQLite and real PG)
- REPRODUCIBILITY CONTRACT: authoritative sufficiency for a pack version is
  the persisted immutable `sufficiency` + `sufficiency_detail` computed
  once at assembly; "pack UUID X / version N was READY" never changes
  afterward; there is NO live/current sufficiency helper and no
  get_current_ready_pack semantics (test-pinned: the service exposes no
  evaluate/current/effective surface)
- contradictions are ASSEMBLY INPUTS: `ContradictionDeclaration`s supplied
  to `assemble_pack` (sides validated as disjoint subsets of the selected
  evidence) become per-pack `evidence_contradictions` rows starting
  UNRESOLVED and participate in the assembly identity (same selections with
  vs without a declaration are distinct packs — never deduped);
  `resolve_contradiction` stays an audited mutation on the contradiction
  row (non-unresolved status + mandatory reason, stamps
  resolved_by=operator + resolved_at, refuses re-resolution; DB CHECK
  enforces resolution-field consistency) but NEVER changes any pack's
  stored sufficiency
- explicit `reassemble_pack(pack_id, policy=None,
  additional_contradictions=None)` produces the NEW version: policy
  defaults to the old pack's persisted snapshot via from_snapshot;
  selections (including display notes) are rebuilt from the old pack's
  items; contradiction definitions + resolution state are carried forward
  into the new pack's OWN rows and snapshot frozen at reassembly time
  (independently explainable later, no evidence text copied); an unchanged
  reassembly returns the existing pack; the §6 flow is test-pinned on
  SQLite and real PG: v1 with a blocking declaration is CONFLICTED,
  resolving its row leaves v1 historically CONFLICTED forever, reassembly
  yields v2 READY with the resolved state carried into v2's rows
- sufficiency evaluation (at assembly only): any UNRESOLVED BLOCKING
  contradiction -> CONFLICTED; policy minimums missing -> INSUFFICIENT with
  named missing entries; else READY; detail records policy name+version;
  BLOCKED reserved (policy v1 defines no deterministic block condition and
  never emits it); absence of evidence is never a pass
- `evidence_packs` (immutable, append-only trigger) also stores
  source-diversity summary (distinct sources, trust-tier distribution,
  reference_only flag), staleness notes (recency basis older than the
  policy's staleness_days — a caution, never a block), locale-limitation
  summary, aggregated licensing cautions (reference_only sources + evidence
  licensing_notes travel with the pack per ADR 0007); the accepted design's
  idea link and AI organization-attempt link are deliberately absent —
  those columns arrive with the Ideas and AI-boundary tasks' own migrations
- `evidence_pack_items` (append-only trigger): mandatory NOT NULL RESTRICT
  FK to research_evidence, roles key_fact/supporting/contradicting/context/
  caution, bounded claim_cluster, bounded optional display_note beside the
  mandatory reference — no evidence_text/statement/excerpt column exists
  (test-pinned); eligibility requires every selected evidence unit to trace
  to the opportunity's admitted research inputs
- `evidence_contradictions`: core fields immutable and DELETE forbidden via
  a guarded PG trigger that permits UPDATE only on the resolution
  dimension; severity low/material/blocking
- assembly idempotency mechanics: identity pre-check returns the existing
  pack; SAVEPOINT race recovery returns the concurrent winner; changed
  set/roles/contradictions/policy appends a new version with old versions
  fully queryable; caller owns commit
- migration `0013_create_evidence_packs`: three tables, frozen literal
  vocabularies, four RESTRICT FKs, identity/version uniques, hash-format +
  assembly-snapshot jsonb-object + resolution-consistency CHECKs,
  append-only triggers on packs/items and the guarded mutation trigger on
  contradictions; symmetric downgrade removes only Task 6 objects
- real ephemeral pgvector PostgreSQL verification passed: migrate to
  `0013`, real chain (payload store + real duplicate engine + promotion +
  two-source evidence), v1 assembly with a blocking declaration ->
  CONFLICTED with the policy inside the stored jsonb snapshot, idempotent
  exact retry, audited resolution leaving v1 CONFLICTED, reassembly -> v2
  READY carrying the resolved contradiction into its own row, stricter
  policy -> v3 INSUFFICIENT with pinned policy snapshot, original-input
  retry deduping to v1, all six pack/item/contradiction-core UPDATE/DELETE
  mutations rejected while a resolution-dimension UPDATE is allowed,
  PG-enforced assembly identity uniqueness, zero workflow/disposition side
  effects, downgrade to `0012` with evidence/opportunities/pgvector
  surviving, re-upgrade; teardown complete
- Task 6 added no AI organization assistance, no Ideas/intent/briefs, no
  claim/evidence maps, no Celery, no API/admin changes, no workflow
  transitions, no commissioning, and no dependency changes
- Task 6 verified (post-correction): 829 backend tests (805 + 24 new), 96
  admin tests, and the full root quality gate passed; schema head `0013`
- PHASE 3 Task 7 (Idea persistence + operator selection) complete:
  `contentos.ideas` added (enums/errors/policy/values/originality/models/
  repository/service); an Idea is a proposed Konsepthane-specific editorial
  concept — never evidence, never a provenance root (ADR 0007), never
  publication approval (ADR 0004), never generated article content
- immutable version identity: each `ideas` row is ONE exact version (`id`
  is what downstream artifacts pin); `logical_idea_id` is the stable
  candidate identity; UNIQUE (logical_idea_id, version), version >= 1;
  revision creates a NEW row (`revise_operator_idea` derives logical id +
  opportunity from the prior version — a caller can never move a logical
  idea between opportunities); repository has no update/delete surface and
  a PG append-only trigger protects rows; concurrent revisions serialize by
  locking the owning EditorialOpportunity row (FOR UPDATE) before version
  allocation — verified on real PG with two threads producing v2/v3
- operator-only origin: the `origin` vocabulary and DB CHECK contain ONLY
  `operator` today, so fake model provenance is impossible at the database
  level; MODEL_ASSISTED + the real generation_attempt FK arrive with the
  AI-boundary task's own migration (dependency-safe staged implementation,
  not a design change; no placeholder UUID was created)
- fields: bounded non-empty working_title (proposed direction, never a
  final/SEO title), angle, audience, value_proposition, rationale (an idea
  without a stated original angle is invalid at the domain layer);
  content_type is the accepted controlled 8-value vocabulary (guide/
  idea_list/checklist/planning_guide/comparison/faq/how_to/inspiration) —
  an editorial choice supplied by the operator, never inferred from a
  source article; locale/market derive from the parent work item through
  the opportunity (callers cannot supply conflicting values); exclusions
  are a bounded deduplicated ordered string list; planning_dimensions use a
  versioned bounded schema (schema_version 1, explicit 12-dimension
  allowlist, bounded strings/lists, NaN/Infinity/nesting rejected)
- deterministic originality guards (design §5.3) with an EXPLICIT typed
  versioned `IdeaOriginalityPolicy` (name/version/min_distinct_sources/
  title_similarity_failure_threshold/fake_ugc_patterns) whose full snapshot
  is persisted per idea version; DEFAULT = default/1 (2 distinct sources,
  0.90 title threshold) documented as initial operational policy, caller
  can supply another; no hidden universal editorial constants
- recorded checks per version (originality_status + originality_detail +
  originality_policy_snapshot): source diversity DERIVED from the
  NormalizedDocument -> FetchSnapshot -> DiscoveryItem -> Source chain
  (three documents from one source = one source; caller can never submit a
  count); working-title similarity against every usable input-document
  title via the existing shared `title_similarity` utility (max similarity,
  most-similar document id, threshold, skipped no-title inputs recorded);
  a near-copy is recorded as FAILED — never rewritten, never hidden;
  missing titles yield NOT_CHECKABLE, which is never promoted to PASSED;
  guards are deterministic protections, not a plagiarism oracle, and a
  FAILED candidate row remains visible (the accepted design gates brief
  commissioning on it later; selection itself stays an operator decision)
- fake-UGC guard: bounded versioned casefolded pattern list (gerçek
  kullanıcı yorumları / annelerden tavsiyeler / testimonial / ratings
  phrasing etc.) scanned over all five text fields; any match is a typed
  hard `FakeUgcRejectionError` with NO idea row persisted (Phase 3 has no
  UGC ingestion; no LLM, no semantic-detection claim)
- append-only `idea_selection_events` (BIGINT monotonic id = audit order):
  action strictly selected/deselected (no approve/publish vocabulary),
  actor operator-only, mandatory bounded reason, validated optional
  request_id, exact idea-version FK RESTRICT; PG append-only trigger;
  effective-selection rule = the LATEST event decides (SELECTED -> its
  exact version; DESELECTED or none -> nothing effective; deselect must
  target the current selection, so no older candidate ever silently
  resurrects); revising a logical idea NEVER retargets an existing
  selection; re-selecting the effective idea is a semantic no-op (no
  duplicate event — verified concurrently on real PG); selection commands
  serialize on the opportunity row lock
- EvidencePack idea link realized (deferred by Task 6): migration 0014 adds
  nullable `evidence_packs.idea_id` FK RESTRICT; `assemble_pack` accepts an
  optional exact idea version (must belong to the same opportunity) and the
  pinned idea participates in the semantic assembly identity (snapshot
  schema bumped to 2; same evidence/policy with a different idea = a
  different pack); `reassemble_pack` carries the existing idea forward
  unless explicitly replaced via `replace_idea=True`; existing packs stay
  NULL and valid (idea_id never NOT NULL); changing the effective selection
  never mutates or repoints an existing pack; Idea never imports
  evidence_packs (dependency stays one-directional)
- migration `0014_create_ideas`: ideas + idea_selection_events with frozen
  literal vocabularies, nonempty/jsonb-shape/version CHECKs, uniques,
  indexes, two append-only trigger functions, plus the evidence_packs
  idea_id column/FK/index; symmetric downgrade removes the pack link FIRST,
  then Task 7 tables only — Task 6 packs survive downgrade to `0013`
  (verified: 3 pack rows intact, idea_id column gone, re-upgrade clean)
- real ephemeral pgvector PostgreSQL verification passed: migrate to
  `0014`, create v1 (PASSED, tr-TR/TR derived), near-copy FAILED with
  recorded similarity 1.0, fake-UGC hard rejection with no row, two-thread
  concurrent revisions -> versions 2 and 3, selection pinning across
  revisions, explicit re-select, concurrent duplicate select -> single
  event, idea/event UPDATE/DELETE trigger-rejected, DB CHECK rejecting
  'model_assisted' origin, pack-idea distinct identity + explicit
  replacement + no repointing, zero workflow/disposition/score side
  effects, downgrade/re-upgrade cycle; teardown complete
- Task 7 added no AI, no MODEL_ASSISTED origin, no ai_generation_attempts,
  no SearchIntentAnalysis, no ContentBrief, no Celery, no API endpoints, no
  admin UI, no commissioning, no workflow transitions, and no dependency
  changes
- Task 7 verified: 874 backend tests (829 + 45 new), 96 admin tests, and
  the full root quality gate passed; schema head `0014`
- PHASE 3 Task 8 (provider-neutral AI boundary) complete: `contentos.ai`
  added (enums/errors/hashing/dto/protocol/validation/fake/models/
  repository/service) — the reusable structured-generation boundary ONLY;
  no real provider, no OpenAI SDK, no network, no domain engine
- `StructuredGenerationProvider` protocol: adapters expose an honest
  `ProviderIdentity` (provider, model_name, model_version None when
  genuinely unavailable — never fabricated) and return provider-neutral
  `ProviderResult` DTOs (JSON payload + identity + bounded finish/usage);
  SDK/HTTP objects and exceptions never cross the boundary — adapters
  translate failures into typed `ProviderFailureError`
  (provider_error/timeout/cancelled) with bounded sanitized error classes
- `GenerationRequest`: purpose (idea_candidates/intent_synthesis/
  brief_composition/evidence_organization), schema name+version, template
  NAME+version (both persisted so template provenance is unambiguous),
  bounded `input_refs` (durable artifact provenance), bounded in-memory
  `input_projection` (NEVER persisted in full), positive-int
  generation_bounds, retry_number (convention: first attempt = 0; changing
  it permits a new attempt); all fields bounded with NaN/Infinity/depth/
  key/list/string rejection
- canonical hashing (`contentos.ai.hashing`, allow_nan=False, sorted keys,
  never repr): `GENERATION_INPUT_SCHEMA_VERSION = 1` input hash over
  input_refs + projection + bounds (same projection with different
  input_refs = different hash — audit honesty; dict order never matters,
  list order always does); `ATTEMPT_IDENTITY_SCHEMA_VERSION = 1` NULL-safe
  DB-UNIQUE `attempt_identity_hash` over purpose/input_hash/provider/
  model_name/model_version-as-explicit-null/schema/template/retry — the
  physical idempotency identity (nullable UNIQUE tuples deliberately not
  used)
- structured output ONLY: provider payload -> versioned Pydantic schema
  validation -> optional typed domain-validator callback (a plain function
  in `StructuredOutputSpec` so future engines plug in without contentos.ai
  importing ideas/packs/intent/briefs) -> SUCCEEDED; any failure is
  recorded VALIDATION_FAILED with stable error class `schema_validation` /
  `domain_validation`; output is never coerced, partially accepted, or
  repaired; no second call; spec/request schema-identity mismatch is
  rejected BEFORE provider invocation
- append-only `ai_generation_attempts` (ONE generic table, migration
  `0015`): purpose/provider/model identity, schema+template identity,
  input_refs + input_hash + attempt_identity_hash (UNIQUE), status
  (succeeded/validation_failed/provider_error/timeout/cancelled — never
  editorial vocabulary), sanitized bounded error_class (NULL exactly when
  succeeded, DB CHECK), retry_number >= 0, bounded usage JSONB (tokens/
  latency/finish_reason; cost amount+currency only when genuinely
  supplied, never invented); NO raw output/prompt/messages/payload columns
  (test-pinned); completed-outcome insert model (no PENDING/RUNNING state
  machine); PG append-only trigger; repository is add/get/list only with
  no "latest AI truth" surface
- expected outcomes are DURABLE FACTS returned in typed
  `GenerationExecution` (attempt, status, created flag, payload only when
  newly SUCCEEDED — idempotent reuse returns no payload since raw output
  is never persisted); contract errors raise typed errors before
  invocation; service flushes, caller commits (failure rows survive
  commit, tested)
- idempotency: identity pre-check + SAVEPOINT race recovery on the UNIQUE;
  sequential identical retries return the same attempt with ZERO extra
  provider invocations (fake invocation counter pinned); truthful
  concurrency contract: under truly concurrent identical execution both callers
  may invoke the provider but exactly ONE durable attempt row exists —
  provider-call serialization would need mutable reservation state and is
  documented as a future orchestration boundary (design-doc note)
- deterministic fake provider (`fake` /
  `deterministic-structured-test-model` / `1`): configurable fixed
  payload/usage/failure kind/claimed identity, deep-copied deterministic
  responses, invocation counter, cost absent unless configured, no
  randomness/network/keys; a result claiming a different identity than the
  adapter declares is detected and recorded as PROVIDER_ERROR
  `provider_identity_mismatch` under the DECLARED identity
- staged Idea AI provenance (migration 0015): `ideas.origin` widened to
  operator/model_assisted, nullable `generation_attempt_id` FK RESTRICT,
  DB CHECK `ck_ideas_origin_attempt_consistency` (operator <-> NULL,
  model_assisted <-> NOT NULL) so fake model provenance stays impossible;
  runtime IdeaService remains OPERATOR-ONLY (no generate/model-assisted
  surface, test-pinned); Task 9's engine must validate the referenced
  attempt is the right successful IDEA_CANDIDATES attempt (deliberately
  not SQL); downgrade restores the operator-only CHECK and FAILS loudly if
  model-assisted rows exist (never lossy conversion)
- staged EvidencePack link (migration 0015): nullable
  `organization_attempt_id` FK RESTRICT; deterministic assembly/reassembly
  always writes NULL (test-pinned) — no AI organization engine exists and
  a deterministic pack is never claimed AI-organized; idea_id/assembly
  hash/sufficiency semantics untouched
- migration `0015_create_ai_generation_attempts`: attempts table with
  frozen literal vocabularies + identity/format/consistency CHECKs +
  jsonb-object CHECKs + purpose/input_hash indexes + append-only trigger,
  plus both staged FK columns/indexes and the widened origin CHECK;
  symmetric downgrade removes pack link, idea link, restores operator-only
  origin, then drops the attempts table
- real ephemeral pgvector PostgreSQL verification passed: migrate to
  `0015`; Task-7-style seed (operator idea + selection + idea-pinned READY
  pack) valid with NULL AI columns; fake-provider SUCCEEDED /
  schema-invalid / domain-invalid / provider-error / timeout / cancelled
  attempts; sequential retry idempotent (one invocation); retry_number
  append; raw duplicate-identity INSERT rejected by the UNIQUE;
  UPDATE/DELETE trigger-rejected; all three idea origin/attempt/FK
  inconsistencies DB-rejected; pack organization column protected; zero
  workflow/disposition/selection/evidence side effects; downgrade to
  `0014` removed only Task 8 objects with all Task 7 rows + pgvector
  surviving and the restored operator-only origin CHECK rejecting a raw
  model_assisted insert; re-upgrade to `0015` WITH existing rows proved
  the upgrade preserves data (idea/pack NULL columns, empty attempts)
- Task 8 added NO OpenAI/Anthropic/Gemini/local-LLM adapter, no network,
  no API key/secret/setting, no idea-generation engine, no
  SearchIntentAnalysis, no ContentBrief, no Celery, no API/admin changes,
  no workflow transitions, and no dependency changes (lockfiles untouched;
  Pydantic/SQLAlchemy/stdlib only)
- Task 8 verified: 905 backend tests (874 + 31 new), 96 admin tests, and
  the full root quality gate passed; schema head `0015`
- PHASE 3 Task 9 (first real OpenAI adapter + model-assisted idea
  generation engine) complete; ADR 0009 accepted (OpenAI first provider:
  official SDK only, Responses API + strict Structured Outputs,
  store=false, no tools, SDK retries disabled, no SDK types/raw
  output/prompts across the boundary, key/model as configuration,
  automated tests never hit live OpenAI); the `openai` SDK (3.6.0) is the
  approved dependency exception, pinned in pyproject/uv.lock
- protocol evolution (smallest, provider-neutral): providers now receive a
  `ProviderOutputSchema` (name, version, plain JSON Schema derived by the
  service from the Pydantic spec, strict flag) alongside the request, and
  `GenerationRequest` gained bounded in-memory `instructions` (rendered
  versioned template text — never persisted, never hashed; substantive
  changes require a template version bump); contentos.ai still imports no
  domain module
- `contentos.ai.providers.openai_provider.OpenAiStructuredProvider`: the
  ONLY module importing the SDK; explicit construction (injectable client,
  no import-time/global client, max_retries=0, bounded timeout); truthful
  identity provider=openai + exact configured model, model_version NULL
  (never fabricated/parsed); `responses.create` with instructions +
  canonical-JSON projection input + strict json_schema text format +
  store=False + max_output_tokens from generation_bounds; refusal/
  incomplete/non-completed/malformed-JSON outputs and SDK exceptions map
  to stable sanitized classes (openai_timeout/_rate_limit/_connection_
  error/_api_error/_sdk_error/_refusal/_incomplete_response/_response_
  not_completed/_malformed_structured_output); usage maps only reported
  tokens + locally measured latency, cost never invented; response IDs
  not persisted; settings CONTENTOS_OPENAI_API_KEY (SecretStr) /
  _MODEL / _TIMEOUT_SECONDS — app + all non-OpenAI features run with none
  set (.env.example documents commented-out safe placeholders)
- `contentos.ideas.generation.IdeaGenerationEngine`: the first end-to-end
  model-assisted domain engine — depends ONLY on the provider-neutral
  boundary (fully tested with the fake provider; never knows OpenAI
  exists); frozen identities generator `idea-generator/1`, template
  `idea-candidates/1`, schema `idea-candidate-batch/1`, input-refs schema
  `idea-generation/1`; purpose strictly IDEA_CANDIDATES
- precondition (design §18): generation runs only on a COMMISSIONED
  opportunity — validated, never mutated (no commissioning command exists
  yet, so tests seed the disposition directly); generation never selects,
  never transitions workflow, never rebuilds packs
- deterministic bounded research projection (never raw HTML/bodies/whole
  articles): topic summary, locale/market, ≤10 admitted inputs (added_at,
  id order), document titles + roles + source labels/trust tiers, ≤20
  ResearchEvidence statements truncated to 500 chars with verification
  status labels (RETRACTED excluded deterministically and counted),
  duplicate/update context, pinned effective OpportunityScore summary
  (exact score id in refs; absent stays absent), allowed content types,
  originality policy summary; exact projected artifact IDs pinned in
  input_refs (opportunity, work item, inputs, documents, evidence,
  decisions, score, policy name+version, generator identity, count)
- structured output: `IdeaCandidateBatchV1` (strict-friendly closed
  models, all fields required/nullable, existing ContentType vocabulary,
  Task-7 exclusions + planning-dimensions revalidated — no second weaker
  vocabulary); model can never supply IDs/logical identity/opportunity/
  locale/market/origin/attempt refs/scores/selection markers; exact
  candidate count enforced (mismatch, exact-duplicate candidates, or any
  fake-UGC candidate rejects the WHOLE batch as VALIDATION_FAILED with
  zero artifacts)
- Task-7 semantics preserved: near-copy titles and insufficient source
  diversity persist as ideas with FAILED originality (recorded, never
  hidden, never auto-deleted); fake UGC remains a hard no-artifact rule;
  every generated idea reruns the SAME originality machinery via the
  shared `originality_inputs_for_opportunity` (no AI-side variant)
- persistence: fresh logical_idea_id + version 1 per candidate, origin
  MODEL_ASSISTED + generation_attempt_id = the exact SUCCEEDED attempt
  (engine revalidates purpose/status/input-ref provenance — FK and caller
  are never trusted); batch materialization is atomic (all or nothing) in
  the same transaction as the attempt (rollback removes both); operator
  IdeaService paths unchanged (regression-tested); failed attempts
  (validation/provider/timeout/cancelled) persist durably with ZERO ideas
- idempotency: exact retry returns the stored attempt AND its existing
  ideas with zero provider calls (`IdeaRepository.list_by_generation_
  attempt`); reused SUCCEEDED attempt with no linked ideas is a typed
  IncompleteMaterializationError (raw output is never re-fetchable;
  recover explicitly with retry_number+1 — tested); policy version,
  template version, provider/model identity, and retry_number each change
  the attempt identity; concurrent identical invocations may double-call
  the provider (Task 8 truth) but attempt-row locking + attempt-scoped
  idea queries guarantee exactly ONE materialized batch and both callers
  resolve to the same idea IDs (verified with threads on real PG)
- real ephemeral pgvector PostgreSQL verification passed (fake provider,
  no network): schema stays `0015` (NO new migration), end-to-end
  generation (3 MODEL_ASSISTED ideas, fresh logical ids, exact attempt
  provenance), exact-retry idempotency (1 invocation), concurrent
  single-batch materialization, durable state exactly 2 attempts + 6
  ideas + 2 batches + 0 selection events + 1 workflow event + disposition
  untouched, no instruction text persisted anywhere
- Task 9 added NO SearchIntentAnalysis, no ContentBrief, no AI pack
  organization, no Celery, no API endpoints, no admin UI, no automatic
  selection/commissioning/workflow transitions, no live OpenAI calls in
  any gate; adapter tests use an injected mocked client; the API key
  never appears in errors/DTOs/rows
- Task 9 verified: 939 backend tests (905 + 34 new), 96 admin tests, and
  the full root quality gate passed; schema head `0015`; the only
  dependency change is the approved `openai` SDK
- Task 9 final contract verification pass: store=False and the production
  max_retries=0 client construction are test-pinned; the pathological
  SUCCEEDED/no-artifact + retry_number+1 contracts re-proven; PROJECT_
  MEMORY's ADR 0009 entry trimmed to a minimal durable reference (940
  backend tests)
- PHASE 3 Task 10 (SearchIntentAnalysis) complete: `contentos.
  search_intent` added (enums/errors/values/models/generation_schemas/
  repository/service) — the FIRST-CLASS versioned artifact (design §8
  option A), never a ContentBrief sub-object
- `search_intent_analyses` (immutable, append-only trigger, migration
  `0016`): UNIQUE (opportunity, version) + DB-backed semantic identity
  UNIQUE (opportunity, engine name+version, input_snapshot_hash); RESTRICT
  FKs to opportunity, the EXACT analyzed idea version, and the optional
  synthesis attempt; every accepted field persisted (primary/secondary
  intents, target_audience, query_concepts, page_purpose, likely_format,
  known_signal_refs, missing_signals, cannibalization status+basis,
  related_references, locale/market, engine identity, input snapshot+hash)
  with nonempty/format/jsonb-shape CHECKs; deliberately NO evidence-pack
  FK — the READY-pack gate belongs to orchestration (design §18), not the
  artifact contract
- selected-idea pin: creation requires the supplied idea to BE the current
  effective selection (typed IdeaNotSelectedError otherwise — none
  selected, wrong idea, or a historical version while a newer one is
  selected); a later selection change NEVER repoints an existing analysis
  (tested); the service never selects/deselects anything
- signals are EXPLICIT observations: callers supply exact SearchSignal ids
  (no implicit "latest" exists anywhere); each observation must match the
  analysis locale/market (typed rejection otherwise); `known_signal_refs`
  freezes id/type/subject/provider/exact canonical value/confidence/
  observed_at/as_of per consumed signal, sorted by observation identity —
  QUERY_SET internal query order stays semantic and preserved as stored;
  a NEW observation id is a NEW analysis input (old versions keep their
  frozen snapshots); signal rows are never mutated or marked consumed
- `missing_signals` is durable data computed from what was ACTUALLY
  supplied (the 5 existing signal-type values; no CPC/difficulty invented)
  — UNKNOWN != ZERO holds: absent volume is named missing, never 0
- semantic fields are bounded validated editorial text (no invented SEO
  enum): deterministic path takes the typed `IntentComposition` DTO
  (primary/page_purpose/likely_format required; bounded order-preserving
  duplicate-rejecting secondary_intents/query_concepts — concepts are
  concepts, never measured demand); `target_audience` is SYSTEM-OWNED from
  the pinned idea in BOTH paths (auditable Idea -> SearchIntent
  continuity)
- engine identity `search-intent-analyzer/1`; identity =
  SEARCH_INTENT_INPUT_SCHEMA_VERSION 1 canonical-JSON SHA-256 snapshot
  covering opportunity/idea/mode/composition (deterministic) or the
  synthesis attempt identity hash (AI), frozen signal snapshots, missing
  signals, cannibalization status+basis, related references; exact retry
  returns the existing analysis, any semantic change appends a version;
  version allocation under the opportunity row lock (concurrent distinct
  analyses got distinct versions on real PG)
- cannibalization truth-states persisted exactly as accepted
  (not_checked/no_known_conflict/potential_conflict/known_conflict);
  default NOT_CHECKED with a basis that truthfully records the
  unavailable published inventory; NO_KNOWN_CONFLICT / POTENTIAL_CONFLICT
  require the exact internal references actually examined (existence-
  validated) and are explicitly scoped `contentos_internal` — never a
  site-wide claim; KNOWN_CONFLICT is REFUSED by the service (accepted
  future vocabulary only; no production/inventory access, ADR 0001/0003
  intact); vague/empty bases and NOT_CHECKED-with-refs are typed
  rejections; related_references are allowlisted internal kinds only
- optional AI synthesis through the EXISTING boundary (purpose strictly
  INTENT_SYNTHESIS, schema `search-intent-synthesis/1`, template
  `search-intent-synthesis/1`): callers explicitly choose
  `compose_deterministic` vs `synthesize` (no ambiguous boolean); the
  strict closed schema proposes ONLY the five semantic fields — system
  facts (ids, locale/market, signal refs, missing signals, cannibalization
  anything, related refs, audience) cannot enter (schema-rejected, tested)
  — and the domain module imports no SDK (fake provider end-to-end tests);
  attempt input_refs pin opportunity/idea/signal ids/analyzer/
  cannibalization + related identities; failed attempts (validation/
  provider/timeout/cancelled) persist durably with ZERO analyses;
  deterministic path creates NO attempt (tested)
- AI artifact idempotency mirrors Task 9: exact retry returns the same
  attempt AND the same analysis with zero provider calls; a reused
  SUCCEEDED attempt with no linked analysis is a typed
  IncompleteAnalysisMaterializationError (raw output never persisted;
  recover with retry_number+1 — tested incl. real PG); synthesis attempts
  are revalidated (purpose/status/input-ref provenance — FK never
  trusted); concurrency contract: provider may be double-called (Task 8
  truth) but attempt-row locking + attempt-scoped lookup guarantee ONE
  analysis per durable attempt (two threads on real PG resolved to the
  same analysis id)
- migration `0016_create_search_intent_analyses`: table with frozen
  literal cannibalization vocabulary, all CHECKs/uniques/indexes, and the
  append-only trigger; symmetric downgrade removes only Task 10 objects —
  verified on real PG with all Task 9/earlier rows and pgvector surviving
  the 0016 -> 0015 -> 0016 cycle
- real ephemeral pgvector PostgreSQL verification passed (fake provider,
  no network, no SEO APIs): all 17 scripted checks true — deterministic
  v1/pin/snapshots/missing-truth/zero-signal honesty, new observation ->
  new version, exact retries (deterministic + AI), internal
  cannibalization states + KNOWN_CONFLICT rejection, AI success/failure/
  pathological/recovery, wrong purpose/status rejection, concurrent
  distinct versions, concurrent AI single-materialization, UPDATE/DELETE
  trigger-rejected, zero workflow/disposition/selection/signal/pack side
  effects
- Task 10 added NO ContentBrief, no brief claims/acceptance, no Celery, no
  API/admin, no Google/Semrush/Search Console or any live SEO
  integration, no Konsepthane production access, no workflow transitions,
  no commissioning/selection side effects, and no dependency changes
- Task 10 verified: 967 backend tests (940 + 27 new), 96 admin tests, and
  the full root quality gate passed; schema head `0016`
- PHASE 3 Task 11 (ContentBrief persistence + claim/evidence map +
  acceptance gate) complete: `contentos.briefs` added (enums/errors/
  values/structure_guard/models/repository/service) — the writing
  CONTRACT and its GATES only; the automated Brief Composition Engine is
  the NEXT task and does not exist yet (no AI call, no BRIEF_COMPOSITION
  attempt, composition_attempt_id always NULL on this path)
- `content_briefs` (migration `0017`): every accepted field; pins EXACT
  Idea/EvidencePack/SearchIntentAnalysis version ids (never
  logical/latest); UNIQUE (work_item, version) + relational identity
  UNIQUE (work_item, idea, pack, intent, engine name+version) + a partial
  unique index enforcing AT MOST ONE non-superseded active brief per work
  item; status strictly draft/accepted_for_drafting/superseded with a
  guarded PG trigger: DELETE forbidden, UPDATE may change ONLY `status`
  and only forward (draft->accepted_for_drafting, draft->superseded,
  accepted->superseded; reverse and status+content updates rejected —
  PG-verified); `brief_claims` (UNIQUE (brief, claim_key), accepted
  6-kind vocabulary — deliberately NO STATISTIC claim kind, that is an
  evidence TYPE; no regex pretends to find every statistic) and
  `brief_claim_evidence` (exact ResearchEvidence RESTRICT links, no text
  copies) are append-only (PG triggers); append-only
  `brief_status_events` audits every status mutation (from/to, operator
  actor, reason, request_id, nullable replacement_brief_id)
- draft creation (`create_draft`, typed `BriefDraftInput` — never a dict):
  requires the work item in BRIEFING (no transition happens on creation);
  full upstream consistency validated (idea/pack/intent same opportunity,
  intent pins the same idea, pack.idea_id NULL-or-equal — a generic pack
  is allowed, nothing fabricated); the pinned idea must still be the
  current effective selection; target_audience/original_angle/idea
  working title are DERIVED from the pinned idea (callers cannot
  contradict upstream); every idea exclusion is retained (brief may only
  add); practical_requirements reuse the Task-7 planning-dimension
  validator; sections/needs/criteria/notes are bounded ordered typed
  structures; FACTUAL/SOURCE_ASSERTION claims REQUIRE >=1 pack-member
  evidence AT CREATION (chosen philosophy, reported: such a map could
  never pass acceptance, so no misleading draft persists — structure-
  guard failures DO persist as inspectable failed drafts); evidence
  outside the pinned pack and unresolvable provenance are creation-time
  rejections; atomic brief+claims+links persistence; same identity+same
  content returns the existing brief, same identity+different content is
  a typed conflict (never a silent overwrite); a changed identity
  component creates the next version and supersedes the active DRAFT
  (mandatory audited reason + replacement pin) — an ACCEPTED brief is
  never silently superseded
- whole-version integrity: `content_hash` (schema-versioned canonical
  JSON SHA-256) covers ALL brief content + the complete claim map with
  evidence links + the structure-guard result and policy snapshot;
  acceptance recomputes it from persisted rows, so out-of-band child
  inserts fail acceptance with a typed conflict (append-only child tables
  alone are not trusted)
- structural copyright guard (deterministic, never AI): ordered
  required-section guidance vs EACH admitted input document's stored
  NormalizedDocument.headings via SequenceMatcher over normalized ordered
  label lists; explicit versioned `BriefStructurePolicy` (default/1,
  threshold 0.8, min 2 checkable headings, not_checkable_blocks_
  acceptance=True) snapshot-persisted per brief; result records checked/
  skipped documents, max similarity, most-similar document, outcome; a
  near-copy of ONE source FAILS; no usable source headings is
  NOT_CHECKABLE and fails acceptance closed per the persisted policy
  (reported); failed drafts stay inspectable, never deleted
- `accept_for_drafting` (explicit OPERATOR command, no generic
  set_status): runs ALL accepted §9.3 gates before mutating — BRIEFING
  state, current selection, idea originality (FAILED and NOT_CHECKABLE
  both fail closed — no accepted policy permits NOT_CHECKABLE, reported),
  COMMISSIONED opportunity (never mutated), duplicate gate reusing Task-3
  semantics (pinned decisions never REJECT; current effective REJECT
  always a hard stop; current effective DUPLICATE a hard stop unless the
  work item's creation event records the audited `duplicate_override` —
  the override stays distinguishable), claim gates (non-retracted
  evidence required for FACTUAL/SOURCE_ASSERTION — RETRACTED never
  satisfies; DISPUTED-only support requires recorded handling so
  disagreement stays visible; INFERENCE/EDITORIAL_JUDGMENT need no
  evidence but stay classified; OBSERVATION/INSTRUCTION follow the
  accepted §9.2 rule — evidence optional, links still pack-bound,
  reported), FACTUAL claims on evidence inside an UNRESOLVED BLOCKING
  contradiction fail (cautious wording cannot bypass), exact pinned pack
  READY, intent pinned (missing signals allowed, missing analysis not),
  full ADR-0007 provenance chain re-resolved per linked evidence,
  structure guard passed, content hash intact, and a non-null
  composition attempt must be a SUCCEEDED BRIEF_COMPOSITION attempt
  (validated for Task 12; never created here)
- acceptance mutation (one caller-owned transaction): DRAFT ->
  ACCEPTED_FOR_DRAFTING + audited status event + explicit WorkflowService
  BRIEFING -> DRAFTING transition (OPERATOR actor, operator reason,
  artifact_refs pinning exact brief/idea/pack/intent ids); a workflow
  failure rolls everything back; exact re-acceptance of the same accepted
  brief whose work item is DRAFTING and whose DRAFTING event pins this
  brief is a semantic no-op (inconsistent history is a typed conflict,
  never silently repaired); SUPERSEDED briefs can never be accepted and
  never resurrect; ACCEPTED_FOR_DRAFTING is an editorial decision — NOT
  publication approval (ADR 0004 untouched; no approved/published
  vocabulary anywhere, test-pinned)
- migration `0017_create_content_briefs`: four tables, frozen literal
  vocabularies, 10 RESTRICT FKs, identity/version/active uniques, the
  guarded brief trigger + three append-only triggers; symmetric downgrade
  removes only Task 11 objects — PG-verified with Task 10/earlier rows
  and pgvector surviving the 0017 -> 0016 -> 0017 cycle
- real ephemeral pgvector PostgreSQL verification passed: migrate to
  `0017`, full real seeded chain (promotion -> selected idea ->
  idea-pinned READY pack -> intent -> commissioned -> walked to BRIEFING
  via legal WorkflowService transitions), draft creation + exact retry,
  acceptance happy path with the DRAFTING workflow event pinning the
  brief, idempotent re-acceptance, all 9 forbidden mutations
  trigger-rejected while a status-only transition is allowed, the
  active-brief partial unique enforced by raw INSERT, expected durable
  state (commissioned, zero AI attempts, claim map intact); one
  migration defect found and fixed during verification (PL/pgSQL RAISE
  placeholder escaping in the guarded trigger)
- Task 11 added NO brief composition engine, no AI/OpenAI call, no new AI
  template/schema, no Celery, no API/admin, no Writer/Editor/QA, no
  publication approval, no media assets, no Konsepthane production
  access, and no dependency changes
- Task 11 verified: 993 backend tests (967 + 26 new), 96 admin tests, and
  the full root quality gate passed; schema head `0017`
- PHASE 3 Task 12 (Brief Composition Engine) complete: `contentos.briefs.
  composition` + `generation_schemas` added; NO migration (schema head
  stays `0017` — Task 11 already had composition_attempt_id); composer
  identity `brief-composer/1` (never a provider name), template
  `brief-composition/1`, schema `brief-composition/1`, purpose strictly
  BRIEF_COMPOSITION; the engine depends only on the provider-neutral
  boundary (fake-provider tests; no openai import outside
  contentos.ai.providers; no live calls anywhere)
- preconditions BEFORE any provider invocation (typed
  CompositionPreconditionError, provider invocations = 0): work item
  BRIEFING, COMMISSIONED opportunity, full Task-11 upstream consistency,
  idea still the effective selection, pack READY (no tokens spent on a
  knowingly unusable brief), and a READY pack carrying an unresolved
  BLOCKING contradiction fails closed as impossible state
- deterministic bounded evidence projection (policy
  `brief-evidence-projection/1`): pack items ordered by role priority
  (key_fact > supporting > contradicting > context > caution), then claim
  cluster, then evidence identity; RETRACTED evidence excluded from the
  AI-selectable set (count recorded); cap 30 with explicit omitted-count
  metadata — the model can never cite what it did not receive (exact
  projected ids + contradiction ids + composer/structure/projection policy
  identities pinned in attempt input_refs under schema marker
  `brief-composition/1`); per-unit projection carries evidence id, pack
  role/cluster/note, type, bounded statement (500 chars), verification
  status, source id/slug/trust tier, freshness, confidence, licensing
  notes — never raw HTML/payloads/whole bodies (test-pinned against the
  captured request)
- strict `BriefCompositionV1` output (extra=forbid, bounds imported from
  the Task-11 persistence limits): the model proposes ONLY
  writing-contract fields (summary/objective/sections/title direction+
  constraints/additional exclusions+uncertainty/link+media NEEDS/FAQ/
  criteria/claims with exact projected evidence ids); system-owned fields
  (ids, locale/market, audience, angle, version/status, engine identity,
  guard results, hashes, cannibalization) cannot enter (smuggling is
  schema-rejected, tested); no article body/prose/final headline
- context-aware domain validation (VALIDATION_FAILED, zero brief rows):
  unknown/outside-projection/retracted evidence ids, factual or
  source-assertion claims without evidence, disputed-only factual claims
  without handling, duplicate claim keys/evidence, duplicate section keys
  ACROSS required+optional (stricter composition-only rule, reported),
  duplicate criterion keys, mandatory-criterion override, and fake-UGC
  framing (reusing the existing Task-7 pattern policy — no second
  incompatible guard)
- deterministic merges the model can never delete: idea exclusions
  (Task-11 path) + pack licensing/reference-only cautions as mandatory
  exclusions; mandatory uncertainty notes from pack staleness, locale
  limitations, intent missing signals (UNKNOWN != ZERO), the
  published-inventory/cannibalization limitation, and contradiction
  records; 7 mandatory policy acceptance criteria (sections/claims/
  uncertainty/exclusions/no-fake-UGC/no-invented-signals/
  no-single-source-copy) merged ahead of model additions;
  practical_requirements derived from the pinned idea's validated
  planning dimensions (never model-invented)
- materialization ONLY through Task-11 `BriefService` (one canonical
  path): minimal refactor split `_create_draft(..., composition_attempt)`
  behind an UNCHANGED manual `create_draft` (still
  manual-brief-input/1 + NULL attempt; the brief-composer identity is
  refused on the manual path) and a narrow `create_composed_draft` that
  validates the attempt (SUCCEEDED + BRIEF_COMPOSITION + input_refs
  matching the exact work-item/idea/pack/intent identity — FK never
  trusted) before persisting engine `brief-composer/1` +
  composition_attempt_id; version allocation, supersession (explicit
  reason; ACCEPTED never bypassed), content hash, and the SAME structure
  guard all stay in Task 11 — a model-mirrored source outline yields a
  SUCCEEDED attempt whose DRAFT persists with guard outcome `failed`
  (inspectable; no auto-retry, no auto-accept; work item stays BRIEFING)
- idempotency/economy: pre-provider short-circuit returns the existing
  automated brief identity with ZERO provider invocations (retry_number
  can never regenerate a materialized same-identity brief); exact reused
  SUCCEEDED attempt returns its materialized brief without re-invocation;
  a reused attempt with no brief is a typed
  IncompleteBriefMaterializationError (recover with retry_number+1 —
  tested); a Task-11 persistence rejection of valid AI output is a typed
  BriefCompositionMaterializationError while the attempt keeps its REAL
  SUCCEEDED status (never retroactively relabeled, tested); failed
  attempts (validation/provider/timeout/cancelled) persist durably with
  zero brief/claim rows; concurrency: provider may be double-called
  (Task-8 truth) but two concurrent first-time compositions converged to
  ONE attempt + ONE brief + one claim map on real PG
- composition NEVER accepts a brief, never transitions BRIEFING ->
  DRAFTING, never mutates opportunity/idea/pack/intent/research rows;
  acceptance remains the explicit operator command
- real ephemeral pgvector PostgreSQL verification passed (fake provider):
  schema stays `0017`; concurrent single-brief convergence, short-circuit
  reuse with zero invocations, guard recorded, work item still BRIEFING
  (no transition), exact durable state (1 attempt, 1 brief, 2 claims, 0
  status events, disposition untouched); teardown complete
- Task 12 added NO migration, no Celery
  (contentos.editorial.compose_content_brief stays unregistered), no
  API/admin, no Writer/article fields, no publication approval, no
  production access, no OpenAI adapter changes, and no dependency changes
- Task 12 verified: 1016 backend tests (993 + 23 new), 96 admin tests,
  and the full root quality gate passed; schema head `0017`

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
raw_payload_blobs tables complete; Phase 3 editorial_work_items, append-only
editorial_workflow_events, editorial_opportunities, append-only
opportunity_research_inputs, append-only opportunity_scores +
opportunity_score_components, append-only search_signals, append-only
evidence_packs + evidence_pack_items + resolution-guarded
evidence_contradictions (now with the nullable idea and
organization-attempt links), append-only ideas + idea_selection_events
(with staged nullable AI generation-attempt provenance), the generic
append-only ai_generation_attempts table, append-only
search_intent_analyses, and the guarded content_briefs + append-only
brief_claims + brief_claim_evidence + brief_status_events tables complete;
schema head `0017`

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

AI integration: provider-neutral boundary complete; the OpenAI adapter
(official SDK, Responses API, strict Structured Outputs, ADR 0009) and the
model-assisted idea generation engine exist; automated gates never call
OpenAI (deterministic fake provider) and no live model call has been made
by any verification

Publishing integration: not started

Pinterest integration: not started

Analytics integration: not started

## Important current constraint

Phase 2 implementation is authorized only one atomic task at a time.

No AI pack organization, Celery orchestration/Beat scheduling,
Writer/Editor/QA, publication approval, or pre-commit configuration
exists yet. Model-assisted idea generation, SearchIntentAnalysis
(deterministic + optional INTENT_SYNTHESIS), ContentBrief persistence +
claim map + acceptance gate, and the Brief Composition Engine
(deterministic assembly + model-assisted wording via BRIEF_COMPOSITION)
all exist as synchronous domain engines; no commissioning command exists
yet, and acceptance remains an explicit operator command. Automated tests
and gates never call a real AI provider. The admin exposes exactly the minimal
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

PHASE 3 TASK 13 (awaiting explicit authorization) — Celery orchestration,
per the accepted design's implementation order item 12: the §18 editorial
jobs (`contentos.editorial.promote_research`, `evaluate_opportunity`,
`generate_idea_candidates`, `build_evidence_pack` with its READY ->
SYSTEM SEO_RESEARCH transition and not-READY -> BLOCKED,
`analyze_search_intent` with SYSTEM -> BRIEFING,
`compose_content_brief`) under the Task-16 contracts (PostgreSQL
authoritative, commit-before-enqueue, at-least-once absorbed by the
§10.3 identities, UUID-only payloads, DOMAIN vs DISPATCH retry
separation, bounded backoff); explicit WorkflowService transitions only
after durable results; commissioning and brief acceptance remain human
commands. This is also where the commissioning operator command likely
lands per design §18.

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
