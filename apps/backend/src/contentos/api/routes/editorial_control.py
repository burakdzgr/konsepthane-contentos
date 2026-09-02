"""Explicit POST-only operator commands for the Phase-3 editorial pipeline.

Every endpoint is one named business action — thin adapters only:

- direct commands call the existing transport-neutral domain services
  (commissioning, rejection, idea selection, contradiction resolution, pack
  reassembly, block resolution, brief acceptance, duplicate reopen) and
  COMMIT here; the services stay authoritative for every rule;
- queue commands validate cheap durable eligibility, then publish exactly
  one of the six frozen Task-13 editorial jobs through the producer-only
  dispatcher — the worker/domain remains authoritative, and a transport
  failure is a 503, never reported as queued;
- there is deliberately NO generic /action, /execute, /state, /transition,
  or /command endpoint, and NO publication/approval/scheduling command —
  ACCEPTED_FOR_DRAFTING is a Phase-3 writing-contract acceptance only.

Server-side request correlation: the RequestContextMiddleware request id is
passed into audited domain commands and queue headers; a client-supplied
body field is never trusted for it.

Single-operator boundary unchanged: no authentication, no roles; deployment
infrastructure remains the access boundary.
"""

import uuid
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from contentos.briefs.enums import BriefStatus
from contentos.briefs.errors import (
    BriefAcceptanceGateError,
    BriefNotFoundError,
    BriefStatusConflictError,
    BriefUpstreamMismatchError,
)
from contentos.briefs.service import BriefService
from contentos.core.context import get_request_id, is_valid_request_id
from contentos.db.session import get_db_session
from contentos.evidence_packs.enums import (
    ContradictionResolutionStatus,
    ContradictionSeverity,
    EvidenceItemRole,
    EvidencePackSufficiency,
)
from contentos.evidence_packs.errors import (
    ContradictionNotFoundError,
    EvidenceNotEligibleError,
    InvalidContradictionError,
    InvalidPackInputError,
    PackConflictError,
    PackNotFoundError,
)
from contentos.evidence_packs.service import EvidencePackService
from contentos.ideas.errors import (
    IdeaNotFoundError,
    InvalidSelectionError,
    SelectionConflictError,
)
from contentos.ideas.generation_schemas import MAX_CANDIDATES, MIN_CANDIDATES
from contentos.ideas.service import IdeaService
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.enums import OpportunityDisposition
from contentos.opportunities.errors import (
    CommissioningConflictError,
    CommissioningGateError,
    InvalidPromotionInputError,
    OpportunityNotFoundError,
    PromotionConflictError,
    PromotionNotEligibleError,
    PromotionRootNotFoundError,
    RejectionConflictError,
)
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.service import (
    OpportunityCommissioningService,
    OpportunityRejectionService,
    ResearchPromotionService,
)
from contentos.workflow.enums import WorkflowState
from contentos.workflow.errors import (
    InvalidWorkflowInputError,
    InvalidWorkflowTransitionError,
    WorkItemNotFoundError,
)
from contentos.workflow.repository import WorkflowRepository
from contentos.workflow.service import WorkflowService

_logger = structlog.get_logger("contentos.api.editorial_control")

router = APIRouter(prefix="/internal/editorial")

MAX_REASON_LENGTH = 1000
MAX_ANGLE_LENGTH = 1000
MAX_SELECTIONS = 200
MAX_CONTRADICTIONS = 50
MAX_CONTRADICTION_SIDE = 20
MAX_SIGNAL_IDS = 50
MAX_RETRY_NUMBER = 50

QUEUE_FAILURE_MESSAGE = "queueing the task failed; no state was changed"

EDITORIAL_TASK_LABELS = Literal[
    "promote_research",
    "evaluate_opportunity",
    "generate_idea_candidates",
    "build_evidence_pack",
    "analyze_search_intent",
    "compose_content_brief",
]

# Contradiction resolution: "unresolved" is not a resolution — excluding it
# here makes the invalid choice a 422 shape error, not a domain call.
RESOLVED_STATUSES = Literal[
    "resolved_cautious_wording",
    "resolved_needs_research",
    "resolved_editorial_judgment",
]


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)


class DuplicateReopenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
    distinct_angle: str = Field(min_length=1, max_length=MAX_ANGLE_LENGTH)


class GenerateIdeasRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_count: int = Field(default=3, ge=MIN_CANDIDATES, le=MAX_CANDIDATES)
    retry_number: int = Field(default=0, ge=0, le=MAX_RETRY_NUMBER)


class EvidenceSelectionEntry(BaseModel):
    """EXACTLY the accepted Task-13 bounded evidence-selection command shape."""

    model_config = ConfigDict(extra="forbid")

    research_evidence_id: uuid.UUID
    role: EvidenceItemRole
    claim_cluster: str = Field(min_length=1, max_length=100)
    display_note: str | None = Field(default=None, max_length=1000)


class ContradictionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_key: str = Field(min_length=1, max_length=100)
    evidence_side_a: list[uuid.UUID] = Field(min_length=1, max_length=MAX_CONTRADICTION_SIDE)
    evidence_side_b: list[uuid.UUID] = Field(min_length=1, max_length=MAX_CONTRADICTION_SIDE)
    nature: str = Field(min_length=1, max_length=1000)
    severity: ContradictionSeverity
    handling_recommendation: str | None = Field(default=None, max_length=1000)


class BuildPackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea_id: uuid.UUID
    selections: list[EvidenceSelectionEntry] = Field(min_length=1, max_length=MAX_SELECTIONS)
    contradictions: list[ContradictionEntry] | None = Field(
        default=None, max_length=MAX_CONTRADICTIONS
    )


class ResolveContradictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_status: RESOLVED_STATUSES
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)


class ReassemblePackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contradictions: list[ContradictionEntry] | None = Field(
        default=None, max_length=MAX_CONTRADICTIONS
    )


class AnalyzeSearchIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea_id: uuid.UUID
    evidence_pack_id: uuid.UUID
    search_signal_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_SIGNAL_IDS)
    retry_number: int = Field(default=0, ge=0, le=MAX_RETRY_NUMBER)


class ComposeBriefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idea_id: uuid.UUID
    evidence_pack_id: uuid.UUID
    search_intent_analysis_id: uuid.UUID
    retry_number: int = Field(default=0, ge=0, le=MAX_RETRY_NUMBER)
    supersede_reason: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)


class QueuedResponse(BaseModel):
    """Queued acknowledgement only: no Celery task IDs or broker details."""

    model_config = ConfigDict(frozen=True)

    status: Literal["queued"]
    task: EDITORIAL_TASK_LABELS
    entity_id: uuid.UUID


class PromotionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["created", "existing"]
    work_item_id: uuid.UUID
    opportunity_id: uuid.UUID
    duplicate_outcome: str


class CommissionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["commissioned", "already_commissioned"]
    opportunity_id: uuid.UUID
    disposition: OpportunityDisposition
    work_item_id: uuid.UUID
    work_item_state: WorkflowState
    opportunity_score_id: uuid.UUID | None


class RejectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["rejected", "already_rejected"]
    opportunity_id: uuid.UUID
    disposition: OpportunityDisposition
    work_item_id: uuid.UUID
    work_item_state: WorkflowState


class SelectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["selected", "already_selected", "deselected"]
    idea_id: uuid.UUID
    opportunity_id: uuid.UUID


class ContradictionResolutionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["resolved"]
    contradiction_id: uuid.UUID
    pack_id: uuid.UUID
    resolution_status: ContradictionResolutionStatus
    note: str


class ReassembleResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["reassembled", "unchanged"]
    evidence_pack_id: uuid.UUID
    version: int
    sufficiency: EvidencePackSufficiency
    note: str


class WorkItemStateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["updated"]
    work_item_id: uuid.UUID
    current_state: WorkflowState


class BriefAcceptanceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["accepted", "already_accepted"]
    brief_id: uuid.UUID
    brief_status: BriefStatus
    work_item_id: uuid.UUID
    work_item_state: WorkflowState


def _dispatcher(request: Request) -> Any:
    return request.app.state.editorial_control_dispatcher


def _current_request_id() -> str | None:
    candidate = get_request_id()
    return candidate if is_valid_request_id(candidate) else None


