// Stage badge semantics for the research pipeline screens. Every badge keeps
// its explicit backend value as visible text; tone only supports the meaning
// and is never the sole carrier of it.

export type BadgeTone = "ok" | "bad" | "warn" | "info" | "neutral";

const DISCOVERY_TONES: Record<string, BadgeTone> = {
  discovered: "neutral",
  accepted: "info",
  fetched: "ok",
  fetch_failed: "bad",
  rejected: "warn",
};

const FETCH_TONES: Record<string, BadgeTone> = {
  success: "ok",
  timeout: "warn",
  network_error: "warn",
  robots_unavailable: "warn",
};

const NORMALIZATION_TONES: Record<string, BadgeTone> = {
  succeeded: "ok",
  failed: "bad",
};

const DUPLICATE_TONES: Record<string, BadgeTone> = {
  unique: "ok",
  related: "info",
  update_existing: "info",
  duplicate: "warn",
  reject: "bad",
};

export function discoveryStateTone(state: string): BadgeTone {
  return DISCOVERY_TONES[state] ?? "neutral";
}

export function fetchOutcomeTone(outcome: string): BadgeTone {
  return FETCH_TONES[outcome] ?? "bad";
}

export function normalizationStatusTone(status: string): BadgeTone {
  return NORMALIZATION_TONES[status] ?? "neutral";
}

export function duplicateOutcomeTone(outcome: string): BadgeTone {
  return DUPLICATE_TONES[outcome] ?? "neutral";
}

export function evidenceCountTone(count: number): BadgeTone {
  return count > 0 ? "ok" : "neutral";
}
