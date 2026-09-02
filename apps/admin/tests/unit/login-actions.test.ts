// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

const cookieStore = {
  set: vi.fn(),
  delete: vi.fn(),
  get: vi.fn(),
};

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => cookieStore),
}));

vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
}));

vi.mock("@/lib/auth-api", () => ({
  loginBackend: vi.fn(),
  logoutBackend: vi.fn(),
}));

import { loginAction, logoutAction } from "@/app/login/actions";
import { loginBackend, logoutBackend } from "@/lib/auth-api";
import { USER_ID } from "./auth-fixtures";

const loginMock = vi.mocked(loginBackend);
const logoutMock = vi.mocked(logoutBackend);

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    data.set(key, value);
  }
  return data;
}

beforeEach(() => {
  vi.clearAllMocks();
  cookieStore.get.mockReturnValue(undefined);
});

describe("loginAction", () => {
  it("sets the HttpOnly cookie and redirects home on success", async () => {
    loginMock.mockResolvedValue({
      kind: "ok",
      token: "raw-session-token",
      expiresAt: "2026-09-03T00:00:00+00:00",
      user: {
        id: USER_ID,
        username: "operator.one",
        display_name: "Operator One",
        roles: ["operator"],
      },
    });
    await expect(
      loginAction(
        form({ username: "operator.one", password: "a-long-password-1" }),
      ),
    ).rejects.toThrow("REDIRECT:/");
    const [name, value, options] = cookieStore.set.mock.calls[0] as [
      string,
      string,
      Record<string, unknown>,
    ];
    expect(name).toBe("contentos_session");
    expect(value).toBe("raw-session-token");
    expect(options.httpOnly).toBe(true);
    expect(options.sameSite).toBe("lax");
  });

  it("redirects with an invalid notice on bad credentials", async () => {
    loginMock.mockResolvedValue({ kind: "invalid_credentials" });
    await expect(
      loginAction(form({ username: "operator.one", password: "wrong" })),
    ).rejects.toThrow("REDIRECT:/login?error=invalid");
    expect(cookieStore.set).not.toHaveBeenCalled();
  });

  it("requires both fields before calling the backend", async () => {
    await expect(loginAction(form({ username: "x" }))).rejects.toThrow(
      "REDIRECT:/login?error=invalid",
    );
    expect(loginMock).not.toHaveBeenCalled();
  });
});

describe("logoutAction", () => {
  it("revokes the backend session and clears the cookie", async () => {
    cookieStore.get.mockReturnValue({ value: "raw-session-token" });
    logoutMock.mockResolvedValue({
      kind: "ok",
      data: { status: "logged_out" },
      requestId: null,
    });
    await expect(logoutAction()).rejects.toThrow(
      "REDIRECT:/login?notice=logged-out",
    );
    expect(logoutMock).toHaveBeenCalled();
    expect(cookieStore.delete).toHaveBeenCalledWith("contentos_session");
  });
});
