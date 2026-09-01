"""Bounded read models for internal research-pipeline visibility.

Everything here is a read-only projection of durable PostgreSQL state: the
queue never contributes operational truth, and no function writes or commits.

Latest-stage semantics (deterministic, FK-linked):

- latest fetch attempt: newest FetchSnapshot for the DiscoveryItem by
  (fetched_at, created_at, id) descending — the same ordering the fetch
  history uses, so "latest" is always the last row of that history;
- latest normalization: newest NormalizedDocument across all of the item's
  snapshots by (normalized_at, created_at, id) descending;
- latest duplicate decision: newest DuplicateDecision by
  (evaluated_at, created_at, id) descending, scoped to the chosen latest
  NormalizedDocument only, so a decision for an older document is never
  presented as if it belonged to the latest one;
- evidence: aggregated over the chosen latest NormalizedDocument (list) or
  over all of the item's documents (detail summary); only counts and the
  newest timestamp — never statements or excerpts.

N+1 avoidance: each list endpoint is one SELECT built from window-function
subqueries (row_number over the partition orderings above) plus one COUNT over
the identical filtered join, so filters on projected stages stay correct and
query count is independent of page size. The detail endpoint issues a small
fixed set of bounded queries for one item.

Deliberately never exposed: raw payload bytes and references, clean_text,
excerpts, evidence statements, wholesale structured/metadata JSON, headers,
redirect chains, and any URL/secret configuration.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from contentos.discovery.enums import (
    DiscoveryLifecycleState,
    DiscoveryMethod,
    DiscoveryRejectionReason,
)
from contentos.discovery.models import DiscoveryItem
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.fetching.models import FetchOutcome, RetryClassification, RobotsDecision
from contentos.fetching.snapshots import FetchSnapshot
from contentos.normalization.enums import NormalizationFailureCode, NormalizationStatus
from contentos.normalization.models import NormalizedDocument
from contentos.research.models import ResearchEvidence
from contentos.sources.enums import (
    DiscoveryStrategy,
    SourceKind,
    SourceLifecycleState,
    TrustTier,
)
from contentos.sources.models import Source

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 100
MAX_PAGE_OFFSET = 1_000_000
MAX_TEXT_SEARCH_LENGTH = 100
MAX_URL_SEARCH_LENGTH = 200
MAX_DETAIL_HISTORY = 20


class _FrozenModel(BaseModel):
    """Immutable read model; enums serialize to their stable persisted values."""

    model_config = ConfigDict(frozen=True)


class SourceListItem(_FrozenModel):
    id: uuid.UUID
    slug: str
    name: str
    kind: SourceKind
    locale: str
    market: str
    lifecycle_state: SourceLifecycleState
    trust_tier: TrustTier
    discovery_strategy: DiscoveryStrategy
    base_url: str
    created_at: datetime
    updated_at: datetime
    total_discovery_items: int
    discovered_count: int
    accepted_count: int
    fetched_count: int
    fetch_failed_count: int
    rejected_count: int


class SourceListPage(_FrozenModel):
    items: list[SourceListItem]
    total: int
    limit: int
    offset: int


class PipelineListItem(_FrozenModel):
    id: uuid.UUID
    source_id: uuid.UUID
    source_slug: str
    source_name: str
    canonical_url: str
    discovery_method: DiscoveryMethod
    lifecycle_state: DiscoveryLifecycleState
    rejection_reason: DiscoveryRejectionReason | None
    discovered_at: datetime
    last_seen_at: datetime
    external_published_at: datetime | None
    fetch_snapshot_id: uuid.UUID | None
    fetch_outcome: FetchOutcome | None
    fetched_at: datetime | None
    status_code: int | None
    retry_classification: RetryClassification | None
    normalized_document_id: uuid.UUID | None
    normalization_status: NormalizationStatus | None
    normalization_failure_code: NormalizationFailureCode | None
    normalized_at: datetime | None
    duplicate_decision_id: uuid.UUID | None
    duplicate_outcome: DuplicateDecisionOutcome | None
    duplicate_evaluated_at: datetime | None
    evidence_count: int
    latest_evidence_at: datetime | None


class PipelineListPage(_FrozenModel):
    items: list[PipelineListItem]
    total: int
    limit: int
    offset: int


class SourceSummary(_FrozenModel):
    id: uuid.UUID
    slug: str
    name: str
    kind: SourceKind
    locale: str
    market: str
    lifecycle_state: SourceLifecycleState
    trust_tier: TrustTier
    discovery_strategy: DiscoveryStrategy
    base_url: str


class DiscoveryItemDetail(_FrozenModel):
    id: uuid.UUID
    source_id: uuid.UUID
    discovered_url: str
    canonical_url: str
    discovery_method: DiscoveryMethod
    lifecycle_state: DiscoveryLifecycleState
    rejection_reason: DiscoveryRejectionReason | None
    rejection_note: str | None
    title_hint: str | None
    locale: str
    external_published_at: datetime | None
    discovered_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class FetchAttempt(_FrozenModel):
    id: uuid.UUID
    fetch_outcome: FetchOutcome
    retry_classification: RetryClassification
    robots_decision: RobotsDecision
    status_code: int | None
    content_type: str | None
    body_size_bytes: int | None
    duration_ms: float
    failure_detail: str | None
    fetched_at: datetime


class NormalizationAttempt(_FrozenModel):
    id: uuid.UUID
    fetch_snapshot_id: uuid.UUID
    normalization_status: NormalizationStatus
    extractor_name: str
    extractor_version: str
    parser_version: str | None
    failure_code: NormalizationFailureCode | None
    failure_detail: str | None
    title: str | None
    author_name: str | None
    external_published_at: datetime | None
    normalized_at: datetime


class DuplicateDecisionSummary(_FrozenModel):
    id: uuid.UUID
    normalized_document_id: uuid.UUID
    engine_name: str
    engine_version: str
    decision: DuplicateDecisionOutcome
    rationale_codes: list[str]
    match_count: int
    evaluated_at: datetime


class EvidenceSummary(_FrozenModel):
    total: int
    by_verification_status: dict[str, int]
    by_evidence_type: dict[str, int]
    latest_extracted_at: datetime | None


class PipelineDetail(_FrozenModel):
    source: SourceSummary
    discovery_item: DiscoveryItemDetail
    fetch_attempts: list[FetchAttempt]
    total_fetch_attempts: int
    fetch_attempts_truncated: bool
    normalization_attempts: list[NormalizationAttempt]
    total_normalization_attempts: int
    normalization_attempts_truncated: bool
    duplicate_decisions: list[DuplicateDecisionSummary]
    total_duplicate_decisions: int
    duplicate_decisions_truncated: bool
    evidence: EvidenceSummary


def _lifecycle_count(state: DiscoveryLifecycleState) -> Any:
    return func.sum(case((DiscoveryItem.lifecycle_state == state, 1), else_=0))


def list_sources(
    session: Session,
    *,
    lifecycle_state: SourceLifecycleState | None = None,
    kind: SourceKind | None = None,
    discovery_strategy: DiscoveryStrategy | None = None,
    search: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    offset: int = 0,
) -> SourceListPage:
    """One aggregate-joined page query plus one count query; never N+1."""
    filters = []
    if lifecycle_state is not None:
        filters.append(Source.lifecycle_state == lifecycle_state)
    if kind is not None:
        filters.append(Source.kind == kind)
    if discovery_strategy is not None:
        filters.append(Source.discovery_strategy == discovery_strategy)
    if search is not None:
        term = search[:MAX_TEXT_SEARCH_LENGTH]
        filters.append(
            Source.slug.icontains(term, autoescape=True)
            | Source.name.icontains(term, autoescape=True)
        )

    counts = (
        select(
            DiscoveryItem.source_id.label("source_id"),
            func.count().label("total_items"),
            _lifecycle_count(DiscoveryLifecycleState.DISCOVERED).label("discovered"),
            _lifecycle_count(DiscoveryLifecycleState.ACCEPTED).label("accepted"),
            _lifecycle_count(DiscoveryLifecycleState.FETCHED).label("fetched"),
            _lifecycle_count(DiscoveryLifecycleState.FETCH_FAILED).label("fetch_failed"),
            _lifecycle_count(DiscoveryLifecycleState.REJECTED).label("rejected"),
        )
        .group_by(DiscoveryItem.source_id)
        .subquery()
    )

    statement = (
        select(
            Source,
            counts.c.total_items,
            counts.c.discovered,
            counts.c.accepted,
            counts.c.fetched,
            counts.c.fetch_failed,
            counts.c.rejected,
        )
        .outerjoin(counts, counts.c.source_id == Source.id)
        .where(*filters)
        .order_by(Source.updated_at.desc(), Source.created_at.desc(), Source.id)
        .limit(limit)
        .offset(offset)
    )
    total = session.scalar(select(func.count()).select_from(Source).where(*filters)) or 0

    items = [
        SourceListItem(
            id=source.id,
            slug=source.slug,
            name=source.name,
            kind=source.kind,
            locale=source.locale,
            market=source.market,
            lifecycle_state=source.lifecycle_state,
            trust_tier=source.trust_tier,
            discovery_strategy=source.discovery_strategy,
            base_url=source.base_url,
            created_at=source.created_at,
            updated_at=source.updated_at,
            total_discovery_items=int(total_items or 0),
            discovered_count=int(discovered or 0),
            accepted_count=int(accepted or 0),
            fetched_count=int(fetched or 0),
            fetch_failed_count=int(fetch_failed or 0),
            rejected_count=int(rejected or 0),
        )
        for source, total_items, discovered, accepted, fetched, fetch_failed, rejected in (
            session.execute(statement)
        )
    ]
    return SourceListPage(items=items, total=int(total), limit=limit, offset=offset)


def _latest_fetch_subquery() -> Any:
    ranked = select(
        FetchSnapshot.id.label("snapshot_id"),
        FetchSnapshot.discovery_item_id.label("discovery_item_id"),
        FetchSnapshot.fetch_outcome.label("fetch_outcome"),
        FetchSnapshot.fetched_at.label("fetched_at"),
        FetchSnapshot.status_code.label("status_code"),
        FetchSnapshot.retry_classification.label("retry_classification"),
        func.row_number()
        .over(
            partition_by=FetchSnapshot.discovery_item_id,
            order_by=(
                FetchSnapshot.fetched_at.desc(),
                FetchSnapshot.created_at.desc(),
                FetchSnapshot.id.desc(),
            ),
        )
        .label("rn"),
    ).subquery()
    return select(ranked).where(ranked.c.rn == 1).subquery()


def _latest_normalization_subquery() -> Any:
    ranked = (
        select(
            NormalizedDocument.id.label("document_id"),
            FetchSnapshot.discovery_item_id.label("discovery_item_id"),
            NormalizedDocument.normalization_status.label("normalization_status"),
            NormalizedDocument.failure_code.label("failure_code"),
            NormalizedDocument.normalized_at.label("normalized_at"),
            func.row_number()
            .over(
                partition_by=FetchSnapshot.discovery_item_id,
                order_by=(
                    NormalizedDocument.normalized_at.desc(),
                    NormalizedDocument.created_at.desc(),
                    NormalizedDocument.id.desc(),
                ),
            )
            .label("rn"),
        )
        .join(FetchSnapshot, NormalizedDocument.fetch_snapshot_id == FetchSnapshot.id)
        .subquery()
    )
    return select(ranked).where(ranked.c.rn == 1).subquery()


def _latest_duplicate_subquery() -> Any:
    ranked = select(
        DuplicateDecision.id.label("decision_id"),
        DuplicateDecision.normalized_document_id.label("normalized_document_id"),
        DuplicateDecision.decision.label("decision"),
        DuplicateDecision.evaluated_at.label("evaluated_at"),
        func.row_number()
        .over(
            partition_by=DuplicateDecision.normalized_document_id,
            order_by=(
                DuplicateDecision.evaluated_at.desc(),
                DuplicateDecision.created_at.desc(),
                DuplicateDecision.id.desc(),
            ),
        )
        .label("rn"),
    ).subquery()
    return select(ranked).where(ranked.c.rn == 1).subquery()


def _evidence_aggregate_subquery() -> Any:
    return (
        select(
            ResearchEvidence.normalized_document_id.label("normalized_document_id"),
            func.count().label("evidence_count"),
            func.max(ResearchEvidence.extracted_at).label("latest_evidence_at"),
        )
        .group_by(ResearchEvidence.normalized_document_id)
        .subquery()
    )


def list_pipeline_items(
    session: Session,
    *,
    source_id: uuid.UUID | None = None,
    lifecycle_state: DiscoveryLifecycleState | None = None,
    discovery_method: DiscoveryMethod | None = None,
    fetch_outcome: FetchOutcome | None = None,
    normalization_status: NormalizationStatus | None = None,
    duplicate_outcome: DuplicateDecisionOutcome | None = None,
    has_evidence: bool | None = None,
    url_contains: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    offset: int = 0,
) -> PipelineListPage:
    """One projected page query plus one count query over the same join."""
    latest_fetch = _latest_fetch_subquery()
    latest_norm = _latest_normalization_subquery()
    latest_dup = _latest_duplicate_subquery()
    evidence = _evidence_aggregate_subquery()

    filters = []
    if source_id is not None:
        filters.append(DiscoveryItem.source_id == source_id)
    if lifecycle_state is not None:
        filters.append(DiscoveryItem.lifecycle_state == lifecycle_state)
    if discovery_method is not None:
        filters.append(DiscoveryItem.discovery_method == discovery_method)
    if fetch_outcome is not None:
        filters.append(latest_fetch.c.fetch_outcome == fetch_outcome)
    if normalization_status is not None:
        filters.append(latest_norm.c.normalization_status == normalization_status)
    if duplicate_outcome is not None:
        filters.append(latest_dup.c.decision == duplicate_outcome)
    if has_evidence is True:
        filters.append(evidence.c.evidence_count.is_not(None))
    elif has_evidence is False:
        filters.append(evidence.c.evidence_count.is_(None))
    if url_contains is not None:
        term = url_contains[:MAX_URL_SEARCH_LENGTH]
        filters.append(DiscoveryItem.canonical_url.icontains(term, autoescape=True))

    def joined(statement: Select[Any]) -> Select[Any]:
        return (
            statement.join(Source, DiscoveryItem.source_id == Source.id)
            .outerjoin(latest_fetch, latest_fetch.c.discovery_item_id == DiscoveryItem.id)
            .outerjoin(latest_norm, latest_norm.c.discovery_item_id == DiscoveryItem.id)
            .outerjoin(
                latest_dup,
                latest_dup.c.normalized_document_id == latest_norm.c.document_id,
            )
            .outerjoin(
                evidence,
                evidence.c.normalized_document_id == latest_norm.c.document_id,
            )
            .where(*filters)
        )

    statement = (
        joined(
            select(
                DiscoveryItem,
                Source.slug,
                Source.name,
                latest_fetch.c.snapshot_id,
                latest_fetch.c.fetch_outcome,
                latest_fetch.c.fetched_at,
                latest_fetch.c.status_code,
                latest_fetch.c.retry_classification,
                latest_norm.c.document_id,
                latest_norm.c.normalization_status,
                latest_norm.c.failure_code,
                latest_norm.c.normalized_at,
                latest_dup.c.decision_id,
                latest_dup.c.decision,
                latest_dup.c.evaluated_at,
                evidence.c.evidence_count,
                evidence.c.latest_evidence_at,
            )
        )
        .order_by(
            DiscoveryItem.last_seen_at.desc(),
            DiscoveryItem.discovered_at.desc(),
            DiscoveryItem.id,
        )
        .limit(limit)
        .offset(offset)
    )
    total = (
        session.scalar(
            select(func.count()).select_from(joined(select(DiscoveryItem.id)).subquery())
        )
        or 0
    )

    items = []
    for row in session.execute(statement):
        (
            item,
            source_slug,
            source_name,
            snapshot_id,
            outcome,
            fetched_at,
            status_code,
            retry_classification,
            document_id,
            norm_status,
            failure_code,
            normalized_at,
            decision_id,
            decision,
            evaluated_at,
            evidence_count,
            latest_evidence_at,
        ) = row
        items.append(
            PipelineListItem(
                id=item.id,
                source_id=item.source_id,
                source_slug=source_slug,
                source_name=source_name,
                canonical_url=item.canonical_url,
                discovery_method=item.discovery_method,
                lifecycle_state=item.lifecycle_state,
                rejection_reason=item.rejection_reason,
                discovered_at=item.discovered_at,
                last_seen_at=item.last_seen_at,
                external_published_at=item.external_published_at,
                fetch_snapshot_id=snapshot_id,
                fetch_outcome=outcome,
                fetched_at=fetched_at,
                status_code=status_code,
                retry_classification=retry_classification,
                normalized_document_id=document_id,
                normalization_status=norm_status,
                normalization_failure_code=failure_code,
                normalized_at=normalized_at,
                duplicate_decision_id=decision_id,
                duplicate_outcome=decision,
                duplicate_evaluated_at=evaluated_at,
                evidence_count=int(evidence_count or 0),
                latest_evidence_at=latest_evidence_at,
            )
        )
    return PipelineListPage(items=items, total=int(total), limit=limit, offset=offset)


def get_pipeline_detail(session: Session, discovery_item_id: uuid.UUID) -> PipelineDetail | None:
    """Bounded fixed set of queries for one DiscoveryItem; None when missing."""
    item = session.get(DiscoveryItem, discovery_item_id)
    if item is None:
        return None
    source = session.get(Source, item.source_id)
    if source is None:  # pragma: no cover - FK guarantees the source exists
        return None

    snapshots = list(
        session.execute(
            select(FetchSnapshot)
            .where(FetchSnapshot.discovery_item_id == item.id)
            .order_by(
                FetchSnapshot.fetched_at.desc(),
                FetchSnapshot.created_at.desc(),
                FetchSnapshot.id.desc(),
            )
            .limit(MAX_DETAIL_HISTORY)
        ).scalars()
    )
    total_snapshots = int(
        session.scalar(
            select(func.count())
            .select_from(FetchSnapshot)
            .where(FetchSnapshot.discovery_item_id == item.id)
        )
        or 0
    )

    documents = list(
        session.execute(
            select(NormalizedDocument)
            .join(FetchSnapshot, NormalizedDocument.fetch_snapshot_id == FetchSnapshot.id)
            .where(FetchSnapshot.discovery_item_id == item.id)
            .order_by(
                NormalizedDocument.normalized_at.desc(),
                NormalizedDocument.created_at.desc(),
                NormalizedDocument.id.desc(),
            )
            .limit(MAX_DETAIL_HISTORY)
        ).scalars()
    )
    total_documents = int(
        session.scalar(
            select(func.count())
            .select_from(NormalizedDocument)
            .join(FetchSnapshot, NormalizedDocument.fetch_snapshot_id == FetchSnapshot.id)
            .where(FetchSnapshot.discovery_item_id == item.id)
        )
        or 0
    )

    decisions = list(
        session.execute(
            select(DuplicateDecision)
            .join(
                NormalizedDocument,
                DuplicateDecision.normalized_document_id == NormalizedDocument.id,
            )
            .join(FetchSnapshot, NormalizedDocument.fetch_snapshot_id == FetchSnapshot.id)
            .where(FetchSnapshot.discovery_item_id == item.id)
            .order_by(
                DuplicateDecision.evaluated_at.desc(),
                DuplicateDecision.created_at.desc(),
                DuplicateDecision.id.desc(),
            )
            .limit(MAX_DETAIL_HISTORY)
        ).scalars()
    )
    total_decisions = int(
        session.scalar(
            select(func.count())
            .select_from(DuplicateDecision)
            .join(
                NormalizedDocument,
                DuplicateDecision.normalized_document_id == NormalizedDocument.id,
            )
            .join(FetchSnapshot, NormalizedDocument.fetch_snapshot_id == FetchSnapshot.id)
            .where(FetchSnapshot.discovery_item_id == item.id)
        )
        or 0
    )

    # One grouped aggregate covers total, both breakdowns, and the newest
    # timestamp without ever selecting statement or excerpt columns.
    evidence_rows = session.execute(
        select(
            ResearchEvidence.verification_status,
            ResearchEvidence.evidence_type,
            func.count(),
            func.max(ResearchEvidence.extracted_at),
        )
        .join(
            NormalizedDocument,
            ResearchEvidence.normalized_document_id == NormalizedDocument.id,
        )
        .join(FetchSnapshot, NormalizedDocument.fetch_snapshot_id == FetchSnapshot.id)
        .where(FetchSnapshot.discovery_item_id == item.id)
        .group_by(ResearchEvidence.verification_status, ResearchEvidence.evidence_type)
    ).all()
    evidence_total = 0
    by_verification_status: dict[str, int] = {}
    by_evidence_type: dict[str, int] = {}
    latest_extracted_at: datetime | None = None
    for verification_status, evidence_type, count, newest in evidence_rows:
        group_count = int(count)
        evidence_total += group_count
        status_key = str(verification_status.value)
        type_key = str(evidence_type.value)
        by_verification_status[status_key] = by_verification_status.get(status_key, 0) + group_count
        by_evidence_type[type_key] = by_evidence_type.get(type_key, 0) + group_count
        if newest is not None and (latest_extracted_at is None or newest > latest_extracted_at):
            latest_extracted_at = newest

    return PipelineDetail(
        source=SourceSummary(
            id=source.id,
            slug=source.slug,
            name=source.name,
            kind=source.kind,
            locale=source.locale,
            market=source.market,
            lifecycle_state=source.lifecycle_state,
            trust_tier=source.trust_tier,
            discovery_strategy=source.discovery_strategy,
            base_url=source.base_url,
        ),
        discovery_item=DiscoveryItemDetail(
            id=item.id,
            source_id=item.source_id,
            discovered_url=item.discovered_url,
            canonical_url=item.canonical_url,
            discovery_method=item.discovery_method,
            lifecycle_state=item.lifecycle_state,
            rejection_reason=item.rejection_reason,
            rejection_note=item.rejection_note,
            title_hint=item.title_hint,
            locale=item.locale,
            external_published_at=item.external_published_at,
            discovered_at=item.discovered_at,
            last_seen_at=item.last_seen_at,
            created_at=item.created_at,
            updated_at=item.updated_at,
        ),
        fetch_attempts=[
            FetchAttempt(
                id=snapshot.id,
                fetch_outcome=snapshot.fetch_outcome,
                retry_classification=snapshot.retry_classification,
                robots_decision=snapshot.robots_decision,
                status_code=snapshot.status_code,
                content_type=snapshot.content_type,
                body_size_bytes=snapshot.body_size_bytes,
                duration_ms=snapshot.duration_ms,
                failure_detail=snapshot.failure_detail,
                fetched_at=snapshot.fetched_at,
            )
            for snapshot in snapshots
        ],
        total_fetch_attempts=total_snapshots,
        fetch_attempts_truncated=total_snapshots > len(snapshots),
        normalization_attempts=[
            NormalizationAttempt(
                id=document.id,
                fetch_snapshot_id=document.fetch_snapshot_id,
                normalization_status=document.normalization_status,
                extractor_name=document.extractor_name,
                extractor_version=document.extractor_version,
                parser_version=document.parser_version,
                failure_code=document.failure_code,
                failure_detail=document.failure_detail,
                title=document.title,
                author_name=document.author_name,
                external_published_at=document.external_published_at,
                normalized_at=document.normalized_at,
            )
            for document in documents
        ],
        total_normalization_attempts=total_documents,
        normalization_attempts_truncated=total_documents > len(documents),
        duplicate_decisions=[
            DuplicateDecisionSummary(
                id=decision.id,
                normalized_document_id=decision.normalized_document_id,
                engine_name=decision.engine_name,
                engine_version=decision.engine_version,
                decision=decision.decision,
                rationale_codes=[str(code) for code in decision.rationale_codes],
                match_count=len(decision.matches),
                evaluated_at=decision.evaluated_at,
            )
            for decision in decisions
        ],
        total_duplicate_decisions=total_decisions,
        duplicate_decisions_truncated=total_decisions > len(decisions),
        evidence=EvidenceSummary(
            total=evidence_total,
            by_verification_status=by_verification_status,
            by_evidence_type=by_evidence_type,
            latest_extracted_at=latest_extracted_at,
        ),
    )
