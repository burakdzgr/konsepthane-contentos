# Konsepthane ContentOS - Current State

Last updated: 2026-09-01

## Current phase

PHASE 2 - Research/Discovery foundation - IN PROGRESS (Tasks 1-9 complete)

Phase 1 foundation is complete and verified (first real CI run passed, both
local quality gates pass, fresh-clone bootstrap verified).

Tasks 1-9 delivered the research/discovery design, Source Registry, shared URL
canonicalization, DiscoveryItem admission, the safe FetchClient boundary,
defensive RSS/Atom plus sitemap discovery, and immutable FetchSnapshot
persistence. The immutable NormalizedDocument persistence boundary now exists;
payload retrieval, extraction, duplicate decisions, and Phase 2 orchestration do not.

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
immutable FetchSnapshot, and immutable NormalizedDocument tables complete;
schema head `0005`

Queue/workers: Redis/Celery foundation and worker entrypoint complete; no domain tasks or Beat scheduling yet

Research discovery: Source Registry, manual/feed/sitemap admission, safe FetchClient,
bounded sitemap-index traversal, immutable FetchSnapshot persistence, and the
NormalizedDocument persistence contract complete; payload retrieval and extraction not started

AI integration: not started

Publishing integration: not started

Pinterest integration: not started

Analytics integration: not started

## Important current constraint

Phase 2 implementation is authorized only one atomic task at a time.

No extraction pipeline, raw-payload reader/backend, duplicate or research-evidence
persistence, domain/queue tasks, Celery Beat, admin business screens, pre-commit
configuration, or editorial business logic exists yet. Backend
unit tests remain offline and require no running PostgreSQL or Redis. Docker Compose
covers local development only; production deployment does not exist. The admin app
has no login, authentication, users, roles, or RBAC by design.

ContentOS is a private single-operator control panel. Application-level users,
authentication, authorization, roles, and RBAC are outside the Phase 1 design;
access protection belongs to future deployment infrastructure.

## Next immediate task

Phase 2 Task 10 (awaiting explicit authorization): define the provider-neutral,
immutable **raw-payload store/reader contract** only. Specify opaque reference,
bounded byte streaming, expected SHA-256/size verification, typed not-found/integrity/
transport errors, and test-double conformance. Do not choose R2/S3/filesystem/BYTEA,
wire FetchClient, or implement extraction in that task; the contract must precede a
production adapter and executable normalization pipeline.

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
