"""Source Registry service: idempotent registration and audited lifecycle."""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.sources.enums import (
    DiscoveryStrategy,
    LifecycleChangeOrigin,
    SourceKind,
    SourceLifecycleState,
    TrustTier,
)
from contentos.sources.models import Source, SourceLifecycleEvent
from contentos.sources.repository import SourceRepository
from contentos.sources.urls import normalize_base_url

_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$")

_DEFAULT_STRATEGY_BY_KIND = {
    SourceKind.RSS_FEED: DiscoveryStrategy.FEED,
    SourceKind.SITEMAP: DiscoveryStrategy.SITEMAP,
    SourceKind.MANUAL: DiscoveryStrategy.MANUAL,
}

# Exact transition semantics from docs/PHASE2_RESEARCH_DISCOVERY.md §1:
# ACTIVE <-> PAUSED; ACTIVE/PAUSED -> DISABLED; DISABLED -> ACTIVE; any ->
# BLOCKED; BLOCKED leaves only to ACTIVE via an explicit decision with reason.
_ALLOWED_TRANSITIONS: dict[SourceLifecycleState, frozenset[SourceLifecycleState]] = {
    SourceLifecycleState.ACTIVE: frozenset(
        {SourceLifecycleState.PAUSED, SourceLifecycleState.DISABLED, SourceLifecycleState.BLOCKED}
    ),
    SourceLifecycleState.PAUSED: frozenset(
        {SourceLifecycleState.ACTIVE, SourceLifecycleState.DISABLED, SourceLifecycleState.BLOCKED}
    ),
    SourceLifecycleState.DISABLED: frozenset(
        {SourceLifecycleState.ACTIVE, SourceLifecycleState.BLOCKED}
    ),
    SourceLifecycleState.BLOCKED: frozenset({SourceLifecycleState.ACTIVE}),
}


class SourceRegistryError(Exception):
    """Base class for Source Registry domain errors."""


class InvalidSourceDefinitionError(SourceRegistryError):
    """The registration input is invalid (slug, strategy, or field shape)."""


class SourceRegistrationConflictError(SourceRegistryError):
    """A conflicting source already exists; nothing was overwritten."""

    def __init__(self, message: str, conflicting_fields: list[str] | None = None) -> None:
        super().__init__(message)
        self.conflicting_fields = conflicting_fields or []


class SourceNotFoundError(SourceRegistryError):
    """No source exists for the given identity."""


class InvalidLifecycleTransitionError(SourceRegistryError):
    """The requested lifecycle transition is not allowed."""


