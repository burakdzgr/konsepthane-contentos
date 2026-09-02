"""Bounded read models for internal Phase-3 editorial visibility.

Everything here is a read-only projection of durable PostgreSQL facts: no
function writes, flushes, commits, publishes to the queue, calls a provider,
or touches the network. The accepted observability rule is binding — every
surfaced score/idea/pack/analysis/brief carries its engine identity, exact
pinned inputs, missing signals, and decision trail, so a recommendation can
always explain itself.

Effective-artifact semantics reuse the domain's own rules, never a UI-only
invention:

- effective score: evaluated_at DESC, id DESC (OpportunityRepository.
  get_effective_score) — replicated as a window subquery for the list and
  marked explicitly on the detail;
- effective idea selection: the latest IdeaSelectionEvent in monotonic
  event-id order decides; a DESELECTED latest event means nothing is
  selected (IdeaService.get_effective_selection);
- latest pack/analysis: highest version, then created_at, then id;
- latest brief: highest version for the work item (status shown truthfully;
  an absent artifact is absent, never invented).

N+1 avoidance: the work-queue list is a small FIXED number of set-based
queries (page + count + one per latest-artifact projection over the page's
ids), so query count is independent of page size. The detail endpoint issues
a bounded fixed set of queries for one work item.

Deliberately never exposed: clean_text, raw payload bytes/references,
excerpts, whole article bodies, HTML, response headers, prompts, raw model
output, provider exception messages, and any URL/secret configuration.
Bounded ResearchEvidence statements are the one governed evidence artifact
the editorial boundary permits.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from contentos.ai.enums import GenerationPurpose, GenerationStatus
from contentos.ai.models import AiGenerationAttempt
from contentos.briefs.enums import BriefActorOrigin, BriefClaimKind, BriefStatus
from contentos.briefs.models import (
    BriefClaim,
    BriefClaimEvidence,
    BriefStatusEvent,
    ContentBrief,
)
from contentos.discovery.models import DiscoveryItem
from contentos.duplicates.enums import DuplicateDecisionOutcome
from contentos.duplicates.models import DuplicateDecision
from contentos.evidence_packs.enums import (
    ContradictionResolutionStatus,
    ContradictionResolver,
    ContradictionSeverity,
    EvidenceItemRole,
    EvidencePackSufficiency,
)
from contentos.evidence_packs.models import (
    EvidenceContradiction,
    EvidencePack,
    EvidencePackItem,
)
from contentos.evidence_packs.service import EvidencePackService
from contentos.fetching.snapshots import FetchSnapshot
from contentos.ideas.enums import (
    ContentType,
    IdeaOrigin,
    IdeaSelectionAction,
    IdeaSelectionActor,
    OriginalityStatus,
)
from contentos.ideas.models import Idea, IdeaSelectionEvent
from contentos.normalization.models import NormalizedDocument
from contentos.opportunities.enums import (
    ComponentAvailability,
    OpportunityActor,
    OpportunityDisposition,
    ResearchInputRole,
    ScoreBand,
    ScoreComponent,
    ScoreEligibility,
)
from contentos.opportunities.models import (
    EditorialOpportunity,
    OpportunityResearchInput,
    OpportunityScore,
    OpportunityScoreComponent,
)
from contentos.research.enums import EvidenceType, ExtractionMethod, VerificationStatus
from contentos.research.models import ResearchEvidence
from contentos.search_intent.enums import CannibalizationStatus
from contentos.search_intent.models import SearchIntentAnalysis
from contentos.signals.enums import SearchSignalType
from contentos.signals.models import SearchSignal
from contentos.sources.enums import TrustTier
from contentos.sources.models import Source
from contentos.workflow.enums import WorkflowActorOrigin, WorkflowState, WorkItemOrigin
from contentos.workflow.models import EditorialWorkflowEvent, EditorialWorkItem
from contentos.workflow.repository import WorkflowRepository

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 100
MAX_PAGE_OFFSET = 1_000_000
MAX_TEXT_SEARCH_LENGTH = 100

MAX_DETAIL_EVENTS = 50
MAX_DETAIL_SCORES = 10
MAX_DETAIL_IDEAS = 20
MAX_DETAIL_SELECTION_EVENTS = 20
MAX_DETAIL_PACKS = 5
MAX_DETAIL_ANALYSES = 5
MAX_DETAIL_BRIEFS = 5
MAX_STATEMENT_LENGTH = 500


class _FrozenModel(BaseModel):
    """Immutable read model; enums serialize to their stable persisted values."""

    model_config = ConfigDict(frozen=True)


# --- work queue --------------------------------------------------------------


class WorkQueueRow(_FrozenModel):
    work_item_id: uuid.UUID
    title_working_label: str
    locale: str
    market: str
    origin: WorkItemOrigin
    current_state: WorkflowState
    current_state_entered_at: datetime
    blocked_reason: str | None
    rejected_reason: str | None
    opportunity_id: uuid.UUID | None
    disposition: OpportunityDisposition | None
    topic_summary: str | None
    score_id: uuid.UUID | None
    score_band: ScoreBand | None
    score_eligibility: ScoreEligibility | None
    score_overall_value: float | None
    score_missing_signals: list[str]
    score_risk_flags: list[str]
    score_evaluated_at: datetime | None
    score_engine_name: str | None
    score_engine_version: str | None
    selected_idea_id: uuid.UUID | None
    selected_idea_title: str | None
    selected_idea_originality: OriginalityStatus | None
    latest_pack_id: uuid.UUID | None
    latest_pack_version: int | None
    latest_pack_sufficiency: EvidencePackSufficiency | None
    latest_analysis_id: uuid.UUID | None
    latest_analysis_version: int | None
    latest_brief_id: uuid.UUID | None
    latest_brief_version: int | None
    latest_brief_status: BriefStatus | None


class WorkQueuePage(_FrozenModel):
    items: list[WorkQueueRow]
    total: int
    limit: int
    offset: int


# --- detail ------------------------------------------------------------------


class WorkItemProjection(_FrozenModel):
    id: uuid.UUID
    locale: str
    market: str
    origin: WorkItemOrigin
    current_state: WorkflowState
    current_state_entered_at: datetime
    title_working_label: str
    blocked_reason: str | None
    blocked_resume_state: WorkflowState | None
    rejected_reason: str | None
    created_at: datetime
    updated_at: datetime


class WorkflowEventView(_FrozenModel):
    id: int
    from_state: WorkflowState | None
    to_state: WorkflowState
    actor_origin: WorkflowActorOrigin
    reason: str
    artifact_refs: dict[str, Any]
    request_id: str | None
    # The named authenticated human (Phase 5); None renders as UNKNOWN —
    # historical rows and system-internal transitions carry no identity.
    actor_user_id: uuid.UUID | None
    actor_display_name: str | None
    occurred_at: datetime


class OpportunityView(_FrozenModel):
    id: uuid.UUID
    disposition: OpportunityDisposition
    disposition_reason: str | None
    disposition_by: OpportunityActor | None
    disposition_at: datetime | None
    topic_summary: str
    update_of_reference: str | None
    promotion_root_document_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ResearchInputView(_FrozenModel):
    id: uuid.UUID
    normalized_document_id: uuid.UUID
    duplicate_decision_id: uuid.UUID
    duplicate_outcome: DuplicateDecisionOutcome | None
    role: ResearchInputRole
    added_by: OpportunityActor
    note: str | None
    added_at: datetime
    document_title: str | None
    external_published_at: datetime | None
    fetched_at: datetime | None
    source_id: uuid.UUID | None
    source_slug: str | None
    source_name: str | None
    trust_tier: TrustTier | None


class ScoreComponentView(_FrozenModel):
    component: ScoreComponent
    availability: ComponentAvailability
    value: float | None
    confidence: float | None
    provider: str | None
    observed_at: datetime | None
    provenance_ref: dict[str, Any]


class ScoreView(_FrozenModel):
    id: uuid.UUID
    engine_name: str
    engine_version: str
    overall_band: ScoreBand
    overall_value: float | None
    eligibility: ScoreEligibility
    missing_signals: list[str]
    risk_flags: list[str]
    weights_snapshot: dict[str, Any]
    threshold_snapshot: dict[str, Any]
    input_snapshot: dict[str, Any]
    evaluated_at: datetime
    created_at: datetime
    effective: bool
    components: list[ScoreComponentView]


class IdeaView(_FrozenModel):
    id: uuid.UUID
    logical_idea_id: uuid.UUID
    version: int
    working_title: str
    angle: str
    audience: str
    value_proposition: str
    content_type: ContentType
    locale: str
    market: str
    rationale: str
    exclusions: list[str]
    planning_dimensions: dict[str, Any]
    originality_status: OriginalityStatus
    originality_detail: dict[str, Any]
    originality_policy_snapshot: dict[str, Any]
    origin: IdeaOrigin
    generation_attempt_id: uuid.UUID | None
    created_at: datetime
    effective_selected: bool


class SelectionEventView(_FrozenModel):
    id: int
    idea_id: uuid.UUID
    action: IdeaSelectionAction
    actor_origin: IdeaSelectionActor
    reason: str
    request_id: str | None
    occurred_at: datetime


class PackItemView(_FrozenModel):
    id: uuid.UUID
    research_evidence_id: uuid.UUID
    role: EvidenceItemRole
    claim_cluster: str
    display_note: str | None
    evidence_type: EvidenceType | None
    verification_status: VerificationStatus | None
    statement: str | None
    normalized_document_id: uuid.UUID | None
    source_id: uuid.UUID | None
    source_slug: str | None
    trust_tier: TrustTier | None
    extracted_at: datetime | None


class ContradictionView(_FrozenModel):
    id: uuid.UUID
    pack_id: uuid.UUID
    claim_key: str
    evidence_side_a: list[str]
    evidence_side_b: list[str]
    nature: str
    severity: ContradictionSeverity
    resolution_status: ContradictionResolutionStatus
    handling_recommendation: str | None
    resolution_reason: str | None
    resolved_by: ContradictionResolver | None
    resolved_at: datetime | None


class PackView(_FrozenModel):
    id: uuid.UUID
    version: int
    idea_id: uuid.UUID | None
    organization_attempt_id: uuid.UUID | None
    assembler_name: str
    assembler_version: str
    sufficiency: EvidencePackSufficiency
    sufficiency_detail: dict[str, Any]
    source_diversity: dict[str, Any]
    staleness_notes: list[dict[str, Any]]
    locale_limitations: dict[str, Any]
    licensing_cautions: list[dict[str, Any]]
    policy_snapshot: dict[str, Any]
    assembly_input_hash: str
    created_at: datetime
    items: list[PackItemView]
    contradictions: list[ContradictionView]


class KnownSignalView(_FrozenModel):
    id: uuid.UUID
    signal_type: SearchSignalType
    provider: str
    subject: str
    observed_at: datetime
    as_of: datetime | None
    recorded_at: datetime


class IntentAnalysisView(_FrozenModel):
    id: uuid.UUID
    version: int
    idea_id: uuid.UUID
    primary_intent: str
    secondary_intents: list[str]
    target_audience: str
    query_concepts: list[str]
    page_purpose: str
    likely_format: str
    known_signal_refs: list[dict[str, Any]]
    known_signals: list[KnownSignalView]
    missing_signals: list[str]
    cannibalization_status: CannibalizationStatus
    cannibalization_basis: dict[str, Any]
    related_references: list[dict[str, Any]]
    locale: str
    market: str
    engine_name: str
    engine_version: str
    synthesis_attempt_id: uuid.UUID | None
    created_at: datetime


class BriefClaimView(_FrozenModel):
    id: uuid.UUID
    claim_key: str
    claim_text: str
    claim_kind: BriefClaimKind
    handling: str | None
    evidence_ids: list[uuid.UUID]


class BriefStatusEventView(_FrozenModel):
    id: int
    from_status: BriefStatus
    to_status: BriefStatus
    actor_origin: BriefActorOrigin
    reason: str
    request_id: str | None
    replacement_brief_id: uuid.UUID | None
    occurred_at: datetime


class BriefView(_FrozenModel):
    id: uuid.UUID
    version: int
    idea_id: uuid.UUID
    evidence_pack_id: uuid.UUID
    search_intent_analysis_id: uuid.UUID
    locale: str
    market: str
    target_audience: str
    intent_summary: str
    original_angle: str
    title_guidance: dict[str, Any]
    content_objective: str
    required_sections: list[dict[str, Any]]
    optional_sections: list[dict[str, Any]]
    practical_requirements: dict[str, Any]
    exclusions: list[str]
    uncertainty_notes: list[str]
    internal_link_needs: list[dict[str, Any]]
    media_needs: list[dict[str, Any]]
    faq_questions: list[str]
    acceptance_criteria: list[dict[str, Any]]
    structure_guard_result: dict[str, Any]
    structure_policy_snapshot: dict[str, Any]
    status: BriefStatus
    composition_attempt_id: uuid.UUID | None
    engine_name: str
    engine_version: str
    content_hash: str
    created_at: datetime
    claims: list[BriefClaimView]
    status_events: list[BriefStatusEventView]


class AiAttemptView(_FrozenModel):
    id: uuid.UUID
    purpose: GenerationPurpose
    provider: str
    model_name: str
    model_version: str | None
    schema_name: str
    schema_version: str
    template_name: str
    template_version: str
    input_hash: str
    input_refs: dict[str, Any]
    status: GenerationStatus
    error_class: str | None
    retry_number: int
    usage: dict[str, Any]
    created_at: datetime


class WorkItemDetail(_FrozenModel):
    work_item: WorkItemProjection
    workflow_events: list[WorkflowEventView]
    total_workflow_events: int
    workflow_events_truncated: bool
    opportunity: OpportunityView | None
    research_inputs: list[ResearchInputView]
    scores: list[ScoreView]
    total_scores: int
    scores_truncated: bool
    ideas: list[IdeaView]
    total_ideas: int
    ideas_truncated: bool
    selection_events: list[SelectionEventView]
    total_selection_events: int
    selection_events_truncated: bool
    effective_selected_idea_id: uuid.UUID | None
    evidence_packs: list[PackView]
    total_evidence_packs: int
    evidence_packs_truncated: bool
    intent_analyses: list[IntentAnalysisView]
    total_intent_analyses: int
    intent_analyses_truncated: bool
    briefs: list[BriefView]
    total_briefs: int
    briefs_truncated: bool
    ai_attempts: list[AiAttemptView]


class EligibleEvidenceView(_FrozenModel):
    id: uuid.UUID
    evidence_type: EvidenceType
    verification_status: VerificationStatus
    statement: str
    extraction_method: ExtractionMethod
    confidence: float | None
    licensing_notes: str | None
    normalized_document_id: uuid.UUID
    source_id: uuid.UUID
    source_slug: str | None
    source_name: str | None
    trust_tier: TrustTier | None
    fetched_at: datetime
    extracted_at: datetime


class EligibleEvidencePage(_FrozenModel):
    items: list[EligibleEvidenceView]
    total: int
    limit: int
    offset: int


# --- work queue query --------------------------------------------------------


def _effective_score_subquery() -> Any:
    """Replicates OpportunityRepository.get_effective_score's ordering."""
    ranked = select(
        OpportunityScore.id.label("score_id"),
        OpportunityScore.opportunity_id.label("opportunity_id"),
        OpportunityScore.overall_band.label("overall_band"),
        OpportunityScore.eligibility.label("eligibility"),
        OpportunityScore.overall_value.label("overall_value"),
        OpportunityScore.missing_signals.label("missing_signals"),
        OpportunityScore.risk_flags.label("risk_flags"),
        OpportunityScore.evaluated_at.label("evaluated_at"),
        OpportunityScore.engine_name.label("engine_name"),
        OpportunityScore.engine_version.label("engine_version"),
        func.row_number()
        .over(
            partition_by=OpportunityScore.opportunity_id,
            order_by=(OpportunityScore.evaluated_at.desc(), OpportunityScore.id.desc()),
        )
        .label("rn"),
    ).subquery()
    return select(ranked).where(ranked.c.rn == 1).subquery()


