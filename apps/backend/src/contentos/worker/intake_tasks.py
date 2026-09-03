"""The self-rescheduling autonomous intake step task.

One task, one bounded slice: the orchestrator decides what the durable
state admits, the task commits, publishes the resulting frozen pipeline
jobs (fetch / promote), and re-enqueues itself until the run reaches a
terminal status. Late acknowledgement means a lost worker requeues the
step; every decision re-derives from durable rows, so at-least-once
delivery is safe by construction.
"""

import uuid
from typing import Any

import structlog
from celery import Celery

from contentos.intake.enums import IntakeEventKind, IntakeRunStatus, IntakeStage
from contentos.intake.errors import IntakeRunNotFoundError
from contentos.intake.orchestrator import IntakeOrchestrator
from contentos.intake.service import IntakeRunService
from contentos.worker.editorial_tasks import PROMOTE_RESEARCH_TASK
from contentos.worker.research_tasks import FETCH_DISCOVERY_ITEM_TASK
from contentos.worker.runtime import WorkerRuntime

INTAKE_STEP_TASK = "contentos.intake.step"

MAX_STEP_RETRIES = 5
STEP_RETRY_SECONDS = 60

_logger = structlog.get_logger("contentos.worker.intake")


def register_intake_tasks(app: Celery, runtime: WorkerRuntime) -> None:
    def intake_step(self: Any, run_id: str) -> dict[str, Any]:
        parsed_id = uuid.UUID(str(run_id))
        session = runtime.create_session()
        try:
            orchestrator = IntakeOrchestrator(
                session, fetch_client_factory=runtime.create_fetch_client
            )
            outcome = orchestrator.advance(parsed_id)
            session.commit()
        except IntakeRunNotFoundError:
            session.rollback()
            return {"status": "missing", "run_id": run_id}
        except Exception as error:
            session.rollback()
            _record_step_error(runtime, parsed_id, error, retries=int(self.request.retries))
            if self.request.retries >= MAX_STEP_RETRIES:
                _mark_failed(runtime, parsed_id, error)
                return {"status": "failed", "run_id": run_id}
            raise self.retry(countdown=STEP_RETRY_SECONDS) from None
        finally:
            session.close()

        for item_id in outcome.fetch_dispatches:
            self.app.send_task(FETCH_DISCOVERY_ITEM_TASK, args=[item_id])
        for document_id in outcome.promote_dispatches:
            self.app.send_task(PROMOTE_RESEARCH_TASK, args=[document_id])
        if outcome.action in ("reschedule", "waiting"):
            self.app.send_task(
                INTAKE_STEP_TASK,
                args=[run_id],
                countdown=outcome.countdown_seconds,
            )
        return {
            "status": outcome.action,
            "run_id": run_id,
            "fetch_dispatches": len(outcome.fetch_dispatches),
            "promote_dispatches": len(outcome.promote_dispatches),
        }

    common_options: dict[str, Any] = {
        "bind": True,
        # shared=False keeps the registration owned by exactly this app
        # (the research/editorial pattern): Celery's shared-task finalize
        # replay would otherwise leak the task into every later app.
        "shared": False,
        "acks_late": True,
        "reject_on_worker_lost": True,
        "max_retries": MAX_STEP_RETRIES,
    }
    app.task(name=INTAKE_STEP_TASK, **common_options)(intake_step)


def _record_step_error(
    runtime: WorkerRuntime, run_id: uuid.UUID, error: Exception, *, retries: int
) -> None:
    """Sanitized durable trace of a failed step (type name only)."""
    session = runtime.create_session()
    try:
        service = IntakeRunService(session)
        run = service.require_run(run_id)
        service.record_event(
            run,
            IntakeStage.RUN,
            IntakeEventKind.STEP_ERROR,
            {"error_type": type(error).__name__, "retries": retries},
        )
        session.commit()
    except Exception:
        session.rollback()
        _logger.warning(
            "intake_step_error_record_failed",
            run_id=str(run_id),
            error_type=type(error).__name__,
        )
    finally:
        session.close()


def _mark_failed(runtime: WorkerRuntime, run_id: uuid.UUID, error: Exception) -> None:
    session = runtime.create_session()
    try:
        service = IntakeRunService(session)
        run = service.require_run(run_id)
        run.status = IntakeRunStatus.FAILED
        run.failure_note = f"step failed after retries: {type(error).__name__}"
        service.record_event(
            run,
            IntakeStage.RUN,
            IntakeEventKind.RUN_FAILED,
            {"error_type": type(error).__name__},
        )
        session.commit()
    except Exception:
        session.rollback()
        _logger.warning("intake_run_failure_record_failed", run_id=str(run_id))
    finally:
        session.close()
