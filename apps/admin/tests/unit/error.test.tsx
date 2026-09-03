import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RouteError from "@/app/error";

describe("RouteError", () => {
  it("shows a safe message without raw exception details", () => {
    const error = Object.assign(
      new Error("secret internal explosion at C:\\contentos\\internal\\module"),
      { digest: "digest-123" },
    );

    render(<RouteError error={error} reset={() => {}} />);
    const text = document.body.textContent ?? "";

    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText(/bir şeyler ters gitti/i)).toBeTruthy();
    expect(text).not.toContain("secret internal explosion");
    expect(text).not.toContain("contentos\\internal");
    expect(text).not.toContain("digest-123");
    expect(text).not.toMatch(/at .*:\d+/);
  });

  it("offers a retry action wired to reset", () => {
    const reset = vi.fn();

    render(<RouteError error={new Error("boom")} reset={reset} />);
    fireEvent.click(screen.getByRole("button", { name: /tekrar dene/i }));

    expect(reset).toHaveBeenCalledTimes(1);
  });
});
