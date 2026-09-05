"""The autopilot runner (ADR 0012): snapshot the durable facts, ask the
planner, perform ONE action.

Acceptances (commission, select idea, accept brief/review, rework routing,
assemble, schedule) go through the SAME domain services the operator's
buttons use, with the accountable operator recorded as actor and an
`autopilot` marker on the workflow event's artifact refs. Production steps
are enqueued as the existing editorial tasks — the autopilot never
re-implements any stage. Every outcome is written to the trail."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contentos.auth.models import User
from contentos.autopilot.enums import AutopilotEventKind, AutopilotMode
from contentos.autopilot.planner import (
    ACTION_ACCEPT_BRIEF,
    ACTION_ACCEPT_REVIEW,
    ACTION_ANALYZE_INTENT,
    ACTION_ASSEMBLE_PACKAGE,
    ACTION_BUILD_PACK,
    ACTION_COMMISSION,
    ACTION_COMPOSE_BRIEF,
    ACTION_GENERATE_DRAFT,
    ACTION_GENERATE_IDEAS,
    ACTION_GENERATE_IMAGE,
    ACTION_GENERATE_REVIEW,
    ACTION_PUBLISH,
    ACTION_REQUEST_REWORK,
    ACTION_RESOLVE_CHANGES,
    ACTION_RUN_QA,
    ACTION_SCHEDULE,
    ACTION_SELECT_IDEA,
    Action,
    Snapshot,
    plan,
)
from contentos.autopilot.service import AutopilotService
from contentos.briefs.repository import BriefRepository
from contentos.briefs.service import BriefService
from contentos.drafts.repository import DraftRepository
from contentos.evidence_packs.enums import EvidenceItemRole
from contentos.evidence_packs.repository import EvidencePackRepository
from contentos.evidence_packs.service import EvidencePackService
from contentos.ideas.enums import OriginalityStatus
from contentos.ideas.repository import IdeaRepository
from contentos.ideas.service import IdeaService
from contentos.media.service import MediaService
from contentos.media.store import MediaStore
from contentos.opportunities.repository import OpportunityRepository
from contentos.opportunities.service import (
    OpportunityCommissioningService,
    commissioning_admits,
)
from contentos.publishing.assembler import PublicationAssembler
from contentos.publishing.models import PublicationPackage
from contentos.publishing.service import PublishingService
from contentos.qa.repository import QaRepository
from contentos.research.enums import VerificationStatus
from contentos.reviews.enums import ReviewVerdict
from contentos.reviews.repository import ReviewRepository
from contentos.search_intent.repository import SearchIntentRepository
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState
from contentos.workflow.models import EditorialWorkflowEvent, EditorialWorkItem
from contentos.workflow.repository import WorkflowRepository
from contentos.workflow.service import WorkflowService

# Task names live in the worker module; the runner only needs the strings.
TASK_BY_ACTION: dict[str, str] = {
    ACTION_GENERATE_IDEAS: "contentos.editorial.generate_idea_candidates",
    ACTION_BUILD_PACK: "contentos.editorial.build_evidence_pack",
    ACTION_ANALYZE_INTENT: "contentos.editorial.analyze_search_intent",
    ACTION_COMPOSE_BRIEF: "contentos.editorial.compose_content_brief",
    ACTION_GENERATE_DRAFT: "contentos.editorial.generate_writer_draft",
    ACTION_GENERATE_REVIEW: "contentos.editorial.generate_editor_review",
    ACTION_RUN_QA: "contentos.editorial.run_qa_gates",
    ACTION_GENERATE_IMAGE: "contentos.editorial.generate_media_image",
    ACTION_PUBLISH: "contentos.editorial.publish_package",
}

# States in which the autopilot may have something to do (the sweep scope).
ACTIONABLE_STATES = (
    WorkflowState.IDEA_SCORING,
    WorkflowState.EVIDENCE_BUILDING,
    WorkflowState.SEO_RESEARCH,
    WorkflowState.BRIEFING,
    WorkflowState.DRAFTING,
    WorkflowState.EDITING,
    WorkflowState.CHANGES_REQUESTED,
    WorkflowState.QA_REVIEW,
    WorkflowState.APPROVED,
    WorkflowState.SCHEDULED,
)

AUTOPILOT_REASON_PREFIX = "otopilot"
MAX_AUTO_SELECTIONS = 200

Enqueuer = Callable[[str, dict[str, Any]], None]

_ORIGINALITY_RANK = {
    OriginalityStatus.PASSED: 0,
    OriginalityStatus.NOT_CHECKABLE: 1,
    OriginalityStatus.FAILED: 2,
}


@dataclass(frozen=True, slots=True)
class StepOutcome:
    work_item_id: uuid.UUID
    mode: AutopilotMode
    action: Action
    performed: bool
    detail: dict[str, Any]


class AutopilotRunner:
    def __init__(
        self,
        session: Session,
        *,
        media_store: MediaStore | None = None,
        enqueue: Enqueuer | None = None,
        request_id: str | None = None,
    ) -> None:
        self._session = session
        self._media_store = media_store
        self._enqueue = enqueue
        self._request_id = request_id
        self._autopilot = AutopilotService(session)

    # --- sweep scope ----------------------------------------------------------

    def actionable_work_item_ids(self, limit: int = 200) -> list[uuid.UUID]:
        return list(
            self._session.scalars(
                select(EditorialWorkItem.id)
                .where(EditorialWorkItem.current_state.in_(ACTIONABLE_STATES))
                .order_by(EditorialWorkItem.current_state_entered_at)
                .limit(limit)
            )
        )

    # --- snapshot -------------------------------------------------------------

    def snapshot(self, work_item: EditorialWorkItem) -> Snapshot:
        opportunities = OpportunityRepository(self._session)
        opportunity = opportunities.get_by_work_item_id(work_item.id)
        opportunity_id = opportunity.id if opportunity is not None else None
        disposition = opportunity.disposition if opportunity is not None else None
        score = opportunities.get_effective_score(opportunity.id) if opportunity else None
        eligible = commissioning_admits(
            disposition=disposition,
            work_item_state=work_item.current_state,
            score_eligibility=score.eligibility if score is not None else None,
        )

        idea_count = 0
        selected_idea_id: uuid.UUID | None = None
        best_idea_id: uuid.UUID | None = None
        latest_pack_id = None
        latest_pack_sufficiency = None
        eligible_evidence_count = 0
        intent_analysis_id: uuid.UUID | None = None
        if opportunity is not None:
            ideas = IdeaRepository(self._session).list_ideas(opportunity.id)
            idea_count = len(ideas)
            selected = IdeaService(self._session).get_effective_selection(opportunity.id)
            selected_idea_id = selected.id if selected is not None else None
            if ideas:
                ranked = sorted(
                    ideas,
                    key=lambda idea: (
                        _ORIGINALITY_RANK.get(idea.originality_status, 9),
                        idea.created_at,
                    ),
                )
                best_idea_id = ranked[0].id
            pack = EvidencePackRepository(self._session).get_latest_pack(opportunity.id)
            if pack is not None:
                latest_pack_id = pack.id
                latest_pack_sufficiency = pack.sufficiency
            eligible_evidence_count = len(
                EvidencePackService(self._session).list_eligible_evidence(opportunity.id)
            )
            if selected_idea_id is not None:
                analyses = SearchIntentRepository(self._session).list_by_idea(selected_idea_id)
                if analyses:
                    intent_analysis_id = analyses[-1].id

        briefs = BriefRepository(self._session)
        brief_rows = briefs.list_by_work_item(work_item.id)
        latest_brief = max(brief_rows, key=lambda row: row.version) if brief_rows else None
        active_brief = briefs.get_active_brief(work_item.id)
        # In DRAFTING the accepted brief is the one that matters.
        brief_for_stage = active_brief or latest_brief

        active_draft = DraftRepository(self._session).get_active_draft(work_item.id)
        active_review = ReviewRepository(self._session).get_active_review(work_item.id)
        rework_cycles = int(
            self._session.scalar(
                select(func.count())
                .select_from(EditorialWorkflowEvent)
                .where(
                    EditorialWorkflowEvent.work_item_id == work_item.id,
                    EditorialWorkflowEvent.to_state == WorkflowState.CHANGES_REQUESTED,
                )
            )
            or 0
        )
        active_qa = QaRepository(self._session).get_active_report(work_item.id)
        open_needs: tuple[int, ...] = ()
        if self._media_store is not None and work_item.current_state is WorkflowState.QA_REVIEW:
            coverage = MediaService(self._session, self._media_store).needs_coverage(work_item.id)
            if coverage:
                open_needs = tuple(
                    entry.need_index for entry in coverage if entry.satisfaction is None
                )
        latest_package = self._session.scalar(
            select(PublicationPackage)
            .where(PublicationPackage.work_item_id == work_item.id)
            .order_by(PublicationPackage.version.desc())
            .limit(1)
        )
        return Snapshot(
            work_item_id=work_item.id,
            state=work_item.current_state,
            opportunity_id=opportunity_id,
            disposition=disposition,
            commission_eligible=eligible,
            idea_count=idea_count,
            selected_idea_id=selected_idea_id,
            best_idea_id=best_idea_id,
            latest_pack_id=latest_pack_id,
            latest_pack_sufficiency=latest_pack_sufficiency,
            eligible_evidence_count=eligible_evidence_count,
            intent_analysis_id=intent_analysis_id,
            latest_brief_id=brief_for_stage.id if brief_for_stage is not None else None,
            latest_brief_status=brief_for_stage.status if brief_for_stage is not None else None,
            active_draft_id=active_draft.id if active_draft is not None else None,
            active_review_id=active_review.id if active_review is not None else None,
            active_review_verdict=active_review.verdict if active_review is not None else None,
            rework_cycles=rework_cycles,
            active_qa_outcome=active_qa.outcome if active_qa is not None else None,
            open_media_needs=open_needs,
            latest_package_id=latest_package.id if latest_package is not None else None,
            in_flight=self._autopilot.in_flight_actions(work_item.id),
        )

    # --- one step -------------------------------------------------------------

    def step(self, work_item_id: uuid.UUID) -> StepOutcome | None:
        """Plan and perform ONE action for one work item; commit is the
        caller's. Returns None when the work item does not exist."""
        state = self._autopilot.state()
        mode = state.mode
        work_item = WorkflowRepository(self._session).get_by_id(work_item_id)
        if work_item is None:
            return None
        snapshot = self.snapshot(work_item)
        action = plan(snapshot, mode)
        if action.kind == "none":
            return StepOutcome(work_item_id, mode, action, False, {})
        if action.is_wait:
            self._autopilot.record_wait_once(
                work_item_id=work_item_id, action=action.name, mode=mode, reason=action.reason
            )
            return StepOutcome(work_item_id, mode, action, False, {"reason": action.reason})
        try:
            detail = (
                self._perform_enqueue(action, state.actor_user_id)
                if action.kind == "enqueue"
                else self._perform_command(work_item, snapshot, action, state.actor_user_id)
            )
        except Exception as error:  # noqa: BLE001 - the trail must record it
            self._session.rollback()
            self._autopilot.record(
                AutopilotEventKind.ERROR,
                work_item_id=work_item_id,
                action=action.name,
                mode=mode,
                detail={"reason": action.reason, "error_type": type(error).__name__},
                request_id=self._request_id,
            )
            return StepOutcome(
                work_item_id, mode, action, False, {"error_type": type(error).__name__}
            )
        self._autopilot.record(
            AutopilotEventKind.ACTION,
            work_item_id=work_item_id,
            action=action.name,
            mode=mode,
            detail={"reason": action.reason, **detail},
            request_id=self._request_id,
        )
        return StepOutcome(work_item_id, mode, action, True, detail)

    # --- enqueue --------------------------------------------------------------

    def _perform_enqueue(self, action: Action, actor_user_id: uuid.UUID | None) -> dict[str, Any]:
        if self._enqueue is None:
            raise RuntimeError("no enqueuer configured for autopilot production steps")
        task_name = TASK_BY_ACTION[action.name]
        payload = dict(action.payload)
        if action.name == ACTION_BUILD_PACK:
            payload["selections"] = self._auto_selections(uuid.UUID(payload["opportunity_id"]))
        if action.name == ACTION_GENERATE_IMAGE:
            if actor_user_id is None:
                raise RuntimeError("image generation needs the accountable operator")
            payload["requested_by_user_id"] = str(actor_user_id)
        self._enqueue(task_name, payload)
        return {"task": task_name, "payload_keys": sorted(payload)}

    def _auto_selections(self, opportunity_id: uuid.UUID) -> list[dict[str, Any]]:
        """Every eligible evidence row, roles from verification status, one
        claim cluster per source document — bounded and deterministic."""
        rows = EvidencePackService(self._session).list_eligible_evidence(opportunity_id)
        selections: list[dict[str, Any]] = []
        for evidence in rows[:MAX_AUTO_SELECTIONS]:
            role = (
                EvidenceItemRole.KEY_FACT
                if evidence.verification_status is VerificationStatus.VERIFIED
                else EvidenceItemRole.SUPPORTING
            )
            selections.append(
                {
                    "research_evidence_id": str(evidence.id),
                    "role": role.value,
                    "claim_cluster": f"kaynak-{str(evidence.normalized_document_id)[:8]}",
                    "display_note": None,
                }
            )
        if not selections:
            raise RuntimeError("no eligible evidence to select")
        return selections

    # --- commands -------------------------------------------------------------

    def _perform_command(
        self,
        work_item: EditorialWorkItem,
        snapshot: Snapshot,
        action: Action,
        actor_user_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        reason = f"{AUTOPILOT_REASON_PREFIX}: {action.reason}"
        refs = {"autopilot": "true"}
        if action.name == ACTION_COMMISSION:
            result = OpportunityCommissioningService(self._session).commission_opportunity(
                uuid.UUID(action.payload["opportunity_id"]),
                reason=reason,
                request_id=self._request_id,
                actor_user_id=actor_user_id,
                extra_artifact_refs=refs,
            )
            return {"commissioned": result.commissioned}
        if action.name == ACTION_SELECT_IDEA:
            IdeaService(self._session).select_idea(
                uuid.UUID(action.payload["idea_id"]), reason=reason, request_id=self._request_id
            )
            return {"idea_id": action.payload["idea_id"]}
        if action.name == ACTION_ACCEPT_BRIEF:
            acceptance = BriefService(self._session).accept_for_drafting(
                uuid.UUID(action.payload["brief_id"]), reason=reason, request_id=self._request_id
            )
            return {"brief_id": action.payload["brief_id"], "accepted": acceptance.accepted}
        if action.name == ACTION_ACCEPT_REVIEW:
            return self._accept_review(work_item, reason, actor_user_id, refs)
        if action.name == ACTION_REQUEST_REWORK:
            return self._request_rework(work_item, reason, actor_user_id, refs)
        if action.name == ACTION_RESOLVE_CHANGES:
            item = WorkflowService(self._session).resolve_changes_requested(
                work_item.id, reason=reason, request_id=self._request_id
            )
            return {"state": item.current_state.value}
        if action.name == ACTION_ASSEMBLE_PACKAGE:
            user = self._require_actor(actor_user_id)
            assembly = PublicationAssembler(self._session).assemble(
                work_item.id, assembled_by=user, request_id=self._request_id
            )
            return {"package_id": str(assembly.package.id), "created": assembly.created}
        if action.name == ACTION_SCHEDULE:
            item = PublishingService(self._session).schedule_publication(
                work_item.id,
                uuid.UUID(action.payload["publication_package_id"]),
                reason=reason,
                actor_user_id=actor_user_id,
                request_id=self._request_id,
            )
            return {"state": item.current_state.value}
        raise RuntimeError(f"unknown autopilot command {action.name}")

    def _accept_review(
        self,
        work_item: EditorialWorkItem,
        reason: str,
        actor_user_id: uuid.UUID | None,
        refs: dict[str, str],
    ) -> dict[str, Any]:
        review = ReviewRepository(self._session).get_active_review(work_item.id)
        draft = DraftRepository(self._session).get_active_draft(work_item.id)
        if review is None or draft is None or review.content_draft_id != draft.id:
            raise RuntimeError("accepting requires an ACTIVE review over the ACTIVE draft")
        if review.verdict is not ReviewVerdict.PASS:
            raise RuntimeError("the ACTIVE review verdict is not pass")
        item = WorkflowService(self._session).transition(
            work_item.id,
            WorkflowState.QA_REVIEW,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason=reason,
            artifact_refs={
                **refs,
                "editorial_review_id": str(review.id),
                "content_draft_id": str(draft.id),
                "review_verdict": review.verdict.value,
                "content_hash": draft.content_hash,
            },
            request_id=self._request_id,
            actor_user_id=actor_user_id,
        )
        return {"state": item.current_state.value, "review_id": str(review.id)}

    def _request_rework(
        self,
        work_item: EditorialWorkItem,
        reason: str,
        actor_user_id: uuid.UUID | None,
        refs: dict[str, str],
    ) -> dict[str, Any]:
        draft = DraftRepository(self._session).get_active_draft(work_item.id)
        review = ReviewRepository(self._session).get_active_review(work_item.id)
        artifact_refs: dict[str, Any] = dict(refs)
        if draft is not None:
            artifact_refs.update(
                {
                    "content_draft_id": str(draft.id),
                    "draft_version": draft.version,
                    "content_brief_id": str(draft.content_brief_id),
                }
            )
        if review is not None:
            artifact_refs["editorial_review_id"] = str(review.id)
        workflow = WorkflowService(self._session)
        workflow.transition(
            work_item.id,
            WorkflowState.CHANGES_REQUESTED,
            actor_origin=WorkflowActorOrigin.OPERATOR,
            reason=reason,
            artifact_refs=artifact_refs,
            request_id=self._request_id,
            responsible_state=WorkflowState.DRAFTING,
            actor_user_id=actor_user_id,
        )
        item = workflow.resolve_changes_requested(
            work_item.id, reason=reason, request_id=self._request_id
        )
        return {"state": item.current_state.value}

    def _require_actor(self, actor_user_id: uuid.UUID | None) -> User:
        user = self._session.get(User, actor_user_id) if actor_user_id is not None else None
        if user is None or not user.is_active:
            raise RuntimeError("the autopilot's accountable operator is missing or inactive")
        return user
