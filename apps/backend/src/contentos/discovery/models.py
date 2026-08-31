"""DiscoveryItem persistence model: a candidate URL, never downloaded content."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
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

from contentos.db.base import Base
from contentos.db.types import JSON_DICT, string_enum
from contentos.discovery.enums import (
    DiscoveryLifecycleState,
    DiscoveryMethod,
    DiscoveryRejectionReason,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DiscoveryItem(Base):
    """A candidate resource discovered through a governed source.

    ``title_hint``/``snippet_hint`` are UNTRUSTED discovery hints supplied by
    the source or operator; they are not normalized content and never evidence.
    """

    __tablename__ = "discovery_items"
    __table_args__ = (
        UniqueConstraint("source_id", "url_hash", name="uq_discovery_items_source_url_hash"),
        Index("ix_discovery_items_lifecycle_state", "lifecycle_state"),
        Index("ix_discovery_items_url_hash", "url_hash"),
        Index("ix_discovery_items_discovered_at", "discovered_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    discovered_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    url_canonicalization_version: Mapped[int] = mapped_column(Integer(), nullable=False)
    discovery_method: Mapped[DiscoveryMethod] = mapped_column(
        string_enum(DiscoveryMethod, "ck_discovery_items_discovery_method", 16),
        nullable=False,
    )
    title_hint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    snippet_hint: Mapped[str | None] = mapped_column(Text(), nullable=True)
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    external_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lifecycle_state: Mapped[DiscoveryLifecycleState] = mapped_column(
        string_enum(DiscoveryLifecycleState, "ck_discovery_items_lifecycle_state", 16),
        nullable=False,
        default=DiscoveryLifecycleState.DISCOVERED,
    )
    rejection_reason: Mapped[DiscoveryRejectionReason | None] = mapped_column(
        string_enum(DiscoveryRejectionReason, "ck_discovery_items_rejection_reason", 20),
        nullable=True,
    )
    rejection_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    # The only field rediscovery may touch (design section 9: "touches last seen").
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DICT, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
