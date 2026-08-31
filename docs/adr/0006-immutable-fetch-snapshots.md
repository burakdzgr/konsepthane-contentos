# ADR 0006: Fetch Snapshots Are Immutable and Append-Only

Status: Accepted
Date: 2026-08-31

## Context

Research evidence must remain auditable over time. Web pages change and
disappear; if a re-fetch overwrote the stored capture, every evidence unit and
duplicate decision derived from the earlier capture would silently lose its
factual basis. Editorial policy requires that a later stage must not overwrite
the evidence that allowed an item to advance.

## Decision

A fetch attempt always produces a new FetchSnapshot row; snapshots are never
updated or deleted by application code. Failed attempts are snapshots too
(with an outcome classification and no payload). Normalized documents,
duplicate decisions, and research evidence reference a specific snapshot `id`,
never "the current content of a URL". Raw payloads are stored behind an opaque
storage reference (`storage_backend` + key) so the initial database-backed
storage can later move to object storage without changing the audit model.
Retention is a future, explicit, logged pruning process; snapshots referenced
by research evidence are retained.

## Consequences

- Historical research remains verifiable against the exact bytes captured.
- Repeated fetch jobs are naturally idempotent-safe: appending is harmless.
- Storage grows monotonically until a governed retention job exists; body-size
  caps and MIME allowlists bound the growth rate.
- "Latest content" is a query concern (newest successful snapshot), not a
  mutation concern.

## Alternatives Considered

- One mutable "current capture" row per URL: rejected; destroys auditability
  and invalidates downstream references.
- Storing only normalized text without raw capture: rejected; extraction bugs
  could never be re-examined or re-run against the original material.
- External blob storage from day one: rejected for now; premature operational
  complexity, and the opaque reference keeps the path open.
