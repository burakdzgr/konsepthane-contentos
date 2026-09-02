// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchCurrentUser, loginBackend, logoutBackend } from "@/lib/auth-api";
import { USER_ID } from "./auth-fixtures";

function jsonResponse(status: number, body: unknown) {
  return {
    status,
    headers: { get: () => null },
    json: async () => body,
  };
}

function stubFetch(implementation: (...args: unknown[]) => unknown) {
  const fetchMock = vi.fn(implementation);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("loginBackend", () => {
  it("returns the token and user on success", async () => {
    const fetchMock = stubFetch(async () =>
      jsonResponse(200, {
        status: "authenticated",
        token: "raw-session-token",
        expires_at: "2026-09-03T00:00:00+00:00",
        user: {
          id: USER_ID,
          username: "operator.one",
          display_name: "Operator One",
          roles: ["operator"],
        },
      }),
    );
    const result = await loginBackend("operator.one", "a-long-password-1");
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.token).toBe("raw-session-token");
      expect(result.user.roles).toEqual(["operator"]);
    }
    const [url, init] = fetchMock.mock.calls[0] as [URL, { body?: string }];
    expect(String(url)).toContain("/internal/auth/login");
    expect(init.body).toContain("operator.one");
  });

  it("maps a 401 to invalid credentials without detail", async () => {
    stubFetch(async () => jsonResponse(401, { detail: "invalid credentials" }));
    const result = await loginBackend("operator.one", "wrong");
    expect(result.kind).toBe("invalid_credentials");
  });

  it("rejects a malformed body", async () => {
    stubFetch(async () => jsonResponse(200, { status: "authenticated" }));
    const result = await loginBackend("operator.one", "a-long-password-1");
    expect(result.kind).toBe("malformed");
  });
});

describe("fetchCurrentUser", () => {
  it("maps a 401 to unauthenticated", async () => {
    stubFetch(async () => jsonResponse(401, {}));
    const result = await fetchCurrentUser();
    expect(result.kind).toBe("unauthenticated");
  });

  it("parses the identity", async () => {
    stubFetch(async () =>
      jsonResponse(200, {
        id: USER_ID,
        username: "operator.one",
        display_name: "Operator One",
        roles: ["operator", "reviewer"],
      }),
    );
    const result = await fetchCurrentUser();
    expect(result.kind).toBe("ok");
  });
});

describe("logoutBackend", () => {
  it("parses the logout acknowledgement", async () => {
    stubFetch(async () => jsonResponse(200, { status: "logged_out" }));
    const result = await logoutBackend();
    expect(result.kind).toBe("ok");
  });
});
