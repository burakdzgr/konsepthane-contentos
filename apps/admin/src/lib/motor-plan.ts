import type { WORKFLOW_STATES } from "@/lib/editorial-api";

// Pure planning logic for the single-page Motor (pipeline wizard) view:
// which visual stage a workflow state belongs to, and which explicit
// operator step(s) the current durable artifacts admit next. The backend
// stays authoritative — this never bypasses a rule, it only decides what
// to OFFER; a stale offer receives the backend's 409.

export type WorkflowState = (typeof WORKFLOW_STATES)[number];

export const MOTOR_STAGES = [
  { key: "fikir", label: "Fikir" },
  { key: "kanit", label: "Kanıt" },
  { key: "brief", label: "SEO & Brief" },
  { key: "taslak", label: "Taslak & Editör" },
  { key: "kalite", label: "QA & Onay" },
  { key: "yayin", label: "Yayın" },
] as const;

export type StageStatus = "normal" | "exception" | "terminal";

const STAGE_BY_STATE: Record<WorkflowState, number> = {
  discovered: 0,
  researching: 0,
  normalized: 0,
  duplicate_check: 0,
  duplicate: 0,
  idea_scoring: 0,
  evidence_building: 1,
  seo_research: 2,
  briefing: 2,
  drafting: 3,
  editing: 3,
  qa_review: 4,
  awaiting_human_review: 4,
  approved: 5,
  scheduled: 5,
  publishing: 5,
  published: 5,
  pinterest_pending: 5,
  distributed: 5,
  measuring: 5,
  refresh_candidate: 5,
  changes_requested: 3,
  blocked: 0,
  approval_expired: 5,
  rejected: 0,
  archived: 0,
};

const EXCEPTION_STATES: ReadonlySet<WorkflowState> = new Set([
  "blocked",
  "changes_requested",
  "approval_expired",
  "duplicate",
]);

const TERMINAL_STATES: ReadonlySet<WorkflowState> = new Set([
  "rejected",
  "archived",
]);

export function stageIndexForState(state: WorkflowState): number {
  return STAGE_BY_STATE[state];
}

export function stageStatusForState(state: WorkflowState): StageStatus {
  if (TERMINAL_STATES.has(state)) {
    return "terminal";
  }
  if (EXCEPTION_STATES.has(state)) {
    return "exception";
  }
  return "normal";
}

// Turkish display labels for every workflow state. Wire values stay
// untouched; this is presentation only.
export const STATE_LABELS_TR: Record<WorkflowState, string> = {
  discovered: "Keşfedildi",
  researching: "Araştırılıyor",
  normalized: "Normalleştirildi",
  duplicate_check: "Kopya kontrolü",
  duplicate: "Kopya",
  idea_scoring: "Fikir puanlama",
  evidence_building: "Kanıt oluşturma",
  seo_research: "SEO araştırması",
  briefing: "Brief hazırlama",
  drafting: "Taslak yazımı",
  editing: "Editör incelemesi",
  qa_review: "QA incelemesi",
  awaiting_human_review: "İnsan onayı bekliyor",
  approved: "Onaylandı",
  scheduled: "Zamanlandı",
  publishing: "Yayınlanıyor",
  published: "Yayınlandı",
  pinterest_pending: "Pinterest bekliyor",
  distributed: "Dağıtıldı",
  measuring: "Ölçümleniyor",
  refresh_candidate: "Yenileme adayı",
  changes_requested: "Değişiklik istendi",
  blocked: "Engellendi",
  approval_expired: "Onay süresi doldu",
  rejected: "Reddedildi",
  archived: "Arşivlendi",
};

export type MotorStepId =
  | "evaluate"
  | "generate-ideas"
  | "select-idea"
  | "build-evidence-link"
  | "worker-wait"
  | "analyze-intent"
  | "compose-brief"
  | "accept-brief"
  | "generate-draft"
  | "submit-draft-link"
  | "generate-editor-review"
  | "accept-review"
  | "run-qa"
  | "waive-qa-gate"
  | "media-link"
  | "approve"
  | "request-changes"
  | "reviewer-required"
  | "assemble-package"
  | "schedule-publication"
  | "publish-now"
  | "published-info"
  | "resolve-block"
  | "resolve-changes-requested"
  | "resolve-approval-expired"
  | "duplicate-link"
  | "terminal-info"
  | "detail-link-only";

