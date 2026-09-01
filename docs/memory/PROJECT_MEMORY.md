# Konsepthane ContentOS - Project Memory

## Project identity

Project name: Konsepthane ContentOS

Internal codename: Konsept-OS

Public platform:
https://konsepthane.net

ContentOS is a separate internal editorial automation system for Konsepthane.

It is NOT the public website and must not be implemented inside the public
Konsepthane application.

## Main purpose

ContentOS will automate and assist the editorial lifecycle:

Discovery
→ Research
→ Duplicate Detection
→ Idea Generation
→ Evidence Collection
→ SEO / Search Intent Research
→ Content Brief
→ Writing
→ Editing
→ QA
→ Human Approval
→ Scheduling
→ Publishing
→ Pinterest Distribution
→ Performance Analysis
→ Content Refresh Suggestions

## Core editorial principle

RESEARCH, DO NOT TRANSLATE-AND-REPUBLISH.

The system must create original Konsepthane content by synthesizing research
from multiple sources.

It must never:

- translate and republish competitor articles
- paraphrase a single competitor article
- copy competitor heading structures
- fabricate statistics
- fabricate user experiences
- fabricate reviews
- fabricate quotes
- fabricate sources
- publish copyrighted images without usage rights
- present Pinterest or Instagram images as automatically reusable assets

## System boundary

ContentOS must remain isolated from the public Konsepthane production system.

ContentOS must NOT directly:

- access Konsepthane production PostgreSQL
- modify production tables
- share migrations with Konsepthane
- mount the production filesystem

Publishing must eventually happen through a versioned and authenticated
Konsepthane Publishing API.

The public website must continue operating even if ContentOS is unavailable.

## Initial market

Primary market: Türkiye

Primary language: Turkish

The architecture may support additional locales later, but initial development
and editorial strategy must remain Turkey-first.

## Initial automation policy

Auto-publishing is disabled at launch.

Initial content requires human review and approval.

Auto-publishing may only be introduced later after real editorial review data
has been collected and quality thresholds have been calibrated.

Even after controlled auto-publishing exists, a configurable percentage of
otherwise eligible content must still be routed to random human review.

## Media policy

Every media asset must have provenance.

Possible states include:

- FIRST_PARTY
- LICENSED_USABLE
- PUBLIC_DOMAIN
- AI_GENERATED
- REFERENCE_ONLY
- UNKNOWN_LICENSE

UNKNOWN_LICENSE media must never auto-publish.

Pinterest, Instagram and competitor-site images are reference material unless
explicit usage rights are verified.

## Memory architecture

This project uses two complementary memory layers.

1. Codebase Memory MCP
   - architecture
   - symbols
   - dependencies
   - call graphs
   - routes
   - code impact

2. Repository documentation
   - product knowledge
   - architecture decisions
   - editorial policies
   - current project state
   - durable engineering decisions

Important decisions must not exist only inside chat history.

## Codebase Memory

codebase-memory-mcp is installed locally.

Expected usage:

- query Codebase Memory before broad repository scans
- use architecture/symbol queries to locate relevant code
- avoid repeatedly reading the entire repository
- keep the graph synchronized as development progresses

## Durable phase and scope decisions

- Phase 2 (Research/Discovery foundation) completed 2026-09-01; the formal
  closure decision record is docs/PHASE2_CLOSURE_AUDIT.md.
- ADR 0008 (Accepted): the vector-similarity duplicate signal — originally
  promised as Phase 2 implementation-order item 11 — is DEFERRED, not
  abandoned. The deterministic URL/hash/title/lexical duplicate engine is
  authoritative for now; re-entry is trigger-based (corpus scale, observed
  duplicate misses, Phase 3 overlap evidence, performance, multilingual
  expansion, provider selection) and any future implementation must follow
  the provider-neutral constraints frozen in ADR 0008.
- Phase 2 completion is not production readiness; the production backlog is
  tracked in the closure audit (§7).
- Phase 3 accepted design (docs/PHASE3_EDITORIAL_INTELLIGENCE.md,
  2026-09-01): the canonical WORKFLOW.md state machine becomes the durable
  `EditorialWorkItem` aggregate (promotion from Phase 2, never replayed
  synthetic history); Phase 3 ends at a versioned ContentBrief whose claim
  map pins ResearchEvidence — the future Writer receives only an accepted
  brief/evidence contract. AI is provider-neutral with one generic
  append-only attempt-provenance record; AI proposes artifacts and can
  never create source provenance. UNKNOWN != ZERO for scoring signals;
  cannibalization is truthfully NOT_CHECKED until a governed Konsepthane
  inventory read contract exists.

## Engineering principle

Quality > Quantity

Research > Content spinning

Evidence > Hallucination

Provenance > Untraceable media

Controlled automation > Blind auto-publishing

Auditability > Hidden behavior

Reliability > Demo-only code

Human governance > Unrestricted autonomous publishing
