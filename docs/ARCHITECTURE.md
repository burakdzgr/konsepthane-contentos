# Konsepthane ContentOS - Architecture Baseline

Status: Phase 0 documentation baseline (target architecture). Phases 1-2
are implemented and closed (see docs/PHASE2_CLOSURE_AUDIT.md); Phase 3 is
designed in docs/PHASE3_EDITORIAL_INTELLIGENCE.md. The module table below
remains the long-term target; per-phase documents record what actually
exists.

## System context

ContentOS is an internal editorial system with its own runtime and PostgreSQL
database. It receives signals from governed external sources, coordinates
human and automated editorial work, and sends approved publication requests to
Konsepthane through a versioned authenticated API.

```text
Governed sources --> ContentOS --> Konsepthane Publishing API --> Konsepthane.net
                         |                         |
                         +--> Pinterest            +--> publication result
                         +<-- analytics providers / Konsepthane analytics
```

The public site must remain available when ContentOS is unavailable. ContentOS
has no direct production database, migration, or filesystem access.

## Technical baseline

| Area | Direction |
| --- | --- |
| API/backend | Python 3.12+, FastAPI, Pydantic v2 |
| Persistence | PostgreSQL, pgvector, SQLAlchemy, Alembic |
| Work execution | Celery workers with Redis as queue/broker |
| Control panel | Next.js, TypeScript |
| AI | Provider abstraction; OpenAI adapter first |
| Packaging/runtime | Docker and Docker Compose |

The initial implementation should be a modular system with explicit module
boundaries, not independently deployed microservices. API processes, workers,
scheduler, and control panel may run as separate containers while sharing one
ContentOS domain model and one ContentOS-owned database.

## Major bounded modules

| # | Module | Responsibility and boundary |
| --- | --- | --- |
| 1 | Source Registry | Stores source identity, type, jurisdiction, permissions, crawl rules, trust notes, rate limits, and enabled state. It is the admission gate for discovery and crawling. |
| 2 | Discovery Engine | Collects candidate URLs, topics, trends, and signals from enabled sources. It creates discovery records; it does not treat a signal as verified evidence. |
| 3 | Crawl Engine | Fetches permitted source material with source-specific limits, timestamps, response metadata, and failure records. It must honor robots, terms, access rules, and retry limits. |
| 4 | Normalization Engine | Converts heterogeneous observations into stable internal records while preserving the raw-source reference and capture time. It must not erase provenance. |
| 5 | Duplicate Detection | Detects exact, semantic, and topic-level overlap against discoveries, work in progress, and published inventory. It returns a decision with similarity evidence rather than deleting candidates. |
| 6 | Trend / Opportunity Engine | Scores viable ideas using recency, audience fit, evidence availability, competition, search demand, editorial value, risk, and estimated cost. Scoring inputs and model/version must be recorded. |
| 7 | Evidence Engine | Builds an evidence pack from multiple sources, links claims to sources, records contradictions and confidence, and blocks unsupported claims from downstream use. |
| 8 | Keyword / Search Intent Engine | Models Turkish queries, intent, entities, SERP observations, cannibalization risk, and target page purpose. It informs briefs; it does not dictate unsupported content. |
| 9 | Brief Engine | Produces the approved writing contract: audience, intent, angle, claim/evidence map, required sections, exclusions, internal-link targets, media needs, and acceptance criteria. |
| 10 | Writer Engine | Creates a draft from the brief and eligible evidence through the AI provider interface or human input. It cannot publish, invent evidence, or bypass policy gates. |
| 11 | Editor Engine | Revises structure, clarity, tone, usefulness, and adherence to the brief while preserving claim provenance and recording substantive changes. |
| 12 | QA Engine | Runs deterministic and model-assisted checks for evidence coverage, factual consistency, originality risk, links, SEO requirements, media eligibility, and publication readiness. It reports; it does not grant final approval. |
| 13 | Visual Research | Identifies visual concepts and reference material needed to explain or promote content. Reference discovery does not confer usage rights. |
| 14 | Media Provenance | Tracks creator/source, license, proof, permitted uses, transformations, expiry, and policy status for every asset. It blocks `UNKNOWN_LICENSE` assets from automatic publication. |
| 15 | Publishing Engine | Validates an approved immutable publication package, calls the versioned Konsepthane Publishing API with idempotency and correlation identifiers, and records the response. It never writes to the production database. |
| 16 | Scheduler | Selects approved items at configured times, enforces calendar and dependency rules, and submits publication/distribution jobs. Scheduling is not approval. |
| 17 | Pinterest Distribution | Creates Pinterest-ready variants only for published, policy-eligible content and media, then records remote identifiers and failures. Other social channels are outside the initial baseline. |
| 18 | Analytics Feedback | Ingests normalized performance signals and attaches them to published content, opportunities, and refresh candidates without rewriting historical decisions. |
| 19 | Cost/Budget Controls | Estimates and records AI, crawl, media, and distribution usage; enforces per-job and period limits; and blocks or escalates work when limits are reached. |
| 20 | Audit/Governance | Maintains append-oriented events for state changes, evidence versions, approvals, policy decisions, provider/model use, costs, external calls, and actor identity. |
| 21 | Admin Control Panel | Provides authenticated views and commands for sources, pipeline queues, evidence, drafts, QA, approvals, scheduling, budgets, failures, and audit history. It invokes backend APIs and contains no independent publishing path. |

