# Konsepthane ContentOS - Current State

Last updated: 2026-08-31

## Current phase

PHASE 2 - Research/Discovery foundation - STARTED (Task 1 complete)

Phase 1 foundation is complete and verified (first real CI run passed, both
local quality gates pass, fresh-clone bootstrap verified).

Phase 2 Task 1 delivered the research/discovery domain design only:
`docs/PHASE2_RESEARCH_DISCOVERY.md` plus ADRs 0005-0007. No Phase 2 runtime
code, models, migrations, endpoints, tasks, or dependencies exist yet.

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

Database: engine/session foundation and Alembic + pgvector migration infrastructure complete; no application models or tables yet

Queue/workers: Redis/Celery foundation and worker entrypoint complete; no domain tasks or Beat scheduling yet

Crawler: not started

AI integration: not started

Publishing integration: not started

Pinterest integration: not started

Analytics integration: not started

## Important current constraint

Phase 1 implementation is authorized only one task at a time.

No application tables, domain/queue tasks, Celery Beat, admin business screens,
pre-commit configuration, or editorial business logic exists yet. Backend tests use
mocks and offline Alembic rendering; none require a running PostgreSQL or Redis.
Docker Compose covers local development only; production deployment does not exist.
The admin app has no login, authentication, users, roles, or RBAC by design.

ContentOS is a private single-operator control panel. Application-level users,
authentication, authorization, roles, and RBAC are outside the Phase 1 design;
access protection belongs to future deployment infrastructure.

## Next immediate task

Phase 2 Task 2 (awaiting explicit authorization): implement the Source
Registry persistence foundation only — `Source` model + kind/lifecycle/trust
enums in a new `contentos/sources` package, Alembic migration
`0002_create_sources`, uniqueness on `slug` and (`kind`, `base_url`), a
repository/service with idempotent registration and audited lifecycle
transitions, unit tests plus ephemeral-Postgres migration verification. No
API endpoints, admin UI, Celery, or discovery logic in Task 2.

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
