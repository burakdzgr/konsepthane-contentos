// @vitest-environment node
import { describe, expect, it } from "vitest";

import { formatUtcTimestamp } from "@/lib/format";

describe("formatUtcTimestamp", () => {
  it("formats an offset timestamp deterministically in UTC", () => {
    expect(formatUtcTimestamp("2026-09-01T12:30:00+00:00")).toBe(
      "2026-09-01 12:30 UTC",
    );
    expect(formatUtcTimestamp("2026-09-01T15:30:00+03:00")).toBe(
      "2026-09-01 12:30 UTC",
    );
  });

  it("formats a naive ISO timestamp as UTC", () => {
    expect(formatUtcTimestamp("2026-01-05T04:05:00Z")).toBe(
      "2026-01-05 04:05 UTC",
    );
  });

  it("renders a placeholder for null, empty, and invalid values", () => {
    expect(formatUtcTimestamp(null)).toBe("—");
    expect(formatUtcTimestamp(undefined)).toBe("—");
    expect(formatUtcTimestamp("")).toBe("—");
    expect(formatUtcTimestamp("not-a-date")).toBe("—");
  });
});
