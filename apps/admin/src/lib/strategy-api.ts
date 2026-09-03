import { z } from "zod";

import {
  parseBackendResponse,
  requestBackend,
  type BackendResult,
} from "@/lib/contentos-api";

export const STRATEGY_STATUSES = ["active", "paused", "archived"] as const;

const audienceSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  priority: z.number().int(),
  status: z.enum(STRATEGY_STATUSES),
  notes: z.string().nullable(),
});
const clusterSchema = audienceSchema.extend({ slug: z.string() });
const keywordSchema = z.object({
  id: z.string().uuid(),
  phrase: z.string(),
  priority: z.number().int(),
  status: z.enum(STRATEGY_STATUSES),
  topic_cluster_id: z.string().uuid().nullable(),
  notes: z.string().nullable(),
});
const overviewSchema = z.object({
  audiences: z.array(audienceSchema),
  clusters: z.array(clusterSchema),
  keywords: z.array(keywordSchema),
});

export type StrategyStatus = (typeof STRATEGY_STATUSES)[number];
export type StrategyOverview = z.infer<typeof overviewSchema>;

export async function fetchStrategyOverview(): Promise<
  BackendResult<StrategyOverview>
> {
  const response = await requestBackend("/internal/strategy/overview");
  if (response === null) return { kind: "unreachable" };
  return parseBackendResponse(response, overviewSchema, [200]);
}

export async function saveStrategy(
  kind: "audiences" | "clusters" | "keywords",
  body: Record<string, unknown>,
  id?: string,
): Promise<boolean> {
  const response = await requestBackend(
    `/internal/strategy/${kind}${id ? `/${id}` : ""}`,
    { method: "POST", jsonBody: body },
  );
  return (
    response !== null && (response.status === 200 || response.status === 201)
  );
}
