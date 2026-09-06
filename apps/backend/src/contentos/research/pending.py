"""Which admitted research documents are still owed a model-assisted
evidence attempt. Exactly ONE automatic attempt per document: a document
with model evidence rows, or with any recorded evidence-extraction attempt
(succeeded with nothing usable, failed, timed out), is never pending again
— the operator can re-trigger explicitly. Bounded, deterministic order."""

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.ai.enums import GenerationPurpose
from contentos.ai.models import AiGenerationAttempt
from contentos.discovery.models import DiscoveryItem
from contentos.fetching.snapshots import FetchSnapshot
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.repository import OpportunityRepository
from contentos.research.model_extractor import MODEL_EXTRACTOR_NAME
from contentos.research.models import ResearchEvidence
from contentos.sources.enums import role_yields_opportunities
from contentos.sources.models import Source

MAX_PENDING_DOCUMENTS = 6


def documents_pending_model_evidence(
    session: Session,
    opportunity_id: uuid.UUID,
    eligible_rows: Iterable[ResearchEvidence] | None = None,
) -> tuple[uuid.UUID, ...]:
    inputs = OpportunityRepository(session).list_research_inputs(opportunity_id)
    document_ids = [row.normalized_document_id for row in inputs]
    if not document_ids:
        return ()
    rows = (
        list(eligible_rows)
        if eligible_rows is not None
        else list(
            session.scalars(
                select(ResearchEvidence).where(
                    ResearchEvidence.normalized_document_id.in_(document_ids)
                )
            )
        )
    )
    with_model_rows = {
        row.normalized_document_id for row in rows if row.extractor_name == MODEL_EXTRACTOR_NAME
    }
    attempted = attempted_document_ids(session, document_ids)
    pending: list[uuid.UUID] = []
    for document_id in document_ids:
        if document_id in with_model_rows or document_id in attempted:
            continue
        source = session.execute(
            select(Source)
            .join(DiscoveryItem, DiscoveryItem.source_id == Source.id)
            .join(FetchSnapshot, FetchSnapshot.discovery_item_id == DiscoveryItem.id)
            .join(NormalizedDocument, NormalizedDocument.fetch_snapshot_id == FetchSnapshot.id)
            .where(NormalizedDocument.id == document_id)
        ).scalar_one_or_none()
        if source is None or not role_yields_opportunities(source.primary_role):
            continue
        if document_id not in pending:
            pending.append(document_id)
        if len(pending) >= MAX_PENDING_DOCUMENTS:
            break
    return tuple(pending)


def attempted_document_ids(session: Session, document_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Documents with ANY persisted evidence-extraction attempt (JSON lookup
    on the attempt's durable input refs; works on PostgreSQL and SQLite)."""
    wanted = {str(document_id) for document_id in document_ids}
    found: set[uuid.UUID] = set()
    rows = session.execute(
        select(AiGenerationAttempt.input_refs).where(
            AiGenerationAttempt.purpose == GenerationPurpose.EVIDENCE_EXTRACTION
        )
    ).all()
    for (refs,) in rows:
        value = refs.get("normalized_document_id") if isinstance(refs, dict) else None
        if isinstance(value, str) and value in wanted:
            found.add(uuid.UUID(value))
    return found
