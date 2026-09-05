"""Autopilot settings and trail (ADR 0012).

The mode is ONE durable row; changing it is a named operator decision and
is itself recorded as a `mode_changed` event. Everything the autopilot
does or decides not to do lands in `autopilot_events` — the operator's
live feed and the audit trail are the same rows."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.autopilot.enums import AutopilotEventKind, AutopilotMode
from contentos.autopilot.models import SETTINGS_ROW_ID, AutopilotEvent, AutopilotSetting
from contentos.core.context import is_valid_request_id

MAX_REASON_LENGTH = 1000
# An action taken within this window counts as "in flight": the planner
# never enqueues the same step twice while the worker may still be on it.
IN_FLIGHT_WINDOW = timedelta(minutes=15)


class AutopilotError(Exception):
    """Base class for autopilot contract errors."""


class InvalidAutopilotInputError(AutopilotError):
    """A mode change violates the contract (blank reason, unnamed actor)."""


@dataclass(frozen=True, slots=True)
class AutopilotState:
    mode: AutopilotMode
    actor_user_id: uuid.UUID | None
    reason: str | None
    updated_at: datetime | None


class AutopilotService:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- settings -----------------------------------------------------------

    def state(self) -> AutopilotState:
        row = self._session.get(AutopilotSetting, SETTINGS_ROW_ID)
        if row is None:
            return AutopilotState(AutopilotMode.OFF, None, None, None)
        return AutopilotState(row.mode, row.actor_user_id, row.reason, row.updated_at)

    def mode(self) -> AutopilotMode:
        return self.state().mode

    def set_mode(
        self,
        mode: AutopilotMode,
        *,
        actor_user_id: uuid.UUID | None,
        reason: str,
        request_id: str | None = None,
    ) -> AutopilotState:
        """Switch the mode as a NAMED decision; the actor becomes accountable
        for every acceptance the autopilot makes while the mode is on."""
        cleaned = reason.strip()
        if not cleaned or len(cleaned) > MAX_REASON_LENGTH:
            raise InvalidAutopilotInputError("reason is required (max 1000 characters)")
        if mode is not AutopilotMode.OFF and actor_user_id is None:
            raise InvalidAutopilotInputError("a named operator must switch the autopilot on")
        if request_id is not None and not is_valid_request_id(request_id):
            raise InvalidAutopilotInputError("request_id is not a valid correlation identifier")
        row = self._session.get(AutopilotSetting, SETTINGS_ROW_ID, with_for_update=True)
        previous = row.mode if row is not None else AutopilotMode.OFF
        if row is None:
            row = AutopilotSetting(id=SETTINGS_ROW_ID)
            self._session.add(row)
        row.mode = mode
        row.actor_user_id = actor_user_id
        row.reason = cleaned
        row.updated_at = datetime.now(UTC)
        self._session.add(
            AutopilotEvent(
                work_item_id=None,
                kind=AutopilotEventKind.MODE_CHANGED,
                action=None,
                mode=mode,
                detail={
                    "from": previous.value,
                    "to": mode.value,
                    "reason": cleaned,
                    "actor_user_id": str(actor_user_id) if actor_user_id else None,
                },
                request_id=request_id,
            )
        )
        self._session.flush()
        return self.state()

    # --- trail ---------------------------------------------------------------

    def record(
        self,
        kind: AutopilotEventKind,
        *,
        work_item_id: uuid.UUID | None,
        action: str | None,
        mode: AutopilotMode,
        detail: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> AutopilotEvent:
        event = AutopilotEvent(
            work_item_id=work_item_id,
            kind=kind,
            action=action,
            mode=mode,
            detail=dict(detail or {}),
            request_id=request_id,
        )
        self._session.add(event)
        self._session.flush()
        return event

    def record_wait_once(
        self,
        *,
        work_item_id: uuid.UUID,
        action: str,
        mode: AutopilotMode,
        reason: str,
    ) -> AutopilotEvent | None:
        """Record a wait ONLY when it differs from the work item's latest
        event, so a 20-second sweep does not flood the trail."""
        latest = self.latest_for_work_item(work_item_id)
        if (
            latest is not None
            and latest.kind is AutopilotEventKind.WAITING
            and latest.action == action
        ):
            return None
        return self.record(
            AutopilotEventKind.WAITING,
            work_item_id=work_item_id,
            action=action,
            mode=mode,
            detail={"reason": reason},
        )

    def latest_for_work_item(self, work_item_id: uuid.UUID) -> AutopilotEvent | None:
        return self._session.scalar(
            select(AutopilotEvent)
            .where(AutopilotEvent.work_item_id == work_item_id)
            .order_by(AutopilotEvent.created_at.desc(), AutopilotEvent.id.desc())
            .limit(1)
        )

    def in_flight_actions(
        self, work_item_id: uuid.UUID, now: datetime | None = None
    ) -> frozenset[str]:
        """Action names taken for this work item inside IN_FLIGHT_WINDOW."""
        since = (now or datetime.now(UTC)) - IN_FLIGHT_WINDOW
        rows = self._session.scalars(
            select(AutopilotEvent.action).where(
                AutopilotEvent.work_item_id == work_item_id,
                AutopilotEvent.kind == AutopilotEventKind.ACTION,
                AutopilotEvent.created_at >= since,
            )
        )
        return frozenset(action for action in rows if action)

    def recent_events(self, limit: int = 50) -> list[AutopilotEvent]:
        return list(
            self._session.scalars(
                select(AutopilotEvent)
                .order_by(AutopilotEvent.created_at.desc(), AutopilotEvent.id.desc())
                .limit(limit)
            )
        )

    def latest_per_work_item(
        self, work_item_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, AutopilotEvent]:
        """The newest event for each given work item (bounded set query)."""
        if not work_item_ids:
            return {}
        rows = self._session.scalars(
            select(AutopilotEvent)
            .where(AutopilotEvent.work_item_id.in_(work_item_ids))
            .order_by(AutopilotEvent.created_at.desc(), AutopilotEvent.id.desc())
        )
        latest: dict[uuid.UUID, AutopilotEvent] = {}
        for event in rows:
            if event.work_item_id is not None and event.work_item_id not in latest:
                latest[event.work_item_id] = event
        return latest
