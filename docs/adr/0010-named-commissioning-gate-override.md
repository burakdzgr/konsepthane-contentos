# ADR 0010: Named Operator Override of the Commissioning Score Gate

Status: Accepted
Date: 2026-09-04

## Context

Design §18 made the deterministic opportunity score the ONLY gate for
commissioning (IDEA_SCORING -> EVIDENCE_BUILDING): a `commissionable`
effective score commissions, `not_commissionable` and
`needs_operator_review` fail closed, and the accepted design explicitly
authorized no override.

Operating the pipeline on real intake showed the consequence. Engine
`opportunity-engine/1` measures only signals with a durable deterministic
source: recency, evidence availability, source diversity, source trust and
duplicate overlap. It measures NOTHING about topic value — search demand,
competition, audience fit and editorial value are persisted as UNKNOWN. With
a single-source, older article the arithmetic tops out below the `strong`
threshold no matter how much evidence is extracted (best case ~0.65 against
0.75), so every one of the 20 open opportunities was `weak /
not_commissionable`. The admin then offered a commission button the backend
refused with 409 (fixed on 2026-09-03), and after that fix the inbox was an
empty decision queue next to a reject-only "Elenecekler" list: a deadlock
in which the human — the only party able to judge the topic — could not
produce anything.

The score is honest about what it measures (the SOURCE BASE), but the gate
was treating "I do not know the topic's value" as "no".

## Decision

1. The score gate stays the DEFAULT. Nothing changes for the automatic path:
   no Celery job, evaluation or generation may commission, and the
   `commission_eligible` read-model flag still means "the gate passes as is".
2. A NAMED operator may commission over a `not_commissionable` or
   `needs_operator_review` effective score by passing `override_gate=true`
   on the existing commissioning command, with the same required reason.
   This is a human editorial decision (ADR 0004 spirit), never a system
   default.
3. An UNSCORED opportunity can never be commissioned, override or not. The
   override lifts the eligibility rule only; disposition OPEN and state
   IDEA_SCORING remain mandatory.
4. The override is recorded durably on the EVIDENCE_BUILDING entry event's
   `artifact_refs`: `commissioning_gate_override = "true"`,
   `overridden_score_eligibility`, `overridden_score_band`, next to the
   pinned `opportunity_score_id`. A passed gate leaves no marker.
5. Read models expose `commission_override_possible` (scored, open,
   IDEA_SCORING, gate refused) so the admin offers "Yine de içerik üret"
   ONLY where the domain would accept it, and never on unscored cards.

## Consequences

- The deadlock is closed without weakening the automatic pipeline or
  hiding the score: the card still says "kaynak tabanı zayıf" and the
  override reason lives next to that verdict forever.
- Audits can list every commissioning that bypassed the gate by filtering
  workflow events on `commissioning_gate_override`.
- The score is worded everywhere as a SOURCE-BASE score, not a topic
  verdict. When demand/competition/audience signals gain a durable
  deterministic source, the engine version bumps and this override should
  become rare; it is not a reason to skip those signals.
- Supersedes the "no override exists" sentences in design §18 notes,
  `docs/memory/CURRENT_STATE.md` and the code docstrings, which now point
  here.
