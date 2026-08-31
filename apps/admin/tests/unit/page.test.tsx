import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import HomePage from "@/app/page";

describe("HomePage", () => {
  it("renders truthful static foundation content", () => {
    render(<HomePage />);

    expect(screen.getByRole("heading", { name: "ContentOS" })).toBeTruthy();
    expect(screen.getByText(/private internal control panel/i)).toBeTruthy();
    expect(
      screen.getByText(/admin foundation environment is running/i),
    ).toBeTruthy();
  });

  it("renders no fake health, status, or metric values", () => {
    render(<HomePage />);
    const text = document.body.textContent ?? "";

    expect(text).not.toMatch(/[0-9]/);
    expect(text).not.toMatch(/healthy|online|ok\b/i);
    expect(text).not.toMatch(/jobs|drafts|posts|users|pending/i);
  });
});
