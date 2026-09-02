"""Read-only projections for Phase-7 publication state.

Packages are summarized — the approved body ships to the Publishing API,
not to the admin screen — and attempts appear exactly as recorded with
their sanitized error classes. No publishing URL or key material exists
anywhere in these rows by construction.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.api.read_models.editorial import _FrozenModel
from contentos.auth.models import User
from contentos.decisions.service import DecisionService
from contentos.publishing.models import PublicationAttempt, PublicationPackage
from contentos.workflow.models import EditorialWorkItem


class PublicationActorView(_FrozenModel):
    id: uuid.UUID
    username: str
    display_name: str


class PublicationAttemptView(_FrozenModel):
    id: uuid.UUID
    attempt_number: int
    status: str
    error_class: str | None
    remote_publication_ref: str | None
    transport_name: str
    created_at: datetime


class PublicationPackageView(_FrozenModel):
    id: uuid.UUID
    version: int
    human_decision_id: uuid.UUID
    content_draft_id: uuid.UUID
    content_brief_id: uuid.UUID
    qa_report_id: uuid.UUID
    content_hash: str
    package_hash: str
    payload_schema_version: str
    # A SUMMARY only: the approved body ships to the API, never here.
    title_proposal: str | None
    locale: str
    market: str
    section_count: int
    manifest_needs: int
    waived_unmet_indexes: list[int]
    assembled_by: PublicationActorView
    created_at: datetime
    attempts: list[PublicationAttemptView]


class PublicationPage(_FrozenModel):
    work_item_id: uuid.UUID
    packages: list[PublicationPackageView]
    # None when no package exists yet; else whether the CURRENT approval
    # still covers the latest package's content.
    latest_package_approval_current: bool | None


def get_publication(session: Session, work_item_id: uuid.UUID) -> PublicationPage | None:
    if session.get(EditorialWorkItem, work_item_id) is None:
        return None
    packages = list(
        session.execute(
            select(PublicationPackage)
            .where(PublicationPackage.work_item_id == work_item_id)
            .order_by(PublicationPackage.version.desc())
        ).scalars()
    )
    attempts_by_package: dict[uuid.UUID, list[PublicationAttempt]] = {}
    if packages:
        for attempt in session.execute(
            select(PublicationAttempt)
            .where(PublicationAttempt.publication_package_id.in_([p.id for p in packages]))
            .order_by(PublicationAttempt.attempt_number)
        ).scalars():
            attempts_by_package.setdefault(attempt.publication_package_id, []).append(attempt)
    user_ids = {package.assembled_by_user_id for package in packages}
    users: dict[uuid.UUID, User] = {}
    if user_ids:
        for user in session.execute(select(User).where(User.id.in_(user_ids))).scalars():
            users[user.id] = user

    def _package_view(package: PublicationPackage) -> PublicationPackageView:
        payload: dict[str, Any] = package.payload
        body = payload.get("body") or {}
        sections = body.get("sections") if isinstance(body, dict) else None
        manifest = package.media_manifest or {}
        user = users[package.assembled_by_user_id]
        return PublicationPackageView(
            id=package.id,
            version=package.version,
            human_decision_id=package.human_decision_id,
            content_draft_id=package.content_draft_id,
            content_brief_id=package.content_brief_id,
            qa_report_id=package.qa_report_id,
            content_hash=package.content_hash,
            package_hash=package.package_hash,
            payload_schema_version=package.payload_schema_version,
            title_proposal=payload.get("title_proposal"),
            locale=str(payload.get("locale", "")),
            market=str(payload.get("market", "")),
            section_count=len(sections) if isinstance(sections, list) else 0,
            manifest_needs=len(manifest.get("needs", {}) or {}),
            waived_unmet_indexes=[
                int(index) for index in (manifest.get("waived_unmet_indexes") or [])
            ],
            assembled_by=PublicationActorView(
                id=user.id, username=user.username, display_name=user.display_name
            ),
            created_at=package.created_at,
            attempts=[
                PublicationAttemptView(
                    id=attempt.id,
                    attempt_number=attempt.attempt_number,
                    status=attempt.status,
                    error_class=attempt.error_class,
                    remote_publication_ref=attempt.remote_publication_ref,
                    transport_name=attempt.transport_name,
                    created_at=attempt.created_at,
                )
                for attempt in attempts_by_package.get(package.id, [])
            ],
        )

    latest_current: bool | None = None
    if packages:
        status = DecisionService(session).approval_status(work_item_id)
        latest_current = bool(
            status.approved
            and status.current
            and status.approved_content_hash == packages[0].content_hash
        )
    return PublicationPage(
        work_item_id=work_item_id,
        packages=[_package_view(package) for package in packages],
        latest_package_approval_current=latest_current,
    )
