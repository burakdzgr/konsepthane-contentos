"""Research mission CRUD and read helpers (the engine does the thinking)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.missions.enums import MissionStage, MissionStatus
from contentos.missions.models import MissionIdeaCandidate, MissionSignal, ResearchMission
from contentos.strategy.models import TopicCluster

MAX_TOPIC = 300
MAX_AUDIENCE = 300
MAX_SEED = 240


@dataclass(frozen=True, slots=True)
class MissionInput:
    topic: str
    goal: str
    audience: str
    seed_keyword: str | None = None
    topic_cluster_id: uuid.UUID | None = None
    locale: str = "tr-TR"
    market: str = "TR"


class ResearchMissionService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, data: MissionInput) -> ResearchMission:
        topic = " ".join(data.topic.split())
        goal = data.goal.strip()
        audience = " ".join(data.audience.split())
        if not topic or not goal or not audience:
            raise ValueError("konu, amaç ve hedef kitle zorunludur")
        if data.topic_cluster_id is not None and (
            self._session.get(TopicCluster, data.topic_cluster_id) is None
        ):
            raise LookupError("konu kümesi bulunamadı")
        seed = " ".join((data.seed_keyword or "").split()) or None
        row = ResearchMission(
            topic=topic[:MAX_TOPIC],
            goal=goal,
            audience=audience[:MAX_AUDIENCE],
            seed_keyword=seed[:MAX_SEED] if seed else None,
            topic_cluster_id=data.topic_cluster_id,
            locale=data.locale,
            market=data.market,
            status=MissionStatus.DRAFT,
            stage=MissionStage.PLANNING,
            plan={},
            query_plan=[],
            keyword_plan=[],
            surface_summary={},
            elimination_summary={},
            result_summary={},
            progress_log=[],
        )
        self._session.add(row)
        self._session.flush()
        return row

    def mark_queued(self, mission_id: uuid.UUID) -> ResearchMission:
        """Idempotent: a mission that is already running stays running."""
        row = self.get(mission_id)
        if row.status in (MissionStatus.RUNNING, MissionStatus.GROUNDING):
            return row
        row.status = MissionStatus.QUEUED
        row.progress_log = [
            *row.progress_log,
            {"stage": row.stage.value, "status": "queued", "note": "Araştırma kuyruğa alındı"},
        ]
        self._session.flush()
        return row

    def list_missions(self) -> list[ResearchMission]:
        return list(
            self._session.scalars(
                select(ResearchMission).order_by(ResearchMission.created_at.desc())
            )
        )

    def get(self, mission_id: uuid.UUID) -> ResearchMission:
        row = self._session.get(ResearchMission, mission_id)
        if row is None:
            raise LookupError("araştırma görevi bulunamadı")
        return row

    def signals(self, mission_id: uuid.UUID) -> list[MissionSignal]:
        self.get(mission_id)
        return list(
            self._session.scalars(
                select(MissionSignal)
                .where(MissionSignal.mission_id == mission_id)
                .order_by(MissionSignal.surface_kind, MissionSignal.created_at)
            )
        )

    def candidates(self, mission_id: uuid.UUID) -> list[MissionIdeaCandidate]:
        self.get(mission_id)
        return list(
            self._session.scalars(
                select(MissionIdeaCandidate)
                .where(MissionIdeaCandidate.mission_id == mission_id)
                .order_by(MissionIdeaCandidate.idea_quality.desc(), MissionIdeaCandidate.title)
            )
        )
