"""Source Registry persistence models."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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
from contentos.db.types import JSON_DICT, JSON_LIST
from contentos.db.types import string_enum as _string_enum
from contentos.sources.enums import (
    DiscoveryStrategy,
    LifecycleChangeOrigin,
    RobotsPolicy,
    SourceCapability,
    SourceKind,
    SourceLifecycleState,
    SourceRole,
    TrustTier,
)


def _default_capabilities() -> list[str]:
    return [SourceCapability.INSPIRATION.value]


class Source(Base):
    """A governed origin from which ContentOS may discover research material."""

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_sources_slug"),
        UniqueConstraint("kind", "base_url", name="uq_sources_kind_base_url"),
        Index("ix_sources_lifecycle_state", "lifecycle_state"),
        Index("ix_sources_kind", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[SourceKind] = mapped_column(
        _string_enum(SourceKind, "ck_sources_kind", 32), nullable=False
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Editorial purpose (migration 0031): technical `kind` says HOW content is
    # acquired; `primary_role` + `capabilities` say WHAT the pipeline may use
    # it for. Capabilities are validated, deduplicated, ordered enum VALUES.
    primary_role: Mapped[SourceRole] = mapped_column(
        _string_enum(SourceRole, "ck_sources_primary_role", 24),
        nullable=False,
        default=SourceRole.INSPIRATION,
        server_default=SourceRole.INSPIRATION.value,
    )
    capabilities: Mapped[list[str]] = mapped_column(
        JSON_LIST, nullable=False, default=_default_capabilities
    )
    locale: Mapped[str] = mapped_column(String(20), nullable=False, default="tr-TR")
    market: Mapped[str] = mapped_column(String(2), nullable=False, default="TR")
    lifecycle_state: Mapped[SourceLifecycleState] = mapped_column(
        _string_enum(SourceLifecycleState, "ck_sources_lifecycle_state", 16),
        nullable=False,
        default=SourceLifecycleState.ACTIVE,
    )
    state_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    state_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trust_tier: Mapped[TrustTier] = mapped_column(
        _string_enum(TrustTier, "ck_sources_trust_tier", 20), nullable=False
    )
    discovery_strategy: Mapped[DiscoveryStrategy] = mapped_column(
        _string_enum(DiscoveryStrategy, "ck_sources_discovery_strategy", 16),
        nullable=False,
    )
    discovery_config: Mapped[dict[str, Any]] = mapped_column(
        JSON_DICT, nullable=False, default=dict
    )
    fetch_policy: Mapped[dict[str, Any]] = mapped_column(JSON_DICT, nullable=False, default=dict)
    robots_policy: Mapped[RobotsPolicy] = mapped_column(
        _string_enum(RobotsPolicy, "ck_sources_robots_policy", 8),
        nullable=False,
        default=RobotsPolicy.OBEY,
    )
    terms_notes: Mapped[str | None] = mapped_column(Text(), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DICT, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SourceLifecycleEvent(Base):
    """Append-only record of one source lifecycle transition (or registration)."""

    __tablename__ = "source_lifecycle_events"
    __table_args__ = (Index("ix_source_lifecycle_events_source_id", "source_id", "changed_at"),)

    # Monotonic identity so append order is the audit order, independent of
    # timestamp precision.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    previous_state: Mapped[SourceLifecycleState | None] = mapped_column(
        _string_enum(SourceLifecycleState, "ck_source_lifecycle_events_previous_state", 16),
        nullable=True,
    )
    new_state: Mapped[SourceLifecycleState] = mapped_column(
        _string_enum(SourceLifecycleState, "ck_source_lifecycle_events_new_state", 16),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    origin: Mapped[LifecycleChangeOrigin] = mapped_column(
        _string_enum(LifecycleChangeOrigin, "ck_source_lifecycle_events_origin", 16),
        nullable=False,
        default=LifecycleChangeOrigin.OPERATOR,
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
