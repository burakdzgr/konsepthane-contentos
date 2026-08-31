import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { parseServerEnv } from "@/lib/env";

describe("parseServerEnv", () => {
  it("accepts a valid configuration", () => {
    const env = parseServerEnv({
      NODE_ENV: "test",
      CONTENTOS_INTERNAL_API_URL: "http://127.0.0.1:8000",
    });

    expect(env.nodeEnv).toBe("test");
    expect(env.internalApiUrl).toBe("http://127.0.0.1:8000");
  });

  it("falls back to the local backend outside production", () => {
    const env = parseServerEnv({ NODE_ENV: "development" });

    expect(env.internalApiUrl).toBe("http://127.0.0.1:8000");
  });

  it.each(["not-a-url", "ftp://internal-host:21", ""])(
    "rejects the invalid internal API URL %j",
    (invalidUrl) => {
      expect(() =>
        parseServerEnv({
          NODE_ENV: "test",
          CONTENTOS_INTERNAL_API_URL: invalidUrl,
        }),
      ).toThrowError(/CONTENTOS_INTERNAL_API_URL/);
    },
  );

  it("does not echo the rejected value in the error message", () => {
    const rejectedValue = "super-secret-internal-host";

    expect(() =>
      parseServerEnv({
        NODE_ENV: "test",
        CONTENTOS_INTERNAL_API_URL: rejectedValue,
      }),
    ).not.toThrowError(new RegExp(rejectedValue));
  });

  it("requires the internal API URL in production", () => {
    expect(() => parseServerEnv({ NODE_ENV: "production" })).toThrowError(
      /required in production/,
    );
  });
});

describe("internal API URL privacy", () => {
  it("is never represented as NEXT_PUBLIC configuration", () => {
    const inspectedSources = [
      "../../src/lib/env.ts",
      "../../src/lib/contentos-api.ts",
      "../../next.config.ts",
    ];

    for (const relativePath of inspectedSources) {
      const source = readFileSync(
        new URL(relativePath, import.meta.url),
        "utf8",
      );
      expect(source).not.toContain("NEXT_PUBLIC");
    }
  });
});
