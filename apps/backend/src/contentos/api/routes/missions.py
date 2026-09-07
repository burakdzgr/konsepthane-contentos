"""Operator-facing research mission API (Turkish-first, queue-backed).

Creating a mission queues its run; the worker commits progress stage by
stage, and the detail endpoint reflects durable state only.
"""

import uuid
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from contentos.db.session import get_db_session
from contentos.missions.enums import MissionStatus
from contentos.missions.models import MissionIdeaCandidate, ResearchMission
from contentos.missions.service import MissionInput, ResearchMissionService
from contentos.opportunities.models import EditorialOpportunity

router = APIRouter(prefix="/internal/research-missions")

RUN_MISSION_TASK = "contentos.research.run_mission"


class MissionDispatcher(Protocol):
    def enqueue_run(self, mission_id: str) -> None: ...


class CeleryMissionDispatcher:
    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._app: Any = None

    def enqueue_run(self, mission_id: str) -> None:
        if self._app is None:
            from contentos.queue.celery import create_celery_app

            self._app = create_celery_app(self._settings)
        self._app.send_task(RUN_MISSION_TASK, args=[mission_id])


def _dispatcher(request: Request) -> MissionDispatcher:
    existing = getattr(request.app.state, "mission_dispatcher", None)
    if existing is None:
        existing = CeleryMissionDispatcher(request.app.state.settings)
        request.app.state.mission_dispatcher = existing
    return existing


class MissionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=300)
    goal: str = Field(min_length=1, max_length=2000)
    audience: str = Field(min_length=1, max_length=300)
    seed_keyword: str | None = Field(default=None, max_length=240)
    topic_cluster_id: uuid.UUID | None = None


class MissionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    topic: str
    goal: str
    audience: str
    seed_keyword: str | None
    topic_cluster_id: uuid.UUID | None
    locale: str
    market: str
    status: str
    stage: str
    plan: dict[str, Any]
    query_plan: list[dict[str, Any]]
    keyword_plan: list[dict[str, Any]]
    surface_summary: dict[str, Any]
    elimination_summary: dict[str, Any]
    result_summary: dict[str, Any]
    progress_log: list[dict[str, Any]]
    failure_reason: str | None


class SignalView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    surface_kind: str
    title: str
    snippet: str | None
    reference_url: str | None
    query: str | None
    signal_role: str
    normalized_document_id: uuid.UUID | None
    provenance: dict[str, Any]


class CandidateView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    angle: str
    candidate_kind: str
    cluster_key: str
    primitives: list[dict[str, Any]]
    implementation_steps: list[str]
    factual_claims_needed: list[str]
    signal_ids: list[str]
    is_cliche: bool
    cliche_reason: str | None
    idea_quality: int
    quality_factors: dict[str, Any]
    idea_confidence: str
    factual_evidence_confidence: str
    recommendation: str
    merged_into_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None
    work_item_id: uuid.UUID | None = None
    rationale: str


class MissionDetail(BaseModel):
    mission: MissionView
    signals: list[SignalView]
    candidates: list[CandidateView]


class QueuedMission(BaseModel):
    mission: MissionView
    queued: bool


def _not_found(error: LookupError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(error))


@router.get("", response_model=list[MissionView])
def list_missions(session: Annotated[Session, Depends(get_db_session)]) -> list[ResearchMission]:
    return ResearchMissionService(session).list_missions()


@router.post("", response_model=QueuedMission, status_code=201)
def create_mission(
    body: MissionCreate,
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
) -> QueuedMission:
    service = ResearchMissionService(session)
    try:
        row = service.create(MissionInput(**body.model_dump()))
        service.mark_queued(row.id)
        session.commit()
    except (ValueError, LookupError) as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from None
    queued = _enqueue(request, session, row)
    return QueuedMission(mission=MissionView.model_validate(row), queued=queued)


@router.get("/{mission_id}", response_model=MissionDetail)
def get_mission(
    mission_id: uuid.UUID, session: Annotated[Session, Depends(get_db_session)]
) -> MissionDetail:
    service = ResearchMissionService(session)
    try:
        row = service.get(mission_id)
    except LookupError as error:
        raise _not_found(error) from None
    return MissionDetail(
        mission=MissionView.model_validate(row),
        signals=[SignalView.model_validate(x) for x in service.signals(mission_id)],
        candidates=[_candidate_view(session, x) for x in service.candidates(mission_id)],
    )


def _candidate_view(session: Session, candidate: MissionIdeaCandidate) -> CandidateView:
    view = CandidateView.model_validate(candidate)
    if candidate.opportunity_id is not None:
        opportunity = session.get(EditorialOpportunity, candidate.opportunity_id)
        if opportunity is not None:
            view.work_item_id = opportunity.work_item_id
    return view


@router.post("/{mission_id}/run", response_model=QueuedMission)
def run_mission(
    mission_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
) -> QueuedMission:
    service = ResearchMissionService(session)
    try:
        row = service.get(mission_id)
    except LookupError as error:
        raise _not_found(error) from None
    if row.status in (MissionStatus.RUNNING, MissionStatus.GROUNDING):
        return QueuedMission(mission=MissionView.model_validate(row), queued=False)
    service.mark_queued(row.id)
    session.commit()
    queued = _enqueue(request, session, row)
    return QueuedMission(mission=MissionView.model_validate(row), queued=queued)


def _enqueue(request: Request, session: Session, row: ResearchMission) -> bool:
    try:
        _dispatcher(request).enqueue_run(str(row.id))
    except Exception as error:  # noqa: BLE001 - durable state stays truthful
        row.status = MissionStatus.FAILED
        row.failure_reason = f"kuyruğa alınamadı: {type(error).__name__}"
        session.commit()
        return False
    return True


__all__ = ["CeleryMissionDispatcher", "MissionDispatcher", "router"]
