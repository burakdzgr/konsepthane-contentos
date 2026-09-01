"""Explicit POST-only operator control endpoints for the research pipeline.

Every endpoint is a thin adapter over an existing domain service or a
producer-only Celery publish — no domain rule lives here:

- state transitions call `SourceRegistryService` / `DiscoveryService`, which
  stay authoritative for validation, transition matrices, and audit events;
- the two task triggers validate durable eligibility, then enqueue the frozen
  Task 16 entry-point jobs by entity UUID only — the control API never
  accepts a URL to fetch, so registered durable entities alone determine what
  the crawler may touch;
- acceptance and fetch remain two separate operator decisions: nothing here
  auto-accepts, auto-fetches, or chains admissions into execution.

Single-operator boundary unchanged: no authentication, no roles; deployment
infrastructure remains the access boundary.
"""

import uuid
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from contentos.core.context import get_request_id, is_valid_request_id
from contentos.db.session import get_db_session
from contentos.discovery.enums import (
    DiscoveryLifecycleState,
    DiscoveryRejectionReason,
)
from contentos.discovery.repository import DiscoveryItemRepository
from contentos.discovery.service import (
    DiscoveryItemNotFoundError,
    DiscoveryService,
    InvalidDiscoveryTransitionError,
)
from contentos.sources.enums import (
    DiscoveryStrategy,
    LifecycleChangeOrigin,
    SourceKind,
    SourceLifecycleState,
    TrustTier,
)
from contentos.sources.repository import SourceRepository
from contentos.sources.service import (
    InvalidLifecycleTransitionError,
    InvalidSourceDefinitionError,
    SourceNotFoundError,
    SourceRegistrationConflictError,
    SourceRegistryService,
)

_logger = structlog.get_logger("contentos.api.research_control")

router = APIRouter(prefix="/internal/research")

# Phase 2 control policy: only functional kinds are registrable here.
# Placeholder provider kinds and container kinds (editorial/competitor sites
# are consumed through governed feed/sitemap sub-sources) stay out of the
# operator surface until an integration actually exists.
REGISTRABLE_SOURCE_KINDS = frozenset({SourceKind.RSS_FEED, SourceKind.SITEMAP, SourceKind.MANUAL})

# The only (kind, strategy) pairs with an automated Phase 2 discovery
# implementation; everything else must not be queued as a guaranteed no-op.
AUTOMATED_DISCOVERY_PAIRS = frozenset(
    {
        (SourceKind.RSS_FEED, DiscoveryStrategy.FEED),
        (SourceKind.SITEMAP, DiscoveryStrategy.SITEMAP),
    }
)

MAX_REASON_LENGTH = 1000
MAX_NOTE_LENGTH = 2000
MAX_TERMS_NOTES_LENGTH = 4000

QUEUE_FAILURE_MESSAGE = "queueing the task failed; no state was changed"


