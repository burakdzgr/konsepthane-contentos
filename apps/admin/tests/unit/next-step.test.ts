import { describe, expect, it } from "vitest";

import { nextStep, type NextStepInput } from "@/app/editorial/[id]/next-step";
import { workItemDetail } from "./editorial-fixtures";

function input(overrides: Partial<NextStepInput> = {}): NextStepInput {
  return {
    detail: workItemDetail(),
    drafts: null,
    reviews: null,
    qaReports: null,
    decisions: null,
    media: null,
    publication: null,
    isReviewer: false,
    ...overrides,
  };
}

function withState(
  state: string,
  patch: Partial<ReturnType<typeof workItemDetail>> = {},
) {
  const base = workItemDetail();
  return {
    ...base,
    ...patch,
    work_item: {
      ...base.work_item,
      current_state: state as typeof base.work_item.current_state,
    },
  };
}

describe("nextStep", () => {
  it("asks for the production decision on a commissionable open opportunity", () => {
    const detail = withState("idea_scoring", {
      opportunity: {
        ...workItemDetail().opportunity!,
        disposition: "open",
        commission_eligible: true,
        commission_override_possible: false,
      },
    });
    const step = nextStep(input({ detail }));
    expect(step.key).toBe("commission");
    expect(step.sectionId).toBe("detail-opportunity");
    expect(step.actionable).toBe(true);
  });

  it("names the weak source base and still offers the decision (ADR 0010)", () => {
    const detail = withState("idea_scoring", {
      opportunity: {
        ...workItemDetail().opportunity!,
        disposition: "open",
        commission_eligible: false,
        commission_override_possible: true,
      },
    });
    expect(nextStep(input({ detail })).key).toBe("commission-override");
  });

  it("refuses to commission an unscored opportunity: evaluate first", () => {
    const detail = withState("idea_scoring", {
      scores: [],
      opportunity: {
        ...workItemDetail().opportunity!,
        disposition: "open",
        commission_eligible: false,
        commission_override_possible: false,
      },
    });
    expect(nextStep(input({ detail })).key).toBe("evaluate");
  });

  it("walks the evidence-building stage: ideas -> selection -> pack -> sufficiency", () => {
    expect(
      nextStep(input({ detail: withState("evidence_building", { ideas: [] }) }))
        .key,
    ).toBe("generate-ideas");
    expect(
      nextStep(
        input({
          detail: withState("evidence_building", {
            effective_selected_idea_id: null,
          }),
        }),
      ).key,
    ).toBe("select-idea");
    expect(
      nextStep(
        input({
          detail: withState("evidence_building", { evidence_packs: [] }),
        }),
      ).key,
    ).toBe("build-pack");
    const base = workItemDetail();
    const pack = base.evidence_packs[0]!;
    expect(
      nextStep(
        input({
          detail: withState("evidence_building", {
            evidence_packs: [{ ...pack, sufficiency: "insufficient" }],
          }),
        }),
      ).key,
    ).toBe("pack-insufficient");
    const ready = nextStep(
      input({
        detail: withState("evidence_building", {
          evidence_packs: [{ ...pack, sufficiency: "ready" }],
        }),
      }),
    );
    expect(ready.key).toBe("pack-ready");
    expect(ready.actionable).toBe(false);
  });

  it("points later stages at the section that holds the command", () => {
    expect(
      nextStep(
        input({ detail: withState("seo_research", { intent_analyses: [] }) }),
      ).sectionId,
    ).toBe("detail-intent");
    expect(
      nextStep(input({ detail: withState("briefing", { briefs: [] }) })).key,
    ).toBe("brief");
    expect(nextStep(input({ detail: withState("drafting") })).key).toBe(
      "draft",
    );
    expect(nextStep(input({ detail: withState("editing") })).key).toBe(
      "review",
    );
    expect(nextStep(input({ detail: withState("qa_review") })).key).toBe("qa");
    expect(
      nextStep(input({ detail: withState("awaiting_human_review") })).key,
    ).toBe("reviewer-needed");
    expect(
      nextStep(
        input({ detail: withState("awaiting_human_review"), isReviewer: true }),
      ).key,
    ).toBe("decide-final");
    expect(nextStep(input({ detail: withState("blocked") })).key).toBe(
      "blocked",
    );
    const done = nextStep(input({ detail: withState("published") }));
    expect(done.actionable).toBe(false);
  });
});
