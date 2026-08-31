// @vitest-environment node
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { GET } from "@/app/api/health/route";

describe("GET /api/health", () => {
  it("returns 200 with the stable admin identity", async () => {
    const response = GET();

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      status: "ok",
      service: "contentos-admin",
    });
  });

  it("is independent of backend availability", () => {
    const source = readFileSync(
      new URL("../../src/app/api/health/route.ts", import.meta.url),
      "utf8",
    );

    expect(source).not.toContain("contentos-api");
    expect(source).not.toContain("fetch");
    expect(source).not.toContain("@/lib/env");
  });
});
