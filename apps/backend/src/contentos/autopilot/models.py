"""Autopilot persistence (ADR 0012).

`autopilot_settings` is a single durable row (id = 1) holding the CURRENT
mode and the named operator who set it — that operator is the accountable
actor for every acceptance the autopilot makes on their behalf.
`autopilot_events` is the append-only trail: every action taken, every
wait with its reason, every error. Nothing here is ever edited."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.autopilot.enums import AutopilotEventKind, AutopilotMode
from contentos.db.base import Base
from contentos.db.types import JSON_DICT, string_enum

SETTINGS_ROW_ID = 1


class AutopilotSetting(Base):
    """The one current autopilot mode with its accountable operator."""

    __tablename__ = "autopilot_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_autopilot_settings_singleton"),
        CheckConstraint(
            "(mode = 'off') OR (actor_user_id IS NOT NULL)",
            name="ck_autopilot_settings_named_actor",
        ),
    )

    id: Mapped[int] = mapped_column(Integer(), primary_key=True, default=SETTINGS_ROW_ID)
    mode: Mapped[AutopilotMode] = mapped_column(
        string_enum(AutopilotMode, "ck_autopilot_settings_mode", 16),
        nullable=False,
        default=AutopilotMode.OFF,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AutopilotEvent(Base):
    """Append-only record of one autopilot action, wait, skip or error."""

    __tablename__ = "autopilot_events"
    __table_args__ = (
        Index("ix_autopilot_events_work_item_created", "work_item_id", "created_at"),
        Index("ix_autopilot_events_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    work_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("editorial_work_items.id", ondelete="RESTRICT"), nullable=True
    )
    kind: Mapped[AutopilotEventKind] = mapped_column(
        string_enum(AutopilotEventKind, "ck_autopilot_events_kind", 16), nullable=False
    )
    action: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    mode: Mapped[AutopilotMode] = mapped_column(
        string_enum(AutopilotMode, "ck_autopilot_events_mode", 16), nullable=False
    )
    detail: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
