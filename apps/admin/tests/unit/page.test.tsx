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

    expect(
      screen.getByRole("heading", { name: "Foundation Status" }),
    ).toBeTruthy();
    expect(rowValue("API process")).toBe("Operational");
    expect(rowValue("PostgreSQL")).toBe("Operational");
    expect(rowValue("pgvector")).toBe("Operational");
    expect(rowValue("Redis")).toBe("Operational");
    expect(rowValue("Service")).toBe("Konsepthane ContentOS");
    expect(rowValue("Version")).toBe("0.1.0");
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

    expect(rowValue("API process")).toBe("Operational");
    expect(rowValue("PostgreSQL")).toBe("Not ready");
    expect(rowValue("pgvector")).toBe("Unknown");
    expect(rowValue("Redis")).toBe("Operational");
  });

  it("shows unavailable without inventing failures when unreachable", async () => {
    livenessMock.mockResolvedValue({ kind: "unreachable" });
    readinessMock.mockResolvedValue({ kind: "unreachable" });

    await renderStatusPage();

    expect(rowValue("API process")).toBe("Unavailable");
    expect(rowValue("PostgreSQL")).toBe("Unknown");
    expect(rowValue("pgvector")).toBe("Unknown");
    expect(rowValue("Redis")).toBe("Unknown");
    expect(rowValue("Service")).toBe("Unknown");
    expect(screen.queryByText("Not ready")).toBeNull();
    expect(screen.getByRole("status").textContent).toMatch(
      /cannot be reached/i,
    );
  });

  it("marks unexpected backend data as unknown, not operational", async () => {
    livenessMock.mockResolvedValue({ kind: "malformed" });
    readinessMock.mockResolvedValue({ kind: "malformed" });

    await renderStatusPage();

    expect(rowValue("API process")).toBe("Unknown");
    expect(rowValue("PostgreSQL")).toBe("Unknown");
    expect(screen.queryByText("Operational")).toBeNull();
    expect(screen.getByRole("status").textContent).toMatch(/unexpected data/i);
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
