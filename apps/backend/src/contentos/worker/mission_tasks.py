"""Celery tasks of the research-driven idea engine.

`run_mission` executes the planning→evaluating→grounding stages and commits
after each one (the operator watches live progress). `finalize_mission`
promotes grounded ideas and re-checks while the intake chain fetches the
pages behind open-web signals; it gives up after the grounding window.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from celery import Celery
from sqlalchemy.orm import Session

from contentos.integrations.registry import create_integration_registry
from contentos.missions.engine import MissionEngine
from contentos.missions.enums import MissionStatus
from contentos.missions.models import ResearchMission
from contentos.worker.research_tasks import FETCH_DISCOVERY_ITEM_TASK
from contentos.worker.runtime import WorkerRuntime

RUN_MISSION_TASK = "contentos.research.run_mission"
FINALIZE_MISSION_TASK = "contentos.research.finalize_mission"
EVALUATE_OPPORTUNITY_TASK = "contentos.editorial.evaluate_opportunity"

FINALIZE_DELAY_SECONDS = 60
EVALUATE_DELAY_SECONDS = 180
MAX_FINALIZE_CHECKS = 16

_logger = structlog.get_logger(__name__)


# A run that shows no progress for this long was killed with its worker
# (acks_late redelivery); the redelivered task may start over.
STALE_RUN = timedelta(minutes=20)


def _stale(mission: ResearchMission) -> bool:
    raw = mission.result_summary.get("run_started_at")
    log = mission.progress_log
    last = log[-1].get("at") if log and isinstance(log[-1], dict) else None
    stamp = last if isinstance(last, str) else raw
    if not isinstance(stamp, str):
        return True
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return True
    return datetime.now(UTC) - moment > STALE_RUN


def register_mission_tasks(app: Celery, runtime: WorkerRuntime) -> None:
    @contextmanager
    def task_session() -> Iterator[Session]:
        session = runtime.create_session()
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def engine_for(session: Session) -> MissionEngine:
        provider = (
            runtime.create_generation_provider()
            if runtime.settings.text_provider_configured
            else None
        )
        registry = create_integration_registry(runtime.settings)
        return MissionEngine(
            session,
            provider=provider,
            registry=registry,
            dispatch_fetch=lambda item_id: app.send_task(FETCH_DISCOVERY_ITEM_TASK, args=[item_id]),
            checkpoint=session.commit,
        )

    def run_mission(self: Any, mission_id: str) -> dict[str, Any]:
        parsed = uuid.UUID(mission_id)
        with task_session() as session:
            mission = session.get(ResearchMission, parsed)
            if mission is None:
                return {"status": "missing", "mission_id": mission_id}
            if mission.status in (MissionStatus.RUNNING, MissionStatus.GROUNDING) and not _stale(
                mission
            ):
                return {"status": "already_running", "mission_id": mission_id}
            engine = engine_for(session)
            try:
                engine.run(parsed)
            except Exception as error:  # noqa: BLE001 - the mission row records the failure
                session.commit()
                _logger.warning(
                    "mission_run_failed", mission_id=mission_id, error=type(error).__name__
                )
                return {"status": "failed", "mission_id": mission_id, "error": type(error).__name__}
            session.commit()
        app.send_task(FINALIZE_MISSION_TASK, args=[mission_id], kwargs={"check": 1}, countdown=5)
        return {"status": "grounding", "mission_id": mission_id}

    def finalize_mission(self: Any, mission_id: str, check: int = 1) -> dict[str, Any]:
        parsed = uuid.UUID(mission_id)
        with task_session() as session:
            engine = engine_for(session)
            outcome = engine.finalize(parsed)
            session.commit()
        # Only after the commit (the scoring task must find the rows), and
        # after the grounded pages' evidence extraction had time to land:
        # scoring an idea before its facts exist reads as "no evidence".
        for opportunity_id in outcome.newly_promoted:
            app.send_task(
                EVALUATE_OPPORTUNITY_TASK,
                kwargs={"opportunity_id": str(opportunity_id)},
                countdown=EVALUATE_DELAY_SECONDS,
            )
        if outcome.done or check >= MAX_FINALIZE_CHECKS:
            if not outcome.done:
                with task_session() as session:
                    mission = session.get(ResearchMission, parsed)
                    if mission is not None and mission.status is MissionStatus.GROUNDING:
                        # Give up waiting: close with what was grounded.
                        engine = engine_for(session)
                        engine._complete(  # noqa: SLF001 - deliberate close-out
                            mission, list(outcome.promoted), outcome.pending_fetches
                        )
                        session.commit()
            return {
                "status": "completed",
                "mission_id": mission_id,
                "promoted": [str(value) for value in outcome.promoted],
                "pending_fetches": outcome.pending_fetches,
            }
        app.send_task(
            FINALIZE_MISSION_TASK,
            args=[mission_id],
            kwargs={"check": check + 1},
            countdown=FINALIZE_DELAY_SECONDS,
        )
        return {
            "status": "waiting",
            "mission_id": mission_id,
            "check": check,
            "pending_fetches": outcome.pending_fetches,
        }

    options: dict[str, Any] = {"bind": True, "shared": False, "acks_late": True, "max_retries": 0}
    app.task(name=RUN_MISSION_TASK, **options)(run_mission)
    app.task(name=FINALIZE_MISSION_TASK, **options)(finalize_mission)
