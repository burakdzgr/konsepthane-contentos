"""Simple Turkish-first strategy management API for operators."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.db.session import get_db_session
from contentos.inspiration.enums import (
    InspirationBand,
    OpportunityRecommendation,
    SearchOpportunityBand,
    TrendState,
)
from contentos.inspiration.service import InspirationIntelligenceService
from contentos.strategy.enums import StrategyStatus
from contentos.strategy.models import AudienceStrategy, StrategicKeyword, TopicCluster
from contentos.strategy.service import StrategyService

router = APIRouter(prefix="/internal/strategy")


class StrategyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    priority: int = Field(ge=0, le=100)
    status: StrategyStatus = StrategyStatus.ACTIVE
    notes: str | None = Field(default=None, max_length=2000)


class KeywordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phrase: str = Field(min_length=1, max_length=240)
    priority: int = Field(ge=0, le=100)
    status: StrategyStatus = StrategyStatus.ACTIVE
    topic_cluster_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)


class AudienceView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)
    id: uuid.UUID
    name: str
    priority: int
    status: StrategyStatus
    notes: str | None


class ClusterView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)
    id: uuid.UUID
    name: str
    slug: str
    priority: int
    status: StrategyStatus
    notes: str | None


class KeywordView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)
    id: uuid.UUID
    phrase: str
    priority: int
    status: StrategyStatus
    topic_cluster_id: uuid.UUID | None
    notes: str | None


class StrategyOverview(BaseModel):
    model_config = ConfigDict(frozen=True)
    audiences: list[AudienceView]
    clusters: list[ClusterView]
    keywords: list[KeywordView]


class IntelligenceView(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["evaluated"]
    evaluation_id: uuid.UUID
    inspiration_band: InspirationBand
    search_opportunity: SearchOpportunityBand
    trend_state: TrendState
    recommendation: OpportunityRecommendation
    rationale: str
    signals_created: int


def _commit_or_conflict(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="aynı kapsamda bu kayıt zaten var") from None


@router.get("/overview", response_model=StrategyOverview)
def overview(session: Annotated[Session, Depends(get_db_session)]) -> StrategyOverview:
    service = StrategyService(session)
    return StrategyOverview(
        audiences=[AudienceView.model_validate(row) for row in service.list_audiences()],
        clusters=[ClusterView.model_validate(row) for row in service.list_clusters()],
        keywords=[KeywordView.model_validate(row) for row in service.list_keywords()],
    )


@router.post("/audiences", response_model=AudienceView, status_code=201)
def create_audience(
    body: StrategyInput, session: Annotated[Session, Depends(get_db_session)]
) -> AudienceStrategy:
    try:
        row = StrategyService(session).create_audience(**body.model_dump())
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from None
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="aynı kapsamda bu kayıt zaten var") from None
    _commit_or_conflict(session)
    return row


@router.post("/audiences/{audience_id}", response_model=AudienceView)
def update_audience(
    audience_id: uuid.UUID,
    body: StrategyInput,
    session: Annotated[Session, Depends(get_db_session)],
) -> AudienceStrategy:
    try:
        row = StrategyService(session).update_audience(audience_id, **body.model_dump())
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from None
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="aynı kapsamda bu kayıt zaten var") from None
    _commit_or_conflict(session)
    return row


@router.post("/clusters", response_model=ClusterView, status_code=201)
def create_cluster(
    body: StrategyInput, session: Annotated[Session, Depends(get_db_session)]
) -> TopicCluster:
    try:
        row = StrategyService(session).create_cluster(**body.model_dump())
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from None
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="aynı kapsamda bu kayıt zaten var") from None
    _commit_or_conflict(session)
    return row


@router.post("/clusters/{cluster_id}", response_model=ClusterView)
def update_cluster(
    cluster_id: uuid.UUID, body: StrategyInput, session: Annotated[Session, Depends(get_db_session)]
) -> TopicCluster:
    try:
        row = StrategyService(session).update_cluster(cluster_id, **body.model_dump())
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from None
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="aynı kapsamda bu kayıt zaten var") from None
    _commit_or_conflict(session)
    return row


@router.post("/keywords", response_model=KeywordView, status_code=201)
def create_keyword(
    body: KeywordInput, session: Annotated[Session, Depends(get_db_session)]
) -> StrategicKeyword:
    try:
        row = StrategyService(session).create_keyword(**body.model_dump())
    except LookupError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from None
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="aynı kapsamda bu kayıt zaten var") from None
    _commit_or_conflict(session)
    return row


@router.post("/keywords/{keyword_id}", response_model=KeywordView)
def update_keyword(
    keyword_id: uuid.UUID, body: KeywordInput, session: Annotated[Session, Depends(get_db_session)]
) -> StrategicKeyword:
    try:
        row = StrategyService(session).update_keyword(keyword_id, **body.model_dump())
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except ValueError as error:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from None
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="aynı kapsamda bu kayıt zaten var") from None
    _commit_or_conflict(session)
    return row


@router.post("/opportunities/{opportunity_id}/evaluate", response_model=IntelligenceView)
def evaluate_opportunity_intelligence(
    opportunity_id: uuid.UUID, session: Annotated[Session, Depends(get_db_session)]
) -> IntelligenceView:
    try:
        result = InspirationIntelligenceService(session).evaluate(opportunity_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    session.commit()
    row = result.evaluation
    return IntelligenceView(
        status="evaluated",
        evaluation_id=row.id,
        inspiration_band=row.inspiration_band,
        search_opportunity=row.search_opportunity,
        trend_state=row.trend_state,
        recommendation=row.recommendation,
        rationale=row.rationale,
        signals_created=result.signals_created,
    )
