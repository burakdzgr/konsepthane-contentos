# ADR 0012: Autopilot — Bounded Autonomous Advancement of the Editorial Line

Status: Accepted
Date: 2026-09-05

## Context

Every editorial stage after commissioning (idea candidates, idea choice,
evidence pack, search intent, brief, brief acceptance, writer draft, editor
review, review acceptance, QA gates, media, publication packaging,
scheduling, publish dispatch) is an explicit operator command today. The
design rationale was honest: with no observed production quality history,
every artifact deserved a human look. In operation this produced a line in
which "start discovery" leads to a queue of buttons, not to content.

The operator's stated goal: the line should run by itself from the
discovery click onward, with the produced outputs shown for human
inspection at first (to learn what the machine gets right and wrong), and
later fully autonomous up to and including scheduling and publishing.

Two governance rules already exist and stay binding: ADR 0004 (every
publication requires a named human approval of the exact package; any
auto-publishing needs a new ADR backed by quality evidence) and design §18
(commissioning is a human decision; no job may commission automatically).

## Decision

1. A durable, named **autopilot mode** with three levels:
   - `off` — unchanged behaviour, every step is an operator command.
   - `supervised` — the machine PRODUCES every artifact automatically;
     every ACCEPTANCE stays human (commission, idea choice, brief
     acceptance, review acceptance/rework, media satisfaction, final
     approval, packaging, scheduling, publish dispatch). This is the
     learning phase: outputs appear, the operator judges each one.
   - `autonomous` — acceptances are made by the autopilot on behalf of the
     NAMED operator who switched the mode on, with bounded deterministic
     rules (best originality result picks the idea; a `pass` review is
     accepted; a `revise` review routes ONE bounded rework, at most
     `MAX_REWORK_CYCLES`; open media needs get one generated image each);
     after the human approval the autopilot assembles, schedules and
     dispatches publication.
2. **The ADR 0004 gate is untouched**: `awaiting_human_review` always waits
   for a named reviewer in every mode. Fully autonomous approval remains a
   future ADR that must bring quality evidence, thresholds, kill switches
   and sampled review.
3. **Commissioning by the autopilot is a delegated human decision**, not an
   automatic one: it happens only in `autonomous` mode, only when the
   commissioning gate passes as is (never through the ADR 0010 override),
   and the transition records the enabling operator as `actor_user_id` and
   `autopilot = "true"` in its artifact refs. Switching the mode on IS the
   human decision; it is recorded with reason and actor and can be
   reversed at any moment.
4. **One planner, one runner, existing commands.** `autopilot.planner.plan`
   is a pure function from a durable-fact snapshot to ONE action; the
   runner performs acceptances through the very services the buttons use
   and enqueues production steps as the existing editorial tasks. No stage
   is re-implemented; every artifact, attempt and workflow event is created
   exactly as it would be by hand, with the autopilot marker where it acts.
5. **A sweep, not a scheduler.** A self-re-arming worker task
   (`contentos.autopilot.sweep`, 20 s) plans one step per actionable work
   item. It stops re-arming when the mode is `off` and is re-armed by the
   API on mode changes and by the worker on startup. In-flight actions
   (the same action within 15 minutes) are never repeated, so long AI jobs
   are not double-queued.
6. **The trail is the feed.** `autopilot_events` records every action,
   every wait with its reason, every skip and error; the admin's live
   operations page reads the same rows the auditor reads.

## Consequences

- From the discovery click the line advances without operator clicks up to
  the first acceptance in `supervised` mode and up to final approval in
  `autonomous` mode; the operator's work becomes judging outputs and
  approving packages, and the page shows why anything is waiting.
- Bounded loops: rework cycles, one image per open need per sweep window,
  a 200-item sweep cap, and the daily AI attempt budget already enforced
  by the worker.
- Failure honesty: a failed acceptance is an `error` trail row with the
  error class, the step is retried on the next sweep, and nothing is
  silently skipped. A failed AI production step is a durable failed
  attempt as before.
- Media satisfaction stays human in this first version (the generated
  image must be bound to the need by an operator); binding it automatically
  is a follow-up once the generated-asset ↔ need link is durable.
- Publishing after approval in `autonomous` mode respects ADR 0004: the
  approval is the human review; assembling, scheduling and dispatching the
  approved package are mechanical steps the approval already authorised.
