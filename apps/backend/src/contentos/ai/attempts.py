"""Attempt bookkeeping helpers for automatic re-invocation.

The attempt identity deliberately includes `retry_number`: the same inputs
with the same retry number NEVER call the provider twice. An automatic
re-enqueue (autopilot) therefore has to name a retry number that has not
been used for that purpose and work item yet — otherwise it silently reuses
the stored failed attempt forever. `next_retry_number` derives it from the
durable attempt rows themselves (bounded scan of the newest rows)."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.models import AiGenerationAttempt

MAX_SCANNED_ATTEMPTS = 500


def next_retry_number(
    session: Session,
    purpose: GenerationPurpose,
    *,
    work_item_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
) -> int:
    """One past the highest retry number already recorded for this purpose
    and work item / opportunity (0 when nothing was attempted)."""
    wanted_work_item = str(work_item_id) if work_item_id is not None else None
    wanted_opportunity = str(opportunity_id) if opportunity_id is not None else None
    if wanted_work_item is None and wanted_opportunity is None:
        return 0
    rows = session.execute(
        select(AiGenerationAttempt.input_refs, AiGenerationAttempt.retry_number)
        .where(AiGenerationAttempt.purpose == purpose)
        .order_by(AiGenerationAttempt.created_at.desc(), AiGenerationAttempt.id.desc())
        .limit(MAX_SCANNED_ATTEMPTS)
    ).all()
    highest = -1
    for refs, retry_number in rows:
        if not isinstance(refs, dict):
            continue
        matches = (
            wanted_work_item is not None and refs.get("work_item_id") == wanted_work_item
        ) or (wanted_opportunity is not None and refs.get("opportunity_id") == wanted_opportunity)
        if matches:
            highest = max(highest, int(retry_number))
    return highest + 1


PROVIDER_FAILURE_STATUSES = frozenset({GenerationStatus.PROVIDER_ERROR, GenerationStatus.TIMEOUT})


def consecutive_provider_failures(
    session: Session,
    purpose: GenerationPurpose,
    *,
    work_item_id: uuid.UUID | None = None,
    opportunity_id: uuid.UUID | None = None,
) -> int:
    """How many of the most recent attempts for this purpose and work item /
    opportunity failed at the provider (error or timeout) in a row. A
    validation failure or a success ends the streak; nothing matched is 0."""
    wanted_work_item = str(work_item_id) if work_item_id is not None else None
    wanted_opportunity = str(opportunity_id) if opportunity_id is not None else None
    if wanted_work_item is None and wanted_opportunity is None:
        return 0
    rows = session.execute(
        select(AiGenerationAttempt.input_refs, AiGenerationAttempt.status)
        .where(AiGenerationAttempt.purpose == purpose)
        .order_by(AiGenerationAttempt.created_at.desc(), AiGenerationAttempt.id.desc())
        .limit(MAX_SCANNED_ATTEMPTS)
    ).all()
    streak = 0
    for refs, status in rows:
        if not isinstance(refs, dict):
            continue
        matches = (
            wanted_work_item is not None and refs.get("work_item_id") == wanted_work_item
        ) or (wanted_opportunity is not None and refs.get("opportunity_id") == wanted_opportunity)
        if not matches:
            continue
        if status in PROVIDER_FAILURE_STATUSES:
            streak += 1
            continue
        break
    return streak
