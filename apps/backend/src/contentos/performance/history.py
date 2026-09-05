"""Historical performance as a PRIORITY signal (never a filter).

`HistoricalPerformanceService.aggregate` folds the latest 90-day
assessments of every published content into `IntelligenceSignal` rows of
family ``historical_performance`` keyed by strategy context (cluster,
audience, theme, format) at several grains. `historical_signal_for` is the
read contract other engines call to ORDER candidates — a negative history
lowers priority, it never eliminates an idea, and an absent history is
honestly ``unknown``.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.intelligence.enums import SignalFamily
from contentos.intelligence.models import IntelligenceSignal
from contentos.performance.enums import AssessmentStatus, HistoricalBand, HistoricalOutcome
from contentos.performance.models import PerformanceAssessment, PublishedContent
from contentos.performance.service import PerformanceService
from contentos.strategy.models import AudienceStrategy, TopicCluster
from contentos.strategy.service import normalize_phrase

HISTORICAL_PROVIDER = "contentos-performance"
HISTORICAL_WINDOW_DAYS = 90
MAX_THEME_KEY_IN_CONCEPT = 80
REAL_STATUSES = frozenset(
    {
        AssessmentStatus.RISING,
        AssessmentStatus.STABLE,
        AssessmentStatus.DECLINING,
        AssessmentStatus.VOLATILE,
    }
)


@dataclass(frozen=True, slots=True)
class HistoricalSignal:
    band: HistoricalBand
    outcome: HistoricalOutcome | None
    basis: dict[str, Any]

    def projection(self) -> dict[str, Any]:
        return {
            "band": self.band.value,
            "outcome": self.outcome.value if self.outcome is not None else None,
            "basis": dict(self.basis),
            "priority_only": True,
        }


def historical_concept_key(
    *,
    cluster_id: uuid.UUID | None,
    audience_id: uuid.UUID | None,
    theme_key: str | None,
    content_format: str | None,
) -> str:
    theme = normalize_phrase(theme_key)[:MAX_THEME_KEY_IN_CONCEPT] if theme_key else ""
    return "|".join(
        (
            f"cluster:{cluster_id or '-'}",
            f"audience:{audience_id or '-'}",
            f"theme:{theme or '-'}",
            f"format:{content_format or '-'}",
        )
    )


def _observation_hash(concept_key: str) -> str:
    material = f"{SignalFamily.HISTORICAL_PERFORMANCE.value}|{concept_key}|{HISTORICAL_PROVIDER}||"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class _Group:
    grain: str
    keys: dict[str, str | None]
    subject: str
    publications: list[str]
    assessments: list[str]
    statuses: list[AssessmentStatus]
    impressions: int
    clicks: int
    impression_deltas: list[float]


class HistoricalPerformanceService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._performance = PerformanceService(session)

    def aggregate(self, *, now: datetime | None = None) -> list[IntelligenceSignal]:
        """Write/update one signal per (grain, key) that has real metrics."""
        moment = now if now is not None else datetime.now(UTC)
        latest = self._performance.latest_assessments_for_all(HISTORICAL_WINDOW_DAYS)
        clusters = {row.id: row.name for row in self._session.scalars(select(TopicCluster))}
        audiences = {row.id: row.name for row in self._session.scalars(select(AudienceStrategy))}
        groups: dict[str, _Group] = {}
        for content in self._performance.list_published():
            assessment = latest.get(content.id)
            if assessment is None:
                continue
            for grain, concept_key, keys, subject in _grains(content, clusters, audiences):
                group = groups.get(concept_key)
                if group is None:
                    group = _Group(grain, keys, subject, [], [], [], 0, 0, [])
                    groups[concept_key] = group
                _fold(group, content, assessment)
        written: list[IntelligenceSignal] = []
        for concept_key, group in groups.items():
            real = [status for status in group.statuses if status in REAL_STATUSES]
            if not real:
                continue  # nothing real to learn from: no signal, not a zero
            written.append(self._upsert(concept_key, group, real, moment))
        self._session.flush()
        return written

    def signal_for_key(self, concept_key: str) -> IntelligenceSignal | None:
        return self._session.scalar(
            select(IntelligenceSignal).where(
                IntelligenceSignal.observation_hash == _observation_hash(concept_key)
            )
        )

    def _upsert(
        self, concept_key: str, group: _Group, real: list[AssessmentStatus], moment: datetime
    ) -> IntelligenceSignal:
        rising = sum(1 for status in real if status is AssessmentStatus.RISING)
        declining = sum(1 for status in real if status is AssessmentStatus.DECLINING)
        if rising > declining:
            outcome = HistoricalOutcome.POSITIVE
        elif declining > rising:
            outcome = HistoricalOutcome.NEGATIVE
        else:
            outcome = HistoricalOutcome.NEUTRAL
        value: dict[str, Any] = {
            "outcome": outcome.value,
            "publications": group.publications,
            "assessments": group.assessments,
            "metric_basis": {
                "rising": rising,
                "declining": declining,
                "stable": sum(1 for status in real if status is AssessmentStatus.STABLE),
                "volatile": sum(1 for status in real if status is AssessmentStatus.VOLATILE),
                "impressions": group.impressions,
                "clicks": group.clicks,
                "mean_impressions_pct": (
                    round(sum(group.impression_deltas) / len(group.impression_deltas), 4)
                    if group.impression_deltas
                    else None
                ),
            },
            "window_days": HISTORICAL_WINDOW_DAYS,
            "grain": group.grain,
            "keys": group.keys,
            "publication_count": len(group.publications),
            "real_metric_count": len(real),
            "priority_only": True,
        }
        existing = self.signal_for_key(concept_key)
        if existing is not None:
            existing.value = value
            existing.subject = group.subject
            existing.last_observed_at = moment
            existing.occurrence_count = existing.occurrence_count + 1
            return existing
        row = IntelligenceSignal(
            family=SignalFamily.HISTORICAL_PERFORMANCE,
            subject=group.subject,
            concept_key=concept_key,
            provider=HISTORICAL_PROVIDER,
            value=value,
            occurrence_count=1,
            first_observed_at=moment,
            last_observed_at=moment,
            observation_hash=_observation_hash(concept_key),
        )
        self._session.add(row)
        return row


def historical_signal_for(
    session: Session,
    *,
    cluster_id: uuid.UUID | None,
    audience_id: uuid.UUID | None,
    theme_key: str | None,
    content_format: str | None,
) -> HistoricalSignal:
    """The priority-only read contract: most specific known grain wins."""
    service = HistoricalPerformanceService(session)
    candidates = [
        historical_concept_key(
            cluster_id=cluster_id,
            audience_id=audience_id,
            theme_key=theme_key,
            content_format=content_format,
        )
    ]
    if cluster_id is not None:
        candidates.append(
            historical_concept_key(
                cluster_id=cluster_id, audience_id=None, theme_key=None, content_format=None
            )
        )
    if audience_id is not None:
        candidates.append(
            historical_concept_key(
                cluster_id=None, audience_id=audience_id, theme_key=None, content_format=None
            )
        )
    if theme_key:
        candidates.append(
            historical_concept_key(
                cluster_id=None, audience_id=None, theme_key=theme_key, content_format=None
            )
        )
    for concept_key in dict.fromkeys(candidates):
        signal = service.signal_for_key(concept_key)
        if signal is None:
            continue
        value = signal.value
        real_count = int(value.get("real_metric_count") or 0)
        outcome_raw = value.get("outcome")
        outcome = (
            HistoricalOutcome(outcome_raw)
            if isinstance(outcome_raw, str) and outcome_raw in HistoricalOutcome._value2member_map_
            else None
        )
        return HistoricalSignal(
            band=_band(real_count, outcome),
            outcome=outcome,
            basis={
                "concept_key": concept_key,
                "grain": value.get("grain"),
                "signal_id": str(signal.id),
                "publication_count": value.get("publication_count"),
                "real_metric_count": real_count,
                "metric_basis": value.get("metric_basis", {}),
                "window_days": value.get("window_days", HISTORICAL_WINDOW_DAYS),
                "last_observed_at": signal.last_observed_at.isoformat(),
                "priority_only": True,
            },
        )
    return HistoricalSignal(
        band=HistoricalBand.UNKNOWN,
        outcome=None,
        basis={"reason": "no_history", "priority_only": True},
    )


def _band(real_count: int, outcome: HistoricalOutcome | None) -> HistoricalBand:
    if real_count <= 0 or outcome is None:
        return HistoricalBand.UNKNOWN
    if real_count >= 3 and outcome is not HistoricalOutcome.NEUTRAL:
        return HistoricalBand.STRONG
    if real_count >= 2:
        return HistoricalBand.MODERATE
    return HistoricalBand.WEAK


def _grains(
    content: PublishedContent,
    clusters: dict[uuid.UUID, str],
    audiences: dict[uuid.UUID, str],
) -> list[tuple[str, str, dict[str, str | None], str]]:
    cluster_name = clusters.get(content.topic_cluster_id) if content.topic_cluster_id else None
    audience_name = audiences.get(content.audience_id) if content.audience_id else None
    full_subject = (
        " · ".join(
            part
            for part in (
                cluster_name,
                audience_name,
                content.theme_key,
                content.content_format,
            )
            if part
        )
        or "Strateji bağlamı yok"
    )
    grains: list[tuple[str, str, dict[str, str | None], str]] = [
        (
            "full",
            historical_concept_key(
                cluster_id=content.topic_cluster_id,
                audience_id=content.audience_id,
                theme_key=content.theme_key,
                content_format=content.content_format,
            ),
            {
                "cluster_id": str(content.topic_cluster_id) if content.topic_cluster_id else None,
                "audience_id": str(content.audience_id) if content.audience_id else None,
                "theme_key": content.theme_key,
                "content_format": content.content_format,
            },
            full_subject,
        )
    ]
    if content.topic_cluster_id is not None:
        grains.append(
            (
                "cluster",
                historical_concept_key(
                    cluster_id=content.topic_cluster_id,
                    audience_id=None,
                    theme_key=None,
                    content_format=None,
                ),
                {"cluster_id": str(content.topic_cluster_id)},
                cluster_name or "Küme",
            )
        )
    if content.audience_id is not None:
        grains.append(
            (
                "audience",
                historical_concept_key(
                    cluster_id=None,
                    audience_id=content.audience_id,
                    theme_key=None,
                    content_format=None,
                ),
                {"audience_id": str(content.audience_id)},
                audience_name or "Kitle",
            )
        )
    if content.theme_key:
        grains.append(
            (
                "theme",
                historical_concept_key(
                    cluster_id=None,
                    audience_id=None,
                    theme_key=content.theme_key,
                    content_format=None,
                ),
                {"theme_key": content.theme_key},
                content.theme_key,
            )
        )
    return grains


def _fold(group: _Group, content: PublishedContent, assessment: PerformanceAssessment) -> None:
    group.publications.append(str(content.id))
    group.assessments.append(str(assessment.id))
    group.statuses.append(assessment.status)
    current = assessment.basis.get("current")
    if isinstance(current, dict):
        impressions = current.get("impressions")
        clicks = current.get("clicks")
        if isinstance(impressions, int):
            group.impressions += impressions
        if isinstance(clicks, int):
            group.clicks += clicks
    deltas = assessment.basis.get("deltas")
    if isinstance(deltas, dict):
        pct = deltas.get("impressions_pct")
        if isinstance(pct, int | float) and not isinstance(pct, bool):
            group.impression_deltas.append(float(pct))
