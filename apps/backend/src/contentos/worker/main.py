"""Celery worker entrypoint without import-time startup side effects."""

import sys
from collections.abc import Sequence

from celery import Celery

from contentos.core.config import Settings
from contentos.core.logging import configure_logging
from contentos.queue.celery import create_celery_app
from contentos.worker.signals import install_worker_signal_handlers


def create_worker_app(settings: Settings | None = None) -> Celery:
    """Explicitly build settings, logging, signal hooks, and the Celery app."""
    resolved_settings = settings if settings is not None else Settings()
    configure_logging(resolved_settings)
    install_worker_signal_handlers()
    return create_celery_app(resolved_settings)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the Celery CLI (e.g. `python -m contentos.worker.main worker`)."""
    arguments = list(argv) if argv is not None else ["worker"]
    create_worker_app().worker_main(argv=arguments)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
