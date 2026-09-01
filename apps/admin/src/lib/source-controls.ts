import type { SourceListItem } from "@/lib/research-api";

// UI presentation of the domain lifecycle matrix. The backend service stays
// authoritative — this only keeps obviously invalid options out of the form.
const ALLOWED_TRANSITIONS: Record<string, readonly string[]> = {
  active: ["paused", "disabled", "blocked"],
  paused: ["active", "disabled", "blocked"],
  disabled: ["active", "blocked"],
  blocked: ["active"],
};

export function allowedLifecycleTargets(
  currentState: string,
): readonly string[] {
  return ALLOWED_TRANSITIONS[currentState] ?? [];
}

// Only these (kind, strategy) pairs have an automated Phase 2 discovery
// implementation; the backend refuses everything else with a conflict.
export function isDiscoveryEligible(source: SourceListItem): boolean {
  if (source.lifecycle_state !== "active") {
    return false;
  }
  return (
    (source.kind === "rss_feed" && source.discovery_strategy === "feed") ||
    (source.kind === "sitemap" && source.discovery_strategy === "sitemap")
  );
}