def _latest_selection_subquery() -> Any:
    """The latest selection event decides (IdeaService.get_effective_selection)."""
    ranked = select(
        IdeaSelectionEvent.opportunity_id.label("opportunity_id"),
        IdeaSelectionEvent.idea_id.label("idea_id"),
        IdeaSelectionEvent.action.label("action"),
        func.row_number()
        .over(
            partition_by=IdeaSelectionEvent.opportunity_id,
            order_by=IdeaSelectionEvent.id.desc(),
        )
        .label("rn"),
    ).subquery()
    return select(ranked).where(ranked.c.rn == 1).subquery()


def _latest_pack_subquery() -> Any:
    ranked = select(
        EvidencePack.opportunity_id.label("opportunity_id"),
        EvidencePack.id.label("pack_id"),
        EvidencePack.version.label("version"),
        EvidencePack.sufficiency.label("sufficiency"),
        func.row_number()
        .over(
            partition_by=EvidencePack.opportunity_id,
            order_by=(
                EvidencePack.version.desc(),
                EvidencePack.created_at.desc(),
                EvidencePack.id.desc(),
            ),
        )
        .label("rn"),
    ).subquery()
    return select(ranked).where(ranked.c.rn == 1).subquery()


def _latest_analysis_subquery() -> Any:
    ranked = select(
        SearchIntentAnalysis.opportunity_id.label("opportunity_id"),
        SearchIntentAnalysis.id.label("analysis_id"),
        SearchIntentAnalysis.version.label("version"),
        func.row_number()
        .over(
            partition_by=SearchIntentAnalysis.opportunity_id,
            order_by=(
                SearchIntentAnalysis.version.desc(),
                SearchIntentAnalysis.created_at.desc(),
                SearchIntentAnalysis.id.desc(),
            ),
        )
        .label("rn"),
    ).subquery()
    return select(ranked).where(ranked.c.rn == 1).subquery()