class SourceRegistrationRequest(BaseModel):
    """Minimal governed registration input; no free-form JSON surfaces."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    kind: SourceKind
    base_url: str = Field(min_length=1, max_length=500)
    trust_tier: TrustTier
    locale: str = Field(default="tr-TR", min_length=2, max_length=20)
    market: str = Field(default="TR", min_length=2, max_length=2)
    terms_notes: str | None = Field(default=None, max_length=MAX_TERMS_NOTES_LENGTH)

    @field_validator("kind")
    @classmethod
    def _kind_must_be_registrable(cls, value: SourceKind) -> SourceKind:
        if value not in REGISTRABLE_SOURCE_KINDS:
            raise ValueError(
                "only rss_feed, sitemap, and manual sources are registrable "
                "through the Phase 2 control surface"
            )
        return value


class SourceLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_state: SourceLifecycleState
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)


class DiscoveryRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: DiscoveryRejectionReason
    note: str | None = Field(default=None, max_length=MAX_NOTE_LENGTH)


class DiscoveryRequeueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)


class SourceRegistrationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["registered", "existing"]
    source_id: uuid.UUID
    lifecycle_state: SourceLifecycleState


class SourceLifecycleResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["updated"]
    source_id: uuid.UUID
    lifecycle_state: SourceLifecycleState


class DiscoveryItemMutationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["updated"]
    discovery_item_id: uuid.UUID
    lifecycle_state: DiscoveryLifecycleState


class TaskTriggerResponse(BaseModel):
    """Queued acknowledgement only: no Celery task IDs or broker details."""

    model_config = ConfigDict(frozen=True)

    status: Literal["queued"]
    task: Literal["discover_source", "fetch_discovery_item"]
    entity_id: uuid.UUID


def _dispatcher(request: Request) -> Any:
    return request.app.state.research_control_dispatcher


def _current_request_id() -> str | None:
    candidate = get_request_id()
    return candidate if is_valid_request_id(candidate) else None


def _enqueue_or_503(operation: str, entity_id: uuid.UUID, publish: Any) -> None:
    """Publish one entry-point job; a transport failure is never reported as queued."""
    try:
        publish()
    except Exception as error:
        _logger.warning(
            "research_control_enqueue_failed",
            operation=operation,
            entity_id=str(entity_id),
            error_type=type(error).__name__,
        )
        raise HTTPException(status_code=503, detail=QUEUE_FAILURE_MESSAGE) from None


@router.post("/sources", response_model=SourceRegistrationResponse)
def register_research_source(
    session: Annotated[Session, Depends(get_db_session)],
    body: SourceRegistrationRequest,
) -> SourceRegistrationResponse:
    """Idempotently register a governed source; never a network request."""
    existed_before = SourceRepository(session).get_by_slug(body.slug.strip()) is not None
    service = SourceRegistryService(session)
    try:
        # discovery_strategy deliberately omitted: the service derives the
        # default strategy from the kind (feed/sitemap/manual).
        source = service.register_source(
            slug=body.slug,
            name=body.name,
            kind=body.kind,
            base_url=body.base_url,
            trust_tier=body.trust_tier,
            locale=body.locale,
            market=body.market,
            terms_notes=body.terms_notes,
        )
    except InvalidSourceDefinitionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except SourceRegistrationConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    return SourceRegistrationResponse(
        status="existing" if existed_before else "registered",
        source_id=source.id,
        lifecycle_state=source.lifecycle_state,
    )


@router.post("/sources/{source_id}/lifecycle", response_model=SourceLifecycleResponse)
def transition_research_source_lifecycle(
    session: Annotated[Session, Depends(get_db_session)],
    source_id: uuid.UUID,
    body: SourceLifecycleRequest,
) -> SourceLifecycleResponse:
    """Apply one audited lifecycle transition; the domain matrix is authoritative."""
    try:
        # Origin is fixed server-side: the control surface is the operator.
        source = SourceRegistryService(session).transition_source_state(
            source_id,
            body.new_state,
            reason=body.reason,
            origin=LifecycleChangeOrigin.OPERATOR,
        )
    except SourceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except InvalidLifecycleTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    return SourceLifecycleResponse(
        status="updated",
        source_id=source.id,
        lifecycle_state=source.lifecycle_state,
    )


@router.post("/sources/{source_id}/discover", response_model=TaskTriggerResponse)
def trigger_source_discovery(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    source_id: uuid.UUID,
) -> TaskTriggerResponse:
    """Enqueue `discover_source` for an eligible ACTIVE automated source.

    Reads eligibility only; mutates nothing. New discoveries stay DISCOVERED —
    the Task 16 admission boundary is untouched.
    """
    source = SourceRepository(session).get_by_id(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"no source with id {source_id}")
    if source.lifecycle_state is not SourceLifecycleState.ACTIVE:
        raise HTTPException(
            status_code=409,
            detail=f"source is '{source.lifecycle_state.value}', not 'active'",
        )
    if (source.kind, source.discovery_strategy) not in AUTOMATED_DISCOVERY_PAIRS:
        raise HTTPException(
            status_code=409,
            detail="source has no automated Phase 2 discovery strategy",
        )

    dispatcher = _dispatcher(request)
    request_id = _current_request_id()
    _enqueue_or_503(
        "discover_source",
        source_id,
        lambda: dispatcher.enqueue_discovery(str(source_id), request_id=request_id),
    )
    return TaskTriggerResponse(status="queued", task="discover_source", entity_id=source_id)


@router.post(
    "/discovery-items/{discovery_item_id}/accept",
    response_model=DiscoveryItemMutationResponse,
)
def accept_research_discovery_item(
    session: Annotated[Session, Depends(get_db_session)],
    discovery_item_id: uuid.UUID,
) -> DiscoveryItemMutationResponse:
    """DISCOVERED -> ACCEPTED. Never enqueues fetch: that is a second decision."""
    try:
        item = DiscoveryService(session).accept_item(discovery_item_id)
    except DiscoveryItemNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except InvalidDiscoveryTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    return DiscoveryItemMutationResponse(
        status="updated",
        discovery_item_id=item.id,
        lifecycle_state=item.lifecycle_state,
    )


@router.post(
    "/discovery-items/{discovery_item_id}/reject",
    response_model=DiscoveryItemMutationResponse,
)
def reject_research_discovery_item(
    session: Annotated[Session, Depends(get_db_session)],
    discovery_item_id: uuid.UUID,
    body: DiscoveryRejectRequest,
) -> DiscoveryItemMutationResponse:
    """DISCOVERED -> REJECTED (terminal) with an existing coded reason."""
    try:
        item = DiscoveryService(session).reject_item(discovery_item_id, body.reason, note=body.note)
    except DiscoveryItemNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except InvalidDiscoveryTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    return DiscoveryItemMutationResponse(
        status="updated",
        discovery_item_id=item.id,
        lifecycle_state=item.lifecycle_state,
    )


@router.post(
    "/discovery-items/{discovery_item_id}/requeue",
    response_model=DiscoveryItemMutationResponse,
)
def requeue_research_discovery_item(
    session: Annotated[Session, Depends(get_db_session)],
    discovery_item_id: uuid.UUID,
    body: DiscoveryRequeueRequest,
) -> DiscoveryItemMutationResponse:
    """FETCH_FAILED -> ACCEPTED with a required reason. Never starts fetch."""
    try:
        item = DiscoveryService(session).requeue_fetch(discovery_item_id, reason=body.reason)
    except DiscoveryItemNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except InvalidDiscoveryTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    return DiscoveryItemMutationResponse(
        status="updated",
        discovery_item_id=item.id,
        lifecycle_state=item.lifecycle_state,
    )


@router.post(
    "/discovery-items/{discovery_item_id}/fetch",
    response_model=TaskTriggerResponse,
)
def trigger_discovery_item_fetch(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    discovery_item_id: uuid.UUID,
) -> TaskTriggerResponse:
    """Enqueue `fetch_discovery_item` for an ACCEPTED item of an ACTIVE source.

    Accepts only the item's UUID — the durable registered entities determine
    the URL; the control API can never be handed an arbitrary URL to fetch.
    """
    item = DiscoveryItemRepository(session).get_by_id(discovery_item_id)
    if item is None:
        raise HTTPException(
            status_code=404, detail=f"no discovery item with id {discovery_item_id}"
        )
    if item.lifecycle_state is not DiscoveryLifecycleState.ACCEPTED:
        raise HTTPException(
            status_code=409,
            detail=(f"discovery item is '{item.lifecycle_state.value}', not 'accepted'"),
        )
    source = SourceRepository(session).get_by_id(item.source_id)
    if source is None or source.lifecycle_state is not SourceLifecycleState.ACTIVE:
        raise HTTPException(status_code=409, detail="the item's source is not 'active'")

    dispatcher = _dispatcher(request)
    request_id = _current_request_id()
    _enqueue_or_503(
        "fetch_discovery_item",
        discovery_item_id,
        lambda: dispatcher.enqueue_fetch(str(discovery_item_id), request_id=request_id),
    )
    return TaskTriggerResponse(
        status="queued", task="fetch_discovery_item", entity_id=discovery_item_id
    )
