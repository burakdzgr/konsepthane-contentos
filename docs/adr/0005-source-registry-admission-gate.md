# ADR 0005: Source Registry Is the Sole Admission Gate for Research Intake

Status: Accepted
Date: 2026-08-31

## Context

Phase 2 introduces discovery, crawling, and research intake. Without a single
governed entry point, URLs could enter the pipeline from ad-hoc code paths,
making trust, rate limits, robots posture, terms notes, and market scope
unenforceable and unauditable. Editorial policy also requires that every piece
of research material remain attributable to a governed origin.

## Decision

Every discovery and fetch operation must happen on behalf of a registered
Source in the Source Registry (`contentos.sources`). A Source carries
identity (`slug`, kind, canonical `base_url`), governance (trust tier,
robots policy, fetch/rate policy, terms notes, locale/market), and an audited
lifecycle (`ACTIVE`/`PAUSED`/`DISABLED`/`BLOCKED`, transitions with actor and
reason). Only `ACTIVE` sources are eligible for discovery and fetching;
`BLOCKED` records a policy prohibition that only an explicit operator decision
can lift. Manually submitted URLs also flow through a registered source of
kind `manual`. Trust tier informs future evidence weighting and never grants
republication rights.

## Consequences

- Discovery items, snapshots, and evidence always trace to a governed origin.
- Policy changes (pause/block a source) take effect at one enforcement point.
- Provider-style kinds can be registered before integrations exist, without
  implying functionality.
- Registration must be idempotent (`slug`, and (`kind`, `base_url`) unique) so
  repeated setup cannot fork source identity.

## Alternatives Considered

- Allow direct URL submission without a source record: rejected; breaks
  provenance and policy enforcement.
- Global crawl configuration instead of per-source policy: rejected; sources
  differ materially in trust, limits, and terms.
- A boolean `enabled` flag only: rejected; it cannot distinguish an operator
  pause from a policy prohibition, which have different re-enable semantics.
