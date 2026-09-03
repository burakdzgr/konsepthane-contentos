import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
}));

vi.mock("@/lib/dashboard-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/dashboard-api")>(
    "@/lib/dashboard-api",
  );
  return { ...actual, sendPauseCommand: vi.fn() };
});

import { pauseIntakeAction, resumeIntakeAction } from "@/app/kontrol/actions";
import { sendPauseCommand } from "@/lib/dashboard-api";

const sendMock = vi.mocked(sendPauseCommand);

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

beforeEach(() => {
  vi.clearAllMocks();
});

describe("kontrol pause actions", () => {
  it("pauses a scope with the given reason and lands back on /kontrol", async () => {
    sendMock.mockResolvedValue({
      kind: "ok",
      data: { status: "applied", scope: "writer", is_paused: true },
    });

    const target = await redirectTarget(
      pauseIntakeAction(formData({ scope: "writer", reason: "bakım" })),
    );

    expect(sendMock).toHaveBeenCalledWith("pause", "writer", "bakım");
    expect(target).toBe("/kontrol?notice=durduruldu&scope=writer");
  });

  it("resumes the engine", async () => {
    sendMock.mockResolvedValue({
      kind: "ok",
      data: { status: "applied", scope: "engine", is_paused: false },
    });

    const target = await redirectTarget(
      resumeIntakeAction(formData({ scope: "engine", reason: "devam" })),
    );

    expect(sendMock).toHaveBeenCalledWith("resume", "engine", "devam");
    expect(target).toBe("/kontrol?notice=devam&scope=engine");
  });

  it("rejects an unknown scope without calling the backend", async () => {
    const target = await redirectTarget(
      pauseIntakeAction(formData({ scope: "reactor", reason: "x" })),
    );

    expect(sendMock).not.toHaveBeenCalled();
    expect(target).toBe("/kontrol?error=invalid");
  });

  it("requires a reason", async () => {
    const target = await redirectTarget(
      pauseIntakeAction(formData({ scope: "engine", reason: "  " })),
    );

    expect(sendMock).not.toHaveBeenCalled();
    expect(target).toBe("/kontrol?error=invalid");
  });

  it("maps an unreachable backend to the error banner", async () => {
    sendMock.mockResolvedValue({ kind: "unreachable" });

    const target = await redirectTarget(
      pauseIntakeAction(formData({ scope: "qa", reason: "dur" })),
    );

    expect(target).toBe("/kontrol?error=unreachable");
  });
});
