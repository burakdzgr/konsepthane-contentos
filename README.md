# Konsepthane ContentOS

ContentOS is Konsepthane's internal idea-intelligence and editorial automation
platform. It discovers useful ideas and inspiration signals, evaluates them
against operator strategy, and carries approved opportunities through the
existing evidence, brief, Writer, Editor, QA, media and publishing workflow. It is a
**separate system** from the public Konsepthane website and will communicate
with it only through the versioned, authenticated Publishing API boundary
(ADR 0003). The admin is an authenticated, Turkish-first operator control panel.

The product distinction and current strategy/inspiration model are documented
in [docs/IDEA_INTELLIGENCE.md](docs/IDEA_INTELLIGENCE.md).

## Phase 1 architecture

The backend is a modular monolith in `apps/backend`; the admin panel lives in
`apps/admin`. Implemented foundation:

- **FastAPI** backend: app factory, typed `CONTENTOS_`-prefixed settings,
  structured logging with request-ID correlation, stable JSON error envelope,
  `/health/live` and `/health/ready`
- **PostgreSQL + pgvector** via SQLAlchemy 2 (sync) + Psycopg 3
- **Alembic** migrations (URL comes from settings, never from `alembic.ini`)
- **Redis + Celery** queue foundation and worker entrypoint (JSON-only, UTC,
  no domain tasks yet)
- **Next.js 15 admin** (App Router, strict TypeScript): server-side backend
  client and a truthful Foundation Status page
- **Docker Compose** local stack: postgres, redis, one-shot migrate, api,
  worker, admin
- **GitHub Actions CI** mirroring the local quality gate
- **Codebase Memory MCP** knowledge graph for structural code queries

Editorial features (discovery, ideas, drafts, review, scheduling, Pinterest,
analytics) are **not implemented yet** — they are Phase 2+.

## Required local tools

| Tool       | Version                        |
| ---------- | ------------------------------ |
| Python     | 3.12                           |
| uv         | 0.12.7                         |
| Node.js    | 24.x (`.node-version`)         |
| Corepack   | bundled with Node 24           |
| pnpm       | 11.15.1 (via Corepack pin)     |
| Docker     | Desktop/Engine with Compose v2 |
| PowerShell | 7 (or Windows PowerShell 5.1)  |

## Bootstrap

```powershell
.\scripts\bootstrap.ps1
```

Idempotent and non-destructive: verifies docker/uv/node/corepack, creates
`.env` from `.env.example` if missing (never overwrites), runs
`uv sync --all-groups` for the backend, `corepack pnpm install
--frozen-lockfile` for the workspace, and `docker compose build`.

## Run the local stack

```powershell
docker compose up -d
```

Startup order is enforced by health/dependency conditions: postgres + redis
healthy → `migrate` runs `alembic upgrade head` and exits → api + worker +
admin start.

Local endpoints (all bound to 127.0.0.1 only):

- Admin: <http://127.0.0.1:3000> (health: `/api/health`)
- API: <http://127.0.0.1:8000> (`/health/live`, `/health/ready`)
- PostgreSQL: `127.0.0.1:55432`, Redis: `127.0.0.1:56379` (dev tooling only)

The admin talks to the API **server-side** (inside Compose via
`http://api:8000`); the browser never receives the internal API URL.

Stop with `docker compose down` (add `-v` to also drop the database volume).

## Quality gates

```powershell
.\scripts\check.ps1            # toolchain + backend + admin + repository checks
.\scripts\check.ps1 -Compose   # additionally: build + start stack, smoke, teardown
```

The default gate runs frozen dependency syncs, Ruff (format + lint), mypy,
pytest, Prettier check, ESLint, tsc, Vitest, `next build`, `git diff --check`,
and fails if validation unexpectedly modified tracked files. `-Compose` also
validates/builds/starts the full stack, runs the smoke checks, and always
tears down only this project's Compose resources.

## Smoke testing

```powershell
.\scripts\smoke.ps1
```

Checks a **running** stack: backend live/ready, admin health, admin root page,
that the page truthfully reflects backend readiness, and that no internal API
URL leaks into HTML. It is invoked automatically by `check.ps1 -Compose` and by
CI; run it manually only against an already started stack.

## Database migrations

From `apps/backend` (with `CONTENTOS_DATABASE_URL` pointing at a ContentOS
database):

```powershell
uv run alembic upgrade head
uv run alembic heads
```

Migration `0001` enables the pgvector extension. Its downgrade intentionally
does **not** drop the extension, because future vector data may depend on it.

## Backend development

From `apps/backend`:

```powershell
uv sync --all-groups
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run uvicorn contentos.api.app:create_app --factory --reload --port 8000
uv run python -m contentos.worker.main worker --loglevel=INFO
```

## Admin development

From the repository root:

```powershell
corepack pnpm install --frozen-lockfile
corepack pnpm --filter admin dev
corepack pnpm --filter admin lint
corepack pnpm --filter admin typecheck
corepack pnpm --filter admin test
corepack pnpm --filter admin format:check
corepack pnpm --filter admin build
```

## CI

`.github/workflows/ci.yml` runs on push to `main`, pull requests targeting
`main`, and manual `workflow_dispatch`. Four jobs:

1. **Backend quality** — frozen uv sync, Ruff, mypy, pytest
2. **Admin quality** — frozen pnpm install, Prettier, ESLint, tsc, Vitest, build
3. **Migration/infrastructure integration** — Alembic upgrade plus pgvector,
   Redis, and API readiness verification against real service containers
4. **Compose smoke** — builds and starts the actual Compose stack, runs
   `scripts/smoke.ps1` via `pwsh`, always tears down

The first real GitHub runner execution of this workflow passed successfully.

## Security and boundaries

- Never store production credentials in this repository. `.env` is local-only
  and gitignored; `.env.example` holds safe development defaults.
- ContentOS must never access the Konsepthane production database or
  filesystem directly; publishing will go through a versioned authenticated
  API (ADR 0003).
- The admin panel has no app-level login by design; it must be protected at
  the infrastructure boundary when deployed (ADR 0001/0004 context).

## Repository memory protocol

Read `AGENTS.md`, then `docs/memory/CURRENT_STATE.md` (current status) and
`docs/memory/PROJECT_MEMORY.md` before working. Use the Codebase Memory MCP
graph before broad repository scans, and update the memory docs whenever the
implemented architecture changes. Details: `AGENTS.md`.
