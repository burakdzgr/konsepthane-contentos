"""Internal read-only research-pipeline visibility endpoints.

GET only, deliberately: this router exists so the single operator can inspect
durable pipeline state without psql. It never mutates domain state, never
triggers discovery/fetch/normalization, and never exposes raw payloads,
clean text, excerpts, or evidence statements. PostgreSQL remains the only
operational truth — no queue or worker introspection appears here.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from contentos.api.read_models.research import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MAX_PAGE_OFFSET,
    MAX_TEXT_SEARCH_LENGTH,
    MAX_URL_SEARCH_LENGTH,
    PipelineDetail,
    PipelineListPage,
    SourceListPage,
    get_pipeline_detail,
    list_pipeline_items,
    list_sources,
)
from contentos.db.session import get_db_session
from contentos.discovery.enums import DiscoveryLifecycleState, DiscoveryMethod
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.fetching.models import FetchOutcome
from contentos.normalization.enums import NormalizationStatus
from contentos.sources.enums import DiscoveryStrategy, SourceKind, SourceLifecycleState

router = APIRouter(prefix="/internal/research")

_LimitQuery = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)]
_OffsetQuery = Annotated[int, Query(ge=0, le=MAX_PAGE_OFFSET)]


@router.get("/sources", response_model=SourceListPage)
def list_research_sources(
    session: Annotated[Session, Depends(get_db_session)],
    lifecycle_state: SourceLifecycleState | None = None,
    kind: SourceKind | None = None,
    discovery_strategy: DiscoveryStrategy | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=MAX_TEXT_SEARCH_LENGTH)] = None,
    limit: _LimitQuery = DEFAULT_PAGE_LIMIT,
    offset: _OffsetQuery = 0,
) -> SourceListPage:
    """Bounded, deterministic Source Registry page with discovery counts."""
    return list_sources(
        session,
        lifecycle_state=lifecycle_state,
        kind=kind,
        discovery_strategy=discovery_strategy,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/discovery-items", response_model=PipelineListPage)
def list_research_discovery_items(
    session: Annotated[Session, Depends(get_db_session)],
    source_id: uuid.UUID | None = None,
    lifecycle_state: DiscoveryLifecycleState | None = None,
    discovery_method: DiscoveryMethod | None = None,
    fetch_outcome: FetchOutcome | None = None,
    normalization_status: NormalizationStatus | None = None,
    duplicate_outcome: DuplicateDecisionOutcome | None = None,
    has_evidence: bool | None = None,
    url_contains: Annotated[
        str | None, Query(min_length=1, max_length=MAX_URL_SEARCH_LENGTH)
    ] = None,
    limit: _LimitQuery = DEFAULT_PAGE_LIMIT,
    offset: _OffsetQuery = 0,
) -> PipelineListPage:
    """Bounded pipeline page with deterministic latest-stage projections."""
    return list_pipeline_items(
        session,
        source_id=source_id,
        lifecycle_state=lifecycle_state,
        discovery_method=discovery_method,
        fetch_outcome=fetch_outcome,
        normalization_status=normalization_status,
        duplicate_outcome=duplicate_outcome,
        has_evidence=has_evidence,
        url_contains=url_contains,
        limit=limit,
        offset=offset,
    )


@router.get("/discovery-items/{discovery_item_id}", response_model=PipelineDetail)
def get_research_discovery_item(
    session: Annotated[Session, Depends(get_db_session)],
    discovery_item_id: uuid.UUID,
) -> PipelineDetail:
    """Bounded operational detail for one DiscoveryItem's pipeline chain."""
    detail = get_pipeline_detail(session, discovery_item_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="discovery item not found")
    return detail
