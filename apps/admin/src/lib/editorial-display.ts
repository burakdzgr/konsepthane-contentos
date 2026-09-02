// Badge semantics for the editorial screens. Every badge keeps its explicit
// backend value as visible text; tone only supports the meaning. UNKNOWN and
// absent values must never be toned as good or bad — they stay neutral.

import type { BadgeTone } from "@/lib/pipeline-display";

const WORKFLOW_TONES: Record<string, BadgeTone> = {
  idea_scoring: "neutral",
  evidence_building: "info",
  seo_research: "info",
  briefing: "info",
  drafting: "ok",
  blocked: "warn",
  rejected: "bad",
};

const ELIGIBILITY_TONES: Record<string, BadgeTone> = {
  commissionable: "ok",
  not_commissionable: "bad",
  needs_operator_review: "warn",
};

const SUFFICIENCY_TONES: Record<string, BadgeTone> = {
  ready: "ok",
  insufficient: "warn",
  conflicted: "warn",
  blocked: "bad",
};

const BRIEF_TONES: Record<string, BadgeTone> = {
  draft: "info",
  accepted_for_drafting: "ok",
  superseded: "neutral",
};

const ORIGINALITY_TONES: Record<string, BadgeTone> = {
  passed: "ok",
  failed: "bad",
  not_checkable: "warn",
};

const RESOLUTION_TONES: Record<string, BadgeTone> = {
  unresolved: "warn",
  resolved_cautious_wording: "ok",
  resolved_needs_research: "info",
  resolved_editorial_judgment: "ok",
};

const GENERATION_STATUS_TONES: Record<string, BadgeTone> = {
  succeeded: "ok",
  validation_failed: "bad",
  provider_error: "warn",
  timeout: "warn",
  cancelled: "neutral",
};

export function workflowStateTone(state: string): BadgeTone {
  return WORKFLOW_TONES[state] ?? "neutral";
}

export function scoreEligibilityTone(value: string | null): BadgeTone {
  if (value === null) {
    return "neutral";
  }
  return ELIGIBILITY_TONES[value] ?? "neutral";
}

export function packSufficiencyTone(value: string | null): BadgeTone {
  if (value === null) {
    return "neutral";
  }
  return SUFFICIENCY_TONES[value] ?? "neutral";
}

export function briefStatusTone(value: string | null): BadgeTone {
  if (value === null) {
    return "neutral";
  }
  return BRIEF_TONES[value] ?? "neutral";
}

export function originalityTone(value: string): BadgeTone {
  return ORIGINALITY_TONES[value] ?? "neutral";
}

export function contradictionResolutionTone(value: string): BadgeTone {
  return RESOLUTION_TONES[value] ?? "neutral";
}

export function generationStatusTone(value: string): BadgeTone {
  return GENERATION_STATUS_TONES[value] ?? "neutral";
}

// Cannibalization truth-state wording (Task-10 semantics preserved): the
// scoped claim only — never "no conflict" unless the durable status says so.
export function cannibalizationLabel(status: string): string {
  switch (status) {
    case "not_checked":
      return "Not checked";
    case "no_known_conflict":
      return "No known conflict (contentos-internal scope only)";
    case "potential_conflict":
      return "Potential conflict";
    case "known_conflict":
      return "Known conflict";
    default:
      return status;
  }
}
