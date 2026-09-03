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
  it("renders the primary navigation links with Motor first", () => {
    usePathnameMock.mockReturnValue("/");
    render(<AppNav />);

    const nav = screen.getByRole("navigation", { name: "Birincil" });
    expect(nav).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Motor" }).getAttribute("href"),
    ).toBe("/motor");
    expect(
      screen.getByRole("link", { name: "Durum" }).getAttribute("href"),
    ).toBe("/");
    expect(
      screen.getByRole("link", { name: "Kaynaklar" }).getAttribute("href"),
    ).toBe("/sources");
    expect(
      screen
        .getByRole("link", { name: "Araştırma Hattı" })
        .getAttribute("href"),
    ).toBe("/research");
  });

  it("marks only the current page with aria-current", () => {
    usePathnameMock.mockReturnValue("/sources");
    render(<AppNav />);

    expect(
      screen
        .getByRole("link", { name: "Kaynaklar" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      screen.getByRole("link", { name: "Durum" }).getAttribute("aria-current"),
    ).toBeNull();
  });

  it("keeps Research Pipeline current on detail pages", () => {
    usePathnameMock.mockReturnValue(
      "/research/0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    );
    render(<AppNav />);

    expect(
      screen
        .getByRole("link", { name: "Araştırma Hattı" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      screen.getByRole("link", { name: "Durum" }).getAttribute("aria-current"),
    ).toBeNull();
  });
});
