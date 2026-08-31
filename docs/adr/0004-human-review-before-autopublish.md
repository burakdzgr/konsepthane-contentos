# ADR 0004: Human Review Before Auto-Publish

Status: Accepted
Date: 2026-08-31

## Context

ContentOS will use automated research, scoring, drafting, editing, and QA. These
systems can still produce unsupported claims, unoriginal work, policy violations,
or media-rights mistakes. No observed production quality history exists yet from
which to calibrate safe auto-publishing thresholds.

## Decision

Auto-publishing is disabled at launch. Every publication requires an authorized
human to approve the exact version of content, evidence, QA results, and media
included in the publication package. Substantive changes after approval invalidate
it and require renewed QA and review.

Unknown-license or reference-only media, unsupported factual claims, fake UGC,
and unresolved hard policy failures cannot be approved for publication. Any future
auto-publishing capability requires real review/quality evidence, explicit risk
and eligibility thresholds, kill/rollback controls, sampled human review, and a
new accepted ADR.

## Consequences

- Launch throughput is limited by reviewer capacity.
- The control panel and audit model must make review context and version scope clear.
- Scheduling and worker completion cannot substitute for approval.
- Review outcomes provide data for later quality calibration.
- Approval roles, escalation, service levels, and staffing must be defined before launch.

## Alternatives Considered

- Full auto-publishing at launch: rejected because quality and rights controls
  are not calibrated with observed production evidence.
- Risk-tiered auto-publishing at launch: rejected for the same lack of evidence;
  it may be reconsidered through a later ADR.
- Permanent manual-only publishing: not selected because controlled automation
  may become appropriate after sufficient evidence and governance exist.
