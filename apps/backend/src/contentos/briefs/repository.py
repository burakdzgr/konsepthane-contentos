"""Narrow brief persistence access. Callers own commit.

Brief content, claims, evidence links, and status events are append-only
from this surface: there is no content update, no delete, and deliberately
no method that can add claims or evidence links after a brief version was
created — the whole version is one immutable semantic unit.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.briefs.enums import BriefStatus
from contentos.briefs.models import (
    BriefClaim,
    BriefClaimEvidence,
    BriefStatusEvent,
    ContentBrief,
)


class BriefRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- creation-time inserts (service-internal, one atomic version) ------

    def insert_brief(self, brief: ContentBrief) -> ContentBrief:
        self._session.add(brief)
        self._session.flush()
        return brief

    def insert_claim(self, claim: BriefClaim) -> BriefClaim:
        self._session.add(claim)
        self._session.flush()
        return claim

    def insert_claim_evidence(self, link: BriefClaimEvidence) -> BriefClaimEvidence:
        self._session.add(link)
        self._session.flush()
        return link

    def append_status_event(self, event: BriefStatusEvent) -> BriefStatusEvent:
        self._session.add(event)
        self._session.flush()
        return event

    # --- reads --------------------------------------------------------------

    def get_brief(self, brief_id: uuid.UUID) -> ContentBrief | None:
        return self._session.get(ContentBrief, brief_id)

    def get_by_identity(
        self,
        work_item_id: uuid.UUID,
        idea_id: uuid.UUID,
        evidence_pack_id: uuid.UUID,
        search_intent_analysis_id: uuid.UUID,
        engine_name: str,
        engine_version: str,
    ) -> ContentBrief | None:
        statement = select(ContentBrief).where(
            ContentBrief.work_item_id == work_item_id,
            ContentBrief.idea_id == idea_id,
            ContentBrief.evidence_pack_id == evidence_pack_id,
            ContentBrief.search_intent_analysis_id == search_intent_analysis_id,
            ContentBrief.engine_name == engine_name,
            ContentBrief.engine_version == engine_version,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_composition_attempt(self, composition_attempt_id: uuid.UUID) -> ContentBrief | None:
        statement = select(ContentBrief).where(
            ContentBrief.composition_attempt_id == composition_attempt_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_active_brief(self, work_item_id: uuid.UUID) -> ContentBrief | None:
        """The single non-superseded brief for a work item, if any."""
        statement = select(ContentBrief).where(
            ContentBrief.work_item_id == work_item_id,
            ContentBrief.status != BriefStatus.SUPERSEDED,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_by_work_item(self, work_item_id: uuid.UUID) -> list[ContentBrief]:
        statement = (
            select(ContentBrief)
            .where(ContentBrief.work_item_id == work_item_id)
            .order_by(ContentBrief.version)
        )
        return list(self._session.execute(statement).scalars())

    def next_version(self, work_item_id: uuid.UUID) -> int:
        current = self._session.scalar(
            select(func.max(ContentBrief.version)).where(ContentBrief.work_item_id == work_item_id)
        )
        return int(current or 0) + 1

    def list_claims(self, brief_id: uuid.UUID) -> list[BriefClaim]:
        statement = (
            select(BriefClaim).where(BriefClaim.brief_id == brief_id).order_by(BriefClaim.claim_key)
        )
        return list(self._session.execute(statement).scalars())

    def list_claim_evidence(self, claim_id: uuid.UUID) -> list[BriefClaimEvidence]:
        statement = (
            select(BriefClaimEvidence)
            .where(BriefClaimEvidence.claim_id == claim_id)
            .order_by(BriefClaimEvidence.research_evidence_id)
        )
        return list(self._session.execute(statement).scalars())

    def list_status_events(self, brief_id: uuid.UUID) -> list[BriefStatusEvent]:
        statement = (
            select(BriefStatusEvent)
            .where(BriefStatusEvent.brief_id == brief_id)
            .order_by(BriefStatusEvent.id)
        )
        return list(self._session.execute(statement).scalars())
