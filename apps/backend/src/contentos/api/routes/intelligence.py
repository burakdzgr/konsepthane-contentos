"""Internal read-only intelligence-signal endpoints.

GET only: the operator inspects the durable signal store; nothing here
extracts, enqueues, or touches a source. Extraction runs in the worker
after normalization succeeds.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from contentos.api.read_models.intelligence import (
    DEFAULT_SIGNAL_LIMIT,
    MAX_SIGNAL_LIMIT,
    IntakeRunNotFoundError,
    IntelligenceSummary,
    SignalListPage,
    list_signals,
    summarize,
)
from contentos.db.session import get_db_session
from contentos.intelligence.enums import SignalFamily
from contentos.intelligence.service import OpportunityNotFoundError

router = APIRouter(prefix="/internal/intelligence")

_LimitQuery = Annotated[int, Query(ge=1, le=MAX_SIGNAL_LIMIT)]


@router.get("/signals", response_model=SignalListPage)
def read_signals(
    session: Annotated[Session, Depends(get_db_session)],
    family: SignalFamily | None = None,
    opportunity_id: uuid.UUID | None = None,
    limit: _LimitQuery = DEFAULT_SIGNAL_LIMIT,
) -> SignalListPage:
    try:
        return list_signals(session, family=family, limit=limit, opportunity_id=opportunity_id)
    except OpportunityNotFoundError:
        raise HTTPException(status_code=404, detail="opportunity not found") from None


@router.get("/summary", response_model=IntelligenceSummary)
def read_summary(
    session: Annotated[Session, Depends(get_db_session)],
    run_id: uuid.UUID | None = None,
) -> IntelligenceSummary:
    """Per-family tallies; ``run_id`` bounds them to one intake run's own
    documents so a live run view never shows another run's signals."""
    try:
        return summarize(session, run_id=run_id)
    except IntakeRunNotFoundError:
        raise HTTPException(status_code=404, detail="intake run not found") from None
