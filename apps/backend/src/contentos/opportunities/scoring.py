"""Deterministic opportunity scoring engine v1 (pure calculation, no session).

Engine identity: ``opportunity-engine`` / ``1``. Every policy constant below
is frozen engine-v1 operational policy — initial, explainable, and never
presented as statistically validated truth. Changing any of them requires an
engine version bump; every persisted score carries the exact weights and
thresholds it used.

Value scale (frozen for v1): every component value and the overall value are
normalized contributions in 0..1 where HIGHER IS BETTER for the opportunity
(``duplicate_overlap_risk`` is therefore persisted as inverted risk: 1.0
means no known overlap risk). UNKNOWN components carry NULL values and are
excluded from both numerator and denominator — UNKNOWN is never zero.

v1 computes only signals with a durable deterministic source today: recency,
source diversity, source trust, duplicate overlap risk, and evidence
availability. Search demand, competition, audience fit, editorial value,
seasonality, policy risk, and production cost have no authoritative source
yet and are always persisted as explicit UNKNOWN rows. Risk flags stay empty
in v1: no governed deterministic risk classifier exists, and none is
invented.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from contentos.opportunities.enums import (
    ComponentAvailability,
    ScoreBand,
    ScoreComponent,
    ScoreEligibility,
)

OPPORTUNITY_ENGINE_NAME = "opportunity-engine"
OPPORTUNITY_ENGINE_VERSION = "1"

INPUT_SNAPSHOT_SCHEMA_VERSION = 1
# Bounded snapshot policy: above this, the evidence set is pinned by a
# deterministic set hash + count instead of the full ID list.
MAX_SNAPSHOT_EVIDENCE_IDS = 200

DERIVED_PROVIDER = "derived_phase2"

# --- Frozen v1 policy constants (all persisted in score snapshots) ---------

V1_WEIGHTS: dict[ScoreComponent, float] = {
    ScoreComponent.RECENCY: 0.15,
    ScoreComponent.EVIDENCE_AVAILABILITY: 0.20,
    ScoreComponent.SOURCE_DIVERSITY: 0.15,
    ScoreComponent.SOURCE_TRUST: 0.15,
    ScoreComponent.DUPLICATE_OVERLAP_RISK: 0.10,
    ScoreComponent.SEARCH_DEMAND: 0.10,
    ScoreComponent.COMPETITION: 0.05,
    ScoreComponent.AUDIENCE_FIT: 0.05,
    ScoreComponent.EDITORIAL_VALUE: 0.03,
    ScoreComponent.SEASONALITY: 0.01,
    ScoreComponent.POLICY_RISK: 0.01,
    ScoreComponent.PRODUCTION_COST_ESTIMATE: 0.00,
}

# (max_age_days, value); evaluated top-down, first match wins.
V1_RECENCY_BUCKETS: tuple[tuple[int, float], ...] = (
    (7, 1.0),
    (30, 0.8),
    (90, 0.6),
    (365, 0.4),
)
V1_RECENCY_FLOOR = 0.2  # older than the last bucket

# distinct-source count -> diversity value; counts above the table max at 1.0.
V1_DIVERSITY_VALUES: dict[int, float] = {1: 0.3, 2: 0.6, 3: 0.8}
V1_DIVERSITY_CEILING = 1.0  # 4+ distinct sources

# Existing Source trust tiers -> normalized values; aggregation is the
# arithmetic MEAN over distinct sources (deliberate: never silently only the
# best source).
V1_TRUST_VALUES: dict[str, float] = {
    "official": 1.0,
    "expert": 0.9,
    "reputable": 0.75,
    "general": 0.5,
    "reference_only": 0.25,
}

# Duplicate outcome -> inverted-risk contribution; aggregation is the MIN
# across pinned decisions (the riskiest input governs). ADR 0008 semantics
# preserved; an operator-overridden DUPLICATE stays visibly high-risk.
V1_DUPLICATE_CONTRIBUTION: dict[str, float] = {
    "unique": 1.0,
    "related": 0.7,
    "update_existing": 0.5,
    "duplicate": 0.2,
    "reject": 0.0,
}

# evidence-count buckets: (min_count_inclusive, value); zero evidence is a
# KNOWN fact with value 0.0 — never UNKNOWN.
V1_EVIDENCE_BUCKETS: tuple[tuple[int, float], ...] = (
    (6, 1.0),
    (3, 0.7),
    (1, 0.4),
    (0, 0.0),
)

V1_BAND_THRESHOLDS: dict[str, float] = {"strong": 0.75, "moderate": 0.55}

# Known-signal coverage rule: renormalization must not let one lonely signal
# fabricate an excellent score.
V1_MIN_KNOWN_CORE_COMPONENTS = 3
V1_MIN_KNOWN_WEIGHT_FRACTION = 0.5
CORE_COMPONENTS = frozenset(
    {
        ScoreComponent.RECENCY,
        ScoreComponent.EVIDENCE_AVAILABILITY,
        ScoreComponent.SOURCE_DIVERSITY,
        ScoreComponent.SOURCE_TRUST,
        ScoreComponent.DUPLICATE_OVERLAP_RISK,
    }
)

# v1 defines no deterministic hard scoring condition beyond the intake gates,
# so the INELIGIBLE band is reserved vocabulary and never emitted by v1.


@dataclass(frozen=True, slots=True)
class ScoringInputDocument:
    """One research input's durable identity slice used by the engine."""

    normalized_document_id: uuid.UUID
    source_id: uuid.UUID
    trust_tier: str
    duplicate_decision_id: uuid.UUID
    duplicate_outcome: str
    external_published_at: datetime | None
    fetched_at: datetime | None