export type MotorContext = {
  state: WorkflowState;
  hasScore: boolean;
  hasIdeas: boolean;
  selectedIdeaId: string | null;
  latestPackId: string | null;
  latestAnalysisId: string | null;
  latestBriefId: string | null;
  latestBriefStatus: "draft" | "accepted_for_drafting" | "superseded" | null;
  hasActiveDraft: boolean;
  activeReviewVerdict: "pass" | "revise" | null;
  activeQaOutcome: "ready_for_human_review" | "not_ready" | null;
  unsatisfiedMediaNeeds: number;
  latestPackageId: string | null;
  isReviewer: boolean;
};

// The single question the Motor answers: "what is the next explicit
// step here?" Complex interactions (evidence selection, media binding,
// manual drafts, reject/revoke flows) stay on the detail page and are
// offered as links, never re-implemented.
export function deriveNextSteps(ctx: MotorContext): MotorStepId[] {
  switch (ctx.state) {
    case "idea_scoring": {
      if (!ctx.hasScore) {
        return ["evaluate"];
      }
      if (!ctx.hasIdeas) {
        return ["generate-ideas"];
      }
      if (ctx.selectedIdeaId === null) {
        return ["select-idea", "generate-ideas"];
      }
      return ["worker-wait", "build-evidence-link"];
    }
    case "evidence_building": {
      if (ctx.selectedIdeaId === null) {
        return ["select-idea"];
      }
      if (ctx.latestPackId === null) {
        return ["build-evidence-link"];
      }
      return ["worker-wait", "build-evidence-link"];
    }
    case "seo_research": {
      if (ctx.latestAnalysisId === null) {
        return ["analyze-intent"];
      }
      return ["compose-brief"];
    }
    case "briefing": {
      if (
        ctx.latestBriefId === null ||
        ctx.latestBriefStatus === "superseded"
      ) {
        return ["compose-brief"];
      }
      if (ctx.latestBriefStatus === "draft") {
        return ["accept-brief", "compose-brief"];
      }
      return ["worker-wait", "generate-draft"];
    }
    case "drafting": {
      if (ctx.latestBriefId === null) {
        return ["detail-link-only"];
      }
      if (!ctx.hasActiveDraft) {
        return ["generate-draft", "submit-draft-link"];
      }
      return ["worker-wait", "generate-draft", "submit-draft-link"];
    }
    case "editing": {
      if (ctx.activeReviewVerdict === null) {
        return ["generate-editor-review"];
      }
      if (ctx.activeReviewVerdict === "pass") {
        return ["accept-review", "generate-editor-review"];
      }
      return ["generate-editor-review", "detail-link-only"];
    }
    case "qa_review": {
      if (ctx.activeQaOutcome === null) {
        return ["run-qa"];
      }
      if (ctx.activeQaOutcome === "not_ready") {
        if (ctx.unsatisfiedMediaNeeds > 0) {
          return ["media-link", "waive-qa-gate", "run-qa"];
        }
        return ["run-qa", "detail-link-only"];
      }
      return ["worker-wait"];
    }
    case "awaiting_human_review": {
      if (!ctx.isReviewer) {
        return ["reviewer-required"];
      }
      return ["approve", "request-changes"];
    }
    case "approved": {
      if (ctx.latestPackageId === null) {
        return ["assemble-package"];
      }
      return ["schedule-publication"];
    }
    case "scheduled":
      return ["publish-now"];
    case "publishing":
      return ["worker-wait"];
    case "published":
    case "pinterest_pending":
    case "distributed":
    case "measuring":
    case "refresh_candidate":
      return ["published-info"];
    case "blocked":
      return ["resolve-block"];
    case "changes_requested":
      return ["resolve-changes-requested"];
    case "approval_expired":
      return ["resolve-approval-expired"];
    case "duplicate":
      return ["duplicate-link"];
    case "rejected":
    case "archived":
      return ["terminal-info"];
    default:
      return ["detail-link-only"];
  }
}
