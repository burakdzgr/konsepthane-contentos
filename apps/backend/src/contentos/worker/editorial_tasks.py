"""Idempotent Celery orchestration of the Phase 3 editorial pipeline.

The Phase-2 delivery contract is binding and reused verbatim: PostgreSQL is
authoritative; Celery is transport/execution only; at-least-once delivery is
absorbed by durable domain idempotency; durable results COMMIT before the
next stage is enqueued; DISPATCH retries never redo domain work; queue
completion alone never changes workflow state (every transition goes
through WorkflowService with exact artifact refs). The known commit/broker
gap is inherited unchanged — no outbox in this task.

Human decision boundaries are hard: commissioning (IDEA_SCORING ->
EVIDENCE_BUILDING) and brief acceptance (BRIEFING -> DRAFTING) are NEVER
performed by any task here. Scoring never auto-commissions; idea generation
never auto-selects; composition ends at a DRAFT brief in BRIEFING.

AI tasks build their provider lazily through the WorkerRuntime seam (fake
provider in tests, configured OpenAI in production; missing configuration
is a typed terminal failure with no fallback). The AI attempt retry_number
is ``base_retry_number + celery domain retries`` so every provider retry is
a distinct durable attempt identity; failed attempts are COMMITTED before a
DOMAIN retry is raised.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import structlog
from celery import Celery
from sqlalchemy.orm import Session

from contentos.ai.budget import BudgetExceededError, ensure_daily_attempt_budget
from contentos.ai.enums import GenerationStatus
from contentos.briefs.composition import BriefCompositionEngine
from contentos.briefs.errors import BriefCompositionMaterializationError
from contentos.briefs.repository import BriefRepository
from contentos.drafts.errors import DraftGenerationMaterializationError
from contentos.drafts.generation import WriterEngine
from contentos.drafts.repository import DraftRepository
from contentos.evidence_packs.enums import (
    ContradictionSeverity,
    EvidenceItemRole,
    EvidencePackSufficiency,
)
from contentos.evidence_packs.repository import EvidencePackRepository
from contentos.evidence_packs.service import (
    ContradictionDeclaration,
    EvidencePackService,
    EvidenceSelection,
)
from contentos.ideas.generation import IdeaGenerationEngine
from contentos.ideas.service import IdeaService
from contentos.inspiration.service import InspirationIntelligenceService
from contentos.integrations.registry import create_integration_registry
from contentos.opportunities.enums import OpportunityDisposition
from contentos.opportunities.errors import OpportunityNotFoundError
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.scoring_service import OpportunityScoringService
from contentos.opportunities.service import ResearchPromotionService
from contentos.qa.enums import QaOutcome
from contentos.qa.gates import QaGateEngine
from contentos.qa.repository import QaRepository
from contentos.reviews.errors import ReviewGenerationMaterializationError
from contentos.reviews.generation import EditorEngine
from contentos.reviews.repository import ReviewRepository
from contentos.search_intent.service import SearchIntentService
from contentos.worker.research_tasks import (
    MAX_RETRIES,
    InvalidPipelineInputError,
    _current_request_id,
    _parse_uuid,
    _retry_countdown,
)
from contentos.worker.runtime import WorkerRuntime
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.repository import WorkflowRepository
from contentos.workflow.service import WorkflowService

_logger = structlog.get_logger("contentos.worker.editorial")

PROMOTE_RESEARCH_TASK = "contentos.editorial.promote_research"
EVALUATE_OPPORTUNITY_TASK = "contentos.editorial.evaluate_opportunity"
GENERATE_IDEA_CANDIDATES_TASK = "contentos.editorial.generate_idea_candidates"
BUILD_EVIDENCE_PACK_TASK = "contentos.editorial.build_evidence_pack"
ANALYZE_SEARCH_INTENT_TASK = "contentos.editorial.analyze_search_intent"
COMPOSE_CONTENT_BRIEF_TASK = "contentos.editorial.compose_content_brief"
GENERATE_WRITER_DRAFT_TASK = "contentos.editorial.generate_writer_draft"
GENERATE_EDITOR_REVIEW_TASK = "contentos.editorial.generate_editor_review"
RUN_QA_GATES_TASK = "contentos.editorial.run_qa_gates"
GENERATE_MEDIA_IMAGE_TASK = "contentos.editorial.generate_media_image"
PUBLISH_PACKAGE_TASK = "contentos.editorial.publish_package"

EDITORIAL_TASK_NAMES = (
    PROMOTE_RESEARCH_TASK,
    EVALUATE_OPPORTUNITY_TASK,
    GENERATE_IDEA_CANDIDATES_TASK,
    BUILD_EVIDENCE_PACK_TASK,
    ANALYZE_SEARCH_INTENT_TASK,
    COMPOSE_CONTENT_BRIEF_TASK,
    GENERATE_WRITER_DRAFT_TASK,
    GENERATE_EDITOR_REVIEW_TASK,
    RUN_QA_GATES_TASK,
    GENERATE_MEDIA_IMAGE_TASK,
    PUBLISH_PACKAGE_TASK,
)

MAX_BLOCK_REASON_ITEMS = 5

# Bounded DOMAIN retry classification for AI execution outcomes: a timeout
# or (assumed transient) provider error may retry within the Celery bound;
# VALIDATION_FAILED and CANCELLED are terminal for automatic execution —
# the durable attempt persists and nothing retries blindly.
RETRYABLE_AI_STATUSES = frozenset({GenerationStatus.TIMEOUT, GenerationStatus.PROVIDER_ERROR})


class WorkflowHistoryConflictError(Exception):
    """Durable workflow history is incompatible with this redelivery."""


class EditorialDispatcher(Protocol):
    """Post-commit enqueueing seam for the next editorial stage."""

    def enqueue(
        self, task_name: str, payload: dict[str, Any], *, request_id: str | None = None
    ) -> None: ...


class CeleryEditorialDispatcher:
    """Enqueue registered editorial tasks with JSON-safe kwargs only."""

    def __init__(self, app: Celery) -> None:
        self._app = app

    def enqueue(
        self, task_name: str, payload: dict[str, Any], *, request_id: str | None = None
    ) -> None:
        headers = {"request_id": request_id} if request_id else None
        self._app.tasks[task_name].apply_async(kwargs=payload, headers=headers)


def register_editorial_pipeline_tasks(
    app: Celery,
    runtime: WorkerRuntime,
    *,
    dispatcher: EditorialDispatcher | None = None,
) -> None:
    """Explicitly register the six §18 editorial tasks on ``app``.

    Registration only defines tasks: no database, broker, network, or
    provider activity happens here.
    """
    editorial_dispatcher: EditorialDispatcher = dispatcher or CeleryEditorialDispatcher(app)

    @contextmanager
    def task_session() -> Iterator[Session]:
        session = runtime.create_session()
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def dispatch_next(task: Any, task_name: str, payload: dict[str, Any]) -> str:
        """Enqueue after commit; transport failure triggers a DISPATCH retry."""
        try:
            editorial_dispatcher.enqueue(task_name, payload, request_id=_current_request_id(task))
        except Exception as error:
            _logger.warning(
                "editorial_dispatch_failed",
                task=str(task.name),
                next_task=task_name,
                error_type=type(error).__name__,
                retries=int(task.request.retries),
            )
            raise task.retry(countdown=_retry_countdown(task.request.retries)) from None
        return task_name

    def budget_refusal(task: Any, session: Session, **fields: Any) -> dict[str, Any] | None:
        """The daily spend guard, checked BEFORE any provider invocation.
        A refusal is an execution fact and a truthful task no-op: nothing
        is persisted, no state moves, and nothing retries blindly."""
        try:
            ensure_daily_attempt_budget(session, runtime.settings.ai_daily_attempt_budget)
        except BudgetExceededError as error:
            return _summary(task, "budget_exhausted", detail=str(error), **fields)
        return None

    def handle_ai_outcome(task: Any, session: Session, status: GenerationStatus) -> bool:
        """Commit the durable failed attempt, then DOMAIN-retry if allowed.

        Returns True when the caller should report a terminal failed
        outcome (no retry raised)."""
        if status is GenerationStatus.SUCCEEDED:
            return False
        session.commit()  # the failed attempt is audit history, never rolled back
        if status in RETRYABLE_AI_STATUSES and task.request.retries < MAX_RETRIES:
            raise task.retry(countdown=_retry_countdown(task.request.retries))
        return True

    # --- promote_research ---------------------------------------------------

    def promote_research(self: Any, normalized_document_id: str) -> dict[str, Any]:
        parsed_id = _parse_uuid(normalized_document_id)
        with task_session() as session:
            result = ResearchPromotionService(session).promote_research(parsed_id)
            session.commit()
            next_task = dispatch_next(
                self,
                EVALUATE_OPPORTUNITY_TASK,
                {"opportunity_id": str(result.opportunity_id)},
            )
            return _summary(
                self,
                "completed" if result.created else "reused",
                work_item_id=str(result.work_item_id),
                opportunity_id=str(result.opportunity_id),
                duplicate_outcome=result.duplicate_outcome.value,
                next_task=next_task,
            )

    # --- evaluate_opportunity -----------------------------------------------

    def evaluate_opportunity(self: Any, opportunity_id: str) -> dict[str, Any]:
        parsed_id = _parse_uuid(opportunity_id)
        with task_session() as session:
            evaluation = OpportunityScoringService(session).evaluate_opportunity(parsed_id)
            # Pre-decision enrichment runs ONLY here: the worker composes the
            # provider registry (durable cache/budget through this session);
            # the API process evaluates provider-free. Construction touches
            # no network; every provider call inside is fail-safe.
            intelligence = InspirationIntelligenceService(session).evaluate(
                parsed_id,
                registry=create_integration_registry(runtime.settings, runtime.create_session),
            )
            session.commit()
            # Commissioning remains a HUMAN decision: no downstream dispatch.
            return _summary(
                self,
                "completed" if evaluation.created else "reused",
                opportunity_id=opportunity_id,
                opportunity_score_id=str(evaluation.score.id),
                band=evaluation.score.overall_band.value,
                eligibility=evaluation.score.eligibility.value,
                inspiration_band=intelligence.evaluation.inspiration_band.value,
                search_opportunity=intelligence.evaluation.search_opportunity.value,
                recommendation=intelligence.evaluation.recommendation.value,
                inspiration_signal_count=len(
                    intelligence.evaluation.input_snapshot.get("signal_ids", [])
                ),
            )

    # --- generate_idea_candidates -------------------------------------------

    def generate_idea_candidates(
        self: Any,
        opportunity_id: str,
        candidate_count: int = 3,
        retry_number: int = 0,
    ) -> dict[str, Any]:
        parsed_id = _parse_uuid(opportunity_id)
        with task_session() as session:
            _require_stage(session, parsed_id, WorkflowState.EVIDENCE_BUILDING)
            refused = budget_refusal(self, session, opportunity_id=opportunity_id)
            if refused is not None:
                return refused
            execution = IdeaGenerationEngine(session).generate_candidates(
                parsed_id,
                provider=runtime.create_generation_provider(),
                candidate_count=candidate_count,
                retry_number=retry_number + int(self.request.retries),
            )
            if handle_ai_outcome(self, session, execution.status):
                return _summary(
                    self,
                    "ai_failed",
                    opportunity_id=opportunity_id,
                    attempt_id=str(execution.attempt.id),
                    attempt_status=execution.status.value,
                )
            session.commit()
            # No workflow transition, no automatic selection, no dispatch:
            # the operator still selects an idea explicitly.
            return _summary(
                self,
                "completed" if execution.ideas_created else "reused",
                opportunity_id=opportunity_id,
                attempt_id=str(execution.attempt.id),
                idea_ids=[str(idea.id) for idea in execution.ideas],
            )

    # --- build_evidence_pack ------------------------------------------------

    def build_evidence_pack(
        self: Any,
        opportunity_id: str,
        idea_id: str,
        selections: list[dict[str, Any]],
        contradictions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        parsed_opportunity = _parse_uuid(opportunity_id)
        parsed_idea = _parse_uuid(idea_id)
        mapped_selections = [_map_selection(entry) for entry in selections]
        mapped_contradictions = (
            [_map_contradiction(entry) for entry in contradictions] if contradictions else None
        )
        with task_session() as session:
            work_item = _require_commissioned(session, parsed_opportunity)
            if work_item.current_state not in (
                WorkflowState.EVIDENCE_BUILDING,
                WorkflowState.SEO_RESEARCH,
                WorkflowState.BLOCKED,
            ):
                raise WorkflowHistoryConflictError(
                    "evidence pack assembly requires EVIDENCE_BUILDING "
                    f"(current: {work_item.current_state.value})"
                )
            effective = IdeaService(session).get_effective_selection(parsed_opportunity)
            if effective is None or effective.id != parsed_idea:
                raise InvalidPipelineInputError(
                    "the supplied idea is not the current effective selection"
                )
            # TRANSACTION A: durable pack first.
            assembly = EvidencePackService(session).assemble_pack(
                parsed_opportunity,
                mapped_selections,
                contradictions=mapped_contradictions,
                idea_id=parsed_idea,
            )
            session.commit()
            pack = assembly.pack

            # TRANSACTION B: re-read and move workflow through the service.
            workflow_repo = WorkflowRepository(session)
            work_item = workflow_repo.get_by_id_for_update(work_item.id)
            assert work_item is not None
            analysis_payload = {
                "opportunity_id": opportunity_id,
                "idea_id": idea_id,
                "evidence_pack_id": str(pack.id),
            }
            if pack.sufficiency is EvidencePackSufficiency.READY:
                if work_item.current_state is WorkflowState.EVIDENCE_BUILDING:
                    WorkflowService(session).transition(
                        work_item.id,
                        WorkflowState.SEO_RESEARCH,
                        actor_origin=WorkflowActorOrigin.SYSTEM,
                        reason=(f"evidence pack {pack.id} v{pack.version} is READY"),
                        artifact_refs={
                            "opportunity_id": opportunity_id,
                            "idea_id": idea_id,
                            "evidence_pack_id": str(pack.id),
                            "evidence_pack_version": pack.version,
                            "sufficiency": pack.sufficiency.value,
                        },
                        request_id=_current_request_id(self),
                    )
                    session.commit()
                else:
                    _require_compatible_entry(
                        workflow_repo,
                        work_item.id,
                        WorkflowState.SEO_RESEARCH,
                        "evidence_pack_id",
                        str(pack.id),
                    )
                    if work_item.current_state is not WorkflowState.SEO_RESEARCH:
                        # Pipeline already progressed past analysis dispatch.
                        return _summary(
                            self,
                            "reused",
                            opportunity_id=opportunity_id,
                            evidence_pack_id=str(pack.id),
                            sufficiency=pack.sufficiency.value,
                        )
                next_task = dispatch_next(self, ANALYZE_SEARCH_INTENT_TASK, analysis_payload)
                return _summary(
                    self,
                    "completed" if assembly.created else "reused",
                    opportunity_id=opportunity_id,
                    evidence_pack_id=str(pack.id),
                    sufficiency=pack.sufficiency.value,
                    next_task=next_task,
                )

            # Non-READY: explicit SYSTEM block, never analysis, never REJECT.
            if work_item.current_state is WorkflowState.EVIDENCE_BUILDING:
                missing = pack.sufficiency_detail.get("missing", [])[:MAX_BLOCK_REASON_ITEMS]
                blocking = pack.sufficiency_detail.get("unresolved_blocking_contradictions", [])[
                    :MAX_BLOCK_REASON_ITEMS
                ]
                reason = f"evidence pack {pack.id} v{pack.version} is {pack.sufficiency.value}"
                if missing:
                    reason += f"; missing: {'; '.join(missing)}"
                if blocking:
                    reason += f"; blocking contradictions: {', '.join(blocking)}"
                WorkflowService(session).transition(
                    work_item.id,
                    WorkflowState.BLOCKED,
                    actor_origin=WorkflowActorOrigin.SYSTEM,
                    reason=reason[:1000],
                    artifact_refs={
                        "opportunity_id": opportunity_id,
                        "idea_id": idea_id,
                        "evidence_pack_id": str(pack.id),
                        "evidence_pack_version": pack.version,
                        "sufficiency": pack.sufficiency.value,
                    },
                    request_id=_current_request_id(self),
                )
                session.commit()
            else:
                _require_compatible_entry(
                    workflow_repo,
                    work_item.id,
                    WorkflowState.BLOCKED,
                    "evidence_pack_id",
                    str(pack.id),
                )
            return _summary(
                self,
                "blocked",
                opportunity_id=opportunity_id,
                evidence_pack_id=str(pack.id),
                sufficiency=pack.sufficiency.value,
            )

    # --- analyze_search_intent ----------------------------------------------

    def analyze_search_intent(
        self: Any,
        opportunity_id: str,
        idea_id: str,
        evidence_pack_id: str,
        signal_ids: list[str] | None = None,
        retry_number: int = 0,
    ) -> dict[str, Any]:
        parsed_opportunity = _parse_uuid(opportunity_id)
        parsed_idea = _parse_uuid(idea_id)
        parsed_pack = _parse_uuid(evidence_pack_id)
        parsed_signals = [_parse_uuid(value) for value in (signal_ids or [])]
        with task_session() as session:
            work_item = _require_commissioned(session, parsed_opportunity)
            if work_item.current_state not in (
                WorkflowState.SEO_RESEARCH,
                WorkflowState.BRIEFING,
            ):
                raise WorkflowHistoryConflictError(
                    "search-intent analysis requires SEO_RESEARCH "
                    f"(current: {work_item.current_state.value})"
                )
            pack = EvidencePackRepository(session).get_pack(parsed_pack)
            if (
                pack is None
                or pack.opportunity_id != parsed_opportunity
                or pack.sufficiency is not EvidencePackSufficiency.READY
                or (pack.idea_id is not None and pack.idea_id != parsed_idea)
            ):
                raise InvalidPipelineInputError(
                    "the pinned evidence pack is missing, mismatched, or not READY"
                )
            refused = budget_refusal(self, session, opportunity_id=opportunity_id)
            if refused is not None:
                return refused
            # TRANSACTION A: durable analysis (or durable failed attempt).
            outcome = SearchIntentService(session).synthesize(
                parsed_opportunity,
                idea_id=parsed_idea,
                provider=runtime.create_generation_provider(),
                signal_ids=parsed_signals,
                retry_number=retry_number + int(self.request.retries),
            )
            if handle_ai_outcome(self, session, outcome.status):
                return _summary(
                    self,
                    "ai_failed",
                    opportunity_id=opportunity_id,
                    attempt_id=str(outcome.attempt.id),
                    attempt_status=outcome.status.value,
                )
            session.commit()
            analysis = outcome.analysis
            assert analysis is not None

            # TRANSACTION B: workflow movement after the durable result.
            workflow_repo = WorkflowRepository(session)
            work_item = workflow_repo.get_by_id_for_update(work_item.id)
            assert work_item is not None
            if work_item.current_state is WorkflowState.SEO_RESEARCH:
                WorkflowService(session).transition(
                    work_item.id,
                    WorkflowState.BRIEFING,
                    actor_origin=WorkflowActorOrigin.SYSTEM,
                    reason=f"search intent analysis {analysis.id} v{analysis.version}",
                    artifact_refs={
                        "opportunity_id": opportunity_id,
                        "idea_id": idea_id,
                        "evidence_pack_id": evidence_pack_id,
                        "search_intent_analysis_id": str(analysis.id),
                    },
                    request_id=_current_request_id(self),
                )
                session.commit()
            else:
                _require_compatible_entry(
                    workflow_repo,
                    work_item.id,
                    WorkflowState.BRIEFING,
                    "search_intent_analysis_id",
                    str(analysis.id),
                )
            # Brief composition is an OPERATOR command (§18): stop here.
            return _summary(
                self,
                "completed" if outcome.analysis_created else "reused",
                opportunity_id=opportunity_id,
                search_intent_analysis_id=str(analysis.id),
                missing_signals=list(analysis.missing_signals),
            )

    # --- compose_content_brief ----------------------------------------------

    def compose_content_brief(
        self: Any,
        work_item_id: str,
        idea_id: str,
        evidence_pack_id: str,
        search_intent_analysis_id: str,
        retry_number: int = 0,
        supersede_reason: str | None = None,
    ) -> dict[str, Any]:
        parsed_work_item = _parse_uuid(work_item_id)
        parsed_idea = _parse_uuid(idea_id)
        parsed_pack = _parse_uuid(evidence_pack_id)
        parsed_analysis = _parse_uuid(search_intent_analysis_id)
        with task_session() as session:
            refused = budget_refusal(self, session, work_item_id=work_item_id)
            if refused is not None:
                return refused
            try:
                result = BriefCompositionEngine(session).compose(
                    parsed_work_item,
                    idea_id=parsed_idea,
                    evidence_pack_id=parsed_pack,
                    search_intent_analysis_id=parsed_analysis,
                    provider=runtime.create_generation_provider(),
                    retry_number=retry_number + int(self.request.retries),
                    supersede_reason=supersede_reason,
                    request_id=_current_request_id(self),
                )
            except BriefCompositionMaterializationError:
                # The SUCCEEDED attempt is real audit history: keep it
                # durable, then fail terminally (never relabeled).
                session.commit()
                raise
            if handle_ai_outcome(self, session, result.status):
                return _summary(
                    self,
                    "ai_failed",
                    work_item_id=work_item_id,
                    attempt_id=str(result.attempt.id),
                    attempt_status=result.status.value,
                )
            session.commit()
            brief = result.brief
            assert brief is not None
            # NEVER accept, NEVER transition: the draft waits in BRIEFING
            # for the explicit operator acceptance command.
            return _summary(
                self,
                "completed" if result.brief_created else "reused",
                work_item_id=work_item_id,
                content_brief_id=str(brief.id),
                brief_status=brief.status.value,
                structure_guard=result.structure_guard_outcome,
            )

    # --- generate_writer_draft ----------------------------------------------

    def generate_writer_draft(
        self: Any,
        content_brief_id: str,
        retry_number: int = 0,
        supersede_reason: str | None = None,
    ) -> dict[str, Any]:
        parsed_brief = _parse_uuid(content_brief_id)
        with task_session() as session:
            engine = WriterEngine(session)
            drafts = DraftRepository(session)
            workflow_repo = WorkflowRepository(session)

            # Redelivery after our own transition: durable history must pin
            # the draft this brief produced; then the work is already done.
            brief_row = BriefRepository(session).get_brief(parsed_brief)
            if brief_row is not None:
                work_item = workflow_repo.get_by_id(brief_row.work_item_id)
                if work_item is not None and work_item.current_state is WorkflowState.EDITING:
                    existing = drafts.list_by_work_item(work_item.id)
                    latest = existing[-1] if existing else None
                    if latest is None:
                        raise WorkflowHistoryConflictError(
                            "the work item is in EDITING but no draft exists"
                        )
                    _require_compatible_entry(
                        workflow_repo,
                        work_item.id,
                        WorkflowState.EDITING,
                        "content_draft_id",
                        str(latest.id),
                    )
                    # Re-dispatch on redelivery: the original dispatch may
                    # have been lost in the commit/broker gap; the Editor
                    # task's own guard absorbs the duplicate.
                    next_task = dispatch_next(
                        self,
                        GENERATE_EDITOR_REVIEW_TASK,
                        {"work_item_id": str(work_item.id)},
                    )
                    return _summary(
                        self,
                        "reused",
                        content_brief_id=content_brief_id,
                        content_draft_id=str(latest.id),
                        draft_version=latest.version,
                        next_task=next_task,
                    )

            refused = budget_refusal(self, session, content_brief_id=content_brief_id)
            if refused is not None:
                return refused
            # TRANSACTION A: durable draft (or durable failed attempt).
            try:
                result = engine.generate_draft(
                    parsed_brief,
                    provider=runtime.create_generation_provider(),
                    retry_number=retry_number + int(self.request.retries),
                    supersede_reason=supersede_reason,
                    request_id=_current_request_id(self),
                )
            except DraftGenerationMaterializationError:
                # The SUCCEEDED attempt is real audit history: keep it
                # durable, then fail terminally (never relabeled).
                session.commit()
                raise
            if handle_ai_outcome(self, session, result.status):
                return _summary(
                    self,
                    "ai_failed",
                    content_brief_id=content_brief_id,
                    attempt_id=str(result.attempt.id),
                    attempt_status=result.status.value,
                )
            session.commit()
            draft = result.draft
            assert draft is not None

            # TRANSACTION B: the WORKFLOW.md artifact gate — a durable valid
            # draft exists, so DRAFTING -> EDITING via WorkflowService with
            # the exact draft identity pinned. Queue completion itself never
            # advances state; the Editor review is dispatched AFTER commit.
            work_item = workflow_repo.get_by_id_for_update(draft.work_item_id)
            assert work_item is not None
            if work_item.current_state is WorkflowState.DRAFTING:
                WorkflowService(session).transition(
                    work_item.id,
                    WorkflowState.EDITING,
                    actor_origin=WorkflowActorOrigin.SYSTEM,
                    reason=f"writer draft {draft.id} v{draft.version} is durable and valid",
                    artifact_refs={
                        "content_brief_id": content_brief_id,
                        "content_draft_id": str(draft.id),
                        "draft_version": draft.version,
                        "content_hash": draft.content_hash,
                    },
                    request_id=_current_request_id(self),
                )
                session.commit()
            else:
                _require_compatible_entry(
                    workflow_repo,
                    work_item.id,
                    WorkflowState.EDITING,
                    "content_draft_id",
                    str(draft.id),
                )
            next_task = dispatch_next(
                self,
                GENERATE_EDITOR_REVIEW_TASK,
                {"work_item_id": str(draft.work_item_id)},
            )
            return _summary(
                self,
                "completed" if result.draft_created else "reused",
                content_brief_id=content_brief_id,
                content_draft_id=str(draft.id),
                draft_version=draft.version,
                attempt_id=str(result.attempt.id),
                next_task=next_task,
            )

    # --- generate_editor_review ---------------------------------------------

    def generate_editor_review(
        self: Any,
        work_item_id: str,
        retry_number: int = 0,
        supersede_reason: str | None = None,
    ) -> dict[str, Any]:
        parsed_item = _parse_uuid(work_item_id)
        with task_session() as session:
            reviews = ReviewRepository(session)
            drafts = DraftRepository(session)

            # Redelivery/idempotency: for a plain delivery (no explicit
            # regeneration), an ACTIVE review already covering the ACTIVE
            # draft means the work is done — zero provider spend.
            if retry_number == 0 and supersede_reason is None:
                active_draft = drafts.get_active_draft(parsed_item)
                active_review = reviews.get_active_review(parsed_item)
                if (
                    active_draft is not None
                    and active_review is not None
                    and active_review.content_draft_id == active_draft.id
                ):
                    return _summary(
                        self,
                        "reused",
                        work_item_id=work_item_id,
                        editorial_review_id=str(active_review.id),
                        review_verdict=active_review.verdict.value,
                    )

            # TRANSACTION A: durable review (or durable failed attempt).
            refused = budget_refusal(self, session, work_item_id=work_item_id)
            if refused is not None:
                return refused
            try:
                result = EditorEngine(session).generate_review(
                    parsed_item,
                    provider=runtime.create_generation_provider(),
                    retry_number=retry_number + int(self.request.retries),
                    supersede_reason=supersede_reason,
                    request_id=_current_request_id(self),
                )
            except ReviewGenerationMaterializationError:
                # The SUCCEEDED attempt is real audit history: keep it
                # durable, then fail terminally (never relabeled).
                session.commit()
                raise
            if handle_ai_outcome(self, session, result.status):
                return _summary(
                    self,
                    "ai_failed",
                    work_item_id=work_item_id,
                    attempt_id=str(result.attempt.id),
                    attempt_status=result.status.value,
                )
            session.commit()
            review = result.review
            assert review is not None
            # NO workflow transition and NO downstream dispatch: humans
            # advance out of EDITING (accept-review / request-rework), and
            # the QA stage does not exist yet.
            return _summary(
                self,
                "completed" if result.review_created else "reused",
                work_item_id=work_item_id,
                editorial_review_id=str(review.id),
                review_verdict=review.verdict.value,
                attempt_id=str(result.attempt.id),
            )

    # --- run_qa_gates -------------------------------------------------------

    def run_qa_gates(self: Any, work_item_id: str) -> dict[str, Any]:
        parsed_item = _parse_uuid(work_item_id)
        with task_session() as session:
            workflow_repo = WorkflowRepository(session)

            # Redelivery after our own transition: durable history must pin
            # the report; then the work is already done.
            item = workflow_repo.get_by_id(parsed_item)
            if item is not None and (item.current_state is WorkflowState.AWAITING_HUMAN_REVIEW):
                report = QaRepository(session).get_active_report(parsed_item)
                if report is None:
                    raise WorkflowHistoryConflictError(
                        "the work item is in AWAITING_HUMAN_REVIEW but no QA report exists"
                    )
                _require_compatible_entry(
                    workflow_repo,
                    parsed_item,
                    WorkflowState.AWAITING_HUMAN_REVIEW,
                    "qa_report_id",
                    str(report.id),
                )
                return _summary(
                    self,
                    "reused",
                    work_item_id=work_item_id,
                    qa_report_id=str(report.id),
                    qa_outcome=report.outcome.value,
                )

            # TRANSACTION A: deterministic gates -> durable report (idempotent
            # by content hash). No provider is involved anywhere.
            result = QaGateEngine(session).run_gates(
                parsed_item, request_id=_current_request_id(self)
            )
            session.commit()

            if result.outcome is QaOutcome.READY_FOR_HUMAN_REVIEW:
                # TRANSACTION B: the artifact gate — a durable ready report
                # exists, so QA_REVIEW -> AWAITING_HUMAN_REVIEW via
                # WorkflowService with the exact package pinned. This is the
                # PHASE 4 TERMINAL: the next step is a HUMAN decision, so
                # there is NO downstream dispatch.
                item = workflow_repo.get_by_id_for_update(parsed_item)
                assert item is not None
                if item.current_state is WorkflowState.QA_REVIEW:
                    WorkflowService(session).transition(
                        parsed_item,
                        WorkflowState.AWAITING_HUMAN_REVIEW,
                        actor_origin=WorkflowActorOrigin.SYSTEM,
                        reason=(
                            f"qa report {result.report.id} v{result.report.version} "
                            "passed all hard gates"
                        ),
                        artifact_refs={
                            "qa_report_id": str(result.report.id),
                            "editorial_review_id": str(result.package.review.id),
                            "content_draft_id": str(result.package.draft.id),
                            "content_hash": result.package.draft.content_hash,
                        },
                        request_id=_current_request_id(self),
                    )
                    session.commit()
                else:
                    _require_compatible_entry(
                        workflow_repo,
                        parsed_item,
                        WorkflowState.AWAITING_HUMAN_REVIEW,
                        "qa_report_id",
                        str(result.report.id),
                    )
            return _summary(
                self,
                "completed" if result.created else "reused",
                work_item_id=work_item_id,
                qa_report_id=str(result.report.id),
                qa_outcome=result.outcome.value,
                report_version=result.report.version,
            )

    # --- generate_media_image -----------------------------------------------

    def generate_media_image(
        self: Any,
        work_item_id: str,
        need_index: int,
        requested_by_user_id: str,
        retry_number: int = 0,
    ) -> dict[str, Any]:
        """Phase 6 M4: produce ONE candidate image for one brief media need.

        No workflow transition, no downstream dispatch, and NO satisfaction:
        the durable outcome is an attempt row plus (on success) a
        content-addressed asset carrying the attempt provenance and the
        NAMED commissioning human. A human binds it explicitly (ADR 0004).
        """
        from contentos.auth.models import User as _User
        from contentos.media.errors import MediaInputError, MediaPreconditionError
        from contentos.media.generation import MediaImageEngine

        parsed_item = _parse_uuid(work_item_id)
        parsed_user = _parse_uuid(requested_by_user_id)
        with task_session() as session:
            requested_by = session.get(_User, parsed_user)
            if requested_by is None or not requested_by.is_active:
                # The commissioning identity must be a real ACTIVE human.
                return _summary(
                    self,
                    "precondition_failed",
                    work_item_id=work_item_id,
                    detail="requested_by_user_id does not resolve to an active user",
                )
            refused = budget_refusal(self, session, work_item_id=work_item_id)
            if refused is not None:
                return refused
            engine = MediaImageEngine(session, runtime.create_media_store())
            try:
                result = engine.generate(
                    parsed_item,
                    need_index,
                    requested_by=requested_by,
                    provider=runtime.create_image_provider(),
                    retry_number=retry_number + int(self.request.retries),
                    request_id=_current_request_id(self),
                )
            except (MediaPreconditionError, MediaInputError) as error:
                # Durable state does not admit the generation (state moved,
                # need vanished with a new brief, ...): truthful no-op —
                # never a workflow effect, never a fabricated failure asset.
                return _summary(
                    self,
                    "precondition_failed",
                    work_item_id=work_item_id,
                    detail=str(error)[:500],
                )
            if handle_ai_outcome(self, session, result.status):
                return _summary(
                    self,
                    "ai_failed",
                    work_item_id=work_item_id,
                    attempt_id=str(result.attempt.id),
                    attempt_status=result.status.value,
                )
            session.commit()
            return _summary(
                self,
                "completed" if result.created else "reused",
                work_item_id=work_item_id,
                need_index=need_index,
                attempt_id=str(result.attempt.id),
                media_asset_id=str(result.asset.id) if result.asset is not None else None,
            )

    # --- publish_package -----------------------------------------------------

    def publish_package(self: Any, work_item_id: str) -> dict[str, Any]:
        """Phase 7 P3: execute ONE publication dispatch behind the gates.

        SCHEDULED: the approval is RE-CHECKED (stale -> the wired
        APPROVAL_EXPIRED path fires instead of publishing); then SYSTEM
        SCHEDULED -> PUBLISHING pinned to the scheduled package. The
        dispatch outcome is a durable publication attempt FIRST; success
        advances SYSTEM -> PUBLISHED with the remote reference pinned,
        transient failures retry bounded, terminal failures advance
        SYSTEM -> BLOCKED with the truthful reason — execution failure
        is never an editorial decision (REJECTED is unreachable).
        """
        from contentos.decisions.service import DecisionService
        from contentos.performance.service import record_publication_fail_safe
        from contentos.publishing.models import PublicationPackage
        from contentos.publishing.service import PublishingService
        from contentos.publishing.transport import TransportConfigurationError

        parsed_item = _parse_uuid(work_item_id)
        with task_session() as session:
            workflow_repo = WorkflowRepository(session)
            item = workflow_repo.get_by_id(parsed_item)
            if item is None:
                return _summary(
                    self,
                    "precondition_failed",
                    work_item_id=work_item_id,
                    detail="no such editorial work item",
                )
            publishing = PublishingService(session)

            def _resolve_pinned_package(entered: WorkflowState) -> PublicationPackage:
                entry = workflow_repo.get_latest_entry_event(parsed_item, entered)
                pinned = (
                    (entry.artifact_refs or {}).get("publication_package_id") if entry else None
                )
                if pinned is None:
                    raise WorkflowHistoryConflictError(
                        f"the {entered.value} entry event does not pin a publication package"
                    )
                package = session.get(PublicationPackage, _parse_uuid(str(pinned)))
                if package is None or package.work_item_id != parsed_item:
                    raise WorkflowHistoryConflictError(
                        "the pinned publication package does not resolve"
                    )
                return package

            # Redelivery after completion: durable history must pin it all.
            if item.current_state is WorkflowState.PUBLISHED:
                package = _resolve_pinned_package(WorkflowState.PUBLISHED)
                prior = publishing.successful_attempt(package.id)
                if prior is None:
                    raise WorkflowHistoryConflictError(
                        "the work item is PUBLISHED without a successful attempt"
                    )
                return _summary(
                    self,
                    "reused",
                    work_item_id=work_item_id,
                    publication_package_id=str(package.id),
                    remote_publication_ref=prior.remote_publication_ref,
                )

            if item.current_state not in (WorkflowState.SCHEDULED, WorkflowState.PUBLISHING):
                return _summary(
                    self,
                    "precondition_failed",
                    work_item_id=work_item_id,
                    detail=(
                        "publication requires SCHEDULED or PUBLISHING "
                        f"(current: {item.current_state.value})"
                    ),
                )

            # The transport must exist BEFORE any state moves: an
            # unconfigured boundary is a truthful no-op, never a stuck item.
            try:
                transport = runtime.create_publishing_transport()
            except TransportConfigurationError as error:
                return _summary(
                    self,
                    "transport_unconfigured",
                    work_item_id=work_item_id,
                    detail=str(error),
                )

            if item.current_state is WorkflowState.SCHEDULED:
                decisions = DecisionService(session)
                if not decisions.approval_is_current(parsed_item):
                    # The wired G5 path: a stale approval is surfaced,
                    # never published.
                    decisions.expire_stale_approval(
                        parsed_item,
                        reason=("the approval no longer covers the ACTIVE draft at publish time"),
                        request_id=_current_request_id(self),
                    )
                    session.commit()
                    return _summary(self, "approval_expired", work_item_id=work_item_id)
                package = _resolve_pinned_package(WorkflowState.SCHEDULED)
                WorkflowService(session).transition(
                    parsed_item,
                    WorkflowState.PUBLISHING,
                    actor_origin=WorkflowActorOrigin.SYSTEM,
                    reason=f"publication dispatch of package {package.id} starting",
                    artifact_refs={
                        "publication_package_id": str(package.id),
                        "package_hash": package.package_hash,
                    },
                    request_id=_current_request_id(self),
                )
                session.commit()
            else:
                package = _resolve_pinned_package(WorkflowState.PUBLISHING)

            # Redelivery inside PUBLISHING: an already-successful dispatch
            # is reused — the idempotency key made the remote side safe too.
            prior = publishing.successful_attempt(package.id)
            if prior is None:
                outcome = transport.publish(
                    package.payload,
                    package.media_manifest,
                    runtime.create_media_store().read,
                    publishing.idempotency_key(package),
                    request_id=_current_request_id(self),
                )
                attempt = publishing.record_attempt(
                    package,
                    outcome,
                    transport_name=transport.name,
                    request_id=_current_request_id(self),
                )
                session.commit()  # the execution fact is durable FIRST
                if outcome.status != "succeeded":
                    if (
                        outcome.status in ("transport_error", "timeout")
                        and self.request.retries < MAX_RETRIES
                    ):
                        raise self.retry(countdown=_retry_countdown(self.request.retries))
                    WorkflowService(session).transition(
                        parsed_item,
                        WorkflowState.BLOCKED,
                        actor_origin=WorkflowActorOrigin.SYSTEM,
                        reason=(
                            "publication dispatch failed terminally "
                            f"({outcome.status}: {outcome.error_class}); "
                            "execution failure is not an editorial decision"
                        ),
                        artifact_refs={
                            "publication_package_id": str(package.id),
                            "attempt_number": attempt.attempt_number,
                        },
                        request_id=_current_request_id(self),
                    )
                    session.commit()
                    return _summary(
                        self,
                        "publish_failed",
                        work_item_id=work_item_id,
                        publication_package_id=str(package.id),
                        attempt_status=outcome.status,
                        error_class=outcome.error_class,
                    )
                prior = attempt

            item = workflow_repo.get_by_id_for_update(parsed_item)
            assert item is not None
            if item.current_state is WorkflowState.PUBLISHING:
                WorkflowService(session).transition(
                    parsed_item,
                    WorkflowState.PUBLISHED,
                    actor_origin=WorkflowActorOrigin.SYSTEM,
                    reason=(f"publication package {package.id} accepted by the publishing api"),
                    artifact_refs={
                        "publication_package_id": str(package.id),
                        "package_hash": package.package_hash,
                        "remote_publication_ref": prior.remote_publication_ref,
                    },
                    request_id=_current_request_id(self),
                )
                session.commit()
            else:
                _require_compatible_entry(
                    workflow_repo,
                    parsed_item,
                    WorkflowState.PUBLISHED,
                    "publication_package_id",
                    str(package.id),
                )
            # PUBLISHED = measurement started (agent E): tiny, fail-safe.
            record_publication_fail_safe(
                session,
                work_item_id=parsed_item,
                publication_package_id=package.id,
                publication_attempt_id=prior.id,
                remote_publication_ref=prior.remote_publication_ref,
                published_at=prior.created_at,
            )
            # No downstream dispatch: distribution/measuring are later phases.
            return _summary(
                self,
                "completed",
                work_item_id=work_item_id,
                publication_package_id=str(package.id),
                remote_publication_ref=prior.remote_publication_ref,
            )

    common_options: dict[str, Any] = {
        "bind": True,
        "shared": False,
        "acks_late": True,
        "reject_on_worker_lost": True,
        "max_retries": MAX_RETRIES,
    }
    app.task(name=PROMOTE_RESEARCH_TASK, **common_options)(promote_research)
    app.task(name=EVALUATE_OPPORTUNITY_TASK, **common_options)(evaluate_opportunity)
    app.task(name=GENERATE_IDEA_CANDIDATES_TASK, **common_options)(generate_idea_candidates)
    app.task(name=BUILD_EVIDENCE_PACK_TASK, **common_options)(build_evidence_pack)
    app.task(name=ANALYZE_SEARCH_INTENT_TASK, **common_options)(analyze_search_intent)
    app.task(name=COMPOSE_CONTENT_BRIEF_TASK, **common_options)(compose_content_brief)
    app.task(name=GENERATE_WRITER_DRAFT_TASK, **common_options)(generate_writer_draft)
    app.task(name=GENERATE_EDITOR_REVIEW_TASK, **common_options)(generate_editor_review)
    app.task(name=RUN_QA_GATES_TASK, **common_options)(run_qa_gates)
    app.task(name=GENERATE_MEDIA_IMAGE_TASK, **common_options)(generate_media_image)
    app.task(name=PUBLISH_PACKAGE_TASK, **common_options)(publish_package)


def _require_commissioned(session: Session, opportunity_id: uuid.UUID) -> Any:
    """Revalidate durable state; return the work item (never mutated here)."""
    opportunity = OpportunityRepository(session).get_by_id(opportunity_id)
    if opportunity is None:
        raise OpportunityNotFoundError(f"no opportunity with id {opportunity_id}")
    if opportunity.disposition is not OpportunityDisposition.COMMISSIONED:
        raise InvalidPipelineInputError(
            f"the opportunity is not COMMISSIONED (current: {opportunity.disposition.value})"
        )
    work_item = WorkflowRepository(session).get_by_id(opportunity.work_item_id)
    if work_item is None:  # pragma: no cover - RESTRICT FK guarantees this
        raise OpportunityNotFoundError("opportunity has no resolvable work item")
    return work_item


def _require_stage(session: Session, opportunity_id: uuid.UUID, stage: WorkflowState) -> None:
    work_item = _require_commissioned(session, opportunity_id)
    if work_item.current_state is not stage:
        raise WorkflowHistoryConflictError(
            f"this command requires {stage.value} (current: {work_item.current_state.value})"
        )


def _require_compatible_entry(
    workflow_repo: WorkflowRepository,
    work_item_id: uuid.UUID,
    entered_state: WorkflowState,
    ref_key: str,
    ref_value: str,
) -> None:
    """Redelivery guard: durable history must pin this exact artifact."""
    entry = workflow_repo.get_latest_entry_event(work_item_id, entered_state)
    if entry is None or entry.artifact_refs.get(ref_key) != ref_value:
        raise WorkflowHistoryConflictError(
            f"durable workflow history for {entered_state.value} does not pin "
            f"{ref_key}={ref_value}; refusing to repair or duplicate it"
        )


def _map_selection(entry: dict[str, Any]) -> EvidenceSelection:
    """Bounded JSON command -> the EXISTING EvidenceSelection contract."""
    try:
        return EvidenceSelection(
            research_evidence_id=_parse_uuid(entry["research_evidence_id"]),
            role=EvidenceItemRole(str(entry["role"])),
            claim_cluster=str(entry["claim_cluster"]),
            display_note=(
                str(entry["display_note"]) if entry.get("display_note") is not None else None
            ),
        )
    except (KeyError, ValueError, TypeError):
        raise InvalidPipelineInputError(
            "an evidence selection command entry is malformed"
        ) from None


def _map_contradiction(entry: dict[str, Any]) -> ContradictionDeclaration:
    try:
        return ContradictionDeclaration(
            claim_key=str(entry["claim_key"]),
            evidence_side_a=tuple(_parse_uuid(v) for v in entry["evidence_side_a"]),
            evidence_side_b=tuple(_parse_uuid(v) for v in entry["evidence_side_b"]),
            nature=str(entry["nature"]),
            severity=ContradictionSeverity(str(entry["severity"])),
            handling_recommendation=(
                str(entry["handling_recommendation"])
                if entry.get("handling_recommendation") is not None
                else None
            ),
        )
    except (KeyError, ValueError, TypeError):
        raise InvalidPipelineInputError(
            "a contradiction declaration command entry is malformed"
        ) from None


def _summary(task: Any, status: str, **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": status, "next_task": None}
    payload.update(fields)
    _logger.info(
        "editorial_task_completed",
        task=str(task.name),
        retries=int(task.request.retries),
        **payload,
    )
    return payload
