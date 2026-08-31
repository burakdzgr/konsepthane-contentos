"""Append/read evidence persistence and read-only provenance projections."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from contentos.discovery.models import DiscoveryItem
from contentos.fetching.snapshots import FetchSnapshot
from contentos.normalization.models import NormalizedDocument
from contentos.research.models import ResearchEvidence
from contentos.sources.models import Source


@dataclass(frozen=True, slots=True)
class ResearchProvenance:
    """Complete relational provenance needed to validate an evidence write."""

    document: NormalizedDocument
    snapshot: FetchSnapshot
    discovery_item: DiscoveryItem
    source: Source


class ResearchEvidenceRepository:
    """Persistence-only append/read API for immutable evidence rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, evidence: ResearchEvidence) -> ResearchEvidence:
        self._session.add(evidence)
        self._session.flush()
        return evidence

    def get_by_id(self, evidence_id: uuid.UUID) -> ResearchEvidence | None:
        return self._session.get(ResearchEvidence, evidence_id)

    def get_by_identity(
        self,
        normalized_document_id: uuid.UUID,
        extractor_name: str,
        extractor_version: str,
        evidence_key: str,
    ) -> ResearchEvidence | None:
        statement = select(ResearchEvidence).where(
            ResearchEvidence.normalized_document_id == normalized_document_id,
            ResearchEvidence.extractor_name == extractor_name,
            ResearchEvidence.extractor_version == extractor_version,
            ResearchEvidence.evidence_key == evidence_key,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_normalized_document(
        self, normalized_document_id: uuid.UUID
    ) -> list[ResearchEvidence]:
        statement = (
            select(ResearchEvidence)
            .where(ResearchEvidence.normalized_document_id == normalized_document_id)
            .order_by(
                ResearchEvidence.extracted_at,
                ResearchEvidence.created_at,
                ResearchEvidence.id,
            )
        )
        return list(self._session.execute(statement).scalars())


class ResearchProvenanceRepository:
    """Read-only access to normalized text and its exact governed source chain."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_document(self, normalized_document_id: uuid.UUID) -> NormalizedDocument | None:
        return self._session.get(NormalizedDocument, normalized_document_id)

    def get_provenance(self, normalized_document_id: uuid.UUID) -> ResearchProvenance | None:
        statement = (
            select(NormalizedDocument, FetchSnapshot, DiscoveryItem, Source)
            .join(FetchSnapshot, FetchSnapshot.id == NormalizedDocument.fetch_snapshot_id)
            .join(DiscoveryItem, DiscoveryItem.id == FetchSnapshot.discovery_item_id)
            .join(Source, Source.id == DiscoveryItem.source_id)
            .where(NormalizedDocument.id == normalized_document_id)
        )
        row = self._session.execute(statement).one_or_none()
        return _provenance(row) if row is not None else None


def _provenance(
    row: Row[tuple[NormalizedDocument, FetchSnapshot, DiscoveryItem, Source]],
) -> ResearchProvenance:
    document, snapshot, discovery_item, source = row
    return ResearchProvenance(document, snapshot, discovery_item, source)