def _enqueue_or_503(operation: str, entity_id: uuid.UUID, publish: Any) -> None:
    """Publish one editorial job; a transport failure is never reported as queued."""
    try:
        publish()
    except Exception as error:
        _logger.warning(
            "editorial_control_enqueue_failed",
            operation=operation,
            entity_id=str(entity_id),
            error_type=type(error).__name__,
        )
        raise HTTPException(status_code=503, detail=QUEUE_FAILURE_MESSAGE) from None


def _selection_payload(entries: list[EvidenceSelectionEntry]) -> list[dict[str, Any]]:
    return [
        {
            "research_evidence_id": str(entry.research_evidence_id),
            "role": entry.role.value,
            "claim_cluster": entry.claim_cluster,
            "display_note": entry.display_note,
        }
        for entry in entries
    ]


def _contradiction_payload(
    entries: list[ContradictionEntry] | None,
) -> list[dict[str, Any]] | None:
    if entries is None:
        return None
    return [
        {
            "claim_key": entry.claim_key,
            "evidence_side_a": [str(value) for value in entry.evidence_side_a],
            "evidence_side_b": [str(value) for value in entry.evidence_side_b],
            "nature": entry.nature,
            "severity": entry.severity.value,
            "handling_recommendation": entry.handling_recommendation,
        }
        for entry in entries
    ]


# --- research promotion commands ---------------------------------------------


@router.post(
    "/research/{normalized_document_id}/promote",
    response_model=QueuedResponse,
)
def promote_research_document(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    normalized_document_id: uuid.UUID,
) -> QueuedResponse:
    """Queue `promote_research`; the worker/domain owns eligibility and gates."""
    if session.get(NormalizedDocument, normalized_document_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"no normalized document with id {normalized_document_id}",
        )
    dispatcher = _dispatcher(request)
    request_id = _current_request_id()
    _enqueue_or_503(
        "promote_research",
        normalized_document_id,
        lambda: dispatcher.enqueue_promote(str(normalized_document_id), request_id=request_id),
    )
    return QueuedResponse(
        status="queued", task="promote_research", entity_id=normalized_document_id
    )


