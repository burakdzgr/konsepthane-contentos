# Konsepthane ContentOS - Glossary

## Product and systems

### ContentOS
The separate internal editorial operating system described by this repository.

### Konsepthane
The public Konsepthane.net product and its production systems. It remains the
system of record for published content.

### Publishing API
The versioned, authenticated Konsepthane-owned boundary through which ContentOS
submits approved publication packages and receives publication status/results.

### Admin Control Panel
The internal Next.js interface for authorized editorial and operational users.
It has no independent route to production publishing.

## Editorial artifacts

### Discovery
A captured topic, URL, trend, query, or other candidate signal. It is not yet a
verified fact or commissioned idea.

### Inspiration signal
A bounded idea/concept clue extracted from normalized source material. Multiple
signals may describe the same underlying concept and every signal keeps its
source/document provenance. It is not ResearchEvidence.

### İlham Değeri
An explainable editorial heuristic for novelty, usefulness, specificity,
visual potential, shareability, emotional impact, audience and market fit,
variation potential, and strategic fit. It is not a scientific measurement.

### Audience strategy
An operator-managed audience priority for a locale and market.

### Strategic keyword
An editorial/business compass used for discovery and planning. It is never a
Writer keyword-frequency instruction.

### Topic cluster
A simple operator-managed content family which related strategic keywords and
opportunities strengthen.

### Normalized record
A stable internal representation of source material that retains its source and
capture provenance.

### Duplicate decision
A recorded exact, semantic, or topic-overlap assessment with comparison evidence.

### Opportunity score
A versioned assessment of a candidate's editorial value, relevance, evidence,
search potential, competition, risk, and cost.

### Evidence pack
The versioned collection of claims, citations, excerpts/facts, contradictions,
confidence notes, and source metadata approved for briefing and drafting.

### Claim/evidence map
The explicit relationship between a proposed factual claim and the evidence that
supports, qualifies, or contradicts it.

### Search intent
The user need a query is expected to represent, such as learning, comparing,
finding inspiration, or completing an action.

### Content brief
The writing contract defining audience, intent, angle, evidence, required scope,
exclusions, media needs, internal links, and acceptance criteria.

### Publication package
The immutable, approved combination of content, metadata, evidence references,
media/provenance, target, and operational identifiers sent to the Publishing API.

### Refresh candidate
Published content proposed for reassessment because evidence, freshness, search
behavior, or performance changed. It is not automatically modified.

## Governance and policy

### Human approval
An authorized person's decision on exact content, evidence, QA, and media versions.

### Hard blocker
A failed or missing requirement that cannot be bypassed by scoring or automation,
such as unsupported factual claims or unknown-license publication media.

### Provenance
Traceable origin, ownership/creator, rights basis, transformations, and decision
history for evidence or media.

### `FIRST_PARTY`
Media created by or for Konsepthane with documented usable rights.

### `LICENSED_USABLE`
Media covered by a verified license permitting the intended use and conditions.

### `PUBLIC_DOMAIN`
Media verified as public domain for the intended jurisdiction/use.

### `AI_GENERATED`
Media created using an AI system with required generation provenance and review.

### `REFERENCE_ONLY`
Material usable for research or visual direction but not for publication.

### `UNKNOWN_LICENSE`
Media whose publication rights have not been verified; it cannot auto-publish.

### Fake UGC
Invented material presented as a real user's experience, review, comment, rating,
testimonial, quotation, or submission. It is prohibited.

### ADR (Architecture Decision Record)
A durable record of an important architectural or governance decision, its
context, consequences, and considered alternatives.

## Technical operation

### Provider abstraction
A ContentOS-owned interface that prevents editorial modules from depending on a
specific AI vendor's request/response types.

### Idempotency key
A stable operation identifier used to prevent retries from creating duplicate
external effects, especially duplicate publications.

### Correlation ID
An identifier connecting workflow, job, audit, provider, and external API events
for one logical operation.

### Workflow state
The durable editorial lifecycle state. It advances only through validated,
audited transitions, never merely because a worker process ended successfully.

### Audit event
An append-oriented record of who or what performed an action, when, why, against
which versions, and with what result.
