"""Durable operational pause state and its append-only audit.

`operational_pauses` holds the CURRENT intake state per scope (one row
per scope, created lazily on the first pause). `operational_pause_events`
is the append-only audit of every pause/resume with the named actor and
required reason — the UserEvent pattern. Neither table touches workflow
state: a pause only gates NEW dispatch at the control surface.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
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

from contentos.db.base import Base
from contentos.db.types import string_enum
from contentos.operations.enums import PauseAction, PauseScope

REQUEST_ID_MAX_LENGTH = 128


class OperationalPause(Base):
    """Current intake state for one scope; paused requires a reason."""

    __tablename__ = "operational_pauses"
    __table_args__ = (
        CheckConstraint(
            "(NOT is_paused) OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_operational_pauses_paused_reason",
        ),
    )

    scope: Mapped[PauseScope] = mapped_column(
        string_enum(PauseScope, "ck_operational_pauses_scope", 16),
        primary_key=True,
    )
    is_paused: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class OperationalPauseEvent(Base):
    """Append-only record of one pause or resume with its named actor."""

    __tablename__ = "operational_pause_events"
    __table_args__ = (
        CheckConstraint(
            "length(trim(reason)) > 0",
            name="ck_operational_pause_events_reason_nonempty",
        ),
        CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name="ck_operational_pause_events_request_id_nonempty",
        ),
        Index("ix_operational_pause_events_scope", "scope", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    scope: Mapped[PauseScope] = mapped_column(
        string_enum(PauseScope, "ck_operational_pause_events_scope", 16),
        nullable=False,
    )
    action: Mapped[PauseAction] = mapped_column(
        string_enum(PauseAction, "ck_operational_pause_events_action", 16),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    request_id: Mapped[str | None] = mapped_column(String(REQUEST_ID_MAX_LENGTH), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def as_audit_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.value,
            "action": self.action.value,
            "reason": self.reason,
        }
