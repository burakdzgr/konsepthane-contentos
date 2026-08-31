"""Discovery service: manual admission, idempotent rediscovery, lifecycle."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.core.urls import canonical_url_hash, canonicalize_url
from contentos.discovery.enums import (
    DiscoveryLifecycleState,
    DiscoveryMethod,
    DiscoveryRejectionReason,
)
from contentos.discovery.models import DiscoveryItem
from contentos.discovery.repository import DiscoveryItemRepository
from contentos.sources.enums import DiscoveryStrategy, SourceKind, SourceLifecycleState
from contentos.sources.models import Source
from contentos.sources.repository import SourceRepository
from contentos.sources.service import SourceNotFoundError


class DiscoveryError(Exception):
    """Base class for discovery domain errors."""


class SourceNotEligibleForDiscoveryError(DiscoveryError):
    """The source's lifecycle state does not admit new discovery items."""


class DiscoveryItemNotFoundError(DiscoveryError):
    """No discovery item exists for the given identity."""


class InvalidDiscoveryTransitionError(DiscoveryError):
    """The requested discovery lifecycle transition is not allowed."""


class DiscoveryAdmissionConflictError(DiscoveryError):
    """Admission conflicted with existing data and could not be resolved."""


@dataclass(frozen=True, slots=True)
class DiscoveryAdmission:
    """The item returned by admission and whether this call created it."""

    item: DiscoveryItem
    is_new: bool


