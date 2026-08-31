"""Transactional mapping from FetchResult to immutable FetchSnapshot history."""

import hashlib
import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from contentos.discovery.enums import DiscoveryLifecycleState
from contentos.discovery.repository import DiscoveryItemRepository
from contentos.discovery.service import DiscoveryService, InvalidDiscoveryTransitionError
from contentos.fetching.models import FetchResult
from contentos.fetching.policy import RESPONSE_HEADER_ALLOWLIST
from contentos.fetching.snapshot_repository import FetchSnapshotRepository
from contentos.fetching.snapshots import FetchSnapshot

_SAFE_RESPONSE_HEADERS = frozenset(RESPONSE_HEADER_ALLOWLIST)


class FetchSnapshotError(Exception):
    """Base class for snapshot-recording domain errors."""


class FetchSnapshotItemNotFoundError(FetchSnapshotError):
    """The requested DiscoveryItem does not exist."""


class FetchSnapshotItemNotEligibleError(FetchSnapshotError):
    """The DiscoveryItem is not ACCEPTED for a new fetch attempt result."""


class MissingRawPayloadReferenceError(FetchSnapshotError):
    """A FetchResult body has no retrievable immutable payload reference."""


class InvalidFetchSnapshotInputError(FetchSnapshotError):
    """The FetchResult and payload-reference combination is inconsistent."""


class FetchSnapshotPersistenceError(FetchSnapshotError):
    """The database refused a snapshot recording operation."""


class FetchSnapshotService:
    """Append snapshots and advance DiscoveryItem state without committing."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._items = DiscoveryItemRepository(session)
        self._snapshots = FetchSnapshotRepository(session)
        self._discovery = DiscoveryService(session)

    def record_fetch_result(
        self,
        discovery_item_id: uuid.UUID,
        result: FetchResult,
        *,
        raw_payload_ref: str | None = None,
    ) -> FetchSnapshot:
        """Append one attempt and transition its locked ACCEPTED item atomically."""
        item = self._items.get_by_id_for_update(discovery_item_id)
        if item is None:
            raise FetchSnapshotItemNotFoundError(f"no discovery item with id {discovery_item_id}")
        if item.lifecycle_state is not DiscoveryLifecycleState.ACCEPTED:
            raise FetchSnapshotItemNotEligibleError(
                f"discovery item is {item.lifecycle_state.value}, not accepted"
            )

        payload_ref, body_sha256, body_size_bytes = _payload_metadata(result, raw_payload_ref)
        selected_headers = {
            name.casefold(): value
            for name, value in result.headers.items()
            if name.casefold() in _SAFE_RESPONSE_HEADERS
        }
        snapshot = FetchSnapshot(
            discovery_item_id=item.id,
            requested_url=result.requested_url,
            final_url=result.final_url,
            status_code=result.status_code,
            content_type=result.content_type,
            fetched_at=result.fetched_at,
            body_sha256=body_sha256,
            body_size_bytes=body_size_bytes,
            raw_payload_ref=payload_ref,
            selected_headers=selected_headers,
            duration_ms=result.duration_ms,
            redirect_chain=list(result.redirect_chain),
            fetch_outcome=result.outcome,
            retry_classification=result.retry,
            failure_detail=result.failure_detail,
            robots_decision=result.robots_decision,
            retry_after_seconds=result.retry_after_seconds,
        )
        try:
            with self._session.begin_nested():
                self._snapshots.add(snapshot)
                if result.is_success:
                    self._discovery.mark_fetched(item.id)
                else:
                    self._discovery.mark_fetch_failed(item.id)
        except InvalidDiscoveryTransitionError:
            raise FetchSnapshotItemNotEligibleError(
                "discovery item stopped being accepted during snapshot recording"
            ) from None
        except SQLAlchemyError:
            raise FetchSnapshotPersistenceError("database refused fetch snapshot") from None
        return snapshot


def _payload_metadata(
    result: FetchResult, raw_payload_ref: str | None
) -> tuple[str | None, str | None, int | None]:
    cleaned_ref = raw_payload_ref.strip() if raw_payload_ref is not None else None
    if result.is_success and result.body is None:
        raise InvalidFetchSnapshotInputError("a successful fetch result must contain body bytes")
    if result.body is None:
        if cleaned_ref:
            raise InvalidFetchSnapshotInputError(
                "a payload reference cannot be recorded without body bytes"
            )
        return None, None, None
    if not cleaned_ref:
        raise MissingRawPayloadReferenceError(
            "body bytes require a non-empty immutable raw payload reference"
        )
    return cleaned_ref, hashlib.sha256(result.body).hexdigest(), len(result.body)
