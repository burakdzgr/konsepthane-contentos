import { redirect } from "next/navigation";
import { z } from "zod";

import { getServerEnv } from "@/lib/env";
import { getSessionToken } from "@/lib/session";

// Server-only module: import it exclusively from Server Components and route
// handlers. The internal backend URL must never reach browser JavaScript, so
// no result produced here may carry URLs or raw error details.
//
// Phase 5 G2: every backend call forwards the HttpOnly session cookie as a
// Bearer header; a 401 from a protected route means the session expired or
// was revoked, and the caller is redirected to /login.

export const REQUEST_ID_HEADER = "X-Request-ID";

const REQUEST_TIMEOUT_MS = 5000;

const livenessSchema = z.object({
  status: z.literal("ok"),
  service: z.string().min(1),
  version: z.string().min(1),
  // Older backends omit it; absence renders honestly as unknown.
  environment: z.string().min(1).optional(),
});

const componentStateSchema = z.enum(["ok", "failed", "unknown"]);

const readinessSchema = z.object({
  status: z.enum(["ready", "not_ready"]),
  checks: z.object({
    postgres: componentStateSchema,
    pgvector: componentStateSchema,
    redis: componentStateSchema,
  }),
});

export type BackendLiveness = z.infer<typeof livenessSchema>;
export type BackendReadiness = z.infer<typeof readinessSchema>;
export type BackendComponentState = z.infer<typeof componentStateSchema>;

export type BackendResult<T> =
  | { kind: "ok"; data: T; requestId: string | null }
  | { kind: "unreachable" }
  | { kind: "malformed" };

export type FetchedResponse = {
  status: number;
  headers: { get(name: string): string | null };
  json(): Promise<unknown>;
  // Present on real fetch responses; used only by the media byte proxy.
  arrayBuffer?(): Promise<ArrayBuffer>;
};

export type BackendRequestInit = {
  method?: "GET" | "POST";
  jsonBody?: unknown;
  // Multipart uploads; fetch sets the boundary content-type itself.
  formBody?: FormData;
};

export async function requestBackend(
  path: string,
  init: BackendRequestInit = {},
): Promise<FetchedResponse | null> {
  const baseUrl = getServerEnv().internalApiUrl;
  const headers: Record<string, string> = {
    [REQUEST_ID_HEADER]: `admin-${crypto.randomUUID()}`,
  };
  if (init.jsonBody !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const token = await getSessionToken();
  if (token !== null) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  let response: FetchedResponse;
  try {
    response = await fetch(new URL(path, baseUrl), {
      method: init.method ?? "GET",
      cache: "no-store",
      headers,
      body:
        init.formBody !== undefined
          ? init.formBody
          : init.jsonBody !== undefined
            ? JSON.stringify(init.jsonBody)
            : undefined,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch {
    // Deliberately drop all details: raw fetch errors can embed the internal URL.
    return null;
  }
  if (response.status === 401 && !path.startsWith("/internal/auth/")) {
    // The session expired or was revoked: back to login (server-side).
    redirect("/login?error=expired");
  }
  return response;
}

export async function parseBackendResponse<T>(
  response: FetchedResponse,
  schema: z.ZodType<T>,
  expectedStatuses: readonly number[],
): Promise<BackendResult<T>> {
  if (!expectedStatuses.includes(response.status)) {
    return { kind: "malformed" };
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return { kind: "malformed" };
  }
  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    return { kind: "malformed" };
  }
  return {
    kind: "ok",
    data: parsed.data,
    requestId: response.headers.get(REQUEST_ID_HEADER),
  };
}

export async function fetchBackendLiveness(): Promise<
  BackendResult<BackendLiveness>
> {
  const response = await requestBackend("/health/live");
  if (response === null) {
    return { kind: "unreachable" };
  }
  return parseBackendResponse(response, livenessSchema, [200]);
}

export async function fetchBackendReadiness(): Promise<
  BackendResult<BackendReadiness>
> {
  const response = await requestBackend("/health/ready");
  if (response === null) {
    return { kind: "unreachable" };
  }
  // 503 carries the same truthful readiness contract as 200.
  return parseBackendResponse(response, readinessSchema, [200, 503]);
}
