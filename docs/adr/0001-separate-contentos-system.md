# ADR 0001: Separate ContentOS System

Status: Accepted
Date: 2026-08-31

## Context

ContentOS performs experimental, asynchronous, and AI-assisted editorial work.
Placing it inside the public Konsepthane application or allowing it to share the
production database would couple failures, credentials, migrations, and release
cycles to the public site.

## Decision

ContentOS will be a separate internal system with its own repository/runtime,
PostgreSQL database, migrations, credentials, workers, and deployment lifecycle.
It must not directly access Konsepthane production PostgreSQL, share Konsepthane
migrations, or mount its production filesystem. The public site must continue
operating if ContentOS is unavailable. Publication crosses the boundary only
through the Konsepthane Publishing API defined by ADR 0003.

## Consequences

- Editorial automation failures are isolated from the public runtime and data store.
- Data needed from Konsepthane requires an explicit API or analytics contract.
- ContentOS duplicates only the internal metadata needed for workflow and audit.
- Deployment, monitoring, backup, and access policies must cover ContentOS separately.
- Cross-system consistency is asynchronous and requires idempotency/reconciliation.

## Alternatives Considered

- Build ContentOS inside the public Konsepthane application: rejected because it
  couples operational risk and release cadence.
- Share the production PostgreSQL schema or migrations: rejected because it
  bypasses service ownership and increases data-corruption risk.
- Exchange publication files through a shared filesystem: rejected because it
  lacks a stable authenticated contract and reliable status handling.
