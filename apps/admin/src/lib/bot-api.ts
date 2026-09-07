import { z } from "zod";
import { requestBackend, parseBackendResponse } from "@/lib/contentos-api";
import { WORKFLOW_STATES } from "@/lib/editorial-api";

export const dailyPlanSchema = z.object({
  target: z.number().int().nullable(),
  mode: z.enum(["off", "supervised", "autonomous"]),
  day: z.string(),
  timezone: z.string(),
  completed: z.number().int(),
  in_progress: z.number().int(),
  research: z
    .array(
      z.object({
        source: z.string(),
        status: z.string(),
        fetched: z.number(),
        opportunities: z.number(),
      }),
    )
    .default([]),
  sources: z.array(
    z.object({
      id: z.string().uuid(),
      name: z.string(),
      selected: z.boolean(),
      active: z.boolean(),
    }),
  ),
  items: z.array(
    z.object({
      id: z.string().uuid(),
      title: z.string(),
      state: z.enum(WORKFLOW_STATES),
      completed: z.boolean(),
      reserved_on: z.string(),
      reason: z.string().nullable(),
    }),
  ),
});

export async function fetchDailyPlan() {
  const response = await requestBackend("/internal/autopilot/daily-plan");
  if (response === null) return { kind: "unreachable" } as const;
  return parseBackendResponse(response, dailyPlanSchema, [200]);
}

export async function saveDailyPlan(
  target: number,
  sourceIds: string[],
  enabled: boolean,
) {
  const response = await requestBackend("/internal/autopilot/daily-plan", {
    method: "PUT",
    jsonBody: { target, source_ids: sourceIds, enabled },
  });
  if (response === null) return { kind: "unreachable" } as const;
  if (response.status === 503) return { kind: "queue_failed" } as const;
  return parseBackendResponse(response, dailyPlanSchema, [200]);
}
