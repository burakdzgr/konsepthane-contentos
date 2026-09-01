"""Persistence orchestration for opportunity scoring (engine stays pure).

The service loads durable inputs, builds the bounded canonical input
snapshot, runs the deterministic engine, and persists the append-only score
plus its component rows. It flushes; the caller commits. Scoring NEVER
mutates the opportunity's disposition and NEVER transitions the work item —
it only records a durable evaluation.

Idempotency identity: (opportunity_id, engine_name, engine_version,
input_snapshot_hash). The snapshot pins the exact research-input, decision,
source/trust, recency-timestamp, and evidence-set state used, plus the
evaluation DAY — so a same-day identical retry returns the existing score,
while changed inputs/evidence, a later evaluation day (recency legitimately
moved), or a new engine version append a new score. Old scores are never
mutated.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contentos.discovery.models import DiscoveryItem
from contentos.duplicates.models import DuplicateDecision
from contentos.fetching.snapshots import FetchSnapshot
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.enums import ComponentAvailability
from contentos.opportunities.errors import (
    InvalidScoringStateError,
    OpportunityNotFoundError,
    ScoringConflictError,
)
from contentos.opportunities.models import (
    EditorialOpportunity,
    OpportunityScore,
    OpportunityScoreComponent,
)
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.scoring import (
    DERIVED_PROVIDER,
    INPUT_SNAPSHOT_SCHEMA_VERSION,
    OPPORTUNITY_ENGINE_NAME,
    OPPORTUNITY_ENGINE_VERSION,
    OpportunityScoringEngine,
    ScoringInputDocument,
    ScoringInputs,
    compute_snapshot_hash,
    evidence_snapshot,
)
from contentos.research.models import ResearchEvidence
from contentos.sources.models import Source


@dataclass(frozen=True, slots=True)
class ScoreEvaluation:
    """The durable score of one evaluation; `created` is False on idempotent retry."""

    score: OpportunityScore
    created: bool


class OpportunityScoringService:
    def __init__(self, session: Session, engine: OpportunityScoringEngine | None = None) -> None:
        self._session = session
        self._repository = OpportunityRepository(session)
        self._engine = engine if engine is not None else OpportunityScoringEngine()

    def evaluate_opportunity(
        self, opportunity_id: uuid.UUID, *, evaluated_at: datetime | None = None
    ) -> ScoreEvaluation:
        evaluation_time = evaluated_at if evaluated_at is not None else datetime.now(UTC)

        opportunity = self._repository.get_by_id(opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(f"no opportunity with id {opportunity_id}")

        inputs, snapshot = self._load_inputs(opportunity, evaluation_time)
        snapshot_hash = compute_snapshot_hash(snapshot)

        existing = self._repository.get_score_by_identity(
            opportunity.id,
            OPPORTUNITY_ENGINE_NAME,
            OPPORTUNITY_ENGINE_VERSION,
            snapshot_hash,
        )
        if existing is not None:
            return ScoreEvaluation(score=existing, created=False)

        result = self._engine.evaluate(inputs)
        try:
            with self._session.begin_nested():
                score = self._repository.insert_score(
                    OpportunityScore(
                        opportunity_id=opportunity.id,
                        engine_name=OPPORTUNITY_ENGINE_NAME,
                        engine_version=OPPORTUNITY_ENGINE_VERSION,
                        overall_band=result.overall_band,
                        overall_value=result.overall_value,
                        eligibility=result.eligibility,
                        weights_snapshot=result.weights_snapshot,
                        threshold_snapshot=result.threshold_snapshot,
                        missing_signals=list(result.missing_signals),
                        risk_flags=list(result.risk_flags),
                        input_snapshot=snapshot,
                        input_snapshot_hash=snapshot_hash,
                        evaluated_at=evaluation_time,
                    )
                )
                for evaluation in result.components:
                    is_known = evaluation.availability is ComponentAvailability.KNOWN
                    self._repository.insert_score_component(
                        OpportunityScoreComponent(
                            score_id=score.id,
                            component=evaluation.component,
                            availability=evaluation.availability,
                            value=evaluation.value,
                            confidence=None,
                            provider=DERIVED_PROVIDER if is_known else None,
                            observed_at=evaluation_time if is_known else None,
                            provenance_ref=evaluation.provenance,
                        )
                    )
        except IntegrityError:
            winner = self._repository.get_score_by_identity(
                opportunity.id,
                OPPORTUNITY_ENGINE_NAME,
                OPPORTUNITY_ENGINE_VERSION,
                snapshot_hash,
            )
            if winner is not None:
                return ScoreEvaluation(score=winner, created=False)
            raise ScoringConflictError(
                "scoring conflicted with concurrently written state"
            ) from None
        return ScoreEvaluation(score=score, created=True)

    def _load_inputs(
        self, opportunity: EditorialOpportunity, evaluation_time: datetime
    ) -> tuple[ScoringInputs, dict[str, Any]]:
        research_inputs = self._repository.list_research_inputs(opportunity.id)
        if not research_inputs:
            raise InvalidScoringStateError("the opportunity has no research inputs to evaluate")

        documents: list[ScoringInputDocument] = []
        snapshot_inputs: list[dict[str, Any]] = []
        document_ids: list[uuid.UUID] = []
        source_by_document: dict[uuid.UUID, uuid.UUID] = {}
        for research_input in research_inputs:
            document = self._session.get(NormalizedDocument, research_input.normalized_document_id)
            decision = self._session.get(DuplicateDecision, research_input.duplicate_decision_id)
            snapshot_row = (
                self._session.get(FetchSnapshot, document.fetch_snapshot_id)
                if document is not None
                else None
            )
            item = (
                self._session.get(DiscoveryItem, snapshot_row.discovery_item_id)
                if snapshot_row is not None
                else None
            )
            source = self._session.get(Source, item.source_id) if item is not None else None
            if document is None or decision is None or snapshot_row is None or source is None:
                raise InvalidScoringStateError(
                    "a research input's provenance chain is not resolvable"
                )
            documents.append(
                ScoringInputDocument(
                    normalized_document_id=document.id,
                    source_id=source.id,
                    trust_tier=source.trust_tier.value,
                    duplicate_decision_id=decision.id,
                    duplicate_outcome=decision.decision.value,
                    external_published_at=document.external_published_at,
                    fetched_at=snapshot_row.fetched_at,
                )
            )
            document_ids.append(document.id)
            source_by_document[document.id] = source.id
            snapshot_inputs.append(
                {
                    "research_input_id": str(research_input.id),
                    "normalized_document_id": str(document.id),
                    "duplicate_decision_id": str(decision.id),
                    "duplicate_outcome": decision.decision.value,
                    "role": research_input.role.value,
                    "source_id": str(source.id),
                    "trust_tier": source.trust_tier.value,
                    "external_published_at": (
                        document.external_published_at.isoformat()
                        if document.external_published_at is not None
                        else None
                    ),
                    "fetched_at": snapshot_row.fetched_at.isoformat(),
                }
            )
        snapshot_inputs.sort(key=lambda entry: entry["normalized_document_id"])

        evidence_rows = self._session.execute(
            select(ResearchEvidence.id, ResearchEvidence.normalized_document_id).where(
                ResearchEvidence.normalized_document_id.in_(document_ids)
            )
        ).all()
        evidence_ids = [row[0] for row in evidence_rows]
        documents_with_evidence = {row[1] for row in evidence_rows}
        sources_with_evidence = {
            source_by_document[document_id] for document_id in documents_with_evidence
        }

        inputs = ScoringInputs(
            documents=tuple(documents),
            evidence_count=len(evidence_ids),
            documents_with_evidence=len(documents_with_evidence),
            sources_with_evidence=len(sources_with_evidence),
            evaluated_at=evaluation_time,
        )
        snapshot: dict[str, Any] = {
            "snapshot_schema": INPUT_SNAPSHOT_SCHEMA_VERSION,
            "engine": OPPORTUNITY_ENGINE_NAME,
            "engine_version": OPPORTUNITY_ENGINE_VERSION,
            "opportunity_id": str(opportunity.id),
            "work_item_id": str(opportunity.work_item_id),
            # Day granularity: recency is time-relative, so a later-day
            # re-evaluation with identical inputs is a legitimately new score.
            "evaluated_on": evaluation_time.date().isoformat(),
            "research_inputs": snapshot_inputs,
            "evidence": evidence_snapshot(evidence_ids),
        }
        return inputs, snapshot
