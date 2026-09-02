"""Process-local worker runtime: lazy factories, no import-time connections.

Nothing here touches the database or network at construction or import time.
The engine is created once per worker process on first session use; every task
creates its own Session and must close it. FetchClients are operation-scoped
and closed by the task.
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from contentos.ai.protocol import StructuredGenerationProvider
from contentos.core.config import Settings
from contentos.db.session import create_database_engine, create_session_factory
from contentos.fetching.client import FetchClient
from contentos.fetching.policy import build_fetch_policy
from contentos.payloads.postgres import PostgresRawPayloadStore

SessionFactory = Callable[[], Session]
FetchClientFactory = Callable[[], FetchClient]
ProviderFactory = Callable[[], StructuredGenerationProvider]


class WorkerRuntime:
    """Lazily composed per-process dependencies for pipeline tasks."""

    def __init__(
        self,
        settings: Settings,
        *,
        session_factory: SessionFactory | None = None,
        fetch_client_factory: FetchClientFactory | None = None,
        structured_generation_provider_factory: ProviderFactory | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._fetch_client_factory = fetch_client_factory
        self._provider_factory = structured_generation_provider_factory

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

    def create_generation_provider(self) -> StructuredGenerationProvider:
        """Return the structured-generation provider for AI editorial tasks.

        Called ONLY when an AI task actually needs a provider — never at
        import, worker-app construction, or registration time. Tests inject
        a deterministic fake via the factory seam; the production path
        builds the configured OpenAI adapter lazily. Missing configuration
        raises the typed provider-identity error (no fallback provider, no
        secret leakage, no retry storm) and no domain state is touched.
        """
        if self._provider_factory is not None:
            return self._provider_factory()
        from contentos.ai.providers.openai_provider import (
            create_openai_provider_from_settings,
        )

        return create_openai_provider_from_settings(self._settings)
