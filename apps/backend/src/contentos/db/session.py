"""Database engine and session foundation for ContentOS-owned storage."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from contentos.core.config import Settings

SessionFactory = Callable[[], Session]


def create_database_engine(settings: Settings) -> Engine:
    """Create a pooled PostgreSQL engine; connections open lazily on first use."""
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        pool_timeout=settings.db_pool_timeout_seconds,
        connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory; committing stays an explicit caller decision."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: SessionFactory) -> Iterator[Session]:
    """Yield one session; the caller commits. Failures roll back, re-raise, and close."""
    session = session_factory()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency yielding one request-scoped session without auto-commit."""
    session_factory: SessionFactory = request.app.state.db_session_factory
    with session_scope(session_factory) as session:
        yield session
