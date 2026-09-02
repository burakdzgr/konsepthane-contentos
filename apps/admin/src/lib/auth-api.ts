import { z } from "zod";

import {
  parseBackendResponse,
  requestBackend,
  type BackendResult,
} from "@/lib/contentos-api";

// Server-only module: the authentication client. The session token appears
// exactly once (in the login result) and is stored only in the HttpOnly
// cookie by the login action; nothing here logs or re-exposes it.

const userSchema = z.object({
  id: z.string().uuid(),
  username: z.string(),
  display_name: z.string(),
  roles: z.array(z.enum(["operator", "reviewer"])),
});

const loginResponseSchema = z.object({
  status: z.literal("authenticated"),
  token: z.string().min(1),
  expires_at: z.string().min(1),
  user: userSchema,
});

const logoutResponseSchema = z.object({
  status: z.literal("logged_out"),
});

export type AuthenticatedUser = z.infer<typeof userSchema>;
export type LoginResult =
  | { kind: "ok"; token: string; expiresAt: string; user: AuthenticatedUser }
  | { kind: "invalid_credentials" }
  | { kind: "unreachable" }
  | { kind: "malformed" };

export async function loginBackend(
  username: string,
  password: string,
): Promise<LoginResult> {
  const response = await requestBackend("/internal/auth/login", {
    method: "POST",
    jsonBody: { username, password },
  });
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 401) {
    return { kind: "invalid_credentials" };
  }
  const parsed = await parseBackendResponse(
    response,
    loginResponseSchema,
    [200],
  );
  if (parsed.kind !== "ok") {
    return { kind: parsed.kind };
  }
  return {
    kind: "ok",
    token: parsed.data.token,
    expiresAt: parsed.data.expires_at,
    user: parsed.data.user,
  };
}

export async function logoutBackend(): Promise<
  BackendResult<{ status: "logged_out" }>
> {
  const response = await requestBackend("/internal/auth/logout", {
    method: "POST",
  });
  if (response === null) {
    return { kind: "unreachable" };
  }
  return parseBackendResponse(response, logoutResponseSchema, [200]);
}

export async function fetchCurrentUser(): Promise<
  BackendResult<AuthenticatedUser> | { kind: "unauthenticated" }
> {
  const response = await requestBackend("/internal/auth/me");
  if (response === null) {
    return { kind: "unreachable" };
  }
  if (response.status === 401) {
    return { kind: "unauthenticated" };
  }
  return parseBackendResponse(response, userSchema, [200]);
}
