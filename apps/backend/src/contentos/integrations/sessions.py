"""Session resolution for the cost-control stores.

Provider calls happen inside an API request or a worker task that already
owns a Session. `bind_session` makes that session the one the stores use
(the owner commits); without a bound session a store opens its own
short-lived session from the factory and commits it.
"""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar

from sqlalchemy.orm import Session

SessionFactory = Callable[[], Session]
SessionScope = Callable[[], AbstractContextManager[Session]]

_BOUND: ContextVar[Session | None] = ContextVar("contentos_integrations_session", default=None)


@contextmanager
def bind_session(session: Session) -> Iterator[None]:
    """Route every store access inside the block through `session`."""
    token = _BOUND.set(session)
    try:
        yield
    finally:
        _BOUND.reset(token)


def bound_session() -> Session | None:
    return _BOUND.get()


def make_session_scope(session_factory: SessionFactory) -> SessionScope:
    @contextmanager
    def scope() -> Iterator[Session]:
        bound = _BOUND.get()
        if bound is not None:
            yield bound
            bound.flush()
            return
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return scope
