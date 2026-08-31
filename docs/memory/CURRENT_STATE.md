# Konsepthane ContentOS - Current State

Last updated: 2026-09-01

## Current phase

PHASE 2 - Research/Discovery foundation - IN PROGRESS (Tasks 1-14 complete)

Phase 1 foundation is complete and verified (first real CI run passed, both
local quality gates pass, fresh-clone bootstrap verified).

Tasks 1-12 delivered the research/discovery design, Source Registry, shared URL
canonicalization, DiscoveryItem admission, the safe FetchClient boundary,
defensive RSS/Atom plus sitemap discovery, and immutable FetchSnapshot
persistence. The immutable NormalizedDocument persistence boundary now exists;
the provider-neutral raw-payload contract supports bounded verified reads, and
the first executable HTML/text normalization pipeline and deterministic local
duplicate-decision boundary are complete. No production payload backend or
domain orchestration exists.

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

## Current documentation structure

- AGENTS.md
- docs/PROJECT.md
- docs/ARCHITECTURE.md
- docs/WORKFLOW.md
- docs/EDITORIAL_POLICY.md
- docs/PHASE2_RESEARCH_DISCOVERY.md
- docs/memory/PROJECT_MEMORY.md
- docs/memory/CURRENT_STATE.md
- docs/memory/GLOSSARY.md
- docs/adr/README.md (ADRs 0001-0007)

## Current implementation status

Repository foundation: complete

Backend: application factory, typed settings, structured logging, request context, API error contract, database engine/session foundation, and liveness/readiness endpoints complete

Frontend/control panel: Next.js foundation with server-side backend client, truthful Foundation Status page, and Docker/Compose integration; no business screens yet

Database: engine/session, Alembic + pgvector, Source Registry, DiscoveryItem,
immutable FetchSnapshot, immutable NormalizedDocument, immutable
DuplicateDecision, and immutable ResearchEvidence tables complete; schema head `0007`

Queue/workers: Redis/Celery foundation and worker entrypoint complete; no domain tasks or Beat scheduling yet

Research discovery: Source Registry, manual/feed/sitemap admission, safe FetchClient,
bounded sitemap-index traversal, immutable FetchSnapshot persistence, and the
NormalizedDocument persistence, provider-neutral raw-payload contracts, and executable
bounded HTML/text normalization plus deterministic local duplicate decisions complete;
the immutable ResearchEvidence primitive with exact excerpt provenance and the
deterministic v1 evidence extractor (author/date metadata evidence) are complete;
no production payload adapter or production inventory comparison exists

AI integration: not started

Publishing integration: not started

Pinterest integration: not started

Analytics integration: not started

## Important current constraint

Phase 2 implementation is authorized only one atomic task at a time.

No production raw-payload backend, Evidence Pack, domain/queue tasks, Celery Beat,
admin business screens, pre-commit configuration, or editorial business logic
exists yet. Backend
unit tests remain offline and require no running PostgreSQL or Redis. Docker Compose
covers local development only; production deployment does not exist. The admin app
has no login, authentication, users, roles, or RBAC by design.

ContentOS is a private single-operator control panel. Application-level users,
authentication, authorization, roles, and RBAC are outside the Phase 1 design;
access protection belongs to future deployment infrastructure.

## Next immediate task

Phase 2 Task 15 (awaiting explicit authorization): Celery orchestration of the
research pipeline per the design's job plan (PHASE2_RESEARCH_DISCOVERY.md
section 13) — idempotent domain jobs `discover_source`, `fetch_discovery_item`,
`normalize_fetch`, `evaluate_duplicate`, and `extract_research_evidence` on the
existing Celery foundation. PostgreSQL stays authoritative (queue completion
never advances domain state), database uniqueness absorbs at-least-once
delivery, retry classification follows the fetch boundary's retryable/terminal
contract, and each job schedules the next only after its database write
commits. No Beat scheduling, no new endpoints/UI, no AI, no Evidence Pack.
Rationale: every pipeline stage now has an executable producer, so orchestration
wires existing verified capabilities; the vector-similarity duplicate signal
(design order item 11) remains a later, independent task, and Evidence Pack is
explicitly outside Phase 2.

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
