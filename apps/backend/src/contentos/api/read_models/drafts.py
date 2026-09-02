"""Read-only projections for Phase-4 writer drafts.

Everything here reads DURABLE rows only: the validated draft body, the
claim -> evidence provenance chain, policy verdicts as persisted, and safe
generation-attempt metadata. No raw prompts, provider outputs, or payloads
exist in these tables, and this view adds nothing. Unknown or missing policy
verdicts stay None — the admin renders them as UNKNOWN, never as 0/PASS.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.ai.enums import GenerationPurpose
from contentos.ai.models import AiGenerationAttempt
from contentos.api.read_models.editorial import AiAttemptView, _attempt_views, _FrozenModel
from contentos.briefs.models import BriefClaim, BriefClaimEvidence
from contentos.drafts.enums import DraftActorOrigin, DraftOrigin, DraftStatus
from contentos.drafts.models import ContentDraft, DraftClaimUsage, DraftStatusEvent
from contentos.workflow.models import EditorialWorkItem

MAX_DRAFTS_PER_WORK_ITEM = 50
MAX_DRAFT_ATTEMPTS = 20


class DraftSummaryView(_FrozenModel):
    id: uuid.UUID
    work_item_id: uuid.UUID
    content_brief_id: uuid.UUID
    version: int
    origin: DraftOrigin
    status: DraftStatus
    engine_name: str
    engine_version: str
    title_proposal: str | None
    generation_attempt_id: uuid.UUID | None
    manual_input_hash: str | None
    superseded_by_draft_id: uuid.UUID | None
    body_schema_version: str
    # Truthful policy verdict summaries: None means the persisted record
    # carries no verdict — rendered as UNKNOWN downstream, never as a pass.
    uncertainty_coverage_status: str | None
    originality_outcome: str | None
    content_hash: str
    created_at: datetime


class DraftListPage(_FrozenModel):
    work_item_id: uuid.UUID
    drafts: list[DraftSummaryView]
    total: int
    truncated: bool


class DraftClaimUsageView(_FrozenModel):
    id: uuid.UUID
    brief_claim_id: uuid.UUID
    claim_key: str
    claim_kind: str
    claim_text: str
    handling: str | None
    section_key: str
    block_id: str
    research_evidence_ids: list[uuid.UUID]


class DraftStatusEventView(_FrozenModel):
    id: int
    from_status: DraftStatus
    to_status: DraftStatus
    actor_origin: DraftActorOrigin
    reason: str
    request_id: str | None
    replacement_draft_id: uuid.UUID | None
    occurred_at: datetime


class DraftDetail(_FrozenModel):
    draft: DraftSummaryView
    body: dict[str, Any]
    uncertainty_coverage: dict[str, Any]
    validation_policy_snapshot: dict[str, Any]
    originality_policy_snapshot: dict[str, Any]
    originality_result: dict[str, Any]
    claim_usages: list[DraftClaimUsageView]
    status_events: list[DraftStatusEventView]
    generation_attempts: list[AiAttemptView]
    generation_attempts_truncated: bool


def _summary_view(draft: ContentDraft) -> DraftSummaryView:
    coverage = draft.uncertainty_coverage or {}
    originality = draft.originality_result or {}
    coverage_status = coverage.get("status")
    originality_outcome = originality.get("outcome")
    return DraftSummaryView(
        id=draft.id,
        work_item_id=draft.work_item_id,
        content_brief_id=draft.content_brief_id,
        version=draft.version,
        origin=draft.origin,
        status=draft.status,
        engine_name=draft.engine_name,
        engine_version=draft.engine_version,
        title_proposal=draft.title_proposal,
        generation_attempt_id=draft.generation_attempt_id,
        manual_input_hash=draft.manual_input_hash,
        superseded_by_draft_id=draft.superseded_by_draft_id,
        body_schema_version=draft.body_schema_version,
        uncertainty_coverage_status=(coverage_status if isinstance(coverage_status, str) else None),
        originality_outcome=(originality_outcome if isinstance(originality_outcome, str) else None),
        content_hash=draft.content_hash,
        created_at=draft.created_at,
    )


def list_work_item_drafts(session: Session, work_item_id: uuid.UUID) -> DraftListPage | None:
    """Every draft version of one work item, newest version first."""
    if session.get(EditorialWorkItem, work_item_id) is None:
        return None
    rows = list(
        session.execute(
            select(ContentDraft)
            .where(ContentDraft.work_item_id == work_item_id)
            .order_by(ContentDraft.version.desc())
        ).scalars()
    )
    return DraftListPage(
        work_item_id=work_item_id,
        drafts=[_summary_view(draft) for draft in rows[:MAX_DRAFTS_PER_WORK_ITEM]],
        total=len(rows),
        truncated=len(rows) > MAX_DRAFTS_PER_WORK_ITEM,
    )


def _claim_usage_views(session: Session, draft_id: uuid.UUID) -> list[DraftClaimUsageView]:
    """The draft's claim bindings resolved one hop down the provenance chain:
    DraftClaimUsage -> BriefClaim -> BriefClaimEvidence (identities only)."""
    usage_rows = list(
        session.execute(
            select(DraftClaimUsage, BriefClaim)
            .join(BriefClaim, BriefClaim.id == DraftClaimUsage.brief_claim_id)
            .where(DraftClaimUsage.draft_id == draft_id)
            .order_by(DraftClaimUsage.section_key, DraftClaimUsage.block_id, BriefClaim.claim_key)
        ).all()
    )
    claim_ids = {claim.id for _, claim in usage_rows}
    evidence_by_claim: dict[uuid.UUID, list[uuid.UUID]] = {}
    if claim_ids:
        links = session.execute(
            select(BriefClaimEvidence)
            .where(BriefClaimEvidence.claim_id.in_(claim_ids))
            .order_by(BriefClaimEvidence.claim_id, BriefClaimEvidence.research_evidence_id)
        ).scalars()
        for link in links:
            evidence_by_claim.setdefault(link.claim_id, []).append(link.research_evidence_id)
    return [
        DraftClaimUsageView(
            id=usage.id,
            brief_claim_id=claim.id,
            claim_key=claim.claim_key,
            claim_kind=claim.claim_kind.value,
            claim_text=claim.claim_text,
            handling=claim.handling,
            section_key=usage.section_key,
            block_id=usage.block_id,
            research_evidence_ids=evidence_by_claim.get(claim.id, []),
        )
        for usage, claim in usage_rows
    ]


def get_draft_detail(session: Session, draft_id: uuid.UUID) -> DraftDetail | None:
    """One draft version in full: body, provenance, verdicts, audit, attempts."""
    draft = session.get(ContentDraft, draft_id)
    if draft is None:
        return None

    status_events = [
        DraftStatusEventView(
            id=event.id,
            from_status=event.from_status,
            to_status=event.to_status,
            actor_origin=event.actor_origin,
            reason=event.reason,
            request_id=event.request_id,
            replacement_draft_id=event.replacement_draft_id,
            occurred_at=event.occurred_at,
        )
        for event in session.execute(
            select(DraftStatusEvent)
            .where(DraftStatusEvent.draft_id == draft.id)
            .order_by(DraftStatusEvent.id)
        ).scalars()
    ]

    attempt_ids = list(
        session.execute(
            select(AiGenerationAttempt.id)
            .where(
                AiGenerationAttempt.purpose == GenerationPurpose.WRITER_DRAFT,
                AiGenerationAttempt.input_refs["content_brief_id"].as_string()
                == str(draft.content_brief_id),
            )
            .order_by(AiGenerationAttempt.created_at, AiGenerationAttempt.id)
        ).scalars()
    )
    attempts = _attempt_views(session, set(attempt_ids[:MAX_DRAFT_ATTEMPTS]))

    return DraftDetail(
        draft=_summary_view(draft),
        body=draft.body,
        uncertainty_coverage=draft.uncertainty_coverage,
        validation_policy_snapshot=draft.validation_policy_snapshot,
        originality_policy_snapshot=draft.originality_policy_snapshot,
        originality_result=draft.originality_result,
        claim_usages=_claim_usage_views(session, draft.id),
        status_events=status_events,
        generation_attempts=attempts,
        generation_attempts_truncated=len(attempt_ids) > MAX_DRAFT_ATTEMPTS,
    )
