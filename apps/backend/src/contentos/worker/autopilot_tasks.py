"""Autopilot worker tasks (ADR 0012).

`contentos.autopilot.step`  — ONE planner/runner step for ONE work item.
`contentos.autopilot.sweep` — enqueue a step for every actionable work item,
                              then re-arm itself while the mode is on.

The sweep is the only timer: no Celery beat. It is armed by the API when
the mode is switched on and by the worker on startup, and it stops
re-arming the moment the mode is OFF (a later switch re-arms it). Every
step commits its own trail row; a failing step never blocks the sweep."""

import uuid
from typing import Any

import structlog
from celery import Celery

from contentos.autopilot.enums import AutopilotMode
from contentos.autopilot.runner import AutopilotRunner
from contentos.autopilot.service import AutopilotService
from contentos.worker.runtime import WorkerRuntime

AUTOPILOT_STEP_TASK = "contentos.autopilot.step"
AUTOPILOT_SWEEP_TASK = "contentos.autopilot.sweep"

SWEEP_INTERVAL_SECONDS = 20
MAX_STEPS_PER_SWEEP = 50

_logger = structlog.get_logger("contentos.autopilot")


def register_autopilot_tasks(app: Celery, runtime: WorkerRuntime) -> None:
    """Explicitly register the two autopilot tasks on ``app``."""

    def enqueue_editorial(task_name: str, payload: dict[str, Any]) -> None:
        app.send_task(task_name, kwargs=payload)

    def autopilot_step(self: Any, work_item_id: str) -> dict[str, Any]:
        parsed = uuid.UUID(work_item_id)
        session = runtime.create_session()
        try:
            runner = AutopilotRunner(
                session,
                media_store=runtime.create_media_store(),
                enqueue=enqueue_editorial,
                request_id=_request_id(self),
            )
            outcome = runner.step(parsed)
            session.commit()
        except Exception as error:
            session.rollback()
            _logger.warning(
                "autopilot_step_failed",
                work_item_id=work_item_id,
                error_type=type(error).__name__,
            )
            return {"status": "failed", "work_item_id": work_item_id}
        finally:
            session.close()
        if outcome is None:
            return {"status": "missing", "work_item_id": work_item_id}
        _logger.info(
            "autopilot_step",
            work_item_id=work_item_id,
            mode=outcome.mode.value,
            action=outcome.action.name,
            kind=outcome.action.kind,
            performed=outcome.performed,
        )
        return {
            "status": "performed" if outcome.performed else outcome.action.kind,
            "work_item_id": work_item_id,
            "mode": outcome.mode.value,
            "action": outcome.action.name,
            "reason": outcome.action.reason,
        }

    def autopilot_sweep(self: Any) -> dict[str, Any]:
        session = runtime.create_session()
        try:
            mode = AutopilotService(session).mode()
            if mode is AutopilotMode.OFF:
                return {"status": "off", "steps": 0}
            work_item_ids = AutopilotRunner(session).actionable_work_item_ids(MAX_STEPS_PER_SWEEP)
        finally:
            session.close()
        for work_item_id in work_item_ids:
            app.send_task(AUTOPILOT_STEP_TASK, args=[str(work_item_id)])
        app.send_task(AUTOPILOT_SWEEP_TASK, countdown=SWEEP_INTERVAL_SECONDS)
        return {"status": "armed", "mode": mode.value, "steps": len(work_item_ids)}

    # shared=False: registered on THIS app only, never leaked into other apps.
    common_options = {"bind": True, "max_retries": 0, "acks_late": True, "shared": False}
    app.task(name=AUTOPILOT_STEP_TASK, **common_options)(autopilot_step)
    app.task(name=AUTOPILOT_SWEEP_TASK, **common_options)(autopilot_sweep)


def _request_id(task: Any) -> str | None:
    headers = getattr(task.request, "headers", None) or {}
    candidate = headers.get("request_id") if isinstance(headers, dict) else None
    return candidate if isinstance(candidate, str) and candidate else None
