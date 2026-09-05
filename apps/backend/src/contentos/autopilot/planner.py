"""The autopilot planner (ADR 0012): ONE next action from durable facts.

Pure: takes a `Snapshot` of a work item's durable state and the current
mode, returns ONE `Action`. It never touches a session, never invents a
state, and encodes the whole "what advances by itself / what waits for a
human" policy in one readable place:

- PRODUCTION steps (generate ideas, build the pack, intent analysis,
  compose brief, write draft, editor review, QA gates, media images) run
  automatically in SUPERVISED and AUTONOMOUS mode.
- ACCEPTANCE steps (commission, choose idea, accept brief, accept review,
  rework routing, assemble/schedule/publish) wait for a human in
  SUPERVISED mode and are taken by the autopilot in AUTONOMOUS mode.
- The ADR 0004 gate (final publication approval) ALWAYS waits for a named
  reviewer. Rework is bounded (MAX_REWORK_CYCLES) so a disagreeing editor
  never loops forever.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from contentos.autopilot.enums import AutopilotMode
from contentos.briefs.enums import BriefStatus
from contentos.evidence_packs.enums import EvidencePackSufficiency
from contentos.opportunities.enums import OpportunityDisposition
from contentos.qa.enums import QaOutcome
from contentos.reviews.enums import ReviewVerdict
from contentos.workflow.enums import WorkflowState

MAX_REWORK_CYCLES = 2
DEFAULT_IDEA_CANDIDATES = 3

# Stable action names: they appear in autopilot_events and the admin feed.
ACTION_COMMISSION = "commission"
ACTION_GENERATE_IDEAS = "generate_ideas"
ACTION_SELECT_IDEA = "select_idea"
ACTION_BUILD_PACK = "build_pack"
ACTION_ANALYZE_INTENT = "analyze_intent"
ACTION_COMPOSE_BRIEF = "compose_brief"
ACTION_ACCEPT_BRIEF = "accept_brief"
ACTION_GENERATE_DRAFT = "generate_draft"
ACTION_GENERATE_REVIEW = "generate_review"
ACTION_ACCEPT_REVIEW = "accept_review"
ACTION_REQUEST_REWORK = "request_rework"
ACTION_RESOLVE_CHANGES = "resolve_changes"
ACTION_RUN_QA = "run_qa"
ACTION_GENERATE_IMAGE = "generate_image"
ACTION_ASSEMBLE_PACKAGE = "assemble_package"
ACTION_SCHEDULE = "schedule_publication"
ACTION_PUBLISH = "publish"

PRODUCTION_ACTIONS = frozenset(
    {
        ACTION_GENERATE_IDEAS,
        ACTION_BUILD_PACK,
        ACTION_ANALYZE_INTENT,
        ACTION_COMPOSE_BRIEF,
        ACTION_GENERATE_DRAFT,
        ACTION_GENERATE_REVIEW,
        ACTION_RUN_QA,
        ACTION_GENERATE_IMAGE,
    }
)
ACCEPTANCE_ACTIONS = frozenset(
    {
        ACTION_COMMISSION,
        ACTION_SELECT_IDEA,
        ACTION_ACCEPT_BRIEF,
        ACTION_ACCEPT_REVIEW,
        ACTION_REQUEST_REWORK,
        ACTION_RESOLVE_CHANGES,
        ACTION_ASSEMBLE_PACKAGE,
        ACTION_SCHEDULE,
        ACTION_PUBLISH,
    }
)


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Durable facts the planner needs; built by the runner from the DB."""

    work_item_id: uuid.UUID
    state: WorkflowState
    opportunity_id: uuid.UUID | None = None
    disposition: OpportunityDisposition | None = None
    commission_eligible: bool = False
    idea_count: int = 0
    selected_idea_id: uuid.UUID | None = None
    best_idea_id: uuid.UUID | None = None
    latest_pack_id: uuid.UUID | None = None
    latest_pack_sufficiency: EvidencePackSufficiency | None = None
    eligible_evidence_count: int = 0
    intent_analysis_id: uuid.UUID | None = None
    latest_brief_id: uuid.UUID | None = None
    latest_brief_status: BriefStatus | None = None
    active_draft_id: uuid.UUID | None = None
    active_review_id: uuid.UUID | None = None
    active_review_verdict: ReviewVerdict | None = None
    rework_cycles: int = 0
    active_qa_outcome: QaOutcome | None = None
    open_media_needs: tuple[int, ...] = ()
    media_needs_with_candidate: tuple[int, ...] = ()
    latest_package_id: uuid.UUID | None = None
    # Actions already taken recently (in flight); the planner never repeats them.
    in_flight: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class Action:
    """`enqueue` = a worker task; `command` = a domain acceptance the runner
    performs in-process; `wait` = a human is needed; `none` = nothing to do."""

    kind: str
    name: str
    reason: str
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def is_wait(self) -> bool:
        return self.kind == "wait"


