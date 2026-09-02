"""Auth persistence models (named humans, audited management, sessions).

`users` identity fields are immutable (a DB trigger limits UPDATE to the
credential/role/activation fields); DELETE is forbidden — deactivation
is the removal mechanism, and every management action writes an
append-only `user_events` row. `auth_sessions` stores only the SHA-256
hash of the opaque token (the token itself exists once, in the login
response); the single legal mutation is the one-shot revocation.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.auth.enums import UserEventAction
from contentos.db.base import Base
from contentos.db.types import JSON_LIST, string_enum


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        CheckConstraint("length(trim(username)) > 0", name="ck_users_username_nonempty"),
        CheckConstraint("length(trim(display_name)) > 0", name="ck_users_display_nonempty"),
        CheckConstraint("length(trim(password_hash)) > 0", name="ck_users_password_nonempty"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(length=64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(length=200), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text(), nullable=False)
    roles: Mapped[list[Any]] = mapped_column(JSON_LIST, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    credentials_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UserEvent(Base):
    """Append-only audit of user-management actions."""

    __tablename__ = "user_events"
    __table_args__ = (
        CheckConstraint("length(trim(reason)) > 0", name="ck_user_events_reason_nonempty"),
        Index("ix_user_events_user", "user_id", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[UserEventAction] = mapped_column(
        string_enum(UserEventAction, "ck_user_events_action", 24), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    detail: Mapped[list[Any]] = mapped_column(JSON_LIST, nullable=False, default=list)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuthSession(Base):
    """One issued session: fixed TTL, revocable once, token stored only
    as its SHA-256 hash."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        CheckConstraint(
            "length(token_hash) = 64 AND token_hash = lower(token_hash)",
            name="ck_auth_sessions_token_hash_format",
        ),
        Index("ix_auth_sessions_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(length=64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