def _latest_brief_subquery() -> Any:
    ranked = select(
        ContentBrief.work_item_id.label("work_item_id"),
        ContentBrief.id.label("brief_id"),
        ContentBrief.version.label("version"),
        ContentBrief.status.label("status"),
        func.row_number()
        .over(
            partition_by=ContentBrief.work_item_id,
            order_by=(
                ContentBrief.version.desc(),
                ContentBrief.created_at.desc(),
                ContentBrief.id.desc(),
            ),
        )
        .label("rn"),
    ).subquery()
    return select(ranked).where(ranked.c.rn == 1).subquery()


def list_work_items(
    session: Session,
    *,
    workflow_state: WorkflowState | None = None,
    opportunity_disposition: OpportunityDisposition | None = None,
    locale: str | None = None,
    market: str | None = None,
    blocked: bool | None = None,
    search: str | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    offset: int = 0,
) -> WorkQueuePage:
    """One projected page + one count + five latest-artifact set queries.

    Ordering (reported, operator-urgency stable):
    current_state_entered_at DESC, created_at DESC, id.
    """
    effective_score = _effective_score_subquery()
    latest_selection = _latest_selection_subquery()
    latest_pack = _latest_pack_subquery()
    latest_analysis = _latest_analysis_subquery()
    latest_brief = _latest_brief_subquery()

    filters = []
    if workflow_state is not None:
        filters.append(EditorialWorkItem.current_state == workflow_state)
    if opportunity_disposition is not None:
        filters.append(EditorialOpportunity.disposition == opportunity_disposition)
    if locale is not None:
        filters.append(EditorialWorkItem.locale == locale)
    if market is not None:
        filters.append(EditorialWorkItem.market == market)
    if blocked is True:
        filters.append(EditorialWorkItem.current_state == WorkflowState.BLOCKED)
    elif blocked is False:
        filters.append(EditorialWorkItem.current_state != WorkflowState.BLOCKED)
    if search is not None:
        term = search[:MAX_TEXT_SEARCH_LENGTH]
        filters.append(
            EditorialWorkItem.title_working_label.icontains(term, autoescape=True)
            | EditorialOpportunity.topic_summary.icontains(term, autoescape=True)
        )

    def joined(statement: Select[Any]) -> Select[Any]:
        return statement.outerjoin(
            EditorialOpportunity,
            EditorialOpportunity.work_item_id == EditorialWorkItem.id,
        ).where(*filters)

    statement = (
        joined(
            select(
                EditorialWorkItem,
                EditorialOpportunity,
                effective_score.c.score_id,
                effective_score.c.overall_band,
                effective_score.c.eligibility,
                effective_score.c.overall_value,
                effective_score.c.missing_signals,
                effective_score.c.risk_flags,
                effective_score.c.evaluated_at,
                effective_score.c.engine_name,
                effective_score.c.engine_version,
                latest_selection.c.idea_id,
                latest_selection.c.action,
                Idea.working_title,
                Idea.originality_status,
                latest_pack.c.pack_id,
                latest_pack.c.version,
                latest_pack.c.sufficiency,
                latest_analysis.c.analysis_id,
                latest_analysis.c.version,
                latest_brief.c.brief_id,
                latest_brief.c.version,
                latest_brief.c.status,
            )
        )
        .outerjoin(
            effective_score,
            effective_score.c.opportunity_id == EditorialOpportunity.id,
        )
        .outerjoin(
            latest_selection,
            latest_selection.c.opportunity_id == EditorialOpportunity.id,
        )
        .outerjoin(Idea, Idea.id == latest_selection.c.idea_id)
        .outerjoin(latest_pack, latest_pack.c.opportunity_id == EditorialOpportunity.id)
        .outerjoin(
            latest_analysis,
            latest_analysis.c.opportunity_id == EditorialOpportunity.id,
        )
        .outerjoin(latest_brief, latest_brief.c.work_item_id == EditorialWorkItem.id)
        .order_by(
            EditorialWorkItem.current_state_entered_at.desc(),
            EditorialWorkItem.created_at.desc(),
            EditorialWorkItem.id,
        )
        .limit(limit)
        .offset(offset)
    )
    total = (
        session.scalar(
            select(func.count()).select_from(joined(select(EditorialWorkItem.id)).subquery())
        )
        or 0
    )

    items: list[WorkQueueRow] = []
    for row in session.execute(statement):
        (
            item,
            opportunity,
            score_id,
            score_band,
            score_eligibility,
            score_overall_value,
            score_missing_signals,
            score_risk_flags,
            score_evaluated_at,
            score_engine_name,
            score_engine_version,
            selection_idea_id,
            selection_action,
            selected_title,
            selected_originality,
            pack_id,
            pack_version,
            pack_sufficiency,
            analysis_id,
            analysis_version,
            brief_id,
            brief_version,
            brief_status,
        ) = row
        selected = selection_action is IdeaSelectionAction.SELECTED
        items.append(
            WorkQueueRow(
                work_item_id=item.id,
                title_working_label=item.title_working_label,
                locale=item.locale,
                market=item.market,
                origin=item.origin,
                current_state=item.current_state,
                current_state_entered_at=item.current_state_entered_at,
                blocked_reason=item.blocked_reason,
                rejected_reason=item.rejected_reason,
                opportunity_id=opportunity.id if opportunity else None,
                disposition=opportunity.disposition if opportunity else None,
                topic_summary=opportunity.topic_summary if opportunity else None,
                score_id=score_id,
                score_band=score_band,
                score_eligibility=score_eligibility,
                score_overall_value=score_overall_value,
                score_missing_signals=list(score_missing_signals or []),
                score_risk_flags=list(score_risk_flags or []),
                score_evaluated_at=score_evaluated_at,
                score_engine_name=score_engine_name,
                score_engine_version=score_engine_version,
                selected_idea_id=selection_idea_id if selected else None,
                selected_idea_title=selected_title if selected else None,
                selected_idea_originality=selected_originality if selected else None,
                latest_pack_id=pack_id,
                latest_pack_version=pack_version,
                latest_pack_sufficiency=pack_sufficiency,
                latest_analysis_id=analysis_id,
                latest_analysis_version=analysis_version,
                latest_brief_id=brief_id,
                latest_brief_version=brief_version,
                latest_brief_status=brief_status,
            )
        )
    return WorkQueuePage(items=items, total=int(total), limit=limit, offset=offset)


