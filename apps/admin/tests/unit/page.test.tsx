import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/contentos-api", () => ({
  fetchBackendLiveness: vi.fn(),
  fetchBackendReadiness: vi.fn(),
}));

import HomePage from "@/app/page";
import {
  fetchBackendLiveness,
  fetchBackendReadiness,
  type BackendLiveness,
  type BackendReadiness,
  type BackendResult,
} from "@/lib/contentos-api";

const livenessMock = vi.mocked(fetchBackendLiveness);
const readinessMock = vi.mocked(fetchBackendReadiness);

const okLiveness: BackendResult<BackendLiveness> = {
  kind: "ok",
  data: { status: "ok", service: "Konsepthane ContentOS", version: "0.1.0" },
  requestId: "backend-req-1",
};

function okReadiness(
  status: BackendReadiness["status"],
  checks: BackendReadiness["checks"],
): BackendResult<BackendReadiness> {
  return { kind: "ok", data: { status, checks }, requestId: "backend-req-2" };
}

async function renderStatusPage() {
  render(await HomePage());
}

function rowValue(name: string): string {
  const row = screen.getByText(name).closest(".status-row");
  expect(row).not.toBeNull();
  return row?.querySelector("dd")?.textContent ?? "";
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("Foundation Status page", () => {
  it("renders truthful operational states when the backend is ready", async () => {
    livenessMock.mockResolvedValue(okLiveness);
    readinessMock.mockResolvedValue(
      okReadiness("ready", { postgres: "ok", pgvector: "ok", redis: "ok" }),
    );

    await renderStatusPage();

    expect(screen.getByRole("heading", { name: "Sistem Durumu" })).toBeTruthy();
    expect(rowValue("API süreci")).toBe("Çalışıyor");
    expect(rowValue("PostgreSQL")).toBe("Çalışıyor");
    expect(rowValue("pgvector")).toBe("Çalışıyor");
    expect(rowValue("Redis")).toBe("Çalışıyor");
    expect(rowValue("Servis")).toBe("Konsepthane ContentOS");
    expect(rowValue("Sürüm")).toBe("0.1.0");
  });

  it("renders actual failed and unknown component states when not ready", async () => {
    livenessMock.mockResolvedValue(okLiveness);
    readinessMock.mockResolvedValue(
      okReadiness("not_ready", {
        postgres: "failed",
        pgvector: "unknown",
        redis: "ok",
      }),
    );

    await renderStatusPage();

    expect(rowValue("API süreci")).toBe("Çalışıyor");
    expect(rowValue("PostgreSQL")).toBe("Hazır değil");
    expect(rowValue("pgvector")).toBe("Bilinmiyor");
    expect(rowValue("Redis")).toBe("Çalışıyor");
  });

  it("shows unavailable without inventing failures when unreachable", async () => {
    livenessMock.mockResolvedValue({ kind: "unreachable" });
    readinessMock.mockResolvedValue({ kind: "unreachable" });

    await renderStatusPage();

    expect(rowValue("API süreci")).toBe("Erişilemiyor");
    expect(rowValue("PostgreSQL")).toBe("Bilinmiyor");
    expect(rowValue("pgvector")).toBe("Bilinmiyor");
    expect(rowValue("Redis")).toBe("Bilinmiyor");
    expect(rowValue("Servis")).toBe("Bilinmiyor");
    expect(screen.queryByText("Hazır değil")).toBeNull();
    expect(screen.getByRole("status").textContent).toMatch(
      /şu anda erişilemiyor/i,
    );
  });

  it("marks unexpected backend data as unknown, not operational", async () => {
    livenessMock.mockResolvedValue({ kind: "malformed" });
    readinessMock.mockResolvedValue({ kind: "malformed" });

    await renderStatusPage();

    expect(rowValue("API süreci")).toBe("Bilinmiyor");
    expect(rowValue("PostgreSQL")).toBe("Bilinmiyor");
    expect(screen.queryByText("Çalışıyor")).toBeNull();
    expect(screen.getByRole("status").textContent).toMatch(/beklenmedik veri/i);
  });

  it("never renders fake statistics or the internal API URL", async () => {
    livenessMock.mockResolvedValue(okLiveness);
    readinessMock.mockResolvedValue(
      okReadiness("ready", { postgres: "ok", pgvector: "ok", redis: "ok" }),
    );

    await renderStatusPage();
    const text = document.body.textContent ?? "";

    expect(text).not.toMatch(/%|uptime|jobs|drafts|posts|users|queue depth/i);
    expect(text).not.toContain("http://");
    expect(text).not.toContain("127.0.0.1");
    expect(text).not.toContain("8000");
  });
});
