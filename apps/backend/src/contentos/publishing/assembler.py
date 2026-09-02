"""Deterministic publication-package assembly (Phase 7 P1).

Gates (PHASE7_PUBLISHING_ARCHITECTURE.md §1/§4): assembly happens only
in APPROVED, only under a CURRENT approval (the
`require_current_approval` guard — a stale approval raises, it is
never ridden), only over the exact resolved package (ACTIVE ready QA
report covering the ACTIVE draft whose hash equals the approved hash),
and only when every brief media need is satisfied or consciously
waived. The payload is the approved draft STRUCTURE verbatim plus the
media manifest — nothing is enriched, rewritten, or added. Identical
content converges on the existing package (per-work-item UNIQUE
package hash); changed content gets a new version. The caller commits.
"""

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.ai.hashing import canonical_json
from contentos.auth.models import User
from contentos.briefs.repository import BriefRepository
from contentos.core.context import is_valid_request_id
from contentos.decisions.service import DecisionService
from contentos.drafts.repository import DraftRepository
from contentos.media.enums import SatisfactionStatus
from contentos.media.models import MediaAsset, MediaNeedSatisfaction
from contentos.publishing.errors import PublicationInputError, PublicationPreconditionError
from contentos.publishing.models import PublicationPackage
from contentos.publishing.values import PACKAGE_SCHEMA_VERSION
from contentos.qa.enums import QaOutcome, WaivableGateKey
from contentos.qa.repository import QaRepository
from contentos.workflow.enums import WorkflowState


@dataclass(frozen=True, slots=True)
class AssemblyResult:
    package: PublicationPackage
    created: bool


class PublicationAssembler:
    """Transport-neutral; flushes only — the caller commits."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._decisions = DecisionService(session)
        self._briefs = BriefRepository(session)
        self._drafts = DraftRepository(session)
        self._qa = QaRepository(session)

    def assemble(
        self,
        work_item_id: uuid.UUID,
        *,
        assembled_by: User,
        request_id: str | None = None,
    ) -> AssemblyResult:
        if not assembled_by.is_active:
            raise PublicationPreconditionError("assembly requires an ACTIVE user")
        validated_request_id = _validate_request_id(request_id)

        # The guard: no current approval, no package. StaleApprovalError
        # propagates typed — a stale approval is surfaced, never ridden.
        status = self._decisions.require_current_approval(work_item_id)
        resolved = self._decisions.resolve_package(
            work_item_id, expected_state=WorkflowState.APPROVED
        )
        if resolved.report.outcome is not QaOutcome.READY_FOR_HUMAN_REVIEW:
            raise PublicationPreconditionError(
                "the ACTIVE QA report outcome is "
                f"'{resolved.report.outcome.value}', not 'ready_for_human_review'"
            )
        if status.approved_content_hash != resolved.content_hash:
            raise PublicationPreconditionError(
                "the resolved package hash does not match the approved hash"
            )
        assert status.decision_id is not None  # approved + current implies it

        draft = self._drafts.get_active_draft(work_item_id)
        assert draft is not None and draft.id == resolved.content_draft_id
        brief = self._briefs.get_brief(draft.content_brief_id)
        assert brief is not None  # resolve_package already proved the chain

        media_manifest = self._build_media_manifest(work_item_id, brief)

        payload: dict[str, Any] = {
            "schema_version": PACKAGE_SCHEMA_VERSION,
            "work_item_id": str(work_item_id),
            "locale": brief.locale,
            "market": brief.market,
            # The approved draft structure VERBATIM — never enriched.
            "title_proposal": draft.title_proposal,
            "body": draft.body,
            "body_schema_version": draft.body_schema_version,
        }
        package_hash = hashlib.sha256(
            canonical_json({"payload": payload, "media_manifest": media_manifest}).encode("utf-8")
        ).hexdigest()

        existing = self._session.execute(
            select(PublicationPackage).where(
                PublicationPackage.work_item_id == work_item_id,
                PublicationPackage.package_hash == package_hash,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return AssemblyResult(package=existing, created=False)

        next_version = (
            int(
                self._session.scalar(
                    select(func.max(PublicationPackage.version)).where(
                        PublicationPackage.work_item_id == work_item_id
                    )
                )
                or 0
            )
            + 1
        )
        row = PublicationPackage(
            work_item_id=work_item_id,
            version=next_version,
            human_decision_id=status.decision_id,
            content_draft_id=draft.id,
            content_brief_id=brief.id,
            qa_report_id=resolved.report.id,
            content_hash=resolved.content_hash,
            payload=payload,
            payload_schema_version=PACKAGE_SCHEMA_VERSION,
            package_hash=package_hash,
            media_manifest=media_manifest,
            assembled_by_user_id=assembled_by.id,
            request_id=validated_request_id,
        )
        self._session.add(row)
        self._session.flush()
        return AssemblyResult(package=row, created=True)

    # --- internals ------------------------------------------------------------

    def _build_media_manifest(self, work_item_id: uuid.UUID, brief: Any) -> dict[str, Any]:
        """ACTIVE bindings per need; unmet needs refuse assembly unless a
        media waiver exists (the conscious deferral stays honest: waived
        unmet needs are LISTED in the manifest, never hidden)."""
        needs = list(brief.media_needs)
        if not needs:
            return {"needs": {}, "waived_unmet_indexes": []}
        active = {
            row.need_index: row
            for row in self._session.execute(
                select(MediaNeedSatisfaction).where(
                    MediaNeedSatisfaction.work_item_id == work_item_id,
                    MediaNeedSatisfaction.content_brief_id == brief.id,
                    MediaNeedSatisfaction.status == SatisfactionStatus.ACTIVE,
                )
            ).scalars()
        }
        unmet = sorted(index for index in range(len(needs)) if index not in active)
        if unmet:
            waivers = [
                waiver
                for waiver in self._qa.list_waivers(work_item_id)
                if waiver.gate_key is WaivableGateKey.MEDIA_NEEDS
            ]
            if not waivers:
                raise PublicationPreconditionError(
                    f"media needs {unmet} are unsatisfied and not waived; "
                    "bind assets or record a waiver before assembling"
                )
        asset_ids = {row.media_asset_id for row in active.values()}
        assets: dict[uuid.UUID, MediaAsset] = {}
        if asset_ids:
            for asset in self._session.execute(
                select(MediaAsset).where(MediaAsset.id.in_(asset_ids))
            ).scalars():
                assets[asset.id] = asset
        entries: dict[str, Any] = {}
        for index, row in sorted(active.items()):
            asset = assets[row.media_asset_id]
            entries[str(index)] = {
                "media_asset_id": str(asset.id),
                "content_sha256": asset.content_sha256,
                "media_type": asset.media_type,
                "byte_size": asset.byte_size,
                "alt_text": asset.alt_text,
                "license_note": asset.license_note,
                "source_attribution": asset.source_attribution,
                "origin": asset.origin.value,
            }
        return {"needs": entries, "waived_unmet_indexes": unmet}


def _validate_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    if not is_valid_request_id(value):
        raise PublicationInputError("request_id is not a valid correlation identifier")
    return value
