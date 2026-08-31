# ADR 0007: Research Evidence Carries Non-Bypassable Provenance

Status: Accepted
Date: 2026-08-31

## Context

The core editorial rule is "research, do not translate-and-republish".
Future Writer/Editor/QA stages will consume research output. If evidence could
exist as free-floating text, downstream stages could silently use unsourced or
single-source material, fabricate support, or strip attribution — exactly the
failure modes editorial policy prohibits.

## Decision

The smallest research unit (ResearchEvidence) must reference, with NOT NULL
foreign keys, the exact NormalizedDocument, FetchSnapshot, and Source it came
from, plus bounded excerpt offsets into the normalized text. Provenance fields
are immutable after creation; only `verification_status`
(`UNVERIFIED`/`VERIFIED`/`DISPUTED`/`RETRACTED`) may change, with audit.
Evidence is served to any consumer only through the evidence service, which
always returns provenance with the statement — no text-only accessor exists.
Whole-article evidence units are prohibited by excerpt bounds. AI output can
never be a provenance root: every evidence unit terminates in a fetched
snapshot. Licensing cautions and source trust tier travel with each unit so
later publication gates can always see them.

## Consequences

- A future Evidence Pack can be assembled by reference, without re-deriving
  or re-trusting provenance.
- Copyright review is possible per excerpt, with exact boundaries.
- Machine and human extractions are distinguishable and re-checkable against
  the immutable snapshot (ADR 0006).
- Downstream features must be designed against the evidence service contract;
  bypassing it is an architecture violation, not a configuration choice.

## Alternatives Considered

- Evidence as free text with an optional source URL: rejected; a URL alone is
  not evidence and permits provenance loss.
- Provenance on the future Evidence Pack only: rejected; pack-level provenance
  cannot prove which snapshot supported which individual claim.
- Mutable evidence rows: rejected; silent rewording after verification would
  invalidate review guarantees.