# --- detail query ------------------------------------------------------------


def get_work_item_detail(session: Session, work_item_id: uuid.UUID) -> WorkItemDetail | None:
    """Bounded fixed set of queries for one work item; None when missing."""
    item = session.get(EditorialWorkItem, work_item_id)
    if item is None:
        return None

    blocked_resume_state: WorkflowState | None = None
    if item.current_state is WorkflowState.BLOCKED:
        entry = WorkflowRepository(session).get_latest_entry_event(item.id, WorkflowState.BLOCKED)
        blocked_resume_state = entry.from_state if entry is not None else None

    events = list(
        session.execute(
            select(EditorialWorkflowEvent)
            .where(EditorialWorkflowEvent.work_item_id == item.id)
            .order_by(EditorialWorkflowEvent.id.desc())
            .limit(MAX_DETAIL_EVENTS)
        ).scalars()
    )
    total_events = int(
        session.scalar(
            select(func.count())
            .select_from(EditorialWorkflowEvent)
            .where(EditorialWorkflowEvent.work_item_id == item.id)
        )
        or 0
    )
    # Resolve named actors to display names (identity only, never
    # credential material).
    from contentos.auth.models import User as _User

    actor_ids = {event.actor_user_id for event in events if event.actor_user_id is not None}
    actor_names: dict[uuid.UUID | None, str] = {}
    if actor_ids:
        for user in session.execute(select(_User).where(_User.id.in_(actor_ids))).scalars():
            actor_names[user.id] = user.display_name

    opportunity = session.execute(
        select(EditorialOpportunity).where(EditorialOpportunity.work_item_id == item.id)
    ).scalar_one_or_none()

    research_inputs: list[ResearchInputView] = []
    scores: list[ScoreView] = []
    total_scores = 0
    ideas: list[IdeaView] = []
    total_ideas = 0
    selection_events: list[SelectionEventView] = []
    total_selection_events = 0
    effective_selected_idea_id: uuid.UUID | None = None
    packs: list[PackView] = []
    total_packs = 0
    analyses: list[IntentAnalysisView] = []
    total_analyses = 0
    attempt_ids: set[uuid.UUID] = set()

    if opportunity is not None:
        research_inputs = _research_input_views(session, opportunity.id)
        scores, total_scores = _score_views(session, opportunity.id)
        (
            ideas,
            total_ideas,
            selection_events,
            total_selection_events,
            effective_selected_idea_id,
        ) = _idea_views(session, opportunity.id)
        packs, total_packs = _pack_views(session, opportunity.id)
        analyses, total_analyses = _analysis_views(session, opportunity.id)
        attempt_ids.update(
            idea.generation_attempt_id for idea in ideas if idea.generation_attempt_id
        )
        attempt_ids.update(
            pack.organization_attempt_id for pack in packs if pack.organization_attempt_id
        )
        attempt_ids.update(
            analysis.synthesis_attempt_id for analysis in analyses if analysis.synthesis_attempt_id
        )

    briefs, total_briefs = _brief_views(session, item.id)
    attempt_ids.update(
        brief.composition_attempt_id for brief in briefs if brief.composition_attempt_id
    )

    attempts = _attempt_views(session, attempt_ids)

    return WorkItemDetail(
        work_item=WorkItemProjection(
            id=item.id,
            locale=item.locale,
            market=item.market,
            origin=item.origin,
            current_state=item.current_state,
            current_state_entered_at=item.current_state_entered_at,
            title_working_label=item.title_working_label,
            blocked_reason=item.blocked_reason,
            blocked_resume_state=blocked_resume_state,
            rejected_reason=item.rejected_reason,
            created_at=item.created_at,
            updated_at=item.updated_at,
        ),
        workflow_events=[
            WorkflowEventView(
                id=event.id,
                from_state=event.from_state,
                to_state=event.to_state,
                actor_origin=event.actor_origin,
                reason=event.reason,
                artifact_refs=event.artifact_refs,
                request_id=event.request_id,
                actor_user_id=event.actor_user_id,
                actor_display_name=actor_names.get(event.actor_user_id),
                occurred_at=event.occurred_at,
            )
            for event in events
        ],
        total_workflow_events=total_events,
        workflow_events_truncated=total_events > len(events),
        opportunity=(
            OpportunityView(
                id=opportunity.id,
                disposition=opportunity.disposition,
                disposition_reason=opportunity.disposition_reason,
                disposition_by=opportunity.disposition_by,
                disposition_at=opportunity.disposition_at,
                topic_summary=opportunity.topic_summary,
                update_of_reference=opportunity.update_of_reference,
                promotion_root_document_id=opportunity.promotion_root_document_id,
                created_at=opportunity.created_at,
                updated_at=opportunity.updated_at,
            )
            if opportunity is not None
            else None
        ),
        research_inputs=research_inputs,
        scores=scores,
        total_scores=total_scores,
        scores_truncated=total_scores > len(scores),
        ideas=ideas,
        total_ideas=total_ideas,
        ideas_truncated=total_ideas > len(ideas),
        selection_events=selection_events,
        total_selection_events=total_selection_events,
        selection_events_truncated=total_selection_events > len(selection_events),
        effective_selected_idea_id=effective_selected_idea_id,
        evidence_packs=packs,
        total_evidence_packs=total_packs,
        evidence_packs_truncated=total_packs > len(packs),
        intent_analyses=analyses,
        total_intent_analyses=total_analyses,
        intent_analyses_truncated=total_analyses > len(analyses),
        briefs=briefs,
        total_briefs=total_briefs,
        briefs_truncated=total_briefs > len(briefs),
        ai_attempts=attempts,
    )


