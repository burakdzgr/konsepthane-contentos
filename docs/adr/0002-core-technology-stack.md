# ADR 0002: Core Technology Stack

Status: Accepted
Date: 2026-08-31

## Context

ContentOS needs typed APIs, long-running editorial jobs, relational workflow and
audit data, semantic retrieval, a browser-based control panel, AI-provider
flexibility, and reproducible local/runtime packaging. Phase 0 must establish a
coherent baseline without prematurely defining implementation details.

## Decision

Use:

- Python 3.12+, FastAPI, and Pydantic v2 for backend APIs and application services;
- SQLAlchemy and Alembic for ContentOS-owned persistence and migrations;
- PostgreSQL with pgvector for relational data and vector similarity;
- Redis and Celery for queued/background work;
- Next.js and TypeScript for the internal control panel;
- a ContentOS-owned AI provider abstraction with an OpenAI adapter first;
- Docker and Docker Compose for packaging and initial environment orchestration.

Begin as a modular system with explicit bounded modules. API, worker, scheduler,
database, queue, and control panel may be separate containers; the domain is not
split into microservices without evidence that independent deployment is needed.

## Consequences

- Backend and worker code can share validation, domain, and persistence contracts.
- PostgreSQL supports durable workflow/audit data while pgvector supports semantic use cases.
- Celery tasks must be idempotent and PostgreSQL, not Redis, remains the durable state store.
- Provider-specific AI fields must be translated at adapter boundaries.
- The team must operate both Python and TypeScript toolchains.
- Production topology, hosting, authentication product, and observability stack remain deferred.

## Alternatives Considered

- TypeScript/Node.js for all services: viable, but Python was selected for the
  initial research, NLP, and AI workflow ecosystem.
- Django as the backend framework: viable, but FastAPI plus an explicit control
  panel/API boundary better fits the selected modular API direction.
- Separate database/vector service: deferred; PostgreSQL plus pgvector reduces
  initial operational complexity.
- Microservices from the start: rejected because current scale and boundaries do
  not justify distributed ownership and operational cost.
