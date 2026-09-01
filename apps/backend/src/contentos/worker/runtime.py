"""Process-local worker runtime: lazy factories, no import-time connections.

Nothing here touches the database or network at construction or import time.
The engine is created once per worker process on first session use; every task
creates its own Session and must close it. FetchClients are operation-scoped
and closed by the task.
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from contentos.core.config import Settings
from contentos.db.session import create_database_engine, create_session_factory
from contentos.fetching.client import FetchClient
from contentos.fetching.policy import build_fetch_policy
from contentos.payloads.postgres import PostgresRawPayloadStore

SessionFactory = Callable[[], Session]
FetchClientFactory = Callable[[], FetchClient]


class WorkerRuntime:
    """Lazily composed per-process dependencies for research pipeline tasks."""

    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: SessionFactory | None = None,
        fetch_client_factory: FetchClientFactory | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._fetch_client_factory = fetch_client_factory

    @property
    def settings(self) -> Settings:
        return self._settings

    def create_session(self) -> Session:
        """Return a fresh task-scoped Session; the engine is built lazily once."""
        if self._session_factory is None:
            engine = create_database_engine(self._settings)
            self._session_factory = create_session_factory(engine)
        return self._session_factory()

    def create_fetch_client(self) -> FetchClient:
        """Return an operation-scoped fetch client; callers must close it."""
        if self._fetch_client_factory is not None:
            return self._fetch_client_factory()
        return FetchClient(build_fetch_policy(self._settings))

    def create_payload_store(self, session: Session) -> PostgresRawPayloadStore:
        """Compose the durable payload provider bound to the task session."""
        return PostgresRawPayloadStore(
            session, max_payload_bytes=self._settings.fetch_max_body_bytes
        )