class SourceRegistryService:
    """Registration and lifecycle for governed sources.

    The service flushes but never commits; callers own the transaction
    (session_scope pattern). The one exception is uniqueness-race recovery in
    ``register_source``, which must roll back the failed flush before
    re-reading the winning row.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = SourceRepository(session)

    def register_source(
        self,
        *,
        slug: str,
        name: str,
        kind: SourceKind,
        base_url: str,
        trust_tier: TrustTier,
        locale: str = "tr-TR",
        market: str = "TR",
        discovery_strategy: DiscoveryStrategy | None = None,
        discovery_config: dict[str, Any] | None = None,
        fetch_policy: dict[str, Any] | None = None,
        terms_notes: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Source:
        """Idempotently register a source.

        Re-registering an identical definition returns the existing source.
        Any conflicting definition raises SourceRegistrationConflictError and
        never silently overwrites existing configuration.
        """
        definition = self._validated_definition(
            slug=slug,
            name=name,
            kind=kind,
            base_url=base_url,
            trust_tier=trust_tier,
            locale=locale,
            market=market,
            discovery_strategy=discovery_strategy,
            discovery_config=discovery_config,
            fetch_policy=fetch_policy,
            terms_notes=terms_notes,
            metadata=metadata,
        )

        existing = self._find_existing(definition)
        if existing is not None:
            return existing

        source = Source(
            slug=definition["slug"],
            name=definition["name"],
            kind=definition["kind"],
            base_url=definition["base_url"],
            trust_tier=definition["trust_tier"],
            locale=definition["locale"],
            market=definition["market"],
            discovery_strategy=definition["discovery_strategy"],
            discovery_config=definition["discovery_config"],
            fetch_policy=definition["fetch_policy"],
            terms_notes=definition["terms_notes"],
            metadata_json=definition["metadata"],
        )
        try:
            self._repository.add(source)
        except IntegrityError:
            # Uniqueness race: another writer inserted first. The database is
            # the final authority; recover deterministically.
            self._session.rollback()
            winner = self._find_existing(definition)
            if winner is not None:
                return winner
            raise SourceRegistrationConflictError(
                "source registration conflicts with an existing source"
            ) from None

        self._repository.add_lifecycle_event(
            SourceLifecycleEvent(
                source_id=source.id,
                previous_state=None,
                new_state=source.lifecycle_state,
                reason="registered",
                origin=LifecycleChangeOrigin.OPERATOR,
            )
        )
        return source

    def transition_source_state(
        self,
        source_id: uuid.UUID,
        new_state: SourceLifecycleState,
        *,
        reason: str,
        origin: LifecycleChangeOrigin = LifecycleChangeOrigin.OPERATOR,
    ) -> Source:
        """Apply one validated, audited lifecycle transition."""
        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise InvalidLifecycleTransitionError("a lifecycle transition requires a reason")

        source = self._repository.get_by_id(source_id)
        if source is None:
            raise SourceNotFoundError(f"no source with id {source_id}")

        current = source.lifecycle_state
        if new_state == current:
            raise InvalidLifecycleTransitionError(f"source is already in state '{current.value}'")
        if new_state not in _ALLOWED_TRANSITIONS[current]:
            raise InvalidLifecycleTransitionError(
                f"transition '{current.value}' -> '{new_state.value}' is not allowed"
            )

        source.lifecycle_state = new_state
        source.state_reason = cleaned_reason
        source.state_changed_at = datetime.now(UTC)
        self._repository.add_lifecycle_event(
            SourceLifecycleEvent(
                source_id=source.id,
                previous_state=current,
                new_state=new_state,
                reason=cleaned_reason,
                origin=origin,
            )
        )
        return source

    def _validated_definition(
        self,
        *,
        slug: str,
        name: str,
        kind: SourceKind,
        base_url: str,
        trust_tier: TrustTier,
        locale: str,
        market: str,
        discovery_strategy: DiscoveryStrategy | None,
        discovery_config: dict[str, Any] | None,
        fetch_policy: dict[str, Any] | None,
        terms_notes: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        cleaned_slug = slug.strip()
        if not _SLUG_PATTERN.fullmatch(cleaned_slug):
            raise InvalidSourceDefinitionError(
                "slug must be 1-100 lowercase letters, digits, or inner hyphens"
            )
        cleaned_name = name.strip()
        if not cleaned_name:
            raise InvalidSourceDefinitionError("name must not be empty")

        resolved_strategy = discovery_strategy or _DEFAULT_STRATEGY_BY_KIND.get(kind)
        if resolved_strategy is None:
            raise InvalidSourceDefinitionError(
                f"source kind '{kind.value}' requires an explicit discovery_strategy"
            )

        return {
            "slug": cleaned_slug,
            "name": cleaned_name,
            "kind": kind,
            "base_url": normalize_base_url(base_url),
            "trust_tier": trust_tier,
            "locale": locale,
            "market": market,
            "discovery_strategy": resolved_strategy,
            "discovery_config": discovery_config or {},
            "fetch_policy": fetch_policy or {},
            "terms_notes": terms_notes,
            "metadata": metadata or {},
        }

    def _find_existing(self, definition: dict[str, Any]) -> Source | None:
        """Return the existing identical source, raise on conflict, or None."""
        by_slug = self._repository.get_by_slug(definition["slug"])
        by_identity = self._repository.get_by_identity(definition["kind"], definition["base_url"])

        if by_slug is None and by_identity is None:
            return None
        if by_slug is not None and by_identity is not None and by_slug.id != by_identity.id:
            raise SourceRegistrationConflictError(
                "slug and (kind, base_url) belong to two different existing sources",
                conflicting_fields=["slug", "kind", "base_url"],
            )
        existing = by_slug or by_identity
        assert existing is not None

        differing = self._differing_fields(existing, definition)
        if differing:
            raise SourceRegistrationConflictError(
                "a source with this identity exists with a different definition: "
                + ", ".join(differing),
                conflicting_fields=differing,
            )
        return existing

    @staticmethod
    def _differing_fields(existing: Source, definition: dict[str, Any]) -> list[str]:
        comparisons: list[tuple[str, object, object]] = [
            ("slug", existing.slug, definition["slug"]),
            ("kind", existing.kind, definition["kind"]),
            ("base_url", existing.base_url, definition["base_url"]),
            ("name", existing.name, definition["name"]),
            ("trust_tier", existing.trust_tier, definition["trust_tier"]),
            ("locale", existing.locale, definition["locale"]),
            ("market", existing.market, definition["market"]),
            ("discovery_strategy", existing.discovery_strategy, definition["discovery_strategy"]),
            ("discovery_config", existing.discovery_config, definition["discovery_config"]),
            ("fetch_policy", existing.fetch_policy, definition["fetch_policy"]),
            ("terms_notes", existing.terms_notes, definition["terms_notes"]),
            ("metadata", existing.metadata_json, definition["metadata"]),
        ]
        return [field for field, current, proposed in comparisons if current != proposed]