class DiscoveryService:
    """Admission and lifecycle for discovery items.

    Flushes but never commits; callers own the transaction. Uniqueness-race
    recovery rolls back the failed flush before re-reading the winning row
    (same convention as source registration).
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._items = DiscoveryItemRepository(session)
        self._sources = SourceRepository(session)

    def discover_manual(
        self,
        source_id: uuid.UUID,
        url: str,
        *,
        title_hint: str | None = None,
        snippet_hint: str | None = None,
        locale: str | None = None,
        external_published_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DiscoveryItem:
        """Idempotently admit a manually supplied candidate URL.

        Rediscovery of the same canonical URL for the same source returns the
        existing row and only refreshes ``last_seen_at``: lifecycle state,
        rejection state, fetch state, and stored hints are never touched, and
        a rejected item is never resurrected. No network I/O happens here.
        """
        source = self._require_active_source(source_id)
        return self._admit(
            source,
            url,
            method=DiscoveryMethod.MANUAL,
            title_hint=title_hint,
            snippet_hint=snippet_hint,
            locale=locale,
            external_published_at=external_published_at,
            metadata=metadata,
        ).item

    def require_feed_source(self, source_id: uuid.UUID) -> Source:
        """Return an active RSS-feed source configured for feed discovery."""
        source = self._require_active_source(source_id)
        if (
            source.kind is not SourceKind.RSS_FEED
            or source.discovery_strategy is not DiscoveryStrategy.FEED
        ):
            raise SourceNotEligibleForDiscoveryError(
                f"source '{source.slug}' is not an RSS feed configured for feed discovery"
            )
        return source

    def discover_feed(
        self,
        source_id: uuid.UUID,
        url: str,
        *,
        title_hint: str | None = None,
        snippet_hint: str | None = None,
        external_published_at: datetime | None = None,
    ) -> DiscoveryAdmission:
        """Idempotently admit one untrusted candidate from an RSS/Atom feed."""
        source = self.require_feed_source(source_id)
        return self._admit(
            source,
            url,
            method=DiscoveryMethod.FEED,
            title_hint=title_hint,
            snippet_hint=snippet_hint,
            locale=None,
            external_published_at=external_published_at,
            metadata=None,
        )

    def _require_active_source(self, source_id: uuid.UUID) -> Source:
        source = self._sources.get_by_id(source_id)
        if source is None:
            raise SourceNotFoundError(f"no source with id {source_id}")
        if source.lifecycle_state is not SourceLifecycleState.ACTIVE:
            raise SourceNotEligibleForDiscoveryError(
                f"source '{source.slug}' is {source.lifecycle_state.value}, not active"
            )
        return source

    def _admit(
        self,
        source: Source,
        url: str,
        *,
        method: DiscoveryMethod,
        title_hint: str | None,
        snippet_hint: str | None,
        locale: str | None,
        external_published_at: datetime | None,
        metadata: dict[str, Any] | None,
    ) -> DiscoveryAdmission:
        """Shared canonical admission primitive; public methods enforce method rules."""

        canonical = canonicalize_url(url)
        url_hash = canonical_url_hash(canonical.url)

        existing = self._items.get_by_source_and_hash(source.id, url_hash)
        if existing is not None:
            existing.last_seen_at = datetime.now(UTC)
            self._session.flush()
            return DiscoveryAdmission(item=existing, is_new=False)

        item = DiscoveryItem(
            source_id=source.id,
            discovered_url=url.strip(),
            canonical_url=canonical.url,
            url_hash=url_hash,
            url_canonicalization_version=canonical.version,
            discovery_method=method,
            title_hint=title_hint,
            snippet_hint=snippet_hint,
            locale=locale or source.locale,
            external_published_at=external_published_at,
            metadata_json=metadata or {},
        )
        try:
            return DiscoveryAdmission(item=self._items.add(item), is_new=True)
        except IntegrityError:
            # Uniqueness race: another writer admitted the same canonical URL
            # first. The database is the final authority.
            self._session.rollback()
            winner = self._items.get_by_source_and_hash(source.id, url_hash)
            if winner is not None:
                winner.last_seen_at = datetime.now(UTC)
                self._session.flush()
                return DiscoveryAdmission(item=winner, is_new=False)
            raise DiscoveryAdmissionConflictError(
                "discovery admission conflicts with existing data"
            ) from None

    def accept_item(self, item_id: uuid.UUID) -> DiscoveryItem:
        """DISCOVERED -> ACCEPTED: the item is admitted for fetching."""
        item = self._require_state(item_id, DiscoveryLifecycleState.DISCOVERED)
        item.lifecycle_state = DiscoveryLifecycleState.ACCEPTED
        self._session.flush()
        return item

    def reject_item(
        self,
        item_id: uuid.UUID,
        reason: DiscoveryRejectionReason,
        *,
        note: str | None = None,
    ) -> DiscoveryItem:
        """DISCOVERED -> REJECTED (terminal) with a coded reason."""
        item = self._require_state(item_id, DiscoveryLifecycleState.DISCOVERED)
        item.lifecycle_state = DiscoveryLifecycleState.REJECTED
        item.rejection_reason = reason
        item.rejection_note = note
        self._session.flush()
        return item

    def mark_fetched(self, item_id: uuid.UUID) -> DiscoveryItem:
        """ACCEPTED -> FETCHED: a successful immutable snapshot exists."""
        item = self._require_state(item_id, DiscoveryLifecycleState.ACCEPTED)
        item.lifecycle_state = DiscoveryLifecycleState.FETCHED
        self._session.flush()
        return item

    def mark_fetch_failed(self, item_id: uuid.UUID) -> DiscoveryItem:
        """ACCEPTED -> FETCH_FAILED: bounded fetch attempts are exhausted."""
        item = self._require_state(item_id, DiscoveryLifecycleState.ACCEPTED)
        item.lifecycle_state = DiscoveryLifecycleState.FETCH_FAILED
        self._session.flush()
        return item

    def requeue_fetch(self, item_id: uuid.UUID, *, reason: str) -> DiscoveryItem:
        """FETCH_FAILED -> ACCEPTED: explicit re-queue with a required reason."""
        cleaned_reason = reason.strip()
        if not cleaned_reason:
            raise InvalidDiscoveryTransitionError("re-queueing a failed fetch requires a reason")
        item = self._require_state(item_id, DiscoveryLifecycleState.FETCH_FAILED)
        item.lifecycle_state = DiscoveryLifecycleState.ACCEPTED
        item.metadata_json = {**item.metadata_json, "last_requeue_reason": cleaned_reason}
        self._session.flush()
        return item

    def _require_state(
        self, item_id: uuid.UUID, expected: DiscoveryLifecycleState
    ) -> DiscoveryItem:
        item = self._items.get_by_id(item_id)
        if item is None:
            raise DiscoveryItemNotFoundError(f"no discovery item with id {item_id}")
        if item.lifecycle_state is not expected:
            raise InvalidDiscoveryTransitionError(
                f"transition requires state '{expected.value}', "
                f"item is '{item.lifecycle_state.value}'"
            )
        return item
