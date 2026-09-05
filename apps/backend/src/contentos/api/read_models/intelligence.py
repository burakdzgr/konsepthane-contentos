"""Read-only projections of the intelligence signal store.

Bounded, Turkish-neutral JSON: enum values are internal English contracts,
signal subjects are the stored PII-free patterns, and counts are counts of
durable rows (a family with no rows simply has none — no strength is
inferred from that).
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from contentos.intelligence.enums import SignalFamily
from contentos.intelligence.models import IntelligenceSignal
from contentos.intelligence.repository import IntelligenceSignalRepository
from contentos.intelligence.service import IntelligenceSignalService

DEFAULT_SIGNAL_LIMIT = 50
MAX_SIGNAL_LIMIT = 200


class IntelligenceSignalView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: uuid.UUID
    family: SignalFamily
    subject: str
    concept_key: str
    locale: str
    market: str
    source_id: uuid.UUID | None
    normalized_document_id: uuid.UUID | None
    opportunity_id: uuid.UUID | None
    provider: str
    value: dict[str, Any]
    occurrence_count: int
    first_observed_at: datetime
    last_observed_at: datetime


class SignalListPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[IntelligenceSignalView]
    limit: int
    bounded: bool = True
    family: SignalFamily | None = None
    opportunity_id: uuid.UUID | None = None


class FamilySummaryView(BaseModel):
    model_config = ConfigDict(frozen=True)

    family: SignalFamily
    signal_count: int
    occurrence_total: int
    distinct_sources: int
    last_observed_at: datetime | None


class IntelligenceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    families: list[FamilySummaryView]
    total_signals: int
    # Present when the summary was bounded to one intake run's documents.
    run_id: uuid.UUID | None = None
    run_document_count: int | None = None


class IntakeRunNotFoundError(LookupError):
    """The ``run_id`` bound names no intake run."""


def list_signals(
    session: Session,
    *,
    family: SignalFamily | None,
    limit: int,
    opportunity_id: uuid.UUID | None,
) -> SignalListPage:
    rows: list[IntelligenceSignal]
    if opportunity_id is not None:
        rows = IntelligenceSignalService(session).signals_for_opportunity(opportunity_id)
        if family is not None:
            rows = [row for row in rows if row.family is family]
        rows = rows[:limit]
    else:
        rows = IntelligenceSignalRepository(session).list_signals(family=family, limit=limit)
    return SignalListPage(
        items=[IntelligenceSignalView.model_validate(row) for row in rows],
        limit=limit,
        family=family,
        opportunity_id=opportunity_id,
    )


def summarize(session: Session, *, run_id: uuid.UUID | None = None) -> IntelligenceSummary:
    document_ids: list[uuid.UUID] | None = None
    if run_id is not None:
        from contentos.api.read_models.intake import run_document_ids

        document_ids = run_document_ids(session, run_id)
        if document_ids is None:
            raise IntakeRunNotFoundError(f"no intake run with id {run_id}")
    tallies = {
        tally.family: tally
        for tally in IntelligenceSignalRepository(session).tally_by_family(
            document_ids=document_ids
        )
    }
    families = [
        FamilySummaryView(
            family=family,
            signal_count=tallies[family].signal_count if family in tallies else 0,
            occurrence_total=tallies[family].occurrence_total if family in tallies else 0,
            distinct_sources=tallies[family].distinct_sources if family in tallies else 0,
            last_observed_at=tallies[family].last_observed_at if family in tallies else None,
        )
        for family in SignalFamily
    ]
    return IntelligenceSummary(
        families=families,
        total_signals=sum(view.signal_count for view in families),
        run_id=run_id,
        run_document_count=None if document_ids is None else len(document_ids),
    )