def _research_input_views(session: Session, opportunity_id: uuid.UUID) -> list[ResearchInputView]:
    rows = session.execute(
        select(
            OpportunityResearchInput,
            DuplicateDecision.decision,
            NormalizedDocument.title,
            NormalizedDocument.external_published_at,
            FetchSnapshot.fetched_at,
            Source.id,
            Source.slug,
            Source.name,
            Source.trust_tier,
        )
        .outerjoin(
            DuplicateDecision,
            DuplicateDecision.id == OpportunityResearchInput.duplicate_decision_id,
        )
        .outerjoin(
            NormalizedDocument,
            NormalizedDocument.id == OpportunityResearchInput.normalized_document_id,
        )
        .outerjoin(FetchSnapshot, FetchSnapshot.id == NormalizedDocument.fetch_snapshot_id)
        .outerjoin(DiscoveryItem, DiscoveryItem.id == FetchSnapshot.discovery_item_id)
        .outerjoin(Source, Source.id == DiscoveryItem.source_id)
        .where(OpportunityResearchInput.opportunity_id == opportunity_id)
        .order_by(OpportunityResearchInput.added_at, OpportunityResearchInput.id)
    ).all()
    return [
        ResearchInputView(
            id=research_input.id,
            normalized_document_id=research_input.normalized_document_id,
            duplicate_decision_id=research_input.duplicate_decision_id,
            duplicate_outcome=outcome,
            role=research_input.role,
            added_by=research_input.added_by,
            note=research_input.note,
            added_at=research_input.added_at,
            document_title=title,
            external_published_at=published_at,
            fetched_at=fetched_at,
            source_id=source_id,
            source_slug=source_slug,
            source_name=source_name,
            trust_tier=trust_tier,
        )
        for (
            research_input,
            outcome,
            title,
            published_at,
            fetched_at,
            source_id,
            source_slug,
            source_name,
            trust_tier,
        ) in rows
    ]


