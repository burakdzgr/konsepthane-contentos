import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/contentos-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/contentos-api")>(
    "@/lib/contentos-api",
  );
  return {
    ...actual,
    fetchBackendReadiness: vi.fn(),
  };
});

import LoginPage from "@/app/login/page";
import { fetchBackendReadiness } from "@/lib/contentos-api";

const readinessMock = vi.mocked(fetchBackendReadiness);

async function renderPage(params: Record<string, string> = {}) {
  render(
    await LoginPage({
      searchParams: Promise.resolve(params),
    }),
  );
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Login page", () => {
  it("renders the form and the truthful foundation status", async () => {
    readinessMock.mockResolvedValue({
      kind: "ok",
      data: {
        status: "ready",
        checks: { postgres: "ok", pgvector: "ok", redis: "ok" },
      },
      requestId: null,
    });
    await renderPage();
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(screen.getByLabelText("Username")).toBeTruthy();
    expect(screen.getByLabelText("Password")).toBeTruthy();
    expect(screen.getByText("Operational")).toBeTruthy();
    expect(screen.getByText(/no.*self-registration/i)).toBeTruthy();
  });

  it("shows Unavailable when the backend is not ready", async () => {
    readinessMock.mockResolvedValue({ kind: "unreachable" });
    await renderPage();
    expect(screen.getByText("Unavailable")).toBeTruthy();
  });

  it("shows expiry and invalid-credential notices", async () => {
    readinessMock.mockResolvedValue({ kind: "unreachable" });
    await renderPage({ error: "expired" });
    expect(screen.getByText(/session has expired/i)).toBeTruthy();
  });

  it("never renders the internal backend URL", async () => {
    readinessMock.mockResolvedValue({ kind: "unreachable" });
    const { container } = render(
      await LoginPage({ searchParams: Promise.resolve({}) }),
    );
    expect(container.innerHTML).not.toContain("127.0.0.1:8000");
    expect(container.innerHTML).not.toContain("CONTENTOS_INTERNAL_API_URL");
  });
});