@dataclass(frozen=True, slots=True)
class ScoringInputs:
    """Pure engine inputs; building them from durable rows is the service's job."""

    documents: tuple[ScoringInputDocument, ...]
    evidence_count: int
    documents_with_evidence: int
    sources_with_evidence: int
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class ComponentEvaluation:
    component: ScoreComponent
    availability: ComponentAvailability
    value: float | None
    provenance: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ScoringResult:
    overall_band: ScoreBand
    overall_value: float | None
    eligibility: ScoreEligibility
    components: tuple[ComponentEvaluation, ...]
    missing_signals: tuple[str, ...]
    risk_flags: tuple[str, ...]
    weights_snapshot: dict[str, Any]
    threshold_snapshot: dict[str, Any]


def weights_snapshot() -> dict[str, Any]:
    return {
        "engine": OPPORTUNITY_ENGINE_NAME,
        "engine_version": OPPORTUNITY_ENGINE_VERSION,
        "weights": {component.value: weight for component, weight in V1_WEIGHTS.items()},
        "value_scale": "0..1 contribution; higher is better",
        "aggregations": {
            "recency": "most recent basis timestamp across inputs",
            "source_trust": "arithmetic mean over distinct sources",
            "duplicate_overlap_risk": "min inverted-risk contribution across pinned decisions",
        },
        "note": "initial engine-v1 operational policy; not statistically validated",
    }


def threshold_snapshot() -> dict[str, Any]:
    return {
        "engine": OPPORTUNITY_ENGINE_NAME,
        "engine_version": OPPORTUNITY_ENGINE_VERSION,
        "bands": dict(V1_BAND_THRESHOLDS),
        "eligibility": {
            "strong": ScoreEligibility.COMMISSIONABLE.value,
            "moderate": ScoreEligibility.NEEDS_OPERATOR_REVIEW.value,
            "weak": ScoreEligibility.NOT_COMMISSIONABLE.value,
        },
        "coverage_rule": {
            "min_known_core_components": V1_MIN_KNOWN_CORE_COMPONENTS,
            "min_known_weight_fraction": V1_MIN_KNOWN_WEIGHT_FRACTION,
            "on_failure": ScoreEligibility.NEEDS_OPERATOR_REVIEW.value,
        },
        "recency_buckets_days": [list(bucket) for bucket in V1_RECENCY_BUCKETS],
        "recency_floor": V1_RECENCY_FLOOR,
        "diversity_values": {str(k): v for k, v in V1_DIVERSITY_VALUES.items()},
        "diversity_ceiling": V1_DIVERSITY_CEILING,
        "trust_values": dict(V1_TRUST_VALUES),
        "duplicate_contribution": dict(V1_DUPLICATE_CONTRIBUTION),
        "evidence_buckets": [list(bucket) for bucket in V1_EVIDENCE_BUCKETS],
        "ineligible_band": "reserved; v1 defines no hard scoring condition",
        "note": "initial engine-v1 operational policy; not statistically validated",
    }


