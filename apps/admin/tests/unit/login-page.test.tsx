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
    expect(screen.getByRole("heading", { name: "Giriş yap" })).toBeTruthy();
    expect(screen.getByLabelText("Kullanıcı adı")).toBeTruthy();
    expect(screen.getByLabelText("Parola")).toBeTruthy();
    expect(screen.getByText("Çalışıyor")).toBeTruthy();
    expect(screen.getByText(/kendi kendine kayıt/i)).toBeTruthy();
  });

  it("shows Unavailable when the backend is not ready", async () => {
    readinessMock.mockResolvedValue({ kind: "unreachable" });
    await renderPage();
    expect(screen.getByText("Erişilemiyor")).toBeTruthy();
  });

  it("shows expiry and invalid-credential notices", async () => {
    readinessMock.mockResolvedValue({ kind: "unreachable" });
    await renderPage({ error: "expired" });
    expect(screen.getByText(/oturumunuzun süresi doldu/i)).toBeTruthy();
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