## Core records and lineage

The detailed schema is deferred, but implementation must preserve lineage among:

- source and source policy;
- captured observation and normalized discovery;
- duplicate decision and opportunity score;
- evidence pack, individual claim, citation, contradiction, and confidence;
- search intent analysis and content brief;
- draft/editorial version, QA report, and human approval;
- media asset and provenance decision;
- schedule, publication package, API attempt/result, and distribution result;
- analytics observation, cost entry, and audit event.

Records used for approval or publishing must be versioned. An approval must point
to the exact content, evidence, and media versions reviewed.

## Integration boundaries

### Konsepthane Publishing API

- Versioned contract and authenticated service identity.
- TLS, least-privilege authorization, idempotency keys, and correlation IDs.
- Explicit validation and stable machine-readable error responses.
- Publication status/result returned or queryable without database access.
- Rights/provenance metadata included for every submitted media asset.
- Contract details and endpoint shapes must be agreed before implementation.

### AI providers

Domain modules depend on a provider-neutral interface for text generation,
embeddings, and any future media generation. Adapters translate provider
requests/responses and expose model, token/cost, latency, safety, and error
metadata. Provider-specific objects must not leak into domain records. The
initial adapter targets OpenAI; adding or replacing a provider must not require
rewriting editorial modules.

### External sources, Pinterest, and analytics

Every connector is governed by explicit credentials, permissions, rate limits,
retry policy, and normalized result contracts. A connector failure must be
isolated and visible; it must not silently advance workflow state.

## Work execution and consistency

- Long-running crawl, AI, QA, publish, distribution, and analytics work runs as
  idempotent Celery jobs.
- Redis transports work; PostgreSQL stores durable workflow state and results.
- Retries use bounded backoff and must not duplicate publications or charges
  where an idempotency mechanism is available.
- State transitions occur through application services with precondition checks
  and audit events, not direct control-panel database writes.
- Failed or exhausted jobs move to an operator-visible blocked state.

## Security and governance

- Separate ContentOS and Konsepthane credentials, databases, migrations, and deployments.
- Secrets remain outside source control and are scoped per connector/environment.
- Role-based access must distinguish viewing, editing, approval, scheduling,
  publishing operations, source administration, and budget administration.
- Auto-publishing is disabled initially; human approval is a server-side gate.
- Unknown-license media and unsupported factual claims are hard publication blockers.
- Important boundary, technology, and governance changes require ADRs.

## Deferred implementation decisions

Phase 0 does not decide detailed database tables, endpoint URLs, deployment
topology beyond Docker Compose, authentication product/protocol, crawler vendor,
analytics providers, scoring formulas, budget values, or model selection. Those
choices require implementation context and, where architectural, follow-up ADRs.