class OpportunityScoringEngine:
    """Pure deterministic evaluation; no I/O, no session, no randomness."""

    name = OPPORTUNITY_ENGINE_NAME
    version = OPPORTUNITY_ENGINE_VERSION

    def evaluate(self, inputs: ScoringInputs) -> ScoringResult:
        evaluations = [
            self._recency(inputs),
            self._source_diversity(inputs),
            self._source_trust(inputs),
            self._duplicate_overlap(inputs),
            self._evidence_availability(inputs),
        ]
        computed = {evaluation.component for evaluation in evaluations}
        for component in ScoreComponent:
            if component not in computed:
                evaluations.append(
                    ComponentEvaluation(
                        component=component,
                        availability=ComponentAvailability.UNKNOWN,
                        value=None,
                        provenance={"reason": "no durable deterministic signal source exists"},
                    )
                )
        evaluations.sort(key=lambda evaluation: evaluation.component.value)

        known = [
            evaluation
            for evaluation in evaluations
            if evaluation.availability is ComponentAvailability.KNOWN
        ]
        known_weight = sum(V1_WEIGHTS[evaluation.component] for evaluation in known)
        overall_value: float | None = None
        if known and known_weight > 0:
            weighted = sum(
                (evaluation.value or 0.0) * V1_WEIGHTS[evaluation.component] for evaluation in known
            )
            overall_value = round(weighted / known_weight, 4)

        band = self._band(overall_value)
        known_core = sum(1 for evaluation in known if evaluation.component in CORE_COMPONENTS)
        coverage_ok = (
            known_core >= V1_MIN_KNOWN_CORE_COMPONENTS
            and known_weight >= V1_MIN_KNOWN_WEIGHT_FRACTION
        )
        if not coverage_ok or overall_value is None:
            eligibility = ScoreEligibility.NEEDS_OPERATOR_REVIEW
        elif band is ScoreBand.STRONG:
            eligibility = ScoreEligibility.COMMISSIONABLE
        elif band is ScoreBand.MODERATE:
            eligibility = ScoreEligibility.NEEDS_OPERATOR_REVIEW
        else:
            eligibility = ScoreEligibility.NOT_COMMISSIONABLE

        missing = tuple(
            evaluation.component.value
            for evaluation in evaluations
            if evaluation.availability is ComponentAvailability.UNKNOWN
        )
        return ScoringResult(
            overall_band=band,
            overall_value=overall_value,
            eligibility=eligibility,
            components=tuple(evaluations),
            missing_signals=missing,
            risk_flags=(),
            weights_snapshot=weights_snapshot(),
            threshold_snapshot=threshold_snapshot(),
        )

    @staticmethod
    def _band(overall_value: float | None) -> ScoreBand:
        if overall_value is None:
            return ScoreBand.WEAK
        if overall_value >= V1_BAND_THRESHOLDS["strong"]:
            return ScoreBand.STRONG
        if overall_value >= V1_BAND_THRESHOLDS["moderate"]:
            return ScoreBand.MODERATE
        return ScoreBand.WEAK

    @staticmethod
    def _recency(inputs: ScoringInputs) -> ComponentEvaluation:
        best: tuple[datetime, str, uuid.UUID] | None = None
        for document in inputs.documents:
            timestamp = document.external_published_at
            basis = "external_published_at"
            if timestamp is None:
                timestamp = document.fetched_at
                basis = "fetched_at"
            if timestamp is None:
                continue
            if best is None or timestamp > best[0]:
                best = (timestamp, basis, document.normalized_document_id)
        if best is None:
            # An unknown publication/capture date is UNKNOWN, never "old".
            return ComponentEvaluation(
                component=ScoreComponent.RECENCY,
                availability=ComponentAvailability.UNKNOWN,
                value=None,
                provenance={"reason": "no authoritative timestamp on any input"},
            )
        age_days = max((inputs.evaluated_at - best[0]).days, 0)
        value = V1_RECENCY_FLOOR
        for max_days, bucket_value in V1_RECENCY_BUCKETS:
            if age_days <= max_days:
                value = bucket_value
                break
        return ComponentEvaluation(
            component=ScoreComponent.RECENCY,
            availability=ComponentAvailability.KNOWN,
            value=value,
            provenance={
                "basis": best[1],
                "timestamp": best[0].isoformat(),
                "normalized_document_id": str(best[2]),
                "age_days": age_days,
            },
        )

    @staticmethod
    def _source_diversity(inputs: ScoringInputs) -> ComponentEvaluation:
        source_ids = sorted({str(document.source_id) for document in inputs.documents})
        if not source_ids:
            return ComponentEvaluation(
                component=ScoreComponent.SOURCE_DIVERSITY,
                availability=ComponentAvailability.UNKNOWN,
                value=None,
                provenance={"reason": "no research inputs"},
            )
        count = len(source_ids)
        value = V1_DIVERSITY_VALUES.get(count, V1_DIVERSITY_CEILING)
        return ComponentEvaluation(
            component=ScoreComponent.SOURCE_DIVERSITY,
            availability=ComponentAvailability.KNOWN,
            value=value,
            provenance={"distinct_sources": count, "source_ids": source_ids},
        )

    @staticmethod
    def _source_trust(inputs: ScoringInputs) -> ComponentEvaluation:
        tiers_by_source: dict[str, str] = {}
        for document in inputs.documents:
            tiers_by_source[str(document.source_id)] = document.trust_tier
        if not tiers_by_source:
            return ComponentEvaluation(
                component=ScoreComponent.SOURCE_TRUST,
                availability=ComponentAvailability.UNKNOWN,
                value=None,
                provenance={"reason": "no research inputs"},
            )
        values = [V1_TRUST_VALUES[tier] for tier in tiers_by_source.values()]
        value = round(sum(values) / len(values), 4)
        return ComponentEvaluation(
            component=ScoreComponent.SOURCE_TRUST,
            availability=ComponentAvailability.KNOWN,
            value=value,
            provenance={
                "tiers": dict(sorted(tiers_by_source.items())),
                "aggregation": "mean over distinct sources",
            },
        )

    @staticmethod
    def _duplicate_overlap(inputs: ScoringInputs) -> ComponentEvaluation:
        decisions = [
            {
                "duplicate_decision_id": str(document.duplicate_decision_id),
                "outcome": document.duplicate_outcome,
            }
            for document in sorted(inputs.documents, key=lambda d: str(d.duplicate_decision_id))
        ]
        if not decisions:
            return ComponentEvaluation(
                component=ScoreComponent.DUPLICATE_OVERLAP_RISK,
                availability=ComponentAvailability.UNKNOWN,
                value=None,
                provenance={"reason": "no research inputs"},
            )
        value = min(V1_DUPLICATE_CONTRIBUTION[decision["outcome"]] for decision in decisions)
        return ComponentEvaluation(
            component=ScoreComponent.DUPLICATE_OVERLAP_RISK,
            availability=ComponentAvailability.KNOWN,
            value=value,
            provenance={
                "decisions": decisions,
                "aggregation": "min inverted-risk contribution",
                "value_orientation": "1.0 means no known overlap risk",
            },
        )

    @staticmethod
    def _evidence_availability(inputs: ScoringInputs) -> ComponentEvaluation:
        # Zero evidence is a KNOWN fact (value 0.0), never UNKNOWN. This is a
        # raw availability signal, NOT the future EvidencePack sufficiency gate.
        value = 0.0
        for minimum, bucket_value in V1_EVIDENCE_BUCKETS:
            if inputs.evidence_count >= minimum:
                value = bucket_value
                break
        return ComponentEvaluation(
            component=ScoreComponent.EVIDENCE_AVAILABILITY,
            availability=ComponentAvailability.KNOWN,
            value=value,
            provenance={
                "evidence_count": inputs.evidence_count,
                "documents_with_evidence": inputs.documents_with_evidence,
                "sources_with_evidence": inputs.sources_with_evidence,
            },
        )


def compute_snapshot_hash(snapshot: dict[str, Any]) -> str:
    """SHA-256 over a stable canonical JSON serialization (never Python repr)."""
    canonical = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evidence_snapshot(evidence_ids: list[uuid.UUID]) -> dict[str, Any]:
    """Bounded, order-independent evidence-set identity for the input snapshot."""
    ordered = sorted(str(evidence_id) for evidence_id in evidence_ids)
    if len(ordered) <= MAX_SNAPSHOT_EVIDENCE_IDS:
        return {"count": len(ordered), "ids": ordered}
    set_hash = hashlib.sha256("\n".join(ordered).encode("utf-8")).hexdigest()
    return {
        "count": len(ordered),
        "set_hash": set_hash,
        "basis": "research_evidence rows for the opportunity's input documents",
    }
