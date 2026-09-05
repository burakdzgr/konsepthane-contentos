"""Bounded strategy suggestions learned from 90-day outcomes.

A suggestion exists ONLY when at least `MIN_PUBLICATIONS` publications in
the same cluster / audience / theme have real metrics (never from
insufficient or unknown data), is deduplicated by (kind, normalized
title), and never changes strategy on its own: `accept` is a named human
decision that applies ONE bounded change through `StrategyService`.
Anti-self-reinforcement: suggestions raise priorities or add a keyword,
they never remove, pause, or filter anything.
"""

import hashlib
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.auth.models import User
from contentos.performance.enums import (
    AssessmentStatus,
    PerformanceProvider,
    SuggestionKind,
    SuggestionStatus,
)
from contentos.performance.models import PerformanceAssessment, PublishedContent, StrategySuggestion
from contentos.performance.service import PerformanceError, PerformanceService, top_queries
from contentos.strategy.enums import StrategyStatus
from contentos.strategy.models import AudienceStrategy, StrategicKeyword, TopicCluster
from contentos.strategy.service import StrategyService, normalize_phrase

MIN_PUBLICATIONS = 3
MAX_SUGGESTIONS_PER_RUN = 10
MAX_KEYWORD_SUGGESTIONS = 5
RISING_SHARE = 0.6
WINDOW_DAYS = 90
PRIORITY_STEP = 10
NEW_KEYWORD_PRIORITY = 60
MAX_REASON_LENGTH = 2000
REAL_STATUSES = frozenset(
    {
        AssessmentStatus.RISING,
        AssessmentStatus.STABLE,
        AssessmentStatus.DECLINING,
        AssessmentStatus.VOLATILE,
    }
)


class SuggestionNotFoundError(PerformanceError):
    """No strategy suggestion with that id."""


class SuggestionStateError(PerformanceError):
    """The suggestion is not open for a decision."""


class SuggestionActorRequiredError(PerformanceError):
    """Suggestion decisions are named human decisions."""


