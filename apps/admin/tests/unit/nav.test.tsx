import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
}));

import { AppNav } from "@/app/nav";
import { usePathname } from "next/navigation";

const usePathnameMock = vi.mocked(usePathname);

beforeEach(() => {
  vi.resetAllMocks();
});

describe("AppNav", () => {
  it("renders the three primary navigation links", () => {
    usePathnameMock.mockReturnValue("/");
    render(<AppNav />);

    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(nav).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Status" }).getAttribute("href"),
    ).toBe("/");
    expect(
      screen.getByRole("link", { name: "Sources" }).getAttribute("href"),
    ).toBe("/sources");
    expect(
      screen
        .getByRole("link", { name: "Research Pipeline" })
        .getAttribute("href"),
    ).toBe("/research");
  });

  it("marks only the current page with aria-current", () => {
    usePathnameMock.mockReturnValue("/sources");
    render(<AppNav />);

    expect(
      screen
        .getByRole("link", { name: "Sources" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      screen.getByRole("link", { name: "Status" }).getAttribute("aria-current"),
    ).toBeNull();
  });

  it("keeps Research Pipeline current on detail pages", () => {
    usePathnameMock.mockReturnValue(
      "/research/0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    );
    render(<AppNav />);

    expect(
      screen
        .getByRole("link", { name: "Research Pipeline" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      screen.getByRole("link", { name: "Status" }).getAttribute("aria-current"),
    ).toBeNull();
  });
});
