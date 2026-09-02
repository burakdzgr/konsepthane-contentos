"""Read-only projections for Phase-6 media coverage.

The ACTIVE brief's media needs with, per need, the current human
satisfaction (asset metadata incl. origin, accessibility and licensing
fields, provenance) or an honest UNSATISFIED, plus the full
satisfaction history. Storage keys/paths and credential material never
appear here by construction — assets are addressed by id and served
only through the authenticated content route.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.api.read_models.editorial import _FrozenModel
from contentos.auth.models import User
from contentos.briefs.repository import BriefRepository
from contentos.media.enums import MediaOrigin, SatisfactionStatus
from contentos.media.models import MediaAsset, MediaNeedSatisfaction
from contentos.workflow.models import EditorialWorkItem


class MediaActorView(_FrozenModel):
    id: uuid.UUID
    username: str
    display_name: str


class MediaAssetView(_FrozenModel):
    id: uuid.UUID
    origin: MediaOrigin
    content_sha256: str
    byte_size: int
    media_type: str
    width: int | None
    height: int | None
    title: str | None
    alt_text: str
    license_note: str
    source_attribution: str | None
    generation_attempt_id: uuid.UUID | None
    created_by: MediaActorView
    created_at: datetime


class SatisfactionView(_FrozenModel):
    id: uuid.UUID
    need_index: int
    status: SatisfactionStatus
    asset: MediaAssetView
    satisfied_by: MediaActorView
    reason: str
    superseded_by_satisfaction_id: uuid.UUID | None
    created_at: datetime


class NeedCoverageView(_FrozenModel):
    need_index: int
    role: str
    purpose: str
    constraints: str | None
    # None means honestly UNSATISFIED — never hidden, never defaulted.
    satisfaction: SatisfactionView | None


class MediaCoveragePage(_FrozenModel):
    work_item_id: uuid.UUID
    content_brief_id: uuid.UUID | None
    needs: list[NeedCoverageView]
    satisfied_needs: int
    total_needs: int
    history: list[SatisfactionView]


def get_media_coverage(session: Session, work_item_id: uuid.UUID) -> MediaCoveragePage | None:
    if session.get(EditorialWorkItem, work_item_id) is None:
        return None
    brief = BriefRepository(session).get_active_brief(work_item_id)

    satisfactions = list(
        session.execute(
            select(MediaNeedSatisfaction)
            .where(MediaNeedSatisfaction.work_item_id == work_item_id)
            .order_by(MediaNeedSatisfaction.created_at, MediaNeedSatisfaction.id)
        ).scalars()
    )
    asset_ids = {row.media_asset_id for row in satisfactions}
    assets: dict[uuid.UUID, MediaAsset] = {}
    if asset_ids:
        for asset in session.execute(
            select(MediaAsset).where(MediaAsset.id.in_(asset_ids))
        ).scalars():
            assets[asset.id] = asset
    user_ids = {row.satisfied_by_user_id for row in satisfactions} | {
        asset.created_by_user_id for asset in assets.values()
    }
    users: dict[uuid.UUID, User] = {}
    if user_ids:
        for user in session.execute(select(User).where(User.id.in_(user_ids))).scalars():
            users[user.id] = user

    def _actor(user_id: uuid.UUID) -> MediaActorView:
        user = users[user_id]
        return MediaActorView(id=user.id, username=user.username, display_name=user.display_name)

    def _asset_view(asset: MediaAsset) -> MediaAssetView:
        return MediaAssetView(
            id=asset.id,
            origin=asset.origin,
            content_sha256=asset.content_sha256,
            byte_size=asset.byte_size,
            media_type=asset.media_type,
            width=asset.width,
            height=asset.height,
            title=asset.title,
            alt_text=asset.alt_text,
            license_note=asset.license_note,
            source_attribution=asset.source_attribution,
            generation_attempt_id=asset.generation_attempt_id,
            created_by=_actor(asset.created_by_user_id),
            created_at=asset.created_at,
        )

    def _satisfaction_view(row: MediaNeedSatisfaction) -> SatisfactionView:
        return SatisfactionView(
            id=row.id,
            need_index=row.need_index,
            status=row.status,
            asset=_asset_view(assets[row.media_asset_id]),
            satisfied_by=_actor(row.satisfied_by_user_id),
            reason=row.reason,
            superseded_by_satisfaction_id=row.superseded_by_satisfaction_id,
            created_at=row.created_at,
        )

    needs: list[NeedCoverageView] = []
    if brief is not None:
        active_by_index = {
            row.need_index: row
            for row in satisfactions
            if row.status is SatisfactionStatus.ACTIVE and row.content_brief_id == brief.id
        }
        for index, need in enumerate(brief.media_needs):
            active = active_by_index.get(index)
            needs.append(
                NeedCoverageView(
                    need_index=index,
                    role=str(need.get("role", "")),
                    purpose=str(need.get("purpose", "")),
                    constraints=need.get("constraints"),
                    satisfaction=_satisfaction_view(active) if active is not None else None,
                )
            )

    return MediaCoveragePage(
        work_item_id=work_item_id,
        content_brief_id=brief.id if brief is not None else None,
        needs=needs,
        satisfied_needs=sum(1 for need in needs if need.satisfaction is not None),
        total_needs=len(needs),
        history=[_satisfaction_view(row) for row in satisfactions],
    )