def _score_views(session: Session, opportunity_id: uuid.UUID) -> tuple[list[ScoreView], int]:
    score_rows = list(
        session.execute(
            select(OpportunityScore)
            .where(OpportunityScore.opportunity_id == opportunity_id)
            .order_by(OpportunityScore.evaluated_at.desc(), OpportunityScore.id.desc())
            .limit(MAX_DETAIL_SCORES)
        ).scalars()
    )
    total = int(
        session.scalar(
            select(func.count())
            .select_from(OpportunityScore)
            .where(OpportunityScore.opportunity_id == opportunity_id)
        )
        or 0
    )
    components_by_score: dict[uuid.UUID, list[OpportunityScoreComponent]] = {}
    if score_rows:
        component_rows = session.execute(
            select(OpportunityScoreComponent)
            .where(OpportunityScoreComponent.score_id.in_([score.id for score in score_rows]))
            .order_by(OpportunityScoreComponent.component)
        ).scalars()
        for component in component_rows:
            components_by_score.setdefault(component.score_id, []).append(component)
    # The first row IS the effective score: same ordering as the repository.
    views = [
        ScoreView(
            id=score.id,
            engine_name=score.engine_name,
            engine_version=score.engine_version,
            overall_band=score.overall_band,
            overall_value=score.overall_value,
            eligibility=score.eligibility,
            missing_signals=list(score.missing_signals),
            risk_flags=list(score.risk_flags),
            weights_snapshot=score.weights_snapshot,
            threshold_snapshot=score.threshold_snapshot,
            input_snapshot=score.input_snapshot,
            evaluated_at=score.evaluated_at,
            created_at=score.created_at,
            effective=index == 0,
            components=[
                ScoreComponentView(
                    component=component.component,
                    availability=component.availability,
                    value=component.value,
                    confidence=component.confidence,
                    provider=component.provider,
                    observed_at=component.observed_at,
                    provenance_ref=component.provenance_ref,
                )
                for component in components_by_score.get(score.id, [])
            ],
        )
        for index, score in enumerate(score_rows)
    ]
    return views, total


