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
    expect(screen.getByText("Çalışma Alanı")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Kontrol Merkezi" })
        .getAttribute("href"),
    ).toBe("/kontrol");
    expect(
      screen.getByRole("link", { name: "Strateji" }).getAttribute("href"),
    ).toBe("/strateji");
    expect(
      screen.getByRole("link", { name: "Kaynaklar" }).getAttribute("href"),
    ).toBe("/sources");
    expect(
      screen
        .getByRole("link", { name: /Benden Bekleyenler/ })
        .getAttribute("href"),
    ).toBe("/firsatlar");
  });

  it("lists the operator's path in flow order, then the system section", () => {
    usePathnameMock.mockReturnValue("/");
    render(<AppNav badges={{ calisma: 2, firsatlar: 5 }} />);

    const labels = screen
      .getAllByRole("link")
      .map((link) => link.textContent?.replace(/\d+$/, "").trim());
    expect(labels).toEqual([
      "Kontrol Merkezi",
      "Çalışmalar",
      "Kaynaklar",
      "Fikirler",
      "İçerikler",
      "Benden Bekleyenler",
      "Strateji",
      "Performans",
      "Entegrasyonlar",
      "Sistem Sağlığı",
      "Canlı Operasyon",
      "Gelişmiş Motor",
      "Teknik Görünümler",
    ]);
    expect(
      screen.getByRole("link", { name: "Fikirler" }).getAttribute("href"),
    ).toBe("/fikirler");
    expect(
      screen.getByRole("link", { name: "Performans" }).getAttribute("href"),
    ).toBe("/performans");
    expect(
      screen.getByRole("link", { name: "Entegrasyonlar" }).getAttribute("href"),
    ).toBe("/entegrasyonlar");
    // Badges: live runs and genuine human decisions only.
    expect(
      screen.getByRole("link", { name: /Çalışmalar/ }).textContent,
    ).toContain("2");
    expect(
      screen.getByRole("link", { name: /Benden Bekleyenler/ }).textContent,
    ).toContain("5");
  });

  it("moves technical operations under the system section", () => {
    usePathnameMock.mockReturnValue("/");
    render(<AppNav />);

    expect(screen.getByText("Sistem")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Gelişmiş Motor" })).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Teknik Görünümler" }),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Canlı Operasyon" })
        .getAttribute("href"),
    ).toBe("/operasyon");
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

  it("keeps detailed state filters out of the primary navigation", () => {
    usePathnameMock.mockReturnValue("/editorial");
    withSearch({ state: "drafting" });
    render(<AppNav />);

    expect(screen.queryByRole("link", { name: "Taslaklar" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Briefler" })).toBeNull();
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
        .getByRole("link", { name: "Teknik Görünümler" })
        .getAttribute("aria-current"),
    ).toBe("page");
  });
});
