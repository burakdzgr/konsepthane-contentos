import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
  useSearchParams: vi.fn(),
}));

import { AppNav } from "@/app/nav";
import { usePathname, useSearchParams } from "next/navigation";

const usePathnameMock = vi.mocked(usePathname);
const useSearchParamsMock = vi.mocked(useSearchParams);

function withSearch(params: Record<string, string> = {}) {
  useSearchParamsMock.mockReturnValue(
    new URLSearchParams(params) as unknown as ReturnType<
      typeof useSearchParams
    >,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  withSearch();
});

describe("AppNav", () => {
  it("renders the sectioned sidebar with the control center first", () => {
    usePathnameMock.mockReturnValue("/");
    render(<AppNav />);

    const nav = screen.getByRole("navigation", { name: "Birincil" });
    expect(nav).toBeTruthy();
    expect(screen.getByText("Komuta")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Kontrol Merkezi" })
        .getAttribute("href"),
    ).toBe("/kontrol");
    expect(
      screen.getByRole("link", { name: "Motor" }).getAttribute("href"),
    ).toBe("/motor");
    expect(
      screen.getByRole("link", { name: "Kaynaklar" }).getAttribute("href"),
    ).toBe("/sources");
    expect(
      screen
        .getByRole("link", { name: /Onay Bekleyenler/ })
        .getAttribute("href"),
    ).toBe("/editorial?state=awaiting_human_review");
  });

  it("marks unavailable domains honestly instead of dead links", () => {
    usePathnameMock.mockReturnValue("/");
    render(<AppNav />);

    expect(screen.getByText("Dağıtım (mevcut değil)").tagName).toBe("SPAN");
    expect(screen.getByText("Analitik (mevcut değil)").tagName).toBe("SPAN");
    expect(screen.queryByRole("link", { name: /Dağıtım/ })).toBeNull();
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
      screen
        .getByRole("link", { name: "Kontrol Merkezi" })
        .getAttribute("aria-current"),
    ).toBeNull();
  });

  it("distinguishes filtered editorial entries by their state param", () => {
    usePathnameMock.mockReturnValue("/editorial");
    withSearch({ state: "drafting" });
    render(<AppNav />);

    expect(
      screen
        .getByRole("link", { name: "Taslaklar" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      screen
        .getByRole("link", { name: "Briefler" })
        .getAttribute("aria-current"),
    ).toBeNull();
    expect(
      screen
        .getByRole("link", { name: "İçerikler" })
        .getAttribute("aria-current"),
    ).toBeNull();
  });

  it("keeps Research current on detail pages", () => {
    usePathnameMock.mockReturnValue(
      "/research/0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    );
    render(<AppNav />);

    expect(
      screen
        .getByRole("link", { name: "Araştırma (gelişmiş)" })
        .getAttribute("aria-current"),
    ).toBe("page");
  });
});