@router.post(
    "/research/{normalized_document_id}/reopen-duplicate",
    response_model=PromotionResponse,
)
def reopen_duplicate_document(
    session: Annotated[Session, Depends(get_db_session)],
    normalized_document_id: uuid.UUID,
    body: DuplicateReopenRequest,
) -> PromotionResponse:
    """Explicit operator duplicate override: the DUPLICATE decision is never
    falsified, and nothing is auto-evaluated — scoring is a second command."""
    try:
        result = ResearchPromotionService(session).promote_duplicate_override(
            normalized_document_id,
            reason=body.reason,
            distinct_angle=body.distinct_angle,
            request_id=_current_request_id(),
        )
    except PromotionRootNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except (PromotionNotEligibleError, PromotionConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except InvalidPromotionInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return PromotionResponse(
        status="created" if result.created else "existing",
        work_item_id=result.work_item_id,
        opportunity_id=result.opportunity_id,
        duplicate_outcome=result.duplicate_outcome.value,
    )


# --- opportunity commands ----------------------------------------------------


@router.post("/opportunities/{opportunity_id}/evaluate", response_model=QueuedResponse)
def evaluate_opportunity(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    opportunity_id: uuid.UUID,
) -> QueuedResponse:
    """Queue `evaluate_opportunity` — explicit (re-)evaluation, never scoring
    inside the API process."""
    if OpportunityRepository(session).get_by_id(opportunity_id) is None:
        raise HTTPException(status_code=404, detail=f"no opportunity with id {opportunity_id}")
    dispatcher = _dispatcher(request)
    request_id = _current_request_id()
    _enqueue_or_503(
        "evaluate_opportunity",
        opportunity_id,
        lambda: dispatcher.enqueue_evaluate(str(opportunity_id), request_id=request_id),
    )
    return QueuedResponse(status="queued", task="evaluate_opportunity", entity_id=opportunity_id)


@router.post("/opportunities/{opportunity_id}/commission", response_model=CommissionResponse)
def commission_opportunity(
    session: Annotated[Session, Depends(get_db_session)],
    opportunity_id: uuid.UUID,
    body: ReasonRequest,
) -> CommissionResponse:
    """The explicit HUMAN commissioning decision — a direct domain command,
    never a queued task."""
    service = OpportunityCommissioningService(session)
    try:
        result = service.commission_opportunity(
            opportunity_id, reason=body.reason, request_id=_current_request_id()
        )
    except OpportunityNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except (CommissioningGateError, CommissioningConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except InvalidPromotionInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    work_item = WorkflowRepository(session).get_by_id(result.opportunity.work_item_id)
    assert work_item is not None
    return CommissionResponse(
        status="commissioned" if result.commissioned else "already_commissioned",
        opportunity_id=result.opportunity.id,
        disposition=result.opportunity.disposition,
        work_item_id=work_item.id,
        work_item_state=work_item.current_state,
        opportunity_score_id=result.opportunity_score_id,
    )


@router.post("/opportunities/{opportunity_id}/reject", response_model=RejectionResponse)
def reject_opportunity(
    session: Annotated[Session, Depends(get_db_session)],
    opportunity_id: uuid.UUID,
    body: ReasonRequest,
) -> RejectionResponse:
    """Explicit operator rejection of an OPEN opportunity in IDEA_SCORING."""
    try:
        result = OpportunityRejectionService(session).reject_opportunity(
            opportunity_id, reason=body.reason, request_id=_current_request_id()
        )
    except OpportunityNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except RejectionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except InvalidPromotionInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    work_item = WorkflowRepository(session).get_by_id(result.opportunity.work_item_id)
    assert work_item is not None
    return RejectionResponse(
        status="rejected" if result.rejected else "already_rejected",
        opportunity_id=result.opportunity.id,
        disposition=result.opportunity.disposition,
        work_item_id=work_item.id,
        work_item_state=work_item.current_state,
    )


@router.post("/opportunities/{opportunity_id}/generate-ideas", response_model=QueuedResponse)
def generate_idea_candidates(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    opportunity_id: uuid.UUID,
    body: GenerateIdeasRequest,
) -> QueuedResponse:
    """Queue `generate_idea_candidates`; no OpenAI call ever runs in FastAPI,
    and nothing here selects a generated idea."""
    if OpportunityRepository(session).get_by_id(opportunity_id) is None:
        raise HTTPException(status_code=404, detail=f"no opportunity with id {opportunity_id}")
    dispatcher = _dispatcher(request)
    request_id = _current_request_id()
    _enqueue_or_503(
        "generate_idea_candidates",
        opportunity_id,
        lambda: dispatcher.enqueue_generate_ideas(
            str(opportunity_id),
            candidate_count=body.candidate_count,
            retry_number=body.retry_number,
            request_id=request_id,
        ),
    )
    return QueuedResponse(
        status="queued", task="generate_idea_candidates", entity_id=opportunity_id
    )


@router.post(
    "/opportunities/{opportunity_id}/evidence-packs/build",
    response_model=QueuedResponse,
)
def build_evidence_pack(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    opportunity_id: uuid.UUID,
    body: BuildPackRequest,
) -> QueuedResponse:
    """Queue `build_evidence_pack` with the operator's EXPLICIT selections —
    assembly never runs in FastAPI and no selection heuristic exists."""
    if OpportunityRepository(session).get_by_id(opportunity_id) is None:
        raise HTTPException(status_code=404, detail=f"no opportunity with id {opportunity_id}")
    dispatcher = _dispatcher(request)
    request_id = _current_request_id()
    _enqueue_or_503(
        "build_evidence_pack",
        opportunity_id,
        lambda: dispatcher.enqueue_build_pack(
            str(opportunity_id),
            idea_id=str(body.idea_id),
            selections=_selection_payload(body.selections),
            contradictions=_contradiction_payload(body.contradictions),
            request_id=request_id,
        ),
    )
    return QueuedResponse(status="queued", task="build_evidence_pack", entity_id=opportunity_id)


@router.post(
    "/opportunities/{opportunity_id}/analyze-search-intent",
    response_model=QueuedResponse,
)
def analyze_search_intent(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    opportunity_id: uuid.UUID,
    body: AnalyzeSearchIntentRequest,
) -> QueuedResponse:
    """Queue `analyze_search_intent` with EXACT pinned inputs — no implicit
    latest-signal lookup, no live search-provider call, SEO_RESEARCH only."""
    opportunity = OpportunityRepository(session).get_by_id(opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail=f"no opportunity with id {opportunity_id}")
    work_item = WorkflowRepository(session).get_by_id(opportunity.work_item_id)
    if work_item is None or work_item.current_state is not WorkflowState.SEO_RESEARCH:
        state = work_item.current_state.value if work_item else "missing"
        raise HTTPException(
            status_code=409,
            detail=f"search-intent analysis requires SEO_RESEARCH (current: {state})",
        )
    dispatcher = _dispatcher(request)
    request_id = _current_request_id()
    _enqueue_or_503(
        "analyze_search_intent",
        opportunity_id,
        lambda: dispatcher.enqueue_analyze_intent(
            str(opportunity_id),
            idea_id=str(body.idea_id),
            evidence_pack_id=str(body.evidence_pack_id),
            signal_ids=[str(value) for value in body.search_signal_ids],
            retry_number=body.retry_number,
            request_id=request_id,
        ),
    )
    return QueuedResponse(status="queued", task="analyze_search_intent", entity_id=opportunity_id)


# --- idea commands -----------------------------------------------------------


@router.post("/ideas/{idea_id}/select", response_model=SelectionResponse)
def select_idea(
    session: Annotated[Session, Depends(get_db_session)],
    idea_id: uuid.UUID,
    body: ReasonRequest,
) -> SelectionResponse:
    """Explicit operator selection of this EXACT idea version; no workflow
    transition ever results from selection."""
    try:
        result = IdeaService(session).select_idea(
            idea_id, reason=body.reason, request_id=_current_request_id()
        )
    except IdeaNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except SelectionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except InvalidSelectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return SelectionResponse(
        status="selected" if result.created else "already_selected",
        idea_id=result.event.idea_id,
        opportunity_id=result.event.opportunity_id,
    )


@router.post("/ideas/{idea_id}/deselect", response_model=SelectionResponse)
def deselect_idea(
    session: Annotated[Session, Depends(get_db_session)],
    idea_id: uuid.UUID,
    body: ReasonRequest,
) -> SelectionResponse:
    """Explicit operator deselection; never resurrects an older selection."""
    try:
        result = IdeaService(session).deselect_idea(
            idea_id, reason=body.reason, request_id=_current_request_id()
        )
    except IdeaNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except SelectionConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except InvalidSelectionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return SelectionResponse(
        status="deselected",
        idea_id=result.event.idea_id,
        opportunity_id=result.event.opportunity_id,
    )


# --- evidence pack commands --------------------------------------------------


@router.post(
    "/contradictions/{contradiction_id}/resolve",
    response_model=ContradictionResolutionResponse,
)
def resolve_contradiction(
    session: Annotated[Session, Depends(get_db_session)],
    contradiction_id: uuid.UUID,
    body: ResolveContradictionRequest,
) -> ContradictionResolutionResponse:
    """Audited operator resolution of one contradiction row."""
    try:
        contradiction = EvidencePackService(session).resolve_contradiction(
            contradiction_id,
            resolution_status=ContradictionResolutionStatus(body.resolution_status),
            reason=body.reason,
        )
    except ContradictionNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except InvalidContradictionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    return ContradictionResolutionResponse(
        status="resolved",
        contradiction_id=contradiction.id,
        pack_id=contradiction.pack_id,
        resolution_status=contradiction.resolution_status,
        note=(
            "The parent pack's stored sufficiency is unchanged; reassemble a "
            "new pack version to reflect this resolution."
        ),
    )


@router.post("/evidence-packs/{pack_id}/reassemble", response_model=ReassembleResponse)
def reassemble_evidence_pack(
    session: Annotated[Session, Depends(get_db_session)],
    pack_id: uuid.UUID,
    body: ReassemblePackRequest | None = None,
) -> ReassembleResponse:
    """Produce a NEW immutable pack version reflecting current contradiction
    state. The old version stays untouched, and no workflow state advances
    here — dispatching analysis after a READY reassembly stays an explicit
    operator decision (a Task-13 orchestration boundary, reported)."""
    contradictions = None
    if body is not None and body.contradictions is not None:
        from contentos.evidence_packs.service import ContradictionDeclaration

        contradictions = [
            ContradictionDeclaration(
                claim_key=entry.claim_key,
                evidence_side_a=tuple(entry.evidence_side_a),
                evidence_side_b=tuple(entry.evidence_side_b),
                nature=entry.nature,
                severity=entry.severity,
                handling_recommendation=entry.handling_recommendation,
            )
            for entry in body.contradictions
        ]
    try:
        assembly = EvidencePackService(session).reassemble_pack(
            pack_id, additional_contradictions=contradictions
        )
    except PackNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except (EvidenceNotEligibleError, PackConflictError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except InvalidPackInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return ReassembleResponse(
        status="reassembled" if assembly.created else "unchanged",
        evidence_pack_id=assembly.pack.id,
        version=assembly.pack.version,
        sufficiency=assembly.pack.sufficiency,
        note=(
            "Workflow state does not advance automatically; continuing with a "
            "READY pack is the next explicit operator step."
        ),
    )


# --- work item commands ------------------------------------------------------


@router.post("/work-items/{work_item_id}/resolve-block", response_model=WorkItemStateResponse)
def resolve_work_item_block(
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
    body: ReasonRequest,
) -> WorkItemStateResponse:
    """Resolve BLOCKED back to the history-derived prior state — the caller
    can never supply a target state."""
    try:
        item = WorkflowService(session).resolve_block(
            work_item_id, reason=body.reason, request_id=_current_request_id()
        )
    except WorkItemNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except InvalidWorkflowTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except InvalidWorkflowInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return WorkItemStateResponse(
        status="updated", work_item_id=item.id, current_state=item.current_state
    )


@router.post("/work-items/{work_item_id}/reject-blocked", response_model=WorkItemStateResponse)
def reject_blocked_work_item(
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
    body: ReasonRequest,
) -> WorkItemStateResponse:
    """Explicit audited BLOCKED -> REJECTED; no arbitrary target selection."""
    try:
        item = WorkflowService(session).reject_blocked(
            work_item_id, reason=body.reason, request_id=_current_request_id()
        )
    except WorkItemNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except InvalidWorkflowTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except InvalidWorkflowInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return WorkItemStateResponse(
        status="updated", work_item_id=item.id, current_state=item.current_state
    )


@router.post("/work-items/{work_item_id}/compose-brief", response_model=QueuedResponse)
def compose_content_brief(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
    body: ComposeBriefRequest,
) -> QueuedResponse:
    """Queue `compose_content_brief` with exact pins; composition never runs
    in FastAPI and the result is a DRAFT — acceptance stays separate."""
    if WorkflowRepository(session).get_by_id(work_item_id) is None:
        raise HTTPException(
            status_code=404, detail=f"no editorial work item with id {work_item_id}"
        )
    dispatcher = _dispatcher(request)
    request_id = _current_request_id()
    _enqueue_or_503(
        "compose_content_brief",
        work_item_id,
        lambda: dispatcher.enqueue_compose_brief(
            str(work_item_id),
            idea_id=str(body.idea_id),
            evidence_pack_id=str(body.evidence_pack_id),
            search_intent_analysis_id=str(body.search_intent_analysis_id),
            retry_number=body.retry_number,
            supersede_reason=body.supersede_reason,
            request_id=request_id,
        ),
    )
    return QueuedResponse(status="queued", task="compose_content_brief", entity_id=work_item_id)


# --- brief commands ----------------------------------------------------------


@router.post("/briefs/{brief_id}/accept", response_model=BriefAcceptanceResponse)
def accept_brief_for_drafting(
    session: Annotated[Session, Depends(get_db_session)],
    brief_id: uuid.UUID,
    body: ReasonRequest,
) -> BriefAcceptanceResponse:
    """Accept-for-drafting: the Task-11 gates decide; this is NOT publication
    approval — it only releases the writing contract to Phase 4."""
    try:
        acceptance = BriefService(session).accept_for_drafting(
            brief_id, reason=body.reason, request_id=_current_request_id()
        )
    except BriefNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except (
        BriefStatusConflictError,
        BriefAcceptanceGateError,
        BriefUpstreamMismatchError,
    ) as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    work_item = WorkflowRepository(session).get_by_id(acceptance.brief.work_item_id)
    assert work_item is not None
    return BriefAcceptanceResponse(
        status="accepted" if acceptance.accepted else "already_accepted",
        brief_id=acceptance.brief.id,
        brief_status=acceptance.brief.status,
        work_item_id=work_item.id,
        work_item_state=work_item.current_state,
    )
