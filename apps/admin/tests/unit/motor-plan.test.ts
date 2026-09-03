import { describe, expect, it } from "vitest";

import {
  MOTOR_STAGES,
  STATE_LABELS_TR,
  deriveNextSteps,
  stageIndexForState,
  stageStatusForState,
  type MotorContext,
} from "@/lib/motor-plan";
import { WORKFLOW_STATES } from "@/lib/editorial-api";

function context(overrides: Partial<MotorContext> = {}): MotorContext {
  return {
    state: "idea_scoring",
    hasScore: false,
    hasIdeas: false,
    selectedIdeaId: null,
    latestPackId: null,
    latestAnalysisId: null,
    latestBriefId: null,
    latestBriefStatus: null,
    hasActiveDraft: false,
    activeReviewVerdict: null,
    activeQaOutcome: null,
    unsatisfiedMediaNeeds: 0,
    latestPackageId: null,
    isReviewer: true,
    ...overrides,
  };
}

describe("motor plan", () => {
  it("covers every workflow state with a stage, a status and a label", () => {
    for (const state of WORKFLOW_STATES) {
      const index = stageIndexForState(state);
      expect(index).toBeGreaterThanOrEqual(0);
      expect(index).toBeLessThan(MOTOR_STAGES.length);
      expect(["normal", "exception", "terminal"]).toContain(
        stageStatusForState(state),
      );
      expect(STATE_LABELS_TR[state].length).toBeGreaterThan(0);
    }
  });

  it("derives at least one step for every workflow state", () => {
    for (const state of WORKFLOW_STATES) {
      expect(deriveNextSteps(context({ state })).length).toBeGreaterThan(0);
    }
  });

  it("walks idea scoring in order: evaluate, generate, select", () => {
    expect(deriveNextSteps(context())).toEqual(["evaluate"]);
    expect(deriveNextSteps(context({ hasScore: true }))).toEqual([
      "generate-ideas",
    ]);
    expect(
      deriveNextSteps(context({ hasScore: true, hasIdeas: true })),
    ).toEqual(["select-idea", "generate-ideas"]);
  });

  it("sends evidence building to the detail page until a pack exists", () => {
    const base = context({
      state: "evidence_building",
      hasScore: true,
      hasIdeas: true,
      selectedIdeaId: "x",
    });
    expect(deriveNextSteps(base)).toEqual(["build-evidence-link"]);
    expect(deriveNextSteps({ ...base, latestPackId: "p" })).toEqual([
      "worker-wait",
      "build-evidence-link",
    ]);
  });

  it("orders seo and briefing: analyze, compose, accept", () => {
    const seo = context({ state: "seo_research", latestPackId: "p" });
    expect(deriveNextSteps(seo)).toEqual(["analyze-intent"]);
    expect(deriveNextSteps({ ...seo, latestAnalysisId: "a" })).toEqual([
      "compose-brief",
    ]);
    const briefing = context({
      state: "briefing",
      latestBriefId: "b",
      latestBriefStatus: "draft",
    });
    expect(deriveNextSteps(briefing)).toEqual([
      "accept-brief",
      "compose-brief",
    ]);
    expect(
      deriveNextSteps({
        ...briefing,
        latestBriefStatus: "accepted_for_drafting",
      }),
    ).toEqual(["worker-wait", "generate-draft"]);
  });

  it("gates the human decision on the reviewer role", () => {
    const awaiting = context({ state: "awaiting_human_review" });
    expect(deriveNextSteps(awaiting)).toEqual(["approve", "request-changes"]);
    expect(deriveNextSteps({ ...awaiting, isReviewer: false })).toEqual([
      "reviewer-required",
    ]);
  });

  it("offers the media waiver only while unmet needs block QA", () => {
    const qa = context({ state: "qa_review", activeQaOutcome: "not_ready" });
    expect(deriveNextSteps({ ...qa, unsatisfiedMediaNeeds: 2 })).toEqual([
      "media-link",
      "waive-qa-gate",
      "run-qa",
    ]);
    expect(deriveNextSteps(qa)).toEqual(["run-qa", "detail-link-only"]);
  });

  it("orders publication: assemble, schedule, publish", () => {
    const approved = context({ state: "approved" });
    expect(deriveNextSteps(approved)).toEqual(["assemble-package"]);
    expect(deriveNextSteps({ ...approved, latestPackageId: "pkg" })).toEqual([
      "schedule-publication",
    ]);
    expect(deriveNextSteps(context({ state: "scheduled" }))).toEqual([
      "publish-now",
    ]);
    expect(deriveNextSteps(context({ state: "published" }))).toEqual([
      "published-info",
    ]);
  });

  it("maps every exception state to its explicit resolution", () => {
    expect(deriveNextSteps(context({ state: "blocked" }))).toEqual([
      "resolve-block",
    ]);
    expect(deriveNextSteps(context({ state: "changes_requested" }))).toEqual([
      "resolve-changes-requested",
    ]);
    expect(deriveNextSteps(context({ state: "approval_expired" }))).toEqual([
      "resolve-approval-expired",
    ]);
    expect(deriveNextSteps(context({ state: "duplicate" }))).toEqual([
      "duplicate-link",
    ]);
    expect(deriveNextSteps(context({ state: "rejected" }))).toEqual([
      "terminal-info",
    ]);
  });
});
