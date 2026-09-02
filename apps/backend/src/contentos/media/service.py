"""MediaService: asset registration and human need-satisfaction.

Gates (PHASE6_MEDIA_ARCHITECTURE.md §1/§2):
- assets are immutable and content-addressed; identical bytes converge
  on one asset honestly (the first registration's metadata stands);
- the declared media type must match the actual bytes (magic sniffed
  server-side — the client's word is never trusted);
- a need is satisfied ONLY by an explicit named-human command with a
  required reason, bounded to workflow states where the package is not
  under terminal review;
- satisfactions follow the ACTIVE-row + guarded-supersession pattern:
  replacing binds the pointer, unsatisfying leaves no ACTIVE row, and
  every change appends an audit event. The caller commits.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.auth.models import User
from contentos.briefs.enums import BriefStatus
from contentos.briefs.models import ContentBrief
from contentos.briefs.repository import BriefRepository
from contentos.core.context import is_valid_request_id
from contentos.media.dimensions import extract_dimensions
from contentos.media.enums import MediaOrigin, SatisfactionStatus
from contentos.media.errors import (
    MediaConflictError,
    MediaInputError,
    MediaPreconditionError,
)
from contentos.media.models import MediaAsset, MediaNeedSatisfaction, MediaSatisfactionEvent
from contentos.media.store import MediaStore
from contentos.workflow.enums import WorkflowState
from contentos.workflow.repository import WorkflowRepository

MAX_MEDIA_BYTES = 10 * 1024 * 1024
MAX_TEXT_LENGTH = 1000

# The bytes decide the type — the declared type must match its magic.
_MAGIC_BY_TYPE: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}

# Media work happens while the package is NOT under terminal review:
# changing media under a reviewer's feet would make the review dishonest.
PERMITTED_MEDIA_STATES = frozenset(
    {
        WorkflowState.DRAFTING,
        WorkflowState.EDITING,
        WorkflowState.QA_REVIEW,
        WorkflowState.CHANGES_REQUESTED,
    }
)


@dataclass(frozen=True, slots=True)
class NeedCoverage:
    """One brief media need with its current satisfaction, if any."""

    need_index: int
    need: dict[str, Any]
    satisfaction: MediaNeedSatisfaction | None


class MediaService:
    def __init__(self, session: Session, store: MediaStore) -> None:
        self._session = session
        self._store = store
        self._workflow = WorkflowRepository(session)
        self._briefs = BriefRepository(session)

    # --- assets ---------------------------------------------------------------

    def register_upload(
        self,
        data: bytes,
        *,
        media_type: str,
        alt_text: str,
        license_note: str,
        created_by: User,
        title: str | None = None,
        source_attribution: str | None = None,
        request_id: str | None = None,
    ) -> tuple[MediaAsset, bool]:
        """Store an operator upload; returns (asset, created). Identical
        bytes converge on the existing asset honestly (created=False)."""
        self._require_active_user(created_by)
        if not data:
            raise MediaInputError("media content is empty")
        if len(data) > MAX_MEDIA_BYTES:
            raise MediaInputError(
                f"media content exceeds the {MAX_MEDIA_BYTES} byte limit ({len(data)} bytes)"
            )
        magics = _MAGIC_BY_TYPE.get(media_type)
        if magics is None:
            allowed = ", ".join(sorted(_MAGIC_BY_TYPE))
            raise MediaInputError(f"media_type must be one of: {allowed}")
        if not any(data.startswith(magic) for magic in magics):
            raise MediaInputError(
                f"the uploaded bytes do not look like {media_type}; "
                "the declared type must match the actual content"
            )
        if media_type == "image/webp" and data[8:12] != b"WEBP":
            raise MediaInputError(
                "the uploaded bytes do not look like image/webp; "
                "the declared type must match the actual content"
            )
        cleaned_alt = _required_text("alt_text", alt_text)
        cleaned_license = _required_text("license_note", license_note)
        cleaned_title = _optional_text("title", title)
        cleaned_attribution = _optional_text("source_attribution", source_attribution)
        validated_request_id = _validate_request_id(request_id)

        digest = hashlib.sha256(data).hexdigest()
        existing = self._session.execute(
            select(MediaAsset).where(MediaAsset.content_sha256 == digest)
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False

        self._store.put(data)
        width, height = extract_dimensions(data, media_type)
        asset = MediaAsset(
            origin=MediaOrigin.HUMAN_UPLOAD,
            content_sha256=digest,
            byte_size=len(data),
            media_type=media_type,
            width=width,
            height=height,
            title=cleaned_title,
            alt_text=cleaned_alt,
            license_note=cleaned_license,
            source_attribution=cleaned_attribution,
            generation_attempt_id=None,
            created_by_user_id=created_by.id,
            request_id=validated_request_id,
        )
        self._session.add(asset)
        self._session.flush()
        return asset, True

    def get_asset(self, asset_id: uuid.UUID) -> MediaAsset | None:
        return self._session.get(MediaAsset, asset_id)

    def read_asset_bytes(self, asset: MediaAsset) -> bytes:
        return self._store.read(asset.content_sha256)

    def resolve_need(
        self, work_item_id: uuid.UUID, need_index: int
    ) -> tuple[ContentBrief, dict[str, Any]]:
        """The state-bounded (ACTIVE accepted brief, exact need) pair every
        media operation — satisfaction AND generation — must resolve first."""
        brief = self._resolve_brief_in_bounds(work_item_id)
        self._require_need_index(brief, need_index)
        return brief, dict(brief.media_needs[need_index])

    # --- satisfactions --------------------------------------------------------

    def satisfy_need(
        self,
        work_item_id: uuid.UUID,
        need_index: int,
        media_asset_id: uuid.UUID,
        *,
        user: User,
        reason: str,
        request_id: str | None = None,
    ) -> MediaNeedSatisfaction:
        """Bind one need to one asset (idempotent for the same asset;
        replacing supersedes the previous binding with the pointer set)."""
        self._require_active_user(user)
        brief = self._resolve_brief_in_bounds(work_item_id)
        self._require_need_index(brief, need_index)
        asset = self.get_asset(media_asset_id)
        if asset is None:
            raise MediaPreconditionError(f"no media asset with id {media_asset_id}")
        cleaned_reason = _required_text("reason", reason)
        validated_request_id = _validate_request_id(request_id)

        current = self._active_satisfaction(work_item_id, brief.id, need_index)
        if current is not None and current.media_asset_id == media_asset_id:
            return current  # already bound to exactly this asset

        replacement = MediaNeedSatisfaction(
            work_item_id=work_item_id,
            content_brief_id=brief.id,
            need_index=need_index,
            media_asset_id=media_asset_id,
            status=SatisfactionStatus.ACTIVE,
            satisfied_by_user_id=user.id,
            reason=cleaned_reason,
            request_id=validated_request_id,
        )
        if current is not None:
            self._supersede(
                current,
                actor=user,
                reason=cleaned_reason,
                request_id=validated_request_id,
                replacement=replacement,
            )
        else:
            self._session.add(replacement)
            self._session.flush()
        return replacement

    def unsatisfy_need(
        self,
        work_item_id: uuid.UUID,
        need_index: int,
        *,
        user: User,
        reason: str,
        request_id: str | None = None,
    ) -> MediaNeedSatisfaction:
        """Withdraw the ACTIVE binding (no replacement; the need becomes
        honestly unsatisfied again). Returns the superseded row."""
        self._require_active_user(user)
        brief = self._resolve_brief_in_bounds(work_item_id)
        self._require_need_index(brief, need_index)
        current = self._active_satisfaction(work_item_id, brief.id, need_index)
        if current is None:
            raise MediaConflictError(f"need {need_index} has no active satisfaction to withdraw")
        cleaned_reason = _required_text("reason", reason)
        validated_request_id = _validate_request_id(request_id)
        self._supersede(
            current,
            actor=user,
            reason=cleaned_reason,
            request_id=validated_request_id,
            replacement=None,
        )
        return current

    # --- reads ----------------------------------------------------------------

    def needs_coverage(self, work_item_id: uuid.UUID) -> list[NeedCoverage] | None:
        """Per-need coverage against the ACTIVE brief; None when the work
        item or an active brief does not exist. UNSATISFIED needs appear
        with satisfaction=None — never hidden."""
        if self._workflow.get_by_id(work_item_id) is None:
            return None
        brief = self._briefs.get_active_brief(work_item_id)
        if brief is None:
            return None
        return [
            NeedCoverage(
                need_index=index,
                need=dict(need),
                satisfaction=self._active_satisfaction(work_item_id, brief.id, index),
            )
            for index, need in enumerate(brief.media_needs)
        ]

    def list_satisfactions(self, work_item_id: uuid.UUID) -> list[MediaNeedSatisfaction]:
        return list(
            self._session.execute(
                select(MediaNeedSatisfaction)
                .where(MediaNeedSatisfaction.work_item_id == work_item_id)
                .order_by(MediaNeedSatisfaction.created_at, MediaNeedSatisfaction.id)
            ).scalars()
        )

    # --- internals ------------------------------------------------------------

    def _resolve_brief_in_bounds(self, work_item_id: uuid.UUID) -> ContentBrief:
        work_item = self._workflow.get_by_id(work_item_id)
        if work_item is None:
            raise MediaPreconditionError(f"no editorial work item with id {work_item_id}")
        if work_item.current_state not in PERMITTED_MEDIA_STATES:
            permitted = ", ".join(sorted(state.value for state in PERMITTED_MEDIA_STATES))
            raise MediaPreconditionError(
                "media satisfaction is permitted only while the package is not "
                f"under terminal review ({permitted}); "
                f"current: {work_item.current_state.value}"
            )
        brief = self._briefs.get_active_brief(work_item_id)
        if brief is None or brief.status is not BriefStatus.ACCEPTED_FOR_DRAFTING:
            status = brief.status.value if brief is not None else "missing"
            raise MediaPreconditionError(
                f"media needs belong to the accepted brief (brief status: {status})"
            )
        return brief

    def _require_need_index(self, brief: ContentBrief, need_index: int) -> None:
        total = len(brief.media_needs)
        if need_index < 0 or need_index >= total:
            raise MediaInputError(
                f"the brief defines {total} media need(s); index {need_index} does not exist"
            )

    def _require_active_user(self, user: User) -> None:
        if not user.is_active:
            raise MediaPreconditionError("media operations require an ACTIVE user")

    def _active_satisfaction(
        self, work_item_id: uuid.UUID, brief_id: uuid.UUID, need_index: int
    ) -> MediaNeedSatisfaction | None:
        return self._session.execute(
            select(MediaNeedSatisfaction).where(
                MediaNeedSatisfaction.work_item_id == work_item_id,
                MediaNeedSatisfaction.content_brief_id == brief_id,
                MediaNeedSatisfaction.need_index == need_index,
                MediaNeedSatisfaction.status == SatisfactionStatus.ACTIVE,
            )
        ).scalar_one_or_none()

    def _supersede(
        self,
        current: MediaNeedSatisfaction,
        *,
        actor: User,
        reason: str,
        request_id: str | None,
        replacement: MediaNeedSatisfaction | None,
    ) -> None:
        # Shape 1: forward-only status change (pointer untouched).
        current.status = SatisfactionStatus.SUPERSEDED
        self._session.flush()
        if replacement is not None:
            self._session.add(replacement)
            self._session.flush()
            # Shape 2: one-shot pointer set on the superseded row.
            current.superseded_by_satisfaction_id = replacement.id
            self._session.flush()
        self._session.add(
            MediaSatisfactionEvent(
                satisfaction_id=current.id,
                from_status=SatisfactionStatus.ACTIVE,
                to_status=SatisfactionStatus.SUPERSEDED,
                actor_user_id=actor.id,
                reason=reason,
                request_id=request_id,
                replacement_satisfaction_id=replacement.id if replacement is not None else None,
                occurred_at=datetime.now(UTC),
            )
        )
        self._session.flush()


def _required_text(field: str, value: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not cleaned or len(cleaned) > MAX_TEXT_LENGTH:
        raise MediaInputError(f"{field} must be 1..{MAX_TEXT_LENGTH} characters")
    return cleaned


def _optional_text(field: str, value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_TEXT_LENGTH:
        raise MediaInputError(f"{field} must be at most {MAX_TEXT_LENGTH} characters")
    return cleaned


def _validate_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not is_valid_request_id(value):
        raise MediaInputError("request_id is not a valid correlation identifier")
    return value
