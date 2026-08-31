"""Persistence-only NormalizedDocument repository. Callers own transactions."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.normalization.models import NormalizedDocument


class NormalizedDocumentRepository:
    """Append and read immutable extractor-version outputs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, document: NormalizedDocument) -> NormalizedDocument:
        self._session.add(document)
        self._session.flush()
        return document

    def get_by_id(self, document_id: uuid.UUID) -> NormalizedDocument | None:
        return self._session.get(NormalizedDocument, document_id)

    def get_by_snapshot_and_extractor(
        self,
        fetch_snapshot_id: uuid.UUID,
        extractor_name: str,
        extractor_version: str,
    ) -> NormalizedDocument | None:
        statement = select(NormalizedDocument).where(
            NormalizedDocument.fetch_snapshot_id == fetch_snapshot_id,
            NormalizedDocument.extractor_name == extractor_name,
            NormalizedDocument.extractor_version == extractor_version,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_snapshot(self, fetch_snapshot_id: uuid.UUID) -> list[NormalizedDocument]:
        statement = (
            select(NormalizedDocument)
            .where(NormalizedDocument.fetch_snapshot_id == fetch_snapshot_id)
            .order_by(
                NormalizedDocument.normalized_at,
                NormalizedDocument.created_at,
                NormalizedDocument.id,
            )
        )
        return list(self._session.execute(statement).scalars())
