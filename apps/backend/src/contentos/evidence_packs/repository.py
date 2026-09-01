"""Narrow persistence access for evidence packs. Callers own commit.

Packs and items are append-only; contradictions may mutate ONLY their
resolution dimension, and only the service performs that mutation.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.evidence_packs.models import (
    EvidenceContradiction,
    EvidencePack,
    EvidencePackItem,
)


class EvidencePackRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def insert_pack(self, pack: EvidencePack) -> EvidencePack:
        self._session.add(pack)
        self._session.flush()
        return pack

    def insert_item(self, item: EvidencePackItem) -> EvidencePackItem:
        self._session.add(item)
        self._session.flush()
        return item

    def insert_contradiction(self, contradiction: EvidenceContradiction) -> EvidenceContradiction:
        self._session.add(contradiction)
        self._session.flush()
        return contradiction

    def get_pack(self, pack_id: uuid.UUID) -> EvidencePack | None:
        return self._session.get(EvidencePack, pack_id)

    def get_pack_by_identity(
        self,
        opportunity_id: uuid.UUID,
        assembler_name: str,
        assembler_version: str,
        assembly_input_hash: str,
    ) -> EvidencePack | None:
        statement = select(EvidencePack).where(
            EvidencePack.opportunity_id == opportunity_id,
            EvidencePack.assembler_name == assembler_name,
            EvidencePack.assembler_version == assembler_version,
            EvidencePack.assembly_input_hash == assembly_input_hash,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_latest_pack(self, opportunity_id: uuid.UUID) -> EvidencePack | None:
        """The latest pack version; old versions remain fully queryable."""
        statement = (
            select(EvidencePack)
            .where(EvidencePack.opportunity_id == opportunity_id)
            .order_by(EvidencePack.version.desc())
            .limit(1)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def next_version(self, opportunity_id: uuid.UUID) -> int:
        current = self._session.scalar(
            select(func.max(EvidencePack.version)).where(
                EvidencePack.opportunity_id == opportunity_id
            )
        )
        return int(current or 0) + 1

    def list_packs(self, opportunity_id: uuid.UUID) -> list[EvidencePack]:
        statement = (
            select(EvidencePack)
            .where(EvidencePack.opportunity_id == opportunity_id)
            .order_by(EvidencePack.version)
        )
        return list(self._session.execute(statement).scalars())

    def list_items(self, pack_id: uuid.UUID) -> list[EvidencePackItem]:
        statement = (
            select(EvidencePackItem)
            .where(EvidencePackItem.pack_id == pack_id)
            .order_by(EvidencePackItem.claim_cluster, EvidencePackItem.id)
        )
        return list(self._session.execute(statement).scalars())

    def get_contradiction(self, contradiction_id: uuid.UUID) -> EvidenceContradiction | None:
        return self._session.get(EvidenceContradiction, contradiction_id)

    def list_contradictions(self, pack_id: uuid.UUID) -> list[EvidenceContradiction]:
        statement = (
            select(EvidenceContradiction)
            .where(EvidenceContradiction.pack_id == pack_id)
            .order_by(EvidenceContradiction.created_at, EvidenceContradiction.id)
        )
        return list(self._session.execute(statement).scalars())