def _idea_views(
    session: Session, opportunity_id: uuid.UUID
) -> tuple[list[IdeaView], int, list[SelectionEventView], int, uuid.UUID | None]:
    latest_event = session.execute(
        select(IdeaSelectionEvent)
        .where(IdeaSelectionEvent.opportunity_id == opportunity_id)
        .order_by(IdeaSelectionEvent.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    effective_id = (
        latest_event.idea_id
        if latest_event is not None and latest_event.action is IdeaSelectionAction.SELECTED
        else None
    )

    idea_rows = list(
        session.execute(
            select(Idea)
            .where(Idea.opportunity_id == opportunity_id)
            .order_by(Idea.created_at.desc(), Idea.id.desc())
            .limit(MAX_DETAIL_IDEAS)
        ).scalars()
    )
    total_ideas = int(
        session.scalar(
            select(func.count()).select_from(Idea).where(Idea.opportunity_id == opportunity_id)
        )
        or 0
    )
    event_rows = list(
        session.execute(
            select(IdeaSelectionEvent)
            .where(IdeaSelectionEvent.opportunity_id == opportunity_id)
            .order_by(IdeaSelectionEvent.id.desc())
            .limit(MAX_DETAIL_SELECTION_EVENTS)
        ).scalars()
    )
    total_events = int(
        session.scalar(
            select(func.count())
            .select_from(IdeaSelectionEvent)
            .where(IdeaSelectionEvent.opportunity_id == opportunity_id)
        )
        or 0
    )

    idea_views = [
        IdeaView(
            id=idea.id,
            logical_idea_id=idea.logical_idea_id,
            version=idea.version,
            working_title=idea.working_title,
            angle=idea.angle,
            audience=idea.audience,
            value_proposition=idea.value_proposition,
            content_type=idea.content_type,
            locale=idea.locale,
            market=idea.market,
            rationale=idea.rationale,
            exclusions=list(idea.exclusions),
            planning_dimensions=idea.planning_dimensions,
            originality_status=idea.originality_status,
            originality_detail=idea.originality_detail,
            originality_policy_snapshot=idea.originality_policy_snapshot,
            origin=idea.origin,
            generation_attempt_id=idea.generation_attempt_id,
            created_at=idea.created_at,
            effective_selected=idea.id == effective_id,
        )
        for idea in idea_rows
    ]
    event_views = [
        SelectionEventView(
            id=event.id,
            idea_id=event.idea_id,
            action=event.action,
            actor_origin=event.actor_origin,
            reason=event.reason,
            request_id=event.request_id,
            occurred_at=event.occurred_at,
        )
        for event in event_rows
    ]
    return idea_views, total_ideas, event_views, total_events, effective_id


def _pack_views(session: Session, opportunity_id: uuid.UUID) -> tuple[list[PackView], int]:
    pack_rows = list(
        session.execute(
            select(EvidencePack)
            .where(EvidencePack.opportunity_id == opportunity_id)
            .order_by(
                EvidencePack.version.desc(),
                EvidencePack.created_at.desc(),
                EvidencePack.id.desc(),
            )
            .limit(MAX_DETAIL_PACKS)
        ).scalars()
    )
    total = int(
        session.scalar(
            select(func.count())
            .select_from(EvidencePack)
            .where(EvidencePack.opportunity_id == opportunity_id)
        )
        or 0
    )
    if not pack_rows:
        return [], total
    pack_ids = [pack.id for pack in pack_rows]

    item_rows = session.execute(
        select(
            EvidencePackItem,
            ResearchEvidence.evidence_type,
            ResearchEvidence.verification_status,
            ResearchEvidence.statement,
            ResearchEvidence.normalized_document_id,
            ResearchEvidence.source_id,
            ResearchEvidence.extracted_at,
            Source.slug,
            Source.trust_tier,
        )
        .outerjoin(ResearchEvidence, ResearchEvidence.id == EvidencePackItem.research_evidence_id)
        .outerjoin(Source, Source.id == ResearchEvidence.source_id)
        .where(EvidencePackItem.pack_id.in_(pack_ids))
        .order_by(EvidencePackItem.created_at, EvidencePackItem.id)
    ).all()
    items_by_pack: dict[uuid.UUID, list[PackItemView]] = {}
    for (
        pack_item,
        evidence_type,
        verification_status,
        statement,
        document_id,
        source_id,
        extracted_at,
        source_slug,
        trust_tier,
    ) in item_rows:
        items_by_pack.setdefault(pack_item.pack_id, []).append(
            PackItemView(
                id=pack_item.id,
                research_evidence_id=pack_item.research_evidence_id,
                role=pack_item.role,
                claim_cluster=pack_item.claim_cluster,
                display_note=pack_item.display_note,
                evidence_type=evidence_type,
                verification_status=verification_status,
                statement=(statement[:MAX_STATEMENT_LENGTH] if statement is not None else None),
                normalized_document_id=document_id,
                source_id=source_id,
                source_slug=source_slug,
                trust_tier=trust_tier,
                extracted_at=extracted_at,
            )
        )

    contradiction_rows = session.execute(
        select(EvidenceContradiction)
        .where(EvidenceContradiction.pack_id.in_(pack_ids))
        .order_by(EvidenceContradiction.created_at, EvidenceContradiction.id)
    ).scalars()
    contradictions_by_pack: dict[uuid.UUID, list[ContradictionView]] = {}
    for contradiction in contradiction_rows:
        contradictions_by_pack.setdefault(contradiction.pack_id, []).append(
            ContradictionView(
                id=contradiction.id,
                pack_id=contradiction.pack_id,
                claim_key=contradiction.claim_key,
                evidence_side_a=[str(value) for value in contradiction.evidence_side_a],
                evidence_side_b=[str(value) for value in contradiction.evidence_side_b],
                nature=contradiction.nature,
                severity=contradiction.severity,
                resolution_status=contradiction.resolution_status,
                handling_recommendation=contradiction.handling_recommendation,
                resolution_reason=contradiction.resolution_reason,
                resolved_by=contradiction.resolved_by,
                resolved_at=contradiction.resolved_at,
            )
        )

    views = [
        PackView(
            id=pack.id,
            version=pack.version,
            idea_id=pack.idea_id,
            organization_attempt_id=pack.organization_attempt_id,
            assembler_name=pack.assembler_name,
            assembler_version=pack.assembler_version,
            sufficiency=pack.sufficiency,
            sufficiency_detail=pack.sufficiency_detail,
            source_diversity=pack.source_diversity,
            staleness_notes=pack.staleness_notes,
            locale_limitations=pack.locale_limitations,
            licensing_cautions=pack.licensing_cautions,
            policy_snapshot=pack.policy_snapshot,
            assembly_input_hash=pack.assembly_input_hash,
            created_at=pack.created_at,
            items=items_by_pack.get(pack.id, []),
            contradictions=contradictions_by_pack.get(pack.id, []),
        )
        for pack in pack_rows
    ]
    return views, total


def _analysis_views(
    session: Session, opportunity_id: uuid.UUID
) -> tuple[list[IntentAnalysisView], int]:
    analysis_rows = list(
        session.execute(
            select(SearchIntentAnalysis)
            .where(SearchIntentAnalysis.opportunity_id == opportunity_id)
            .order_by(
                SearchIntentAnalysis.version.desc(),
                SearchIntentAnalysis.created_at.desc(),
                SearchIntentAnalysis.id.desc(),
            )
            .limit(MAX_DETAIL_ANALYSES)
        ).scalars()
    )
    total = int(
        session.scalar(
            select(func.count())
            .select_from(SearchIntentAnalysis)
            .where(SearchIntentAnalysis.opportunity_id == opportunity_id)
        )
        or 0
    )
    if not analysis_rows:
        return [], total

    signal_ids: set[uuid.UUID] = set()
    for analysis in analysis_rows:
        for ref in analysis.known_signal_refs:
            raw = ref.get("signal_id")
            if isinstance(raw, str):
                try:
                    signal_ids.add(uuid.UUID(raw))
                except ValueError:  # pragma: no cover - refs are domain-frozen
                    continue
    signals_by_id: dict[uuid.UUID, SearchSignal] = {}
    if signal_ids:
        for signal in session.execute(
            select(SearchSignal).where(SearchSignal.id.in_(signal_ids))
        ).scalars():
            signals_by_id[signal.id] = signal

    views = []
    for analysis in analysis_rows:
        known_signals: list[KnownSignalView] = []
        for ref in analysis.known_signal_refs:
            raw = ref.get("signal_id")
            if not isinstance(raw, str):
                continue
            try:
                known = signals_by_id.get(uuid.UUID(raw))
            except ValueError:  # pragma: no cover - refs are domain-frozen
                known = None
            if known is not None:
                known_signals.append(
                    KnownSignalView(
                        id=known.id,
                        signal_type=known.signal_type,
                        provider=known.provider,
                        subject=known.subject,
                        observed_at=known.observed_at,
                        as_of=known.as_of,
                        recorded_at=known.recorded_at,
                    )
                )
        views.append(
            IntentAnalysisView(
                id=analysis.id,
                version=analysis.version,
                idea_id=analysis.idea_id,
                primary_intent=analysis.primary_intent,
                secondary_intents=list(analysis.secondary_intents),
                target_audience=analysis.target_audience,
                query_concepts=list(analysis.query_concepts),
                page_purpose=analysis.page_purpose,
                likely_format=analysis.likely_format,
                known_signal_refs=analysis.known_signal_refs,
                known_signals=known_signals,
                missing_signals=list(analysis.missing_signals),
                cannibalization_status=analysis.cannibalization_status,
                cannibalization_basis=analysis.cannibalization_basis,
                related_references=analysis.related_references,
                locale=analysis.locale,
                market=analysis.market,
                engine_name=analysis.engine_name,
                engine_version=analysis.engine_version,
                synthesis_attempt_id=analysis.synthesis_attempt_id,
                created_at=analysis.created_at,
            )
        )
    return views, total


def _brief_views(session: Session, work_item_id: uuid.UUID) -> tuple[list[BriefView], int]:
    brief_rows = list(
        session.execute(
            select(ContentBrief)
            .where(ContentBrief.work_item_id == work_item_id)
            .order_by(
                ContentBrief.version.desc(),
                ContentBrief.created_at.desc(),
                ContentBrief.id.desc(),
            )
            .limit(MAX_DETAIL_BRIEFS)
        ).scalars()
    )
    total = int(
        session.scalar(
            select(func.count())
            .select_from(ContentBrief)
            .where(ContentBrief.work_item_id == work_item_id)
        )
        or 0
    )
    if not brief_rows:
        return [], total
    brief_ids = [brief.id for brief in brief_rows]

    claims_by_brief: dict[uuid.UUID, list[BriefClaim]] = {}
    claim_rows = list(
        session.execute(
            select(BriefClaim)
            .where(BriefClaim.brief_id.in_(brief_ids))
            .order_by(BriefClaim.created_at, BriefClaim.id)
        ).scalars()
    )
    for claim in claim_rows:
        claims_by_brief.setdefault(claim.brief_id, []).append(claim)
    links_by_claim: dict[uuid.UUID, list[uuid.UUID]] = {}
    if claim_rows:
        for link in session.execute(
            select(BriefClaimEvidence)
            .where(BriefClaimEvidence.claim_id.in_([claim.id for claim in claim_rows]))
            .order_by(BriefClaimEvidence.created_at, BriefClaimEvidence.id)
        ).scalars():
            links_by_claim.setdefault(link.claim_id, []).append(link.research_evidence_id)

    events_by_brief: dict[uuid.UUID, list[BriefStatusEvent]] = {}
    for event in session.execute(
        select(BriefStatusEvent)
        .where(BriefStatusEvent.brief_id.in_(brief_ids))
        .order_by(BriefStatusEvent.id)
    ).scalars():
        events_by_brief.setdefault(event.brief_id, []).append(event)

    views = [
        BriefView(
            id=brief.id,
            version=brief.version,
            idea_id=brief.idea_id,
            evidence_pack_id=brief.evidence_pack_id,
            search_intent_analysis_id=brief.search_intent_analysis_id,
            locale=brief.locale,
            market=brief.market,
            target_audience=brief.target_audience,
            intent_summary=brief.intent_summary,
            original_angle=brief.original_angle,
            title_guidance=brief.title_guidance,
            content_objective=brief.content_objective,
            required_sections=brief.required_sections,
            optional_sections=brief.optional_sections,
            practical_requirements=brief.practical_requirements,
            exclusions=list(brief.exclusions),
            uncertainty_notes=list(brief.uncertainty_notes),
            internal_link_needs=brief.internal_link_needs,
            media_needs=brief.media_needs,
            faq_questions=list(brief.faq_questions),
            acceptance_criteria=brief.acceptance_criteria,
            structure_guard_result=brief.structure_guard_result,
            structure_policy_snapshot=brief.structure_policy_snapshot,
            status=brief.status,
            composition_attempt_id=brief.composition_attempt_id,
            engine_name=brief.engine_name,
            engine_version=brief.engine_version,
            content_hash=brief.content_hash,
            created_at=brief.created_at,
            claims=[
                BriefClaimView(
                    id=claim.id,
                    claim_key=claim.claim_key,
                    claim_text=claim.claim_text,
                    claim_kind=claim.claim_kind,
                    handling=claim.handling,
                    evidence_ids=links_by_claim.get(claim.id, []),
                )
                for claim in claims_by_brief.get(brief.id, [])
            ],
            status_events=[
                BriefStatusEventView(
                    id=event.id,
                    from_status=event.from_status,
                    to_status=event.to_status,
                    actor_origin=event.actor_origin,
                    reason=event.reason,
                    request_id=event.request_id,
                    replacement_brief_id=event.replacement_brief_id,
                    occurred_at=event.occurred_at,
                )
                for event in events_by_brief.get(brief.id, [])
            ],
        )
        for brief in brief_rows
    ]
    return views, total


def _attempt_views(session: Session, attempt_ids: set[uuid.UUID]) -> list[AiAttemptView]:
    """Safe persisted attempt metadata only — the boundary never stores raw
    provider payloads, prompts, or outputs, and this view adds nothing."""
    if not attempt_ids:
        return []
    rows = session.execute(
        select(AiGenerationAttempt)
        .where(AiGenerationAttempt.id.in_(attempt_ids))
        .order_by(AiGenerationAttempt.created_at, AiGenerationAttempt.id)
    ).scalars()
    return [
        AiAttemptView(
            id=attempt.id,
            purpose=attempt.purpose,
            provider=attempt.provider,
            model_name=attempt.model_name,
            model_version=attempt.model_version,
            schema_name=attempt.schema_name,
            schema_version=attempt.schema_version,
            template_name=attempt.template_name,
            template_version=attempt.template_version,
            input_hash=attempt.input_hash,
            input_refs=attempt.input_refs,
            status=attempt.status,
            error_class=attempt.error_class,
            retry_number=attempt.retry_number,
            usage=attempt.usage,
            created_at=attempt.created_at,
        )
        for attempt in rows
    ]


# --- eligible evidence -------------------------------------------------------


def list_eligible_evidence(
    session: Session,
    opportunity_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_LIMIT,
    offset: int = 0,
) -> EligibleEvidencePage | None:
    """Page over EvidencePackService.list_eligible_evidence — the domain's
    own eligibility rule (evidence tracing to admitted research inputs).
    Nothing here invents a selection: the HUMAN selects evidence. None when
    the opportunity does not exist."""
    if session.get(EditorialOpportunity, opportunity_id) is None:
        return None
    eligible = EvidencePackService(session).list_eligible_evidence(opportunity_id)
    total = len(eligible)
    window = eligible[offset : offset + limit]

    sources_by_id: dict[uuid.UUID, Source] = {}
    if window:
        for source in session.execute(
            select(Source).where(Source.id.in_({evidence.source_id for evidence in window}))
        ).scalars():
            sources_by_id[source.id] = source

    items = [
        EligibleEvidenceView(
            id=evidence.id,
            evidence_type=evidence.evidence_type,
            verification_status=evidence.verification_status,
            statement=evidence.statement[:MAX_STATEMENT_LENGTH],
            extraction_method=evidence.extraction_method,
            confidence=float(evidence.confidence) if evidence.confidence is not None else None,
            licensing_notes=evidence.licensing_notes,
            normalized_document_id=evidence.normalized_document_id,
            source_id=evidence.source_id,
            source_slug=(
                sources_by_id[evidence.source_id].slug
                if evidence.source_id in sources_by_id
                else None
            ),
            source_name=(
                sources_by_id[evidence.source_id].name
                if evidence.source_id in sources_by_id
                else None
            ),
            trust_tier=(
                sources_by_id[evidence.source_id].trust_tier
                if evidence.source_id in sources_by_id
                else None
            ),
            fetched_at=evidence.fetched_at,
            extracted_at=evidence.extracted_at,
        )
        for evidence in window
    ]
    return EligibleEvidencePage(items=items, total=total, limit=limit, offset=offset)
