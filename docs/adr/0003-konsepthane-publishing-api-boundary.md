# ADR 0003: Konsepthane Publishing API Boundary

Status: Accepted
Date: 2026-08-31

## Context

ContentOS must publish approved content without gaining direct access to
Konsepthane production storage or coupling to its internal schema. Publication
also needs validation, authorization, idempotency, traceability, and stable
failure handling across independently deployed systems.

## Decision

Konsepthane will own a versioned, authenticated Publishing API as the only
ContentOS publication boundary. ContentOS will submit an immutable approved
publication package using a least-privilege service identity over TLS. Requests
must carry an idempotency key and correlation ID. The contract must validate
content, target, approval/version data, and media provenance, and return or make
queryable a stable publication result and machine-readable errors.

ContentOS will never implement publishing by directly accessing production
PostgreSQL, sharing migrations, or writing to a production filesystem. Concrete
endpoint shapes, authentication protocol, version lifecycle, and reconciliation
mechanism must be agreed before integration implementation.

## Consequences

- Konsepthane retains ownership of public content validation and persistence.
- ContentOS can retry safely only when it preserves logical operation identity.
- Contract evolution requires versioning and compatibility rules.
- Publication is asynchronous from the editorial workflow and needs status reconciliation.
- API unavailability blocks publication but must not affect the public site's availability.
- Both systems need correlated audit/observability records without sharing databases.

## Alternatives Considered

- Direct production database writes: rejected because they bypass ownership,
  validation, authorization, and migration boundaries.
- Shared migrations or ORM models: rejected because they create release coupling.
- Shared filesystem/export folder: rejected because it provides weak validation,
  authentication, idempotency, and result semantics.
- Manual copy/paste as the permanent integration: rejected as unauditable and
  unsuitable for reliable scheduling, though humans may use Konsepthane's own
  emergency process outside ContentOS.
