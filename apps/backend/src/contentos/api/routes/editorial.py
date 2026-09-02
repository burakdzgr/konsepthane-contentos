"""Internal read-only Phase-3 editorial visibility endpoints.

GET only, deliberately: the single operator inspects durable editorial state
without psql. Nothing here mutates domain state, publishes to the queue,
invokes a provider, or exposes raw payloads/clean text/prompts/model output.
The explicit operator commands live in the separate editorial control router.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from contentos.api.read_models.decisions import (
    DecisionListPage,
    list_work_item_decisions,
)
from contentos.api.read_models.drafts import (
    DraftDetail,
    DraftListPage,
    get_draft_detail,
    list_work_item_drafts,
)
from contentos.api.read_models.editorial import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MAX_PAGE_OFFSET,
    MAX_TEXT_SEARCH_LENGTH,
    EligibleEvidencePage,
    WorkItemDetail,
    WorkQueuePage,
    get_work_item_detail,
    list_eligible_evidence,
    list_work_items,
)
from contentos.api.read_models.media import MediaCoveragePage, get_media_coverage
from contentos.api.read_models.publishing import PublicationPage, get_publication
from contentos.api.read_models.qa import (
    QaReportDetail,
    QaReportListPage,
    get_qa_report_detail,
    list_work_item_qa_reports,
)
from contentos.api.read_models.reviews import (
    ReviewDetail,
    ReviewListPage,
    get_review_detail,
    list_work_item_reviews,
)
from contentos.db.session import get_db_session
from contentos.media.models import MediaAsset
from contentos.media.store import MediaStoreError
from contentos.opportunities.enums import OpportunityDisposition
from contentos.workflow.enums import WorkflowState

router = APIRouter(prefix="/internal/editorial")

_LimitQuery = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)]
_OffsetQuery = Annotated[int, Query(ge=0, le=MAX_PAGE_OFFSET)]


@router.get("/work-items", response_model=WorkQueuePage)
def list_editorial_work_items(
    session: Annotated[Session, Depends(get_db_session)],
    workflow_state: WorkflowState | None = None,
    opportunity_disposition: OpportunityDisposition | None = None,
    locale: Annotated[str | None, Query(min_length=2, max_length=20)] = None,
    market: Annotated[str | None, Query(min_length=2, max_length=2)] = None,
    blocked: bool | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=MAX_TEXT_SEARCH_LENGTH)] = None,
    limit: _LimitQuery = DEFAULT_PAGE_LIMIT,
    offset: _OffsetQuery = 0,
) -> WorkQueuePage:
    """Bounded editorial work queue with deterministic latest projections."""
    return list_work_items(
        session,
        workflow_state=workflow_state,
        opportunity_disposition=opportunity_disposition,
        locale=locale,
        market=market,
        blocked=blocked,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/work-items/{work_item_id}", response_model=WorkItemDetail)
def get_editorial_work_item(
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
) -> WorkItemDetail:
    """The principal explainability projection for one work item."""
    detail = get_work_item_detail(session, work_item_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="editorial work item not found")
    return detail


@router.get("/work-items/{work_item_id}/drafts", response_model=DraftListPage)
def list_editorial_work_item_drafts(
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
) -> DraftListPage:
    """Every durable draft version of one work item, newest first."""
    page = list_work_item_drafts(session, work_item_id)
    if page is None:
        raise HTTPException(status_code=404, detail="editorial work item not found")
    return page


@router.get("/drafts/{draft_id}", response_model=DraftDetail)
def get_editorial_draft(
    session: Annotated[Session, Depends(get_db_session)],
    draft_id: uuid.UUID,
) -> DraftDetail:
    """One draft version in full: validated body, claim -> evidence chain,
    policy verdicts as persisted, supersession audit, attempt metadata."""
    detail = get_draft_detail(session, draft_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="content draft not found")
    return detail


@router.get("/work-items/{work_item_id}/reviews", response_model=ReviewListPage)
def list_editorial_work_item_reviews(
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
) -> ReviewListPage:
    """Every durable editor review version of one work item, newest first."""
    page = list_work_item_reviews(session, work_item_id)
    if page is None:
        raise HTTPException(status_code=404, detail="editorial work item not found")
    return page


@router.get("/reviews/{review_id}", response_model=ReviewDetail)
def get_editorial_review(
    session: Annotated[Session, Depends(get_db_session)],
    review_id: uuid.UUID,
) -> ReviewDetail:
    """One review version in full: findings with resolved anchors, the
    deterministic integrity record, policy snapshots, audit, attempts."""
    detail = get_review_detail(session, review_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="editorial review not found")
    return detail


@router.get("/work-items/{work_item_id}/decisions", response_model=DecisionListPage)
def list_editorial_work_item_decisions(
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
) -> DecisionListPage:
    """Every human decision event of one work item plus the derived
    hash-bound approval status."""
    page = list_work_item_decisions(session, work_item_id)
    if page is None:
        raise HTTPException(status_code=404, detail="editorial work item not found")
    return page


@router.get("/work-items/{work_item_id}/media", response_model=MediaCoveragePage)
def get_editorial_work_item_media(
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
) -> MediaCoveragePage:
    """The ACTIVE brief's media needs with per-need coverage (or honest
    UNSATISFIED) plus the audited satisfaction history."""
    page = get_media_coverage(session, work_item_id)
    if page is None:
        raise HTTPException(status_code=404, detail="editorial work item not found")
    return page


@router.get("/work-items/{work_item_id}/publication", response_model=PublicationPage)
def get_editorial_work_item_publication(
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
) -> PublicationPage:
    """Publication packages (summaries + pins, never the body) and every
    dispatch attempt exactly as recorded."""
    page = get_publication(session, work_item_id)
    if page is None:
        raise HTTPException(status_code=404, detail="editorial work item not found")
    return page


@router.get("/media-assets/{asset_id}/content")
def get_media_asset_content(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    asset_id: uuid.UUID,
) -> Response:
    """Stream one asset's bytes with its true content type. The store
    layout stays internal: assets are addressed by id only."""
    asset = session.get(MediaAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="media asset not found")
    try:
        data = request.app.state.media_store.read(asset.content_sha256)
    except MediaStoreError:
        raise HTTPException(
            status_code=503, detail="media content is not available from the store"
        ) from None
    return Response(content=data, media_type=asset.media_type)


@router.get("/work-items/{work_item_id}/qa-reports", response_model=QaReportListPage)
def list_editorial_work_item_qa_reports(
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
) -> QaReportListPage:
    """Every durable QA report version of one work item, newest first,
    plus the work item's audited waivers (always visible)."""
    page = list_work_item_qa_reports(session, work_item_id)
    if page is None:
        raise HTTPException(status_code=404, detail="editorial work item not found")
    return page


@router.get("/qa-reports/{report_id}", response_model=QaReportDetail)
def get_editorial_qa_report(
    session: Annotated[Session, Depends(get_db_session)],
    report_id: uuid.UUID,
) -> QaReportDetail:
    """One QA report in full: gate results exactly as persisted, the
    versioned gate policy, waivers, and the supersession audit."""
    detail = get_qa_report_detail(session, report_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="qa report not found")
    return detail


@router.get(
    "/opportunities/{opportunity_id}/eligible-evidence",
    response_model=EligibleEvidencePage,
)
def list_opportunity_eligible_evidence(
    session: Annotated[Session, Depends(get_db_session)],
    opportunity_id: uuid.UUID,
    limit: _LimitQuery = DEFAULT_PAGE_LIMIT,
    offset: _OffsetQuery = 0,
) -> EligibleEvidencePage:
    """The domain's own pack-eligibility rule, paged; the human selects."""
    page = list_eligible_evidence(session, opportunity_id, limit=limit, offset=offset)
    if page is None:
        raise HTTPException(status_code=404, detail="editorial opportunity not found")
    return page
