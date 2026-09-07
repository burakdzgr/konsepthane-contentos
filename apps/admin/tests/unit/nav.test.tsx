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

beforeEach(() => {
  vi.resetAllMocks();
  useSearchParamsMock.mockReturnValue(
    new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>,
  );
});

describe("AppNav", () => {
  it("renders the compact operator path in reference order", () => {
    usePathnameMock.mockReturnValue("/");
    render(<AppNav badges={{ calisma: 2, firsatlar: 5, onay: 3 }} />);
    expect(
      screen
        .getAllByRole("link")
        .map((link) => link.textContent?.replace(/\d+$/, "").trim()),
    ).toEqual([
      "Kontrol Merkezi",
      "Kaynaklar",
      "Araştırmalar",
      "Çalışmalar",
      "Fikirler",
      "Fırsatlar",
      "İçerikler",
      "Onaylar",
      "Strateji",
      "Performans",
      "Ajanlar",
      "Entegrasyonlar",
      "Sistem",
    ]);
    expect(
      screen.getByRole("link", { name: /Çalışmalar/ }).textContent,
    ).toContain("2");
    expect(screen.getByRole("link", { name: /Onaylar/ }).textContent).toContain(
      "3",
    );
  });

  it("maps labels to real workspaces", () => {
    usePathnameMock.mockReturnValue("/");
    render(<AppNav />);
    expect(
      screen
        .getByRole("link", { name: "Kontrol Merkezi" })
        .getAttribute("href"),
    ).toBe("/kontrol");
    expect(
      screen.getByRole("link", { name: "Kaynaklar" }).getAttribute("href"),
    ).toBe("/sources");
    expect(
      screen.getByRole("link", { name: "Onaylar" }).getAttribute("href"),
    ).toBe("/yayina-hazir");
  });

  it("marks only the current page", () => {
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

  it("keeps internal state filters out of navigation", () => {
    usePathnameMock.mockReturnValue("/editorial");
    useSearchParamsMock.mockReturnValue(
      new URLSearchParams({ state: "drafting" }) as unknown as ReturnType<
        typeof useSearchParams
      >,
    );
    render(<AppNav />);
    expect(screen.queryByRole("link", { name: "Taslaklar" })).toBeNull();
    expect(
      screen
        .getByRole("link", { name: "İçerikler" })
        .getAttribute("aria-current"),
    ).toBeNull();
  });

  it("keeps Çalışmalar current on run details", () => {
    usePathnameMock.mockReturnValue(
      "/calisma/0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0",
    );
    render(<AppNav />);
    expect(
      screen
        .getByRole("link", { name: "Çalışmalar" })
        .getAttribute("aria-current"),
    ).toBe("page");
  });
});
