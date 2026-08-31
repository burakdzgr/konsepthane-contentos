# Konsepthane ContentOS

## Purpose

Konsepthane ContentOS is a separate internal editorial operating system for
Konsepthane.net. It helps the editorial team discover opportunities, assemble
evidence, produce original Turkish content, control quality, publish approved
work, distribute it to Pinterest, and learn from performance.

The public Konsepthane application remains the system of record for published
content. ContentOS is an internal upstream system, not a replacement for the
public site or its CMS/runtime.

## Primary users

- Editors and reviewers who approve or reject content and media.
- Researchers and writers who work from evidence-backed briefs.
- Operators who manage sources, schedules, budgets, integrations, and failures.
- Administrators who audit decisions, access, costs, and publishing activity.

## Editorial pipeline

Discovery
→ Research
→ Normalize
→ Duplicate Detection
→ Idea Scoring
→ Evidence Pack
→ SEO / Search Intent
→ Content Brief
→ Writer
→ Editor
→ QA
→ Human Review
→ Schedule
→ Konsepthane Publishing API
→ Pinterest Distribution
→ Analytics Feedback

Each stage must produce a traceable artifact or decision. A later stage must not
silently overwrite the evidence, policy result, or approval that allowed the
item to advance.

## Phase 0 scope

Phase 0 establishes product boundaries, architecture, editorial governance,
workflow states, shared terminology, and initial architecture decisions. It
does not include application code, infrastructure, dependencies, credentials,
or live integrations.

## Intended system capabilities

- Register and govern discovery/research sources.
- Crawl permitted sources and normalize observations into a stable internal form.
- Detect duplicates and overlapping coverage before commissioning content.
- Score opportunities using editorial value, relevance, evidence quality,
  search intent, trend signals, cost, and risk.
- Create evidence packs, SEO analysis, briefs, drafts, editorial revisions, and
  QA reports with lineage.
- Require human approval before launch-time publishing.
- Schedule and publish through a versioned authenticated Konsepthane API.
- Distribute eligible published content to Pinterest.
- Feed performance signals back into opportunity and refresh decisions.
- Enforce media provenance, budget limits, and an auditable decision history.

## System boundaries

ContentOS must not:

- directly access Konsepthane production PostgreSQL;
- modify or share Konsepthane production migrations;
- mount the Konsepthane production filesystem;
- make the public site depend on ContentOS availability;
- publish unknown-license media automatically;
- treat Pinterest, Instagram, or competitor images as reusable without verified rights;
- translate or paraphrase one source as a substitute for original research;
- fabricate facts, sources, quotations, reviews, or user experiences.

Publishing crosses the system boundary only through a versioned, authenticated
Publishing API owned by Konsepthane. ContentOS keeps its own data store,
migrations, workers, audit records, and release lifecycle.

## Initial technical direction

- Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy, Alembic.
- Database: PostgreSQL with pgvector.
- Queue and workers: Redis and Celery.
- Control panel: Next.js and TypeScript.
- AI: provider-neutral application interface with an initial OpenAI adapter.
- Infrastructure: Docker and Docker Compose.

These are accepted baseline choices, not evidence that an implementation exists.
The detailed boundaries are defined in `ARCHITECTURE.md` and the accepted ADRs.

## Launch governance

Auto-publishing is disabled at launch. Every publishable content version requires
explicit human approval. Approval applies to a specific content and media
version; substantive changes invalidate that approval. Important architectural
or governance changes must be recorded in an ADR.
