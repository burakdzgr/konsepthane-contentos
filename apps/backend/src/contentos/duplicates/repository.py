"""Append/read decisions and bounded local duplicate-comparison queries."""

import uuid

from sqlalchemy import Select, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from contentos.discovery.models import DiscoveryItem
from contentos.duplicates.models import DuplicateDecision
from contentos.duplicates.signals import ComparisonDocument
from contentos.fetching.snapshots import FetchSnapshot
from contentos.normalization.enums import NormalizationStatus
from contentos.normalization.models import NormalizedDocument


class DuplicateDecisionRepository:
    """Persistence-only append/read API for immutable decisions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, decision: DuplicateDecision) -> DuplicateDecision:
        self._session.add(decision)
        self._session.flush()
        return decision

    def get_by_id(self, decision_id: uuid.UUID) -> DuplicateDecision | None:
        return self._session.get(DuplicateDecision, decision_id)

    def get_by_document_and_engine(
        self,
        normalized_document_id: uuid.UUID,
        engine_name: str,
        engine_version: str,
    ) -> DuplicateDecision | None:
        statement = select(DuplicateDecision).where(
            DuplicateDecision.normalized_document_id == normalized_document_id,
            DuplicateDecision.engine_name == engine_name,
            DuplicateDecision.engine_version == engine_version,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_effective_for_document(
        self, normalized_document_id: uuid.UUID
    ) -> DuplicateDecision | None:
        """The latest/effective decision for one document.

        The deterministic ordering (evaluated_at, created_at, id descending)
        is the same "latest is effective" contract the Task 17 read
        projections use; consumers must never reimplement a variant.
        """
        statement = (
            select(DuplicateDecision)
            .where(DuplicateDecision.normalized_document_id == normalized_document_id)
            .order_by(
                DuplicateDecision.evaluated_at.desc(),
                DuplicateDecision.created_at.desc(),
                DuplicateDecision.id.desc(),
            )
            .limit(1)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_document(self, normalized_document_id: uuid.UUID) -> list[DuplicateDecision]:
        statement = (
            select(DuplicateDecision)
            .where(DuplicateDecision.normalized_document_id == normalized_document_id)
            .order_by(
                DuplicateDecision.evaluated_at,
                DuplicateDecision.created_at,
                DuplicateDecision.id,
            )
        )
        return list(self._session.execute(statement).scalars())


class DuplicateCandidateRepository:
    """Read-only bounded projection over local normalized-document provenance."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_document(self, normalized_document_id: uuid.UUID) -> ComparisonDocument | None:
        statement = self._projection().where(NormalizedDocument.id == normalized_document_id)
        row = self._session.execute(statement).one_or_none()
        return _comparison_document(row) if row is not None else None

    def list_candidates(
        self,
        target: ComparisonDocument,
        *,
        limit: int,
    ) -> tuple[ComparisonDocument, ...]:
        """Prioritize exact-signal candidates, then fill with recent successful rows."""
        base = self._projection().where(
            NormalizedDocument.normalization_status == NormalizationStatus.SUCCEEDED,
            NormalizedDocument.id != target.normalized_document_id,
            NormalizedDocument.fetch_snapshot_id != target.fetch_snapshot_id,
        )
        exact_conditions = [DiscoveryItem.canonical_url == target.canonical_url]
        if target.content_fingerprint is not None:
            exact_conditions.append(
                NormalizedDocument.content_fingerprint == target.content_fingerprint
            )
        if target.raw_body_sha256 is not None:
            exact_conditions.append(FetchSnapshot.body_sha256 == target.raw_body_sha256)
        if target.final_url is not None:
            exact_conditions.append(FetchSnapshot.final_url == target.final_url)

        ordering = (NormalizedDocument.normalized_at.desc(), NormalizedDocument.id)
        exact_rows = self._session.execute(
            base.where(or_(*exact_conditions)).order_by(*ordering).limit(limit)
        ).all()
        candidates = [_comparison_document(row) for row in exact_rows]
        seen = {candidate.normalized_document_id for candidate in candidates}
        remaining = limit - len(candidates)
        if remaining > 0:
            recent_statement = base
            if seen:
                recent_statement = recent_statement.where(NormalizedDocument.id.not_in(seen))
            recent_rows = self._session.execute(
                recent_statement.order_by(*ordering).limit(remaining)
            ).all()
            candidates.extend(_comparison_document(row) for row in recent_rows)
        return tuple(candidates)

    @staticmethod
    def _projection() -> Select[tuple[NormalizedDocument, FetchSnapshot, DiscoveryItem]]:
        return (
            select(NormalizedDocument, FetchSnapshot, DiscoveryItem)
            .join(FetchSnapshot, FetchSnapshot.id == NormalizedDocument.fetch_snapshot_id)
            .join(DiscoveryItem, DiscoveryItem.id == FetchSnapshot.discovery_item_id)
        )


def _comparison_document(
    row: Row[tuple[NormalizedDocument, FetchSnapshot, DiscoveryItem]],
) -> ComparisonDocument:
    document, snapshot, item = row
    return ComparisonDocument(
        normalized_document_id=document.id,
        fetch_snapshot_id=snapshot.id,
        discovery_item_id=item.id,
        normalization_status=document.normalization_status,
        canonical_url=item.canonical_url,
        final_url=snapshot.final_url,
        raw_body_sha256=snapshot.body_sha256,
        content_fingerprint=document.content_fingerprint,
        title=document.title,
        clean_text=document.clean_text,
    )
