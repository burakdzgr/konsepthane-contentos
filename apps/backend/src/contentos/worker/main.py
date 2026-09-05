"""Celery worker entrypoint without import-time startup side effects."""

import sys
from collections.abc import Sequence

from celery import Celery

from contentos.core.config import Settings
from contentos.core.logging import configure_logging
from contentos.queue.celery import create_celery_app
from contentos.worker.autopilot_tasks import (
    AUTOPILOT_SWEEP_TASK,
    register_autopilot_tasks,
)
from contentos.worker.editorial_tasks import register_editorial_pipeline_tasks
from contentos.worker.intake_tasks import register_intake_tasks
from contentos.worker.performance_tasks import register_performance_tasks
from contentos.worker.research_tasks import register_research_pipeline_tasks
from contentos.worker.runtime import WorkerRuntime
from contentos.worker.signals import install_worker_signal_handlers


def create_worker_app(settings: Settings | None = None) -> Celery:
    """Explicitly build settings, logging, signals, Celery app, and tasks.

    Creating the app registers the research AND editorial pipelines only;
    no database, broker, provider, or network activity happens here.
    """
    resolved_settings = settings if settings is not None else Settings()
    configure_logging(resolved_settings)
    install_worker_signal_handlers()
    app = create_celery_app(resolved_settings)
    runtime = WorkerRuntime(resolved_settings)
    register_research_pipeline_tasks(app, runtime)
    register_editorial_pipeline_tasks(app, runtime)
    register_intake_tasks(app, runtime)
    register_autopilot_tasks(app, runtime)
    register_performance_tasks(app, runtime)
    _arm_autopilot_on_ready(app)
    return app


def _arm_autopilot_on_ready(app: Celery) -> None:
    """Re-arm the autopilot sweep when a worker comes up: the sweep chain is
    the only timer and dies with the worker; the task itself stops re-arming
    while the mode is OFF, so this is always safe."""
    from celery.signals import worker_ready  # type: ignore[import-untyped]

    @worker_ready.connect(weak=False)  # type: ignore[untyped-decorator]
    def _arm(**_kwargs: object) -> None:
        try:
            app.send_task(AUTOPILOT_SWEEP_TASK)
        except Exception:  # noqa: BLE001 - a broker hiccup must not kill startup
            pass


def main(argv: Sequence[str] | None = None) -> None:
    """Run the Celery CLI (e.g. `python -m contentos.worker.main worker`)."""
    arguments = list(argv) if argv is not None else ["worker"]
    app = create_worker_app()
    if arguments and arguments[0] == "beat":
        # `python -m contentos.worker.main beat`: the scheduler process for
        # the performance loop (agent E); the schedule file must live
        # somewhere writable inside the container.
        app.start(beat_arguments(arguments))
        return
    app.worker_main(argv=arguments)


def beat_arguments(arguments: Sequence[str]) -> list[str]:
    """Celery beat argv with a writable default schedule file and log level."""
    result = list(arguments)
    if "--schedule" not in result and not any(a.startswith("--schedule=") for a in result):
        result += ["--schedule", "/tmp/celerybeat-schedule"]
    if not any(a.startswith("--loglevel") for a in result):
        result.append("--loglevel=INFO")
    return result


if __name__ == "__main__":
    main(sys.argv[1:] or None)
