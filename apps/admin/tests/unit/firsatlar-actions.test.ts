// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
}));

vi.mock("@/lib/editorial-control-api", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/editorial-control-api")
  >("@/lib/editorial-control-api");
  return {
    ...actual,
    commissionOpportunity: vi.fn(),
    rejectOpportunity: vi.fn(),
  };
});

import {
  bulkCommissionAction,
  bulkRejectAction,
} from "@/app/firsatlar/actions";
import {
  commissionOpportunity,
  rejectOpportunity,
} from "@/lib/editorial-control-api";

const commissionMock = vi.mocked(commissionOpportunity);
const rejectMock = vi.mocked(rejectOpportunity);

const A = "a1111111-2222-4333-8444-555555555555";
const B = "a2111111-2222-4333-8444-555555555555";
const C = "a3111111-2222-4333-8444-555555555555";

function form(entries: Array<[string, string]>): FormData {
  const data = new FormData();
  for (const [name, value] of entries) {
    data.append(name, value);
  }
  return data;
}

async function redirectOf(promise: Promise<void>): Promise<string> {
  try {
    await promise;
  } catch (error) {
    return (error as Error).message.replace("REDIRECT:", "");
  }
  throw new Error("expected a redirect");
}

beforeEach(() => {
  vi.resetAllMocks();
});

describe("bulk opportunity decisions", () => {
  it("rejects only the ticked cards, one backend command each, and reports counts", async () => {
    rejectMock
      .mockResolvedValueOnce({ kind: "ok", data: {} as never })
      .mockResolvedValueOnce({ kind: "conflict" });

    const target = await redirectOf(
      bulkRejectAction(
        form([
          ["kapsam", "secili"],
          ["secili", A],
          ["secili", B],
          ["secili", "not-a-uuid"],
          ["listelenen", C],
          ["reason", "konu stratejiye uymuyor"],
          ["durum", "elenecek"],
        ]),
      ),
    );

    expect(rejectMock).toHaveBeenCalledTimes(2);
    expect(rejectMock).toHaveBeenCalledWith(A, "konu stratejiye uymuyor");
    expect(rejectMock).toHaveBeenCalledWith(B, "konu stratejiye uymuyor");
    expect(commissionMock).not.toHaveBeenCalled();
    const url = new URL(target, "http://admin");
    expect(url.pathname).toBe("/firsatlar");
    expect(url.searchParams.get("toplu")).toBe("ret");
    expect(url.searchParams.get("basarili")).toBe("1");
    expect(url.searchParams.get("celisen")).toBe("1");
    expect(url.searchParams.get("hatali")).toBe("0");
    // The filter the operator was working in survives the round trip.
    expect(url.searchParams.get("durum")).toBe("elenecek");
  });

  it("uses every listed card when the scope says so", async () => {
    rejectMock.mockResolvedValue({ kind: "ok", data: {} as never });

    await redirectOf(
      bulkRejectAction(
        form([
          ["kapsam", "listelenen"],
          ["secili", A],
          ["listelenen", B],
          ["listelenen", C],
          ["reason", "toplu temizlik"],
        ]),
      ),
    );

    expect(rejectMock).toHaveBeenCalledTimes(2);
    expect(rejectMock).toHaveBeenCalledWith(B, "toplu temizlik");
    expect(rejectMock).toHaveBeenCalledWith(C, "toplu temizlik");
  });

  it("refuses an empty batch or a missing reason without calling the backend", async () => {
    expect(
      await redirectOf(
        bulkRejectAction(
          form([
            ["kapsam", "secili"],
            ["reason", "x"],
          ]),
        ),
      ),
    ).toBe("/firsatlar?durum=karar&error=invalid");
    expect(
      await redirectOf(
        bulkRejectAction(
          form([
            ["kapsam", "secili"],
            ["secili", A],
          ]),
        ),
      ),
    ).toBe("/firsatlar?durum=karar&error=invalid");
    expect(rejectMock).not.toHaveBeenCalled();
  });

  it("commissions only cards the read model marked eligible and counts the rest as skipped", async () => {
    commissionMock.mockResolvedValue({ kind: "ok", data: {} as never });

    const target = await redirectOf(
      bulkCommissionAction(
        form([
          ["kapsam", "secili"],
          ["secili", A],
          ["secili", B],
          ["onaylanabilir", A],
          ["reason", "güçlü skor, strateji eşleşti"],
        ]),
      ),
    );

    // B was never eligible: no 409 round trip, an honest "atlanan" instead.
    expect(commissionMock).toHaveBeenCalledTimes(1);
    expect(commissionMock).toHaveBeenCalledWith(
      A,
      "güçlü skor, strateji eşleşti",
      { overrideGate: false },
    );
    const url = new URL(target, "http://admin");
    expect(url.searchParams.get("toplu")).toBe("onay");
    expect(url.searchParams.get("basarili")).toBe("1");
    expect(url.searchParams.get("atlanan")).toBe("1");
  });

  it("sends overridable cards only with the explicit override tick, flagged as overrides", async () => {
    commissionMock.mockResolvedValue({ kind: "ok", data: {} as never });

    await redirectOf(
      bulkCommissionAction(
        form([
          ["kapsam", "secili"],
          ["secili", A],
          ["secili", B],
          ["secili", C],
          ["onaylanabilir", A],
          ["asilabilir", B],
          ["override_gate", "true"],
          ["reason", "konu stratejik"],
        ]),
      ),
    );

    // A passes the gate as is; B goes through as an override; C (unscored,
    // not overridable) is skipped.
    expect(commissionMock).toHaveBeenCalledTimes(2);
    expect(commissionMock).toHaveBeenCalledWith(A, "konu stratejik", {
      overrideGate: false,
    });
    expect(commissionMock).toHaveBeenCalledWith(B, "konu stratejik", {
      overrideGate: true,
    });
  });

  it("sends overridable cards only with the explicit override tick, flagged as overrides", async () => {
    commissionMock.mockResolvedValue({ kind: "ok", data: {} as never });

    await redirectOf(
      bulkCommissionAction(
        form([
          ["kapsam", "secili"],
          ["secili", A],
          ["secili", B],
          ["secili", C],
          ["onaylanabilir", A],
          ["asilabilir", B],
          ["override_gate", "true"],
          ["reason", "konu stratejik"],
        ]),
      ),
    );

    // A passes the gate as is; B goes through as an override; C (unscored,
    // not overridable) is skipped.
    expect(commissionMock).toHaveBeenCalledTimes(2);
    expect(commissionMock).toHaveBeenCalledWith(A, "konu stratejik", {
      overrideGate: false,
    });
    expect(commissionMock).toHaveBeenCalledWith(B, "konu stratejik", {
      overrideGate: true,
    });
  });
});