def suggestion_hash(kind: SuggestionKind, title: str) -> str:
    material = f"{kind.value}|{normalize_phrase(title)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class StrategySuggestionService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._performance = PerformanceService(session)

    # --- reads -------------------------------------------------------------

    def list_suggestions(self, status: SuggestionStatus | None = None) -> list[StrategySuggestion]:
        statement = select(StrategySuggestion)
        if status is not None:
            statement = statement.where(StrategySuggestion.status == status)
        statement = statement.order_by(StrategySuggestion.proposed_at.desc(), StrategySuggestion.id)
        return list(self._session.scalars(statement))

    def get(self, suggestion_id: uuid.UUID) -> StrategySuggestion | None:
        return self._session.get(StrategySuggestion, suggestion_id)

    def pending_count(self) -> int:
        return len(self.list_suggestions(SuggestionStatus.PROPOSED))

    # --- generation --------------------------------------------------------

    def generate(self, *, now: datetime | None = None) -> list[StrategySuggestion]:
        moment = now if now is not None else datetime.now(UTC)
        latest = self._performance.latest_assessments_for_all(WINDOW_DAYS)
        contents = self._performance.list_published()
        real: list[tuple[PublishedContent, PerformanceAssessment]] = [
            (content, latest[content.id])
            for content in contents
            if content.id in latest and latest[content.id].status in REAL_STATUSES
        ]
        candidates: list[tuple[SuggestionKind, str, str, dict[str, Any]]] = []
        candidates.extend(self._focus_candidates(real))
        candidates.extend(self._keyword_candidates(real))
        written: list[StrategySuggestion] = []
        for kind, title, rationale, basis in candidates[:MAX_SUGGESTIONS_PER_RUN]:
            digest = suggestion_hash(kind, title)
            exists = self._session.scalar(
                select(StrategySuggestion.id).where(StrategySuggestion.suggestion_hash == digest)
            )
            if exists is not None:
                continue
            row = StrategySuggestion(
                kind=kind,
                title=title,
                rationale=rationale,
                basis=basis,
                status=SuggestionStatus.PROPOSED,
                proposed_at=moment,
                suggestion_hash=digest,
            )
            self._session.add(row)
            written.append(row)
        self._session.flush()
        return written

    def _focus_candidates(
        self, real: list[tuple[PublishedContent, PerformanceAssessment]]
    ) -> list[tuple[SuggestionKind, str, str, dict[str, Any]]]:
        clusters = {row.id: row for row in self._session.scalars(select(TopicCluster))}
        audiences = {row.id: row for row in self._session.scalars(select(AudienceStrategy))}
        groups: dict[tuple[str, str], list[tuple[PublishedContent, PerformanceAssessment]]] = (
            defaultdict(list)
        )
        for content, assessment in real:
            if content.topic_cluster_id is not None:
                groups[("cluster", str(content.topic_cluster_id))].append((content, assessment))
            if content.audience_id is not None:
                groups[("audience", str(content.audience_id))].append((content, assessment))
            if content.theme_key:
                groups[("theme", content.theme_key)].append((content, assessment))
        candidates: list[tuple[SuggestionKind, str, str, dict[str, Any]]] = []
        for (grain, key), rows in sorted(groups.items()):
            if len(rows) < MIN_PUBLICATIONS:
                continue
            rising = sum(1 for _, a in rows if a.status is AssessmentStatus.RISING)
            if rising / len(rows) < RISING_SHARE:
                continue
            metrics = {
                "publications": len(rows),
                "rising": rising,
                "stable": sum(1 for _, a in rows if a.status is AssessmentStatus.STABLE),
                "declining": sum(1 for _, a in rows if a.status is AssessmentStatus.DECLINING),
                "volatile": sum(1 for _, a in rows if a.status is AssessmentStatus.VOLATILE),
                "impressions": sum(_current_int(a, "impressions") for _, a in rows),
                "clicks": sum(_current_int(a, "clicks") for _, a in rows),
            }
            basis: dict[str, Any] = {
                "grain": grain,
                "window_days": WINDOW_DAYS,
                "publications": [str(c.id) for c, _ in rows],
                "work_item_ids": [str(c.work_item_id) for c, _ in rows],
                "assessments": [str(a.id) for _, a in rows],
                "metrics": metrics,
            }
            if grain == "cluster":
                cluster = clusters.get(uuid.UUID(key))
                if cluster is None:
                    continue
                basis["cluster_id"] = str(cluster.id)
                basis["cluster_name"] = cluster.name
                candidates.append(
                    (
                        SuggestionKind.CLUSTER_FOCUS,
                        f"{cluster.name} kümesine odaklan",
                        (
                            f"{cluster.name} kümesindeki {len(rows)} yayının {rising} tanesi son "
                            f"{WINDOW_DAYS} günde yükseliyor → bu kümenin alt konu araştırmasını artır."
                        ),
                        basis,
                    )
                )
            elif grain == "audience":
                audience = audiences.get(uuid.UUID(key))
                if audience is None:
                    continue
                basis["audience_id"] = str(audience.id)
                basis["audience_name"] = audience.name
                candidates.append(
                    (
                        SuggestionKind.AUDIENCE_FOCUS,
                        f"{audience.name} kitlesine odaklan",
                        (
                            f"{audience.name} kitlesi için yayınlanan {len(rows)} içeriğin {rising} tanesi "
                            f"son {WINDOW_DAYS} günde güçlü performans gösteriyor → bu kitle için "
                            "araştırma önceliğini artır."
                        ),
                        basis,
                    )
                )
            else:
                theme_cluster = _dominant_cluster(rows)
                basis["theme_key"] = key
                if theme_cluster is not None:
                    basis["cluster_id"] = str(theme_cluster)
                candidates.append(
                    (
                        SuggestionKind.THEME_FOCUS,
                        f"{key} temasını hedef konu yap",
                        (
                            f"{key} temalı {len(rows)} yayının {rising} tanesi son {WINDOW_DAYS} günde "
                            "yükseliyor → bu temayı stratejik hedef konu olarak ekle."
                        ),
                        basis,
                    )
                )
        return candidates

    def _keyword_candidates(
        self, real: list[tuple[PublishedContent, PerformanceAssessment]]
    ) -> list[tuple[SuggestionKind, str, str, dict[str, Any]]]:
        existing = {
            row.normalized_phrase
            for row in self._session.scalars(select(StrategicKeyword))
            if row.status is not StrategyStatus.ARCHIVED
        }
        by_query: dict[str, dict[str, Any]] = {}
        for content, assessment in real:
            if assessment.status not in (AssessmentStatus.RISING, AssessmentStatus.STABLE):
                continue
            queries = top_queries(
                self._performance.snapshots_for(
                    content.id, PerformanceProvider.GOOGLE_SEARCH_CONSOLE
                )
            )
            seen: set[str] = set()
            for entry in queries:
                phrase = str(entry.get("query", "")).strip()
                normalized = normalize_phrase(phrase)
                if not normalized or normalized in existing or normalized in seen:
                    continue
                seen.add(normalized)
                bucket = by_query.setdefault(
                    normalized, {"phrase": phrase, "contents": [], "clusters": []}
                )
                bucket["contents"].append(content)
                if content.topic_cluster_id is not None:
                    bucket["clusters"].append(content.topic_cluster_id)
        candidates: list[tuple[SuggestionKind, str, str, dict[str, Any]]] = []
        for normalized, bucket in sorted(
            by_query.items(), key=lambda item: (-len(item[1]["contents"]), item[0])
        ):
            contents: list[PublishedContent] = bucket["contents"]
            if len(contents) < MIN_PUBLICATIONS:
                continue
            clusters: list[uuid.UUID] = bucket["clusters"]
            cluster_id = max(set(clusters), key=clusters.count) if clusters else None
            basis: dict[str, Any] = {
                "grain": "query",
                "window_days": WINDOW_DAYS,
                "phrase": bucket["phrase"],
                "normalized_phrase": normalized,
                "publications": [str(c.id) for c in contents],
                "work_item_ids": [str(c.work_item_id) for c in contents],
                "metrics": {"publications": len(contents)},
            }
            if cluster_id is not None:
                basis["cluster_id"] = str(cluster_id)
            candidates.append(
                (
                    SuggestionKind.KEYWORD_ADD,
                    f"“{bucket['phrase']}” ifadesini hedef konu olarak ekle",
                    (
                        f"“{bucket['phrase']}” sorgusu {len(contents)} yükselen/stabil yayının en çok "
                        "getiren sorguları arasında ama henüz stratejik hedef değil → keşif ve "
                        "planlamada öncelik kazanması için ekle."
                    ),
                    basis,
                )
            )
            if len(candidates) >= MAX_KEYWORD_SUGGESTIONS:
                break
        return candidates

    # --- decisions -----------------------------------------------------------

    def accept(
        self, suggestion_id: uuid.UUID, *, user: User | None, reason: str
    ) -> StrategySuggestion:
        row, cleaned, moment = self._decision_preamble(suggestion_id, user=user, reason=reason)
        assert user is not None
        applied = self._apply(row)
        row.basis = {**row.basis, "applied": applied}
        row.status = SuggestionStatus.ACCEPTED
        row.decided_at = moment
        row.decided_by_user_id = user.id
        row.decision_reason = cleaned
        self._session.flush()
        return row

    def ignore(
        self, suggestion_id: uuid.UUID, *, user: User | None, reason: str
    ) -> StrategySuggestion:
        row, cleaned, moment = self._decision_preamble(suggestion_id, user=user, reason=reason)
        assert user is not None
        row.status = SuggestionStatus.IGNORED
        row.decided_at = moment
        row.decided_by_user_id = user.id
        row.decision_reason = cleaned
        self._session.flush()
        return row

    def _apply(self, row: StrategySuggestion) -> dict[str, Any]:
        """ONE bounded strategy change per accepted suggestion."""
        strategy = StrategyService(self._session)
        basis = row.basis
        cluster_id = _uuid_or_none(basis.get("cluster_id"))
        if row.kind is SuggestionKind.CLUSTER_FOCUS and cluster_id is not None:
            cluster = self._session.get(TopicCluster, cluster_id)
            if cluster is None:
                raise SuggestionStateError("the suggested cluster no longer exists")
            new_priority = min(100, cluster.priority + PRIORITY_STEP)
            strategy.update_cluster(cluster.id, priority=new_priority)
            return {
                "kind": "cluster_priority",
                "cluster_id": str(cluster.id),
                "priority": new_priority,
            }
        if row.kind is SuggestionKind.AUDIENCE_FOCUS:
            audience_id = _uuid_or_none(basis.get("audience_id"))
            audience = self._session.get(AudienceStrategy, audience_id) if audience_id else None
            if audience is None:
                raise SuggestionStateError("the suggested audience no longer exists")
            new_priority = min(100, audience.priority + PRIORITY_STEP)
            strategy.update_audience(audience.id, priority=new_priority)
            return {
                "kind": "audience_priority",
                "audience_id": str(audience.id),
                "priority": new_priority,
            }
        phrase = (
            basis.get("phrase")
            if row.kind is SuggestionKind.KEYWORD_ADD
            else basis.get("theme_key")
        )
        if not isinstance(phrase, str) or not phrase.strip():
            raise SuggestionStateError("the suggestion carries no phrase to add")
        normalized = normalize_phrase(phrase)
        existing = self._session.scalar(
            select(StrategicKeyword).where(StrategicKeyword.normalized_phrase == normalized)
        )
        if existing is not None:
            return {"kind": "keyword_exists", "keyword_id": str(existing.id)}
        keyword = strategy.create_keyword(
            phrase=phrase,
            priority=NEW_KEYWORD_PRIORITY,
            topic_cluster_id=cluster_id
            if cluster_id and self._session.get(TopicCluster, cluster_id)
            else None,
            notes="Performans döngüsü önerisinden eklendi.",
        )
        return {"kind": "keyword_created", "keyword_id": str(keyword.id)}

    def _decision_preamble(
        self, suggestion_id: uuid.UUID, *, user: User | None, reason: str
    ) -> tuple[StrategySuggestion, str, datetime]:
        if user is None:
            raise SuggestionActorRequiredError("suggestion decisions require a named user")
        cleaned = reason.strip()
        if not cleaned or len(cleaned) > MAX_REASON_LENGTH:
            raise SuggestionStateError("a bounded, non-empty reason is required")
        row = self.get(suggestion_id)
        if row is None:
            raise SuggestionNotFoundError(f"no strategy suggestion with id {suggestion_id}")
        if row.status is not SuggestionStatus.PROPOSED:
            raise SuggestionStateError(f"the suggestion is already '{row.status.value}'")
        return row, cleaned, datetime.now(UTC)


def _current_int(assessment: PerformanceAssessment, key: str) -> int:
    current = assessment.basis.get("current")
    if isinstance(current, dict) and isinstance(current.get(key), int):
        return int(current[key])
    return 0


def _dominant_cluster(
    rows: list[tuple[PublishedContent, PerformanceAssessment]],
) -> uuid.UUID | None:
    clusters = [c.topic_cluster_id for c, _ in rows if c.topic_cluster_id is not None]
    return max(set(clusters), key=clusters.count) if clusters else None


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
