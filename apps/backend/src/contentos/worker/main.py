"""Celery worker entrypoint without import-time startup side effects."""

import sys
from collections.abc import Sequence

from celery import Celery

from contentos.core.config import Settings
from contentos.core.logging import configure_logging
from contentos.queue.celery import create_celery_app
from contentos.worker.editorial_tasks import register_editorial_pipeline_tasks
from contentos.worker.intake_tasks import register_intake_tasks
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
    return app


def main(argv: Sequence[str] | None = None) -> None:
    """Run the Celery CLI (e.g. `python -m contentos.worker.main worker`)."""
    arguments = list(argv) if argv is not None else ["worker"]
    create_worker_app().worker_main(argv=arguments)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
