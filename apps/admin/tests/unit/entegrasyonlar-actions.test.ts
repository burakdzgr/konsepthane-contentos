import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
}));

vi.mock("@/lib/integrations-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/integrations-api")>(
    "@/lib/integrations-api",
  );
  return { ...actual, testIntegration: vi.fn() };
});

import { testIntegrationAction } from "@/app/entegrasyonlar/actions";
import { testIntegration, type IntegrationView } from "@/lib/integrations-api";

const testMock = vi.mocked(testIntegration);

function formData(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) {
    data.set(key, value);
  }
  return data;
}

async function redirectTarget(promise: Promise<void>): Promise<string> {
  try {
    await promise;
  } catch (error) {
    const message = (error as Error).message;
    if (message.startsWith("REDIRECT:")) {
      return message.slice("REDIRECT:".length);
    }
    throw error;
  }
  throw new Error("expected a redirect");
}

const VIEW: IntegrationView = {
  name: "semrush",
  display_name: "Semrush",
  purpose: "",
  configured: true,
  verified: true,
  state: "access_required",
  detail: "API erişimi reddedildi.",
  checked_at: "2026-09-05T10:00:00+00:00",
  last_success_at: null,
  last_error_class: "semrush_http_401",
  freshness: null,
  daily_budget: 200,
  requests_today: 1,
  cache_hours: 72,
  required_env: ["CONTENTOS_SEMRUSH_API_KEY"],
  optional_env: [],
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("testIntegrationAction", () => {
  it("runs the test and lands back with the resulting state", async () => {
    testMock.mockResolvedValue({ kind: "ok", data: VIEW });

    const target = await redirectTarget(
      testIntegrationAction(formData({ provider: "semrush" })),
    );

    expect(testMock).toHaveBeenCalledWith("semrush");
    expect(target).toBe(
      "/entegrasyonlar?notice=test-access_required&provider=semrush",
    );
  });

  it("refuses unknown providers without calling the backend", async () => {
    const target = await redirectTarget(
      testIntegrationAction(formData({ provider: "bing" })),
    );

    expect(testMock).not.toHaveBeenCalled();
    expect(target).toBe("/entegrasyonlar?error=invalid");
  });

  it("maps backend failures to bounded error codes", async () => {
    testMock.mockResolvedValue({ kind: "unreachable" });
    expect(
      await redirectTarget(
        testIntegrationAction(formData({ provider: "google_trends" })),
      ),
    ).toBe("/entegrasyonlar?error=unreachable");

    testMock.mockResolvedValue({ kind: "not-found" });
    expect(
      await redirectTarget(
        testIntegrationAction(formData({ provider: "google_trends" })),
      ),
    ).toBe("/entegrasyonlar?error=not-found");
  });
});
