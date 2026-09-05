"""Live operations read (ADR 0012): one bounded projection for one page."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from contentos.api.read_models.operations import (
    LiveOperationsView,
    load_live_operations,
    read_gateway_screenshot,
)
from contentos.db.session import get_db_session

router = APIRouter(prefix="/internal/operations")


@router.get("/live", response_model=LiveOperationsView)
def live_operations(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
) -> LiveOperationsView:
    """Autopilot state, intake runs, the editorial line with the
    autopilot's last word per item, the merged event feed, and the AI
    gateway's health — read server-side, polled by the admin."""
    return load_live_operations(session, request.app.state.settings)


@router.get("/screenshot")
def gateway_screenshot(request: Request) -> Response:
    """One JPEG frame of the gateway's live browser session, fetched
    server-side with the admin token (never exposed). 503 when the gateway
    is unconfigured, unreachable, or has no connected session."""
    frame = read_gateway_screenshot(request.app.state.settings)
    if frame is None:
        raise HTTPException(status_code=503, detail="gateway browser frame unavailable")
    return Response(content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
