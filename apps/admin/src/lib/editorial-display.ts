// Badge semantics for the editorial screens. Tones are keyed by the backend
// value; the visible text is the Turkish label from `tr-labels.ts` (the
// operator never reads wire vocabulary). Tone only supports the meaning —
// UNKNOWN and absent values must never be toned as good or bad.

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

const DRAFT_STATUS_TONES: Record<string, BadgeTone> = {
  active: "ok",
  superseded: "neutral",
};

export function draftStatusTone(value: string): BadgeTone {
  return DRAFT_STATUS_TONES[value] ?? "neutral";
}

const REVIEW_VERDICT_TONES: Record<string, BadgeTone> = {
  pass: "ok",
  revise: "warn",
};

export function reviewVerdictTone(value: string): BadgeTone {
  return REVIEW_VERDICT_TONES[value] ?? "neutral";
}

const FINDING_SEVERITY_TONES: Record<string, BadgeTone> = {
  blocking: "bad",
  major: "warn",
  minor: "info",
};

export function findingSeverityTone(value: string): BadgeTone {
  return FINDING_SEVERITY_TONES[value] ?? "neutral";
}

// A missing verdict is the truth "BİLİNMİYOR", never a pass and never a zero.
export function verdictLabel(value: string | null): string {
  return value === null ? "BİLİNMİYOR" : value;
}

export function verdictTone(value: string | null): BadgeTone {
  if (value === null) {
    return "neutral";
  }
  if (value === "passed" || value === "evaluated") {
    return "ok";
  }
  if (value === "failed") {
    return "bad";
  }
  return "neutral";
}

// Cannibalization truth-state wording (Task-10 semantics preserved): the
// scoped claim only — never "no conflict" unless the durable status says so.
export function cannibalizationLabel(status: string): string {
  switch (status) {
    case "not_checked":
      return "Kontrol edilmedi";
    case "no_known_conflict":
      return "Bilinen çakışma yok (yalnızca contentos-içi kapsam)";
    case "potential_conflict":
      return "Olası çakışma";
    case "known_conflict":
      return "Bilinen çakışma";
    default:
      return status;
  }
}
