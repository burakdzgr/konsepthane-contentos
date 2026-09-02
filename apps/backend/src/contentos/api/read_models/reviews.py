"""Read-only projections for Phase-4 editor reviews.

DURABLE rows only: verdicts and findings exactly as persisted (findings
are policy signals — never Evidence), the deterministic integrity-gate
record including the writer-envelope recomputation, policy snapshots,
supersession audit, and safe attempt metadata with failures visible.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.ai.enums import GenerationPurpose
from contentos.ai.models import AiGenerationAttempt
from contentos.api.read_models.editorial import AiAttemptView, _attempt_views, _FrozenModel
from contentos.briefs.models import BriefClaim
from contentos.reviews.enums import (
    FindingDimension,
    FindingOrigin,
    FindingSeverity,
    ReviewActorOrigin,
    ReviewStatus,
    ReviewVerdict,
)
from contentos.reviews.models import (
    EditorialReview,
    EditorialReviewFinding,
    EditorialReviewStatusEvent,
)
from contentos.workflow.models import EditorialWorkItem

MAX_REVIEWS_PER_WORK_ITEM = 50
MAX_REVIEW_ATTEMPTS = 20


class ReviewSummaryView(_FrozenModel):
    id: uuid.UUID
    work_item_id: uuid.UUID
    content_draft_id: uuid.UUID
    content_brief_id: uuid.UUID
    version: int
    verdict: ReviewVerdict
    status: ReviewStatus
    engine_name: str
    engine_version: str
    generation_attempt_id: uuid.UUID | None
    superseded_by_review_id: uuid.UUID | None
    finding_counts: dict[str, int]
    # Truthful summary of the deterministic recomputation: None means the
    # persisted record carries no envelope — rendered UNKNOWN downstream.
    writer_envelope_recomputed: bool | None
    content_hash: str
    created_at: datetime


class ReviewListPage(_FrozenModel):
    work_item_id: uuid.UUID
    reviews: list[ReviewSummaryView]
    total: int
    truncated: bool


class ReviewFindingView(_FrozenModel):
    id: uuid.UUID
    finding_key: str
    dimension: FindingDimension
    severity: FindingSeverity
    origin: FindingOrigin
    block_id: str | None
    brief_claim_id: uuid.UUID | None
    claim_key: str | None
    claim_kind: str | None
    description: str
    recommendation: str | None


class ReviewStatusEventView(_FrozenModel):
    id: int
    from_status: ReviewStatus
    to_status: ReviewStatus
    actor_origin: ReviewActorOrigin
    reason: str
    request_id: str | None
    replacement_review_id: uuid.UUID | None
    occurred_at: datetime


class ReviewDetail(_FrozenModel):
    review: ReviewSummaryView
    integrity_gate_result: dict[str, Any]
    verdict_policy_snapshot: dict[str, Any]
    review_scope: dict[str, Any]
    findings: list[ReviewFindingView]
    status_events: list[ReviewStatusEventView]
    generation_attempts: list[AiAttemptView]
    generation_attempts_truncated: bool


def _finding_counts(findings: list[EditorialReviewFinding]) -> dict[str, int]:
    counts = {severity.value: 0 for severity in FindingSeverity}
    for finding in findings:
        counts[finding.severity.value] += 1
    return counts


def _summary_view(
    review: EditorialReview, findings: list[EditorialReviewFinding]
) -> ReviewSummaryView:
    gate = review.integrity_gate_result or {}
    recomputed = gate.get("writer_envelope_recomputed")
    return ReviewSummaryView(
        id=review.id,
        work_item_id=review.work_item_id,
        content_draft_id=review.content_draft_id,
        content_brief_id=review.content_brief_id,
        version=review.version,
        verdict=review.verdict,
        status=review.status,
        engine_name=review.engine_name,
        engine_version=review.engine_version,
        generation_attempt_id=review.generation_attempt_id,
        superseded_by_review_id=review.superseded_by_review_id,
        finding_counts=_finding_counts(findings),
        writer_envelope_recomputed=(recomputed if isinstance(recomputed, bool) else None),
        content_hash=review.content_hash,
        created_at=review.created_at,
    )


def _findings_for(session: Session, review_id: uuid.UUID) -> list[EditorialReviewFinding]:
    return list(
        session.execute(
            select(EditorialReviewFinding)
            .where(EditorialReviewFinding.review_id == review_id)
            .order_by(EditorialReviewFinding.finding_key)
        ).scalars()
    )


def list_work_item_reviews(session: Session, work_item_id: uuid.UUID) -> ReviewListPage | None:
    """Every review version of one work item, newest version first."""
    if session.get(EditorialWorkItem, work_item_id) is None:
        return None
    rows = list(
        session.execute(
            select(EditorialReview)
            .where(EditorialReview.work_item_id == work_item_id)
            .order_by(EditorialReview.version.desc())
        ).scalars()
    )
    return ReviewListPage(
        work_item_id=work_item_id,
        reviews=[
            _summary_view(review, _findings_for(session, review.id))
            for review in rows[:MAX_REVIEWS_PER_WORK_ITEM]
        ],
        total=len(rows),
        truncated=len(rows) > MAX_REVIEWS_PER_WORK_ITEM,
    )


def get_review_detail(session: Session, review_id: uuid.UUID) -> ReviewDetail | None:
    """One review version in full: findings with resolved claim anchors,
    the deterministic gate record, audit trail, safe attempt metadata."""
    review = session.get(EditorialReview, review_id)
    if review is None:
        return None

    finding_rows = _findings_for(session, review.id)
    claim_ids = {
        finding.brief_claim_id for finding in finding_rows if finding.brief_claim_id is not None
    }
    claims_by_id: dict[uuid.UUID, BriefClaim] = {}
    if claim_ids:
        for claim in session.execute(
            select(BriefClaim).where(BriefClaim.id.in_(claim_ids))
        ).scalars():
            claims_by_id[claim.id] = claim
    findings = [
        ReviewFindingView(
            id=finding.id,
            finding_key=finding.finding_key,
            dimension=finding.dimension,
            severity=finding.severity,
            origin=finding.origin,
            block_id=finding.block_id,
            brief_claim_id=finding.brief_claim_id,
            claim_key=(
                claims_by_id[finding.brief_claim_id].claim_key
                if finding.brief_claim_id in claims_by_id
                else None
            ),
            claim_kind=(
                claims_by_id[finding.brief_claim_id].claim_kind.value
                if finding.brief_claim_id in claims_by_id
                else None
            ),
            description=finding.description,
            recommendation=finding.recommendation,
        )
        for finding in finding_rows
    ]

    status_events = [
        ReviewStatusEventView(
            id=event.id,
            from_status=event.from_status,
            to_status=event.to_status,
            actor_origin=event.actor_origin,
            reason=event.reason,
            request_id=event.request_id,
            replacement_review_id=event.replacement_review_id,
            occurred_at=event.occurred_at,
        )
        for event in session.execute(
            select(EditorialReviewStatusEvent)
            .where(EditorialReviewStatusEvent.review_id == review.id)
            .order_by(EditorialReviewStatusEvent.id)
        ).scalars()
    ]

    attempt_ids = list(
        session.execute(
            select(AiGenerationAttempt.id)
            .where(
                AiGenerationAttempt.purpose == GenerationPurpose.EDITOR_REVIEW,
                AiGenerationAttempt.input_refs["work_item_id"].as_string()
                == str(review.work_item_id),
            )
            .order_by(AiGenerationAttempt.created_at, AiGenerationAttempt.id)
        ).scalars()
    )
    attempts = _attempt_views(session, set(attempt_ids[:MAX_REVIEW_ATTEMPTS]))

    return ReviewDetail(
        review=_summary_view(review, finding_rows),
        integrity_gate_result=review.integrity_gate_result,
        verdict_policy_snapshot=review.verdict_policy_snapshot,
        review_scope=review.review_scope,
        findings=findings,
        status_events=status_events,
        generation_attempts=attempts,
        generation_attempts_truncated=len(attempt_ids) > MAX_REVIEW_ATTEMPTS,
    )
