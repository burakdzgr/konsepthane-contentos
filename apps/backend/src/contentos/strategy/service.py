"""Transport-neutral strategy management and bounded context matching."""

import re
import unicodedata
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.strategy.enums import StrategyStatus
from contentos.strategy.models import AudienceStrategy, StrategicKeyword, TopicCluster

MAX_STRATEGY_MATCHES = 8


def normalize_phrase(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    ascii_like = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(re.findall(r"[\w]+", ascii_like, flags=re.UNICODE))


def _required(value: str, name: str, limit: int) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} must not be empty")
    if len(cleaned) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    return cleaned


def _priority(value: int) -> int:
    if isinstance(value, bool) or not 0 <= value <= 100:
        raise ValueError("priority must be between 0 and 100")
    return value


def _changed_priority(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("priority must be an integer")
    return _priority(value)


@dataclass(frozen=True, slots=True)
class StrategyContext:
    audiences: tuple[AudienceStrategy, ...]
    keywords: tuple[StrategicKeyword, ...]
    clusters: tuple[TopicCluster, ...]

    def projection(self) -> dict[str, object]:
        return {
            "audiences": [
                {"id": str(row.id), "name": row.name, "priority": row.priority}
                for row in self.audiences
            ],
            "keywords": [
                {
                    "id": str(row.id),
                    "phrase": row.phrase,
                    "priority": row.priority,
                    "topic_cluster_id": str(row.topic_cluster_id) if row.topic_cluster_id else None,
                }
                for row in self.keywords
            ],
            "clusters": [
                {"id": str(row.id), "name": row.name, "priority": row.priority}
                for row in self.clusters
            ],
            "bounded": True,
            "max_keywords": MAX_STRATEGY_MATCHES,
        }


class StrategyService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_audiences(self) -> list[AudienceStrategy]:
        return list(
            self._session.scalars(
                select(AudienceStrategy).order_by(
                    AudienceStrategy.priority.desc(), AudienceStrategy.name
                )
            )
        )

    def list_clusters(self) -> list[TopicCluster]:
        return list(
            self._session.scalars(
                select(TopicCluster).order_by(TopicCluster.priority.desc(), TopicCluster.name)
            )
        )

    def list_keywords(self) -> list[StrategicKeyword]:
        return list(
            self._session.scalars(
                select(StrategicKeyword).order_by(
                    StrategicKeyword.priority.desc(), StrategicKeyword.phrase
                )
            )
        )

    def create_audience(
        self,
        *,
        name: str,
        priority: int,
        status: StrategyStatus = StrategyStatus.ACTIVE,
        notes: str | None = None,
        locale: str = "tr-TR",
        market: str = "TR",
    ) -> AudienceStrategy:
        row = AudienceStrategy(
            name=_required(name, "name", 160),
            priority=_priority(priority),
            status=status,
            notes=notes.strip() if notes and notes.strip() else None,
            locale=locale,
            market=market.upper(),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def update_audience(self, audience_id: uuid.UUID, **changes: object) -> AudienceStrategy:
        row = self._session.get(AudienceStrategy, audience_id)
        if row is None:
            raise LookupError("audience strategy not found")
        if "name" in changes:
            row.name = _required(str(changes["name"]), "name", 160)
        if "priority" in changes:
            row.priority = _changed_priority(changes["priority"])
        if "status" in changes:
            row.status = StrategyStatus(str(changes["status"]))
        if "notes" in changes:
            row.notes = str(changes["notes"]).strip() or None
        self._session.flush()
        return row

    def create_cluster(
        self,
        *,
        name: str,
        priority: int,
        status: StrategyStatus = StrategyStatus.ACTIVE,
        notes: str | None = None,
        locale: str = "tr-TR",
        market: str = "TR",
    ) -> TopicCluster:
        clean = _required(name, "name", 200)
        row = TopicCluster(
            name=clean,
            slug=normalize_phrase(clean).replace(" ", "-"),
            priority=_priority(priority),
            status=status,
            notes=notes.strip() if notes and notes.strip() else None,
            locale=locale,
            market=market.upper(),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def update_cluster(self, cluster_id: uuid.UUID, **changes: object) -> TopicCluster:
        row = self._session.get(TopicCluster, cluster_id)
        if row is None:
            raise LookupError("topic cluster not found")
        if "name" in changes:
            row.name = _required(str(changes["name"]), "name", 200)
            row.slug = normalize_phrase(row.name).replace(" ", "-")
        if "priority" in changes:
            row.priority = _changed_priority(changes["priority"])
        if "status" in changes:
            row.status = StrategyStatus(str(changes["status"]))
        if "notes" in changes:
            row.notes = str(changes["notes"]).strip() or None
        self._session.flush()
        return row

    def create_keyword(
        self,
        *,
        phrase: str,
        priority: int,
        topic_cluster_id: uuid.UUID | None = None,
        status: StrategyStatus = StrategyStatus.ACTIVE,
        notes: str | None = None,
        locale: str = "tr-TR",
        market: str = "TR",
    ) -> StrategicKeyword:
        clean = _required(phrase, "phrase", 240)
        if (
            topic_cluster_id is not None
            and self._session.get(TopicCluster, topic_cluster_id) is None
        ):
            raise LookupError("topic cluster not found")
        row = StrategicKeyword(
            phrase=clean,
            normalized_phrase=normalize_phrase(clean),
            priority=_priority(priority),
            topic_cluster_id=topic_cluster_id,
            status=status,
            notes=notes.strip() if notes and notes.strip() else None,
            locale=locale,
            market=market.upper(),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def update_keyword(self, keyword_id: uuid.UUID, **changes: object) -> StrategicKeyword:
        row = self._session.get(StrategicKeyword, keyword_id)
        if row is None:
            raise LookupError("strategic keyword not found")
        if "phrase" in changes:
            row.phrase = _required(str(changes["phrase"]), "phrase", 240)
            row.normalized_phrase = normalize_phrase(row.phrase)
        if "priority" in changes:
            row.priority = _changed_priority(changes["priority"])
        if "status" in changes:
            row.status = StrategyStatus(str(changes["status"]))
        if "topic_cluster_id" in changes:
            raw = changes["topic_cluster_id"]
            cluster_id = uuid.UUID(str(raw)) if raw else None
            if cluster_id is not None and self._session.get(TopicCluster, cluster_id) is None:
                raise LookupError("topic cluster not found")
            row.topic_cluster_id = cluster_id
        if "notes" in changes:
            row.notes = str(changes["notes"]).strip() or None
        self._session.flush()
        return row

    def context_for_text(
        self, text: str, *, locale: str = "tr-TR", market: str = "TR"
    ) -> StrategyContext:
        normalized = normalize_phrase(text)
        keywords = [
            row
            for row in self.list_keywords()
            if row.status is StrategyStatus.ACTIVE
            and row.locale == locale
            and row.market == market.upper()
            and _term_overlap(row.normalized_phrase, normalized)
        ]
        keywords = keywords[:MAX_STRATEGY_MATCHES]
        cluster_ids = {row.topic_cluster_id for row in keywords if row.topic_cluster_id is not None}
        clusters = [row for row in self.list_clusters() if row.id in cluster_ids]
        audiences = [
            row
            for row in self.list_audiences()
            if row.status is StrategyStatus.ACTIVE
            and row.locale == locale
            and row.market == market.upper()
            and _term_overlap(normalize_phrase(row.name), normalized)
        ]
        return StrategyContext(
            tuple(audiences[:MAX_STRATEGY_MATCHES]),
            tuple(keywords),
            tuple(clusters[:MAX_STRATEGY_MATCHES]),
        )

    def priority_for_text(self, text: str, *, locale: str = "tr-TR", market: str = "TR") -> int:
        context = self.context_for_text(text, locale=locale, market=market)
        return max((row.priority for row in context.keywords), default=0)


def _term_overlap(strategy_phrase: str, text: str) -> bool:
    strategy_tokens = {token for token in strategy_phrase.split() if len(token) >= 3}
    text_tokens = set(text.split())
    distinctive_overlap = any(len(token) >= 6 and token in text_tokens for token in strategy_tokens)
    return bool(strategy_tokens) and (
        strategy_phrase in text
        or len(strategy_tokens & text_tokens) >= min(2, len(strategy_tokens))
        or distinctive_overlap
    )
