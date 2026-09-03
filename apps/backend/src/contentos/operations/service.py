"""Audited intake pause/resume and the dispatch gate.

The service owns exactly three behaviors:

- ``pause``/``resume``: idempotent state change with an append-only
  audit event recorded ONLY when the state actually changes;
- ``ensure_dispatch_allowed``: the single question the control surface
  asks before publishing a job — is the ENGINE or this scope paused?

Pauses gate NEW dispatch only. They never cancel running tasks, never
touch workflow state, and are never an editorial decision.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.operations.enums import PauseAction, PauseScope
from contentos.operations.errors import IntakePausedError
from contentos.operations.models import OperationalPause, OperationalPauseEvent

MAX_REASON_LENGTH = 500


@dataclass(frozen=True)
class PauseState:
    scope: PauseScope
    is_paused: bool
    reason: str | None
    actor_user_id: uuid.UUID | None
    updated_at: datetime | None


@dataclass(frozen=True)
class PauseChange:
    scope: PauseScope
    is_paused: bool
    changed: bool


class OperationsService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def states(self) -> list[PauseState]:
        """Every scope's current state; scopes without a row are honestly
        NOT paused (the default), never invented as unknown."""
        rows = {row.scope: row for row in self._session.scalars(select(OperationalPause)).all()}
        states: list[PauseState] = []
        for scope in PauseScope:
            row = rows.get(scope)
            if row is None:
                states.append(PauseState(scope, False, None, None, None))
            else:
                states.append(
                    PauseState(scope, row.is_paused, row.reason, row.actor_user_id, row.updated_at)
                )
        return states

    def state_for(self, scope: PauseScope) -> PauseState:
        row = self._session.get(OperationalPause, scope)
        if row is None:
            return PauseState(scope, False, None, None, None)
        return PauseState(scope, row.is_paused, row.reason, row.actor_user_id, row.updated_at)

    def pause(
        self,
        scope: PauseScope,
        *,
        reason: str,
        actor_user_id: uuid.UUID | None,
        request_id: str | None = None,
    ) -> PauseChange:
        return self._transition(
            scope,
            paused=True,
            reason=reason,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )

    def resume(
        self,
        scope: PauseScope,
        *,
        reason: str,
        actor_user_id: uuid.UUID | None,
        request_id: str | None = None,
    ) -> PauseChange:
        return self._transition(
            scope,
            paused=False,
            reason=reason,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )

    def _transition(
        self,
        scope: PauseScope,
        *,
        paused: bool,
        reason: str,
        actor_user_id: uuid.UUID | None,
        request_id: str | None,
    ) -> PauseChange:
        normalized = reason.strip()
        if not normalized or len(normalized) > MAX_REASON_LENGTH:
            raise ValueError(f"a pause-control reason must be 1..{MAX_REASON_LENGTH} characters")
        row = self._session.get(OperationalPause, scope)
        if row is None:
            if not paused:
                # Resuming a never-paused scope is a no-op, not an event.
                return PauseChange(scope, False, False)
            row = OperationalPause(
                scope=scope,
                is_paused=True,
                reason=normalized,
                actor_user_id=actor_user_id,
            )
            self._session.add(row)
        else:
            if row.is_paused == paused:
                return PauseChange(scope, paused, False)
            row.is_paused = paused
            row.reason = normalized if paused else None
            row.actor_user_id = actor_user_id
        self._session.add(
            OperationalPauseEvent(
                scope=scope,
                action=PauseAction.PAUSED if paused else PauseAction.RESUMED,
                reason=normalized,
                actor_user_id=actor_user_id,
                request_id=request_id,
            )
        )
        return PauseChange(scope, paused, True)

    def ensure_dispatch_allowed(self, scope: PauseScope) -> None:
        """Raise typed when the ENGINE or the given scope is paused.

        Called BEFORE any queue publish; nothing is persisted here."""
        engine = self._session.get(OperationalPause, PauseScope.ENGINE)
        if engine is not None and engine.is_paused:
            raise IntakePausedError(PauseScope.ENGINE, engine.reason or "paused")
        if scope is PauseScope.ENGINE:
            return
        row = self._session.get(OperationalPause, scope)
        if row is not None and row.is_paused:
            raise IntakePausedError(scope, row.reason or "paused")

    def recent_events(self, limit: int = 20) -> list[OperationalPauseEvent]:
        return list(
            self._session.scalars(
                select(OperationalPauseEvent).order_by(OperationalPauseEvent.id.desc()).limit(limit)
            ).all()
        )
