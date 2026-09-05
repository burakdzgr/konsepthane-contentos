"""Integration persistence: provider status, daily request log, response cache.

None of these rows ever carries a secret: status rows hold state, a
Turkish detail sentence and a bounded error class; the cache holds parsed
vendor payloads keyed by a sha256 of the request identity (never the key).
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from contentos.db.base import Base
from contentos.db.types import JSON_DICT, string_enum
from contentos.integrations.enums import ProviderState


class IntegrationStatusRecord(Base):
    """One row per provider: the last observed state (upserted)."""

    __tablename__ = "integration_status"
    __table_args__ = (
        CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_integration_status_provider_nonempty",
        ),
    )

    provider: Mapped[str] = mapped_column(String(40), primary_key=True)
    state: Mapped[ProviderState] = mapped_column(
        string_enum(ProviderState, "ck_integration_status_state", 24),
        nullable=False,
    )
    detail: Mapped[str] = mapped_column(Text(), nullable=False, default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProviderRequestLog(Base):
    """Requests actually sent per provider per UTC day (the daily budget)."""

    __tablename__ = "provider_request_log"
    __table_args__ = (
        Index("uq_provider_request_log_day", "provider", "day", unique=True),
        CheckConstraint(
            "request_count >= 0",
            name="ck_provider_request_log_count_nonnegative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    day: Mapped[date] = mapped_column(Date(), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ProviderCacheEntry(Base):
    """A parsed provider payload with an expiry (cost control, not truth)."""

    __tablename__ = "provider_cache"
    __table_args__ = (
        Index("uq_provider_cache_key", "provider", "cache_key", unique=True),
        Index("ix_provider_cache_expires", "expires_at"),
        CheckConstraint(
            "length(cache_key) = 64 AND cache_key = lower(cache_key)",
            name="ck_provider_cache_key_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
