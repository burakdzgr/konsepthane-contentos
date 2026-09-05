"""Refresh opportunities: a decline becomes a HUMAN-gated rework proposal.

Detection is idempotent (one open proposal per published content) and the
diagnosis carries only what was actually computed. Approval is a NAMED
decision that moves the work item onto the existing canonical rework
route (PUBLISHED/PINTEREST_PENDING/DISTRIBUTED -> MEASURING ->
REFRESH_CANDIDATE) through `WorkflowService`; the next step
(REFRESH_CANDIDATE -> RESEARCHING) stays with a human or the autopilot's
governed path, and NOTHING here publishes. Original provenance is untouched.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from contentos.auth.models import User
from contentos.inspiration.models import InspirationSignal
from contentos.intelligence.models import IntelligenceSignal
from contentos.performance.enums import AssessmentStatus, PerformanceProvider, RefreshStatus
from contentos.performance.models import (
    PerformanceAssessment,
    PublishedContent,
    RefreshOpportunity,
)
from contentos.performance.service import PerformanceError, PerformanceService, top_queries
from contentos.strategy.service import StrategyService, normalize_phrase
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.models import EditorialWorkItem
from contentos.workflow.service import WorkflowService

TRIGGER_WINDOWS: tuple[int, ...] = (28, 90)
MAX_QUERY_CHANGES = 10
MAX_NEW_SIGNALS = 10
MAX_CANNIBALIZATION_HINTS = 5
POSITION_DROP_THRESHOLD = 2.0
MAX_REASON_LENGTH = 2000

# Every state from which the canonical route reaches REFRESH_CANDIDATE, with
# the exact transitions (STRUCTURAL_TRANSITIONS in contentos.workflow.service).
_ROUTE_TO_REFRESH: dict[WorkflowState, tuple[WorkflowState, ...]] = {
    WorkflowState.PUBLISHED: (WorkflowState.MEASURING, WorkflowState.REFRESH_CANDIDATE),
    WorkflowState.PINTEREST_PENDING: (WorkflowState.MEASURING, WorkflowState.REFRESH_CANDIDATE),
    WorkflowState.DISTRIBUTED: (WorkflowState.MEASURING, WorkflowState.REFRESH_CANDIDATE),
    WorkflowState.MEASURING: (WorkflowState.REFRESH_CANDIDATE,),
    WorkflowState.REFRESH_CANDIDATE: (),
}


class RefreshNotFoundError(PerformanceError):
    """No refresh opportunity with that id."""


class RefreshStateError(PerformanceError):
    """The opportunity is not open for a decision."""


class RefreshActorRequiredError(PerformanceError):
    """Refresh decisions are named human decisions."""


class RefreshWorkflowStateError(PerformanceError):
    """The work item is not in a state the rework route can leave from."""


class RefreshOpportunityService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._performance = PerformanceService(session)

    # --- reads ---------------------------------------------------------------

    def list_opportunities(self, status: RefreshStatus | None = None) -> list[RefreshOpportunity]:
        statement = select(RefreshOpportunity)
        if status is not None:
            statement = statement.where(RefreshOpportunity.status == status)
        statement = statement.order_by(RefreshOpportunity.proposed_at.desc(), RefreshOpportunity.id)
        return list(self._session.scalars(statement))

    def get(self, refresh_id: uuid.UUID) -> RefreshOpportunity | None:
        return self._session.get(RefreshOpportunity, refresh_id)

    def open_for(self, published_content_id: uuid.UUID) -> RefreshOpportunity | None:
        return self._session.scalar(
            select(RefreshOpportunity)
            .where(
                RefreshOpportunity.published_content_id == published_content_id,
                RefreshOpportunity.status == RefreshStatus.PROPOSED,
            )
            .order_by(RefreshOpportunity.proposed_at.desc())
            .limit(1)
        )

    def latest_for(self, published_content_id: uuid.UUID) -> RefreshOpportunity | None:
        return self._session.scalar(
            select(RefreshOpportunity)
            .where(RefreshOpportunity.published_content_id == published_content_id)
            .order_by(RefreshOpportunity.proposed_at.desc(), RefreshOpportunity.id.desc())
            .limit(1)
        )

    def pending_count(self) -> int:
        return len(self.list_opportunities(RefreshStatus.PROPOSED))

    # --- detection -----------------------------------------------------------

    def detect(self, *, now: datetime | None = None) -> list[RefreshOpportunity]:
        """Propose a refresh for every content whose latest 28/90-day
        assessment is DECLINING; idempotent per trigger assessment."""
        moment = now if now is not None else datetime.now(UTC)
        proposed: list[RefreshOpportunity] = []
        for content in self._performance.list_published():
            trigger = self._declining_trigger(content)
            if trigger is None:
                continue
            if self.open_for(content.id) is not None:
                continue
            already_decided = self._session.scalar(
                select(RefreshOpportunity.id).where(
                    RefreshOpportunity.trigger_assessment_id == trigger.id
                )
            )
            if already_decided is not None:
                continue
            diagnosis = self.diagnose(content, trigger, now=moment)
            row = RefreshOpportunity(
                published_content_id=content.id,
                status=RefreshStatus.PROPOSED,
                trigger_assessment_id=trigger.id,
                diagnosis=diagnosis,
                recommendation=self.recommendation_text(content, diagnosis),
                proposed_at=moment,
            )
            self._session.add(row)
            proposed.append(row)
        self._session.flush()
        return proposed

    def _declining_trigger(self, content: PublishedContent) -> PerformanceAssessment | None:
        candidates = [
            assessment
            for window in TRIGGER_WINDOWS
            if (assessment := self._performance.latest_assessment(content.id, window)) is not None
            and assessment.status is AssessmentStatus.DECLINING
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda row: (row.assessed_at, row.window_days), reverse=True)
        return candidates[0]

    def diagnose(
        self, content: PublishedContent, assessment: PerformanceAssessment, *, now: datetime
    ) -> dict[str, Any]:
        """Only what is actually computed; absent inputs are stated as such."""
        basis = assessment.basis
        deltas = _dict_field(basis, "deltas")
        current = _dict_field(basis, "current")
        previous = _dict_field(basis, "previous")
        gsc_snapshots = self._performance.snapshots_for(
            content.id, PerformanceProvider.GOOGLE_SEARCH_CONSOLE
        )
        queries_now = top_queries(gsc_snapshots)
        diagnosis: dict[str, Any] = {
            "window_days": assessment.window_days,
            "assessment_status": assessment.status.value,
            "position_movement": {
                "previous": previous.get("position"),
                "current": current.get("position"),
                "delta": deltas.get("position_delta"),
            },
            "impressions_pct": deltas.get("impressions_pct"),
            "clicks_pct": deltas.get("clicks_pct"),
            "content_age_days": max(0, (now - content.published_at).days),
            "query_changes": self._query_changes(content),
            "top_queries": [
                {"query": str(entry.get("query", "")), "position": entry.get("position")}
                for entry in queries_now[:MAX_QUERY_CHANGES]
            ],
        }
        concept_keys = _concept_keys(content, queries_now)
        diagnosis["concept_keys"] = sorted(concept_keys)
        diagnosis["new_signals"] = (
            self._new_signals(concept_keys, content.published_at) if concept_keys else []
        )
        diagnosis["strategy_fit"] = self._strategy_fit(content, queries_now)
        diagnosis["cannibalization_hint"] = (
            self._cannibalization(content, queries_now) if queries_now else []
        )
        return diagnosis

    def _query_changes(self, content: PublishedContent) -> dict[str, Any]:
        summaries = self._performance.latest_summary_snapshots(
            content.id, PerformanceProvider.GOOGLE_SEARCH_CONSOLE, limit=2
        )
        if len(summaries) < 2:
            return {"available": False, "reason": "fewer_than_two_query_summaries"}
        latest, earlier = summaries[0], summaries[1]
        latest_queries = _query_map(latest.metrics)
        earlier_queries = _query_map(earlier.metrics)
        lost = sorted(set(earlier_queries) - set(latest_queries))[:MAX_QUERY_CHANGES]
        new = sorted(set(latest_queries) - set(earlier_queries))[:MAX_QUERY_CHANGES]
        drops: list[dict[str, Any]] = []
        for query in sorted(set(latest_queries) & set(earlier_queries)):
            before = earlier_queries[query]
            after = latest_queries[query]
            if (
                before is not None
                and after is not None
                and after - before >= POSITION_DROP_THRESHOLD
            ):
                drops.append({"query": query, "from": before, "to": after})
        return {
            "available": True,
            "compared_periods": [
                {"start": earlier.period_start.isoformat(), "end": earlier.period_end.isoformat()},
                {"start": latest.period_start.isoformat(), "end": latest.period_end.isoformat()},
            ],
            "lost_queries": lost,
            "new_queries": new,
            "position_drops": drops[:MAX_QUERY_CHANGES],
        }

    def _new_signals(self, concept_keys: set[str], since: datetime) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for row in self._session.scalars(
            select(IntelligenceSignal)
            .where(
                IntelligenceSignal.concept_key.in_(sorted(concept_keys)),
                IntelligenceSignal.last_observed_at > since,
            )
            .order_by(IntelligenceSignal.last_observed_at.desc())
            .limit(MAX_NEW_SIGNALS)
        ):
            found.append(
                {
                    "kind": "intelligence",
                    "family": row.family.value,
                    "concept_key": row.concept_key,
                    "subject": row.subject,
                    "observed_at": row.last_observed_at.isoformat(),
                }
            )
        remaining = MAX_NEW_SIGNALS - len(found)
        if remaining > 0:
            for signal in self._session.scalars(
                select(InspirationSignal)
                .where(
                    InspirationSignal.concept_key.in_(sorted(concept_keys)),
                    InspirationSignal.created_at > since,
                )
                .order_by(InspirationSignal.created_at.desc())
                .limit(remaining)
            ):
                found.append(
                    {
                        "kind": "inspiration",
                        "family": "inspiration",
                        "concept_key": signal.concept_key,
                        "subject": signal.title,
                        "observed_at": signal.created_at.isoformat(),
                    }
                )
        return found

    def _strategy_fit(
        self, content: PublishedContent, queries: list[dict[str, Any]]
    ) -> dict[str, Any]:
        work_item = self._session.get(EditorialWorkItem, content.work_item_id)
        if work_item is None:
            return {"available": False}
        text = " ".join(
            [work_item.title_working_label, *(str(entry.get("query", "")) for entry in queries)]
        )
        context = StrategyService(self._session).context_for_text(
            text, locale=work_item.locale, market=work_item.market
        )
        return {
            "available": True,
            "clusters": [row.name for row in context.clusters],
            "keywords": [row.phrase for row in context.keywords],
            "audiences": [row.name for row in context.audiences],
            "priority": max((row.priority for row in context.keywords), default=0),
        }

    def _cannibalization(
        self, content: PublishedContent, queries: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        mine = {normalize_phrase(str(entry.get("query", ""))) for entry in queries}
        mine.discard("")
        hints: list[dict[str, Any]] = []
        for other in self._performance.list_published():
            if other.id == content.id:
                continue
            theirs = {
                normalize_phrase(str(entry.get("query", "")))
                for entry in top_queries(
                    self._performance.snapshots_for(
                        other.id, PerformanceProvider.GOOGLE_SEARCH_CONSOLE
                    )
                )
            }
            shared = sorted((mine & theirs) - {""})
            if shared:
                hints.append(
                    {"work_item_id": str(other.work_item_id), "shared_queries": shared[:5]}
                )
            if len(hints) >= MAX_CANNIBALIZATION_HINTS:
                break
        return hints

    def recommendation_text(self, content: PublishedContent, diagnosis: dict[str, Any]) -> str:
        parts: list[str] = []
        movement = diagnosis.get("position_movement", {})
        if movement.get("previous") is not None and movement.get("current") is not None:
            parts.append(
                f"Ortalama pozisyon {movement['previous']} → {movement['current']} "
                f"({diagnosis.get('window_days')} günlük pencere)."
            )
        impressions_pct = diagnosis.get("impressions_pct")
        if isinstance(impressions_pct, int | float):
            parts.append(f"Gösterimler %{abs(round(impressions_pct * 100))} düştü.")
        changes = diagnosis.get("query_changes", {})
        if changes.get("available") and changes.get("lost_queries"):
            parts.append(f"Kaybedilen sorgular: {', '.join(changes['lost_queries'][:3])}.")
        if diagnosis.get("new_signals"):
            parts.append(
                f"Yayından sonra {len(diagnosis['new_signals'])} yeni ilham/istihbarat sinyali gözlendi; "
                "içeriği bu sinyallerle güncellemek değerli olabilir."
            )
        if diagnosis.get("cannibalization_hint"):
            parts.append(
                "Aynı sorgularda başka yayınlar da görünüyor; birleştirme veya odak ayrımı değerlendirilmeli."
            )
        parts.append(
            f"Öneri: içeriği ({diagnosis.get('content_age_days', 0)} günlük) araştırma yenileme "
            "rotasına almak; onay yalnızca yeniden araştırmayı başlatır, yayın kararı ayrıdır."
        )
        return " ".join(parts)

    # --- decisions --------------------------------------------------------------

    def approve(
        self,
        refresh_id: uuid.UUID,
        *,
        user: User | None,
        reason: str,
        request_id: str | None = None,
    ) -> RefreshOpportunity:
        row, cleaned_reason, moment = self._decision_preamble(refresh_id, user=user, reason=reason)
        assert user is not None
        content = self._performance.get(row.published_content_id)
        if content is None:
            raise RefreshStateError("the refresh opportunity has no published content")
        work_item = self._session.get(EditorialWorkItem, content.work_item_id)
        if work_item is None:
            raise RefreshWorkflowStateError("the published work item no longer exists")
        route = _ROUTE_TO_REFRESH.get(work_item.current_state)
        if route is None:
            raise RefreshWorkflowStateError(
                f"a refresh cannot start from state '{work_item.current_state.value}'"
            )
        workflow = WorkflowService(self._session)
        for target in route:
            workflow.transition(
                work_item.id,
                target,
                actor_origin=WorkflowActorOrigin.OPERATOR,
                actor_user_id=user.id,
                reason=f"içerik güncelleme fırsatı onaylandı: {cleaned_reason}",
                artifact_refs={
                    "refresh_opportunity_id": str(row.id),
                    "trigger_assessment_id": str(row.trigger_assessment_id),
                    "published_content_id": str(content.id),
                    "publication_package_id": str(content.publication_package_id),
                    "next_step": "refresh_candidate -> researching (human or autopilot)",
                },
                request_id=request_id,
            )
        row.status = RefreshStatus.APPROVED
        row.decided_at = moment
        row.decided_by_user_id = user.id
        row.decision_reason = cleaned_reason
        self._session.flush()
        return row

    def dismiss(
        self,
        refresh_id: uuid.UUID,
        *,
        user: User | None,
        reason: str,
        request_id: str | None = None,
    ) -> RefreshOpportunity:
        row, cleaned_reason, moment = self._decision_preamble(refresh_id, user=user, reason=reason)
        assert user is not None
        row.status = RefreshStatus.DISMISSED
        row.decided_at = moment
        row.decided_by_user_id = user.id
        row.decision_reason = cleaned_reason
        self._session.flush()
        return row

    def _decision_preamble(
        self, refresh_id: uuid.UUID, *, user: User | None, reason: str
    ) -> tuple[RefreshOpportunity, str, datetime]:
        if user is None:
            raise RefreshActorRequiredError("refresh decisions require a named user")
        cleaned = reason.strip()
        if not cleaned or len(cleaned) > MAX_REASON_LENGTH:
            raise RefreshStateError("a bounded, non-empty reason is required")
        row = self.get(refresh_id)
        if row is None:
            raise RefreshNotFoundError(f"no refresh opportunity with id {refresh_id}")
        if row.status is not RefreshStatus.PROPOSED:
            raise RefreshStateError(f"the refresh opportunity is already '{row.status.value}'")
        return row, cleaned, datetime.now(UTC)


def _query_map(metrics: dict[str, Any]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    queries = metrics.get("top_queries")
    if not isinstance(queries, list):
        return result
    for entry in queries:
        if not isinstance(entry, dict):
            continue
        query = str(entry.get("query", "")).strip()
        if not query:
            continue
        position = entry.get("position")
        result[query] = (
            float(position)
            if isinstance(position, int | float) and not isinstance(position, bool)
            else None
        )
    return result


def _concept_keys(content: PublishedContent, queries: list[dict[str, Any]]) -> set[str]:
    keys = {normalize_phrase(str(entry.get("query", ""))) for entry in queries}
    if content.theme_key:
        keys.add(normalize_phrase(content.theme_key))
    keys.discard("")
    return keys


def _dict_field(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    return dict(value) if isinstance(value, dict) else {}