def _wait(name: str, reason: str) -> Action:
    return Action(kind="wait", name=name, reason=reason)


def _none(reason: str) -> Action:
    return Action(kind="none", name="idle", reason=reason)


def _enqueue(name: str, reason: str, **payload: Any) -> Action:
    return Action(kind="enqueue", name=name, reason=reason, payload=payload)


def _command(name: str, reason: str, **payload: Any) -> Action:
    return Action(kind="command", name=name, reason=reason, payload=payload)


def plan(snapshot: Snapshot, mode: AutopilotMode) -> Action:
    if mode is AutopilotMode.OFF:
        return _none("otopilot kapalı")
    action = _plan(snapshot, mode)
    if action.kind in ("enqueue", "command") and action.name in snapshot.in_flight:
        return _none(f"{action.name} zaten sürüyor")
    return action


def _plan(s: Snapshot, mode: AutopilotMode) -> Action:  # noqa: PLR0911, PLR0912
    autonomous = mode is AutopilotMode.AUTONOMOUS
    state = s.state

    if state is WorkflowState.IDEA_SCORING:
        if s.opportunity_id is None or s.disposition is not OpportunityDisposition.OPEN:
            return _none("açık fırsat yok")
        if not s.commission_eligible:
            return _wait("commission_gate", "kaynak tabanı görevlendirilebilir değil; insan kararı")
        if autonomous:
            return _command(
                ACTION_COMMISSION,
                "kaynak tabanı görevlendirilebilir; otopilot görevlendiriyor",
                opportunity_id=str(s.opportunity_id),
            )
        return _wait("commission_decision", "üretim kararı operatörde (denetimli mod)")

    if state is WorkflowState.EVIDENCE_BUILDING:
        if s.opportunity_id is None:
            return _none("fırsat yok")
        if s.idea_count == 0:
            return _enqueue(
                ACTION_GENERATE_IDEAS,
                "fikir adayı yok; üretiliyor",
                opportunity_id=str(s.opportunity_id),
                candidate_count=DEFAULT_IDEA_CANDIDATES,
            )
        if s.selected_idea_id is None:
            if autonomous and s.best_idea_id is not None:
                return _command(
                    ACTION_SELECT_IDEA,
                    "en iyi özgünlük sonucuna sahip aday seçiliyor",
                    idea_id=str(s.best_idea_id),
                )
            return _wait("idea_selection", "fikir seçimi operatörde")
        if s.latest_pack_id is None:
            if s.eligible_evidence_count == 0:
                return _wait("no_evidence", "seçilebilir kanıt yok; araştırma girdisi gerekli")
            return _enqueue(
                ACTION_BUILD_PACK,
                "kanıt paketi yok; uygun kanıttan oluşturuluyor",
                opportunity_id=str(s.opportunity_id),
                idea_id=str(s.selected_idea_id),
            )
        if s.latest_pack_sufficiency is EvidencePackSufficiency.READY:
            return _none("paket hazır; sistem SEO araştırmasına geçiriyor")
        return _wait(
            "pack_insufficient",
            f"kanıt paketi {s.latest_pack_sufficiency.value if s.latest_pack_sufficiency else 'bilinmiyor'}; "
            "yeni araştırma girdisi gerekli",
        )

    if state is WorkflowState.SEO_RESEARCH:
        if s.opportunity_id is None or s.selected_idea_id is None or s.latest_pack_id is None:
            return _none("SEO araştırması için gerekli artefaktlar eksik")
        if s.intent_analysis_id is None:
            return _enqueue(
                ACTION_ANALYZE_INTENT,
                "arama niyeti analizi yok; kuyruğa alınıyor",
                opportunity_id=str(s.opportunity_id),
                idea_id=str(s.selected_idea_id),
                evidence_pack_id=str(s.latest_pack_id),
            )
        return _none("analiz var; sistem brif hazırlığına geçiriyor")

    if state is WorkflowState.BRIEFING:
        if s.latest_brief_id is None:
            if (
                s.selected_idea_id is None
                or s.latest_pack_id is None
                or s.intent_analysis_id is None
            ):
                return _none("brief için gerekli artefaktlar eksik")
            return _enqueue(
                ACTION_COMPOSE_BRIEF,
                "brief yok; oluşturuluyor",
                work_item_id=str(s.work_item_id),
                idea_id=str(s.selected_idea_id),
                evidence_pack_id=str(s.latest_pack_id),
                search_intent_analysis_id=str(s.intent_analysis_id),
            )
        if s.latest_brief_status is BriefStatus.DRAFT:
            if autonomous:
                return _command(
                    ACTION_ACCEPT_BRIEF,
                    "brief taslak; kabul ediliyor",
                    brief_id=str(s.latest_brief_id),
                )
            return _wait("brief_acceptance", "brief kabulü operatörde")
        return _none("brief kabul edildi; sistem yazıma geçiriyor")

    if state is WorkflowState.DRAFTING:
        if s.latest_brief_id is None:
            return _none("kabul edilmiş brief yok")
        if s.active_draft_id is None:
            return _enqueue(
                ACTION_GENERATE_DRAFT,
                "etkin taslak yok; yazar motoru çalıştırılıyor",
                content_brief_id=str(s.latest_brief_id),
            )
        return _none("taslak var; sistem editör aşamasına geçiriyor")

    if state is WorkflowState.EDITING:
        if s.active_draft_id is None:
            return _wait("no_active_draft", "etkin taslak yok")
        if s.active_review_id is None:
            return _enqueue(
                ACTION_GENERATE_REVIEW,
                "editör değerlendirmesi yok; üretiliyor",
                work_item_id=str(s.work_item_id),
            )
        if s.active_review_verdict is ReviewVerdict.PASS:
            if autonomous:
                return _command(
                    ACTION_ACCEPT_REVIEW,
                    "editör geçti dedi; kabul ediliyor",
                    review_id=str(s.active_review_id),
                )
            return _wait("review_acceptance", "editör geçti; kabul operatörde")
        if autonomous:
            if s.rework_cycles >= MAX_REWORK_CYCLES:
                return _wait(
                    "rework_limit",
                    f"editör {s.rework_cycles} kez düzelt dedi; sınır doldu, insan kararı",
                )
            return _command(
                ACTION_REQUEST_REWORK,
                "editör düzelt dedi; taslak yeniden çalışmaya yönlendiriliyor",
                review_id=str(s.active_review_id),
            )
        return _wait("review_revise", "editör düzelt dedi; karar operatörde")

    if state is WorkflowState.CHANGES_REQUESTED:
        if autonomous:
            return _command(ACTION_RESOLVE_CHANGES, "yeniden çalışma yazıma yönlendiriliyor")
        return _wait("changes_requested", "yeniden çalışma yönlendirmesi operatörde")

    if state is WorkflowState.QA_REVIEW:
        if s.active_qa_outcome is None:
            return _enqueue(
                ACTION_RUN_QA,
                "QA raporu yok; kapılar çalıştırılıyor",
                work_item_id=str(s.work_item_id),
            )
        if s.active_qa_outcome is QaOutcome.READY_FOR_HUMAN_REVIEW:
            return _none("QA geçti; sistem insan onayına geçiriyor")
        if s.open_media_needs:
            pending = [n for n in s.open_media_needs if n not in s.media_needs_with_candidate]
            if pending and autonomous:
                return _enqueue(
                    ACTION_GENERATE_IMAGE,
                    f"görsel ihtiyacı #{pending[0]} açık; görsel üretiliyor",
                    work_item_id=str(s.work_item_id),
                    need_index=pending[0],
                )
            return _wait(
                "media_satisfaction",
                "üretilen görsellerin ihtiyaca bağlanması operatörde"
                if not pending
                else "açık görsel ihtiyaçları var; denetimli modda operatör karar verir",
            )
        return _wait("qa_not_ready", "QA kapıları geçmedi; bulgular operatörde")

    if state is WorkflowState.AWAITING_HUMAN_REVIEW:
        return _wait("final_approval", "nihai yayın onayı adlı bir inceleyicide (ADR 0004)")

    if state is WorkflowState.APPROVED:
        if not autonomous:
            return _wait("publication", "yayın paketi ve zamanlama operatörde (denetimli mod)")
        if s.latest_package_id is None:
            return _command(
                ACTION_ASSEMBLE_PACKAGE, "onaylı içerik için yayın paketi birleştiriliyor"
            )
        return _command(
            ACTION_SCHEDULE,
            "yayın paketi hazır; zamanlanıyor",
            publication_package_id=str(s.latest_package_id),
        )

    if state is WorkflowState.SCHEDULED:
        if autonomous:
            return _enqueue(
                ACTION_PUBLISH,
                "zamanlandı; yayın gönderimi kuyruğa alınıyor",
                work_item_id=str(s.work_item_id),
            )
        return _wait("publish", "yayın gönderimi operatörde (denetimli mod)")

    if state is WorkflowState.BLOCKED:
        return _wait("blocked", "iş öğesi engellendi; çözüm operatörde")

    return _none(f"{state.value} aşamasında otopilot adımı yok")
