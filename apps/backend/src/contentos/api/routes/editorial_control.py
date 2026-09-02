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
  or /command endpoint; approval lives ONLY on the reviewer decisions
  router, and scheduling exists ONLY as the Phase-7 governed operator
  command gated on a current approval + a durable publication package.

Server-side request correlation: the RequestContextMiddleware request id is
passed into audited domain commands and queue headers; a client-supplied
body field is never trusted for it.

Access boundary (Phase 5): every route requires an authenticated OPERATOR
session (router-level guard in the app factory); audited commands record
the named actor from `request.state.current_user`.
"""

import uuid
from typing import Annotated, Any, Literal

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Request,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from contentos.briefs.enums import BriefStatus
from contentos.briefs.errors import (
    BriefAcceptanceGateError,
    BriefNotFoundError,
    BriefStatusConflictError,
    BriefUpstreamMismatchError,
)
from contentos.briefs.repository import BriefRepository
from contentos.briefs.service import BriefService
from contentos.core.context import get_request_id, is_valid_request_id
from contentos.db.session import get_db_session
from contentos.decisions.errors import DecisionPreconditionError, StaleApprovalError
from contentos.drafts.enums import DraftBlockKind, DraftOrigin, DraftStatus
from contentos.drafts.errors import (
    DraftConflictError,
    DraftInputError,
    DraftNotFoundError,
    DraftPolicyViolationError,
    DraftPreconditionError,
    DraftStatusConflictError,
)
from contentos.drafts.repository import DraftRepository
from contentos.drafts.service import DraftService
from contentos.drafts.values import (
    MAX_BLOCK_ID_LENGTH,
    MAX_BLOCK_TEXT_LENGTH,
    MAX_BLOCKS_PER_SECTION,
    MAX_CLAIM_REFS_PER_BLOCK,
    MAX_HEADING_LENGTH,
    MAX_SECTION_KEY_LENGTH,
    MAX_SECTIONS,
    MAX_TITLE_PROPOSAL_LENGTH,
    MAX_UNCERTAINTY_REF_LENGTH,
    MAX_UNCERTAINTY_REFS_PER_BLOCK,
    DraftBlock,
    DraftBodyInput,
    DraftSection,
)
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
from contentos.media.errors import (
    MediaConflictError,
    MediaInputError,
    MediaPreconditionError,
)
from contentos.media.service import MAX_MEDIA_BYTES, MediaService
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
from contentos.publishing.assembler import PublicationAssembler
from contentos.publishing.errors import (
    PublicationInputError,
    PublicationPreconditionError,
)
from contentos.publishing.service import PublishingService
from contentos.qa.enums import WaivableGateKey
from contentos.qa.errors import QaInputError, QaPreconditionError
from contentos.qa.repository import QaRepository
from contentos.qa.service import QaService
from contentos.reviews.enums import ReviewVerdict
from contentos.reviews.repository import ReviewRepository
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
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
    "generate_writer_draft",
    "generate_editor_review",
    "run_qa_gates",
    "generate_media_image",
    "publish_package",
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


class GenerateDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retry_number: int = Field(default=0, ge=0, le=MAX_RETRY_NUMBER)
    supersede_reason: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)


class DraftBlockEntry(BaseModel):
    """EXACTLY the bounded writer-draft-body/1 block shape; the domain
    revalidates everything (safe text, slugs, refs) — these are 422 bounds."""

    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(min_length=1, max_length=MAX_BLOCK_ID_LENGTH)
    kind: DraftBlockKind
    text: str = Field(min_length=1, max_length=MAX_BLOCK_TEXT_LENGTH)
    claim_refs: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_CLAIM_REFS_PER_BLOCK)
    uncertainty_refs: list[
        Annotated[str, Field(min_length=1, max_length=MAX_UNCERTAINTY_REF_LENGTH)]
    ] = Field(default_factory=list, max_length=MAX_UNCERTAINTY_REFS_PER_BLOCK)
    link_need_ref: int | None = Field(default=None, ge=0)
    media_need_ref: int | None = Field(default=None, ge=0)


class DraftSectionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=MAX_SECTION_KEY_LENGTH)
    heading: str = Field(min_length=1, max_length=MAX_HEADING_LENGTH)
    blocks: list[DraftBlockEntry] = Field(min_length=1, max_length=MAX_BLOCKS_PER_SECTION)


class SubmitDraftRequest(BaseModel):
    """Operator-authored draft: the SAME persistence gates as the writer
    engine (structure, claim refs, policies, manual-input idempotency)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
    title_proposal: str | None = Field(default=None, max_length=MAX_TITLE_PROPOSAL_LENGTH)
    supersede_reason: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)
    sections: list[DraftSectionEntry] = Field(min_length=1, max_length=MAX_SECTIONS)


class DraftSubmissionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["created", "reused"]
    content_draft_id: uuid.UUID
    draft_version: int
    draft_origin: DraftOrigin
    draft_status: DraftStatus
    work_item_id: uuid.UUID
    work_item_state: WorkflowState


class ReworkRequest(BaseModel):
    """Rework with a BOUNDED responsible-state choice: the vocabulary is
    fixed per review context by WorkflowService, never caller-extensible."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)
    responsible_state: Literal["drafting", "editing"] = "drafting"


class WaiveQaGateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_key: Literal["media_needs"]
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)


class WaiverResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["waived"]
    work_item_id: uuid.UUID
    gate_key: Literal["media_needs"]
    note: str


class AcceptReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["accepted"]
    work_item_id: uuid.UUID
    work_item_state: WorkflowState
    editorial_review_id: uuid.UUID
    review_verdict: ReviewVerdict


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


def _current_user_id(request: Request) -> uuid.UUID | None:
    """The authenticated user resolved by the router-level guard; recorded
    on directly-performed workflow transitions (Phase 5 G3)."""
    user = getattr(request.state, "current_user", None)
    return user.id if user is not None else None


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


# --- writer draft commands ---------------------------------------------------


@router.post("/briefs/{brief_id}/generate-draft", response_model=QueuedResponse)
def generate_writer_draft(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    brief_id: uuid.UUID,
    body: GenerateDraftRequest,
) -> QueuedResponse:
    """Queue `generate_writer_draft`; no provider call ever runs in FastAPI.
    Regeneration is the SAME explicit command with retry_number+1 — the
    domain requires a supersede reason whenever an active draft exists and
    reuses the durable attempt/draft for a repeated identity."""
    if BriefRepository(session).get_brief(brief_id) is None:
        raise HTTPException(status_code=404, detail=f"no content brief with id {brief_id}")
    dispatcher = _dispatcher(request)
    request_id = _current_request_id()
    _enqueue_or_503(
        "generate_writer_draft",
        brief_id,
        lambda: dispatcher.enqueue_generate_writer_draft(
            str(brief_id),
            retry_number=body.retry_number,
            supersede_reason=body.supersede_reason,
            request_id=request_id,
        ),
    )
    return QueuedResponse(status="queued", task="generate_writer_draft", entity_id=brief_id)


@router.post("/briefs/{brief_id}/submit-draft", response_model=DraftSubmissionResponse)
def submit_operator_draft(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    brief_id: uuid.UUID,
    body: SubmitDraftRequest,
) -> DraftSubmissionResponse:
    """Operator-authored draft through the FULL persistence gates, then the
    same artifact gate as the machine path: durable draft first, then the
    explicit DRAFTING -> EDITING transition with the draft identity pinned.
    Resubmitting identical content while still DRAFTING reuses the draft
    (manual-input idempotency) and completes the transition. The Editor
    review is dispatched AFTER the commit; a dispatch failure is logged
    and non-fatal — state already advanced truthfully, and the explicit
    generate-editor-review command covers the gap."""
    draft_body = DraftBodyInput(
        sections=tuple(
            DraftSection(
                key=section.key,
                heading=section.heading,
                blocks=tuple(
                    DraftBlock(
                        block_id=block.block_id,
                        kind=block.kind,
                        text=block.text,
                        claim_refs=tuple(block.claim_refs),
                        uncertainty_refs=tuple(block.uncertainty_refs),
                        link_need_ref=block.link_need_ref,
                        media_need_ref=block.media_need_ref,
                    )
                    for block in section.blocks
                ),
            )
            for section in body.sections
        )
    )
    request_id = _current_request_id()
    try:
        creation = DraftService(session).create_operator_draft(
            brief_id,
            draft_body,
            title_proposal=body.title_proposal,
            supersede_reason=body.supersede_reason,
            request_id=request_id,
        )
    except DraftNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except (
        DraftPreconditionError,
        DraftConflictError,
        DraftStatusConflictError,
    ) as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except (DraftInputError, DraftPolicyViolationError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()

    draft = creation.draft
    # WORKFLOW.md's artifact gate: the durable valid draft is committed, so
    # the explicit transition follows — queue/HTTP completion is never state.
    item = WorkflowRepository(session).get_by_id_for_update(draft.work_item_id)
    assert item is not None
    if item.current_state is WorkflowState.DRAFTING:
        WorkflowService(session).transition(
            draft.work_item_id,
            WorkflowState.EDITING,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason=body.reason,
            artifact_refs={
                "content_brief_id": str(brief_id),
                "content_draft_id": str(draft.id),
                "draft_version": draft.version,
                "content_hash": draft.content_hash,
            },
            request_id=request_id,
            actor_user_id=_current_user_id(request),
        )
        session.commit()
    item = WorkflowRepository(session).get_by_id(draft.work_item_id)
    assert item is not None
    if item.current_state is WorkflowState.EDITING:
        # Post-commit downstream dispatch (best-effort by design here: the
        # durable state is already truthful; never 503 after a commit).
        try:
            _dispatcher(request).enqueue_generate_editor_review(
                str(draft.work_item_id),
                retry_number=0,
                supersede_reason=None,
                request_id=request_id,
            )
        except Exception as error:
            _logger.warning(
                "editorial_control_post_commit_dispatch_failed",
                operation="generate_editor_review",
                entity_id=str(draft.work_item_id),
                error_type=type(error).__name__,
            )
    return DraftSubmissionResponse(
        status="created" if creation.created else "reused",
        content_draft_id=draft.id,
        draft_version=draft.version,
        draft_origin=draft.origin,
        draft_status=draft.status,
        work_item_id=item.id,
        work_item_state=item.current_state,
    )


@router.post("/work-items/{work_item_id}/generate-editor-review", response_model=QueuedResponse)
def generate_editor_review(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
    body: GenerateDraftRequest,
) -> QueuedResponse:
    """Queue `generate_editor_review`; no provider call ever runs in
    FastAPI. Re-review is the SAME explicit command with retry_number+1 —
    the domain requires a supersede reason over an active review."""
    if WorkflowRepository(session).get_by_id(work_item_id) is None:
        raise HTTPException(
            status_code=404, detail=f"no editorial work item with id {work_item_id}"
        )
    dispatcher = _dispatcher(request)
    request_id = _current_request_id()
    _enqueue_or_503(
        "generate_editor_review",
        work_item_id,
        lambda: dispatcher.enqueue_generate_editor_review(
            str(work_item_id),
            retry_number=body.retry_number,
            supersede_reason=body.supersede_reason,
            request_id=request_id,
        ),
    )
    return QueuedResponse(status="queued", task="generate_editor_review", entity_id=work_item_id)


@router.post("/work-items/{work_item_id}/accept-review", response_model=AcceptReviewResponse)
def accept_editor_review(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
    body: ReasonRequest,
) -> AcceptReviewResponse:
    """The explicit HUMAN advance out of EDITING: requires an ACTIVE review
    with verdict `pass` pinning the ACTIVE draft, then a WorkflowService
    OPERATOR transition to QA_REVIEW with the review pinned. The Editor's
    verdict is a signal; the human is the actor."""
    if WorkflowRepository(session).get_by_id(work_item_id) is None:
        raise HTTPException(
            status_code=404, detail=f"no editorial work item with id {work_item_id}"
        )
    review = ReviewRepository(session).get_active_review(work_item_id)
    active_draft = DraftRepository(session).get_active_draft(work_item_id)
    if review is None or active_draft is None:
        raise HTTPException(
            status_code=409,
            detail="accepting requires an ACTIVE editor review over an ACTIVE draft",
        )
    if review.content_draft_id != active_draft.id:
        raise HTTPException(
            status_code=409,
            detail="the ACTIVE review does not cover the ACTIVE draft; re-review first",
        )
    if review.verdict is not ReviewVerdict.PASS:
        raise HTTPException(
            status_code=409,
            detail=f"the ACTIVE review verdict is '{review.verdict.value}', not 'pass'",
        )
    try:
        item = WorkflowService(session).transition(
            work_item_id,
            WorkflowState.QA_REVIEW,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason=body.reason,
            artifact_refs={
                "editorial_review_id": str(review.id),
                "content_draft_id": str(active_draft.id),
                "review_verdict": review.verdict.value,
                "content_hash": active_draft.content_hash,
            },
            request_id=_current_request_id(),
            actor_user_id=_current_user_id(request),
        )
    except WorkItemNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except InvalidWorkflowTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except InvalidWorkflowInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    # Post-commit downstream dispatch of the deterministic QA run
    # (best-effort by design: state already advanced truthfully).
    try:
        _dispatcher(request).enqueue_run_qa(str(work_item_id), request_id=_current_request_id())
    except Exception as error:
        _logger.warning(
            "editorial_control_post_commit_dispatch_failed",
            operation="run_qa_gates",
            entity_id=str(work_item_id),
            error_type=type(error).__name__,
        )
    return AcceptReviewResponse(
        status="accepted",
        work_item_id=item.id,
        work_item_state=item.current_state,
        editorial_review_id=review.id,
        review_verdict=review.verdict,
    )


@router.post("/work-items/{work_item_id}/request-rework", response_model=WorkItemStateResponse)
def request_writer_rework(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
    body: ReworkRequest,
) -> WorkItemStateResponse:
    """Enter CHANGES_REQUESTED with a durably recorded responsible state
    (the Task 6 routing foundation). The choice is BOUNDED: WorkflowService
    validates it against the fixed per-context vocabulary (from EDITING
    only DRAFTING; from QA_REVIEW, DRAFTING or EDITING). The current
    active draft — and the ACTIVE editor review / QA report, when they
    exist — are pinned server-side. Never an arbitrary target."""
    if WorkflowRepository(session).get_by_id(work_item_id) is None:
        raise HTTPException(
            status_code=404, detail=f"no editorial work item with id {work_item_id}"
        )
    active = DraftRepository(session).get_active_draft(work_item_id)
    refs: dict[str, Any] | None = None
    if active is not None:
        refs = {
            "content_draft_id": str(active.id),
            "draft_version": active.version,
            "content_brief_id": str(active.content_brief_id),
        }
        active_review = ReviewRepository(session).get_active_review(work_item_id)
        if active_review is not None:
            refs["editorial_review_id"] = str(active_review.id)
        active_report = QaRepository(session).get_active_report(work_item_id)
        if active_report is not None:
            refs["qa_report_id"] = str(active_report.id)
    try:
        item = WorkflowService(session).transition(
            work_item_id,
            WorkflowState.CHANGES_REQUESTED,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason=body.reason,
            artifact_refs=refs,
            request_id=_current_request_id(),
            responsible_state=WorkflowState(body.responsible_state),
            actor_user_id=_current_user_id(request),
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


@router.post("/work-items/{work_item_id}/run-qa", response_model=QueuedResponse)
def run_qa_gates(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
) -> QueuedResponse:
    """Queue the deterministic `run_qa_gates` re-run; the worker/domain owns
    every gate rule, and re-runs are idempotent by content hash."""
    if WorkflowRepository(session).get_by_id(work_item_id) is None:
        raise HTTPException(
            status_code=404, detail=f"no editorial work item with id {work_item_id}"
        )
    dispatcher = _dispatcher(request)
    request_id = _current_request_id()
    _enqueue_or_503(
        "run_qa_gates",
        work_item_id,
        lambda: dispatcher.enqueue_run_qa(str(work_item_id), request_id=request_id),
    )
    return QueuedResponse(status="queued", task="run_qa_gates", entity_id=work_item_id)


@router.post("/work-items/{work_item_id}/waive-qa-gate", response_model=WaiverResponse)
def waive_qa_gate(
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
    body: WaiveQaGateRequest,
) -> WaiverResponse:
    """Audited HUMAN waiver of one waivable gate (v1: media only). The
    waiver limits scope honestly — needs stay visible — and does NOT
    re-run the gates by itself: run-qa is the explicit next step."""
    try:
        QaService(session).add_waiver(
            work_item_id,
            WaivableGateKey(body.gate_key),
            reason=body.reason,
            request_id=_current_request_id(),
        )
    except QaPreconditionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except QaInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return WaiverResponse(
        status="waived",
        work_item_id=work_item_id,
        gate_key=body.gate_key,
        note=(
            "The waiver is recorded and audited; gates were NOT re-run. "
            "Run QA explicitly to produce a new report that consumes it."
        ),
    )


@router.post(
    "/work-items/{work_item_id}/resolve-changes-requested",
    response_model=WorkItemStateResponse,
)
def resolve_changes_requested(
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
    body: ReasonRequest,
) -> WorkItemStateResponse:
    """Route out of CHANGES_REQUESTED to the durable history-derived target
    (the recorded responsible state, else the origin) — the caller can
    never supply a target state."""
    try:
        item = WorkflowService(session).resolve_changes_requested(
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


# --- Phase 6 M2: media commands ----------------------------------------------


class MediaUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["registered", "already_exists"]
    media_asset_id: uuid.UUID
    content_sha256: str
    media_type: str
    byte_size: int


class SatisfyMediaNeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_asset_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)


class MediaSatisfactionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["satisfied", "unsatisfied"]
    work_item_id: uuid.UUID
    need_index: int
    satisfaction_id: uuid.UUID
    media_asset_id: uuid.UUID


def _media_service(request: Request, session: Session) -> MediaService:
    return MediaService(session, request.app.state.media_store)


def _current_user(request: Request) -> Any:
    user = getattr(request.state, "current_user", None)
    if user is None:  # the router guard always sets it; defense in depth
        raise HTTPException(status_code=401, detail="authentication required")
    return user


@router.post("/media-assets", response_model=MediaUploadResponse)
async def upload_media_asset(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    file: Annotated[UploadFile, File()],
    alt_text: Annotated[str, Form(min_length=1, max_length=1000)],
    license_note: Annotated[str, Form(min_length=1, max_length=1000)],
    title: Annotated[str | None, Form(max_length=1000)] = None,
    source_attribution: Annotated[str | None, Form(max_length=1000)] = None,
) -> MediaUploadResponse:
    """Operator upload into the ContentOS-owned store: server-side
    hashing, magic-sniffed type matching, honest hash-dedupe. Uploading
    satisfies nothing by itself — satisfaction is a separate command."""
    data = await file.read(MAX_MEDIA_BYTES + 1)
    try:
        asset, created = _media_service(request, session).register_upload(
            data,
            media_type=file.content_type or "",
            alt_text=alt_text,
            license_note=license_note,
            title=title,
            source_attribution=source_attribution,
            created_by=_current_user(request),
            request_id=_current_request_id(),
        )
    except MediaInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except MediaPreconditionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    session.commit()
    return MediaUploadResponse(
        status="registered" if created else "already_exists",
        media_asset_id=asset.id,
        content_sha256=asset.content_sha256,
        media_type=asset.media_type,
        byte_size=asset.byte_size,
    )


@router.post(
    "/work-items/{work_item_id}/media-needs/{need_index}/generate-image",
    response_model=QueuedResponse,
)
def generate_media_image(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
    need_index: Annotated[int, Path(ge=0, le=100)],
) -> QueuedResponse:
    """Queue ONE candidate-image generation for one brief media need,
    commissioned by the authenticated operator. Generation satisfies
    nothing by itself — a human binds the asset explicitly."""
    try:
        MediaService(session, request.app.state.media_store).resolve_need(work_item_id, need_index)
    except MediaPreconditionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except MediaInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    dispatcher = _dispatcher(request)
    request_id = _current_request_id()
    requested_by = _current_user(request)
    _enqueue_or_503(
        "generate_media_image",
        work_item_id,
        lambda: dispatcher.enqueue_generate_media_image(
            str(work_item_id),
            need_index,
            str(requested_by.id),
            request_id=request_id,
        ),
    )
    return QueuedResponse(status="queued", task="generate_media_image", entity_id=work_item_id)


@router.post(
    "/work-items/{work_item_id}/media-needs/{need_index}/satisfy",
    response_model=MediaSatisfactionResponse,
)
def satisfy_media_need(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
    need_index: int,
    body: SatisfyMediaNeedRequest,
) -> MediaSatisfactionResponse:
    """Explicit audited HUMAN binding of one brief media need to one
    asset (replacing supersedes the previous binding). Gates are NOT
    re-run by itself: run-qa is the explicit next step."""
    try:
        satisfaction = _media_service(request, session).satisfy_need(
            work_item_id,
            need_index,
            body.media_asset_id,
            user=_current_user(request),
            reason=body.reason,
            request_id=_current_request_id(),
        )
    except MediaPreconditionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except MediaConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except MediaInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return MediaSatisfactionResponse(
        status="satisfied",
        work_item_id=work_item_id,
        need_index=need_index,
        satisfaction_id=satisfaction.id,
        media_asset_id=satisfaction.media_asset_id,
    )


@router.post(
    "/work-items/{work_item_id}/media-needs/{need_index}/unsatisfy",
    response_model=MediaSatisfactionResponse,
)
def unsatisfy_media_need(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
    need_index: int,
    body: ReasonRequest,
) -> MediaSatisfactionResponse:
    """Withdraw the ACTIVE binding: the need becomes honestly
    unsatisfied again (audited; the history stays)."""
    try:
        withdrawn = _media_service(request, session).unsatisfy_need(
            work_item_id,
            need_index,
            user=_current_user(request),
            reason=body.reason,
            request_id=_current_request_id(),
        )
    except MediaPreconditionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except MediaConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except MediaInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return MediaSatisfactionResponse(
        status="unsatisfied",
        work_item_id=work_item_id,
        need_index=need_index,
        satisfaction_id=withdrawn.id,
        media_asset_id=withdrawn.media_asset_id,
    )


# --- Phase 7 P2: publication package + scheduling commands -------------------


class PublicationPackageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["assembled", "already_exists"]
    publication_package_id: uuid.UUID
    work_item_id: uuid.UUID
    version: int
    package_hash: str
    content_hash: str


class SchedulePublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publication_package_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=MAX_REASON_LENGTH)


@router.post(
    "/work-items/{work_item_id}/assemble-publication-package",
    response_model=PublicationPackageResponse,
)
def assemble_publication_package(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
) -> PublicationPackageResponse:
    """Assemble the immutable publication package from the pinned APPROVED
    artifacts under the current-approval guard. Identical content
    converges on the existing package; nothing is enriched."""
    try:
        result = PublicationAssembler(session).assemble(
            work_item_id,
            assembled_by=_current_user(request),
            request_id=_current_request_id(),
        )
    except StaleApprovalError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except DecisionPreconditionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except PublicationPreconditionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except PublicationInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return PublicationPackageResponse(
        status="assembled" if result.created else "already_exists",
        publication_package_id=result.package.id,
        work_item_id=work_item_id,
        version=result.package.version,
        package_hash=result.package.package_hash,
        content_hash=result.package.content_hash,
    )


@router.post(
    "/work-items/{work_item_id}/schedule-publication",
    response_model=WorkItemStateResponse,
)
def schedule_publication(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
    body: SchedulePublicationRequest,
) -> WorkItemStateResponse:
    """OPERATOR command APPROVED -> SCHEDULED: requires the CURRENT
    approval and an explicit durable package covering exactly the
    approved content. Scheduling publishes NOTHING by itself."""
    try:
        item = PublishingService(session).schedule_publication(
            work_item_id,
            body.publication_package_id,
            reason=body.reason,
            actor_user_id=_current_user_id(request),
            request_id=_current_request_id(),
        )
    except StaleApprovalError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except PublicationPreconditionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except InvalidWorkflowTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except InvalidWorkflowInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return WorkItemStateResponse(
        status="updated", work_item_id=item.id, current_state=item.current_state
    )


@router.post(
    "/work-items/{work_item_id}/resolve-approval-expired",
    response_model=WorkItemStateResponse,
)
def resolve_approval_expired(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
    body: ReasonRequest,
) -> WorkItemStateResponse:
    """Route out of APPROVAL_EXPIRED to the DERIVED target: back to
    AWAITING_HUMAN_REVIEW while the ACTIVE ready report still covers the
    ACTIVE draft, else back to QA_REVIEW — the caller never chooses."""
    try:
        item = PublishingService(session).resolve_approval_expired(
            work_item_id,
            reason=body.reason,
            actor_user_id=_current_user_id(request),
            request_id=_current_request_id(),
        )
    except PublicationPreconditionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except InvalidWorkflowTransitionError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except InvalidWorkflowInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    session.commit()
    return WorkItemStateResponse(
        status="updated", work_item_id=item.id, current_state=item.current_state
    )


@router.post("/work-items/{work_item_id}/publish", response_model=QueuedResponse)
def publish_work_item(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
    work_item_id: uuid.UUID,
) -> QueuedResponse:
    """Queue the governed `publish_package` dispatch. Permitted from
    SCHEDULED (normal) and PUBLISHING (re-drive after a crash or an
    unconfigured transport); the worker re-checks the approval and a
    stale one expires instead of publishing."""
    item = WorkflowRepository(session).get_by_id(work_item_id)
    if item is None:
        raise HTTPException(
            status_code=404, detail=f"no editorial work item with id {work_item_id}"
        )
    if item.current_state not in (WorkflowState.SCHEDULED, WorkflowState.PUBLISHING):
        raise HTTPException(
            status_code=409,
            detail=(
                "publication requires SCHEDULED or PUBLISHING "
                f"(current: {item.current_state.value})"
            ),
        )
    dispatcher = _dispatcher(request)
    request_id = _current_request_id()
    _enqueue_or_503(
        "publish_package",
        work_item_id,
        lambda: dispatcher.enqueue_publish(str(work_item_id), request_id=request_id),
    )
    return QueuedResponse(status="queued", task="publish_package", entity_id=work_item_id)
