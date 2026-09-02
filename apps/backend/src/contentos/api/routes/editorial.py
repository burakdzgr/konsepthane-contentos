"""Internal read-only Phase-3 editorial visibility endpoints.

GET only, deliberately: the single operator inspects durable editorial state
without psql. Nothing here mutates domain state, publishes to the queue,
invokes a provider, or exposes raw payloads/clean text/prompts/model output.
The explicit operator commands live in the separate editorial control router.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

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
from contentos.db.session import get_db_session
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
