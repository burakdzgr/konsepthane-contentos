import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NewSourcePage from "@/app/sources/new/page";

async function renderPage(params: Record<string, string> = {}) {
  render(await NewSourcePage({ searchParams: Promise.resolve(params) }));
}

describe("Register source page", () => {
  it("renders the minimal registration form with functional kinds only", async () => {
    await renderPage();

    expect(screen.getByRole("heading", { name: "Kaynak kaydet" })).toBeTruthy();
    expect(screen.getByLabelText("Slug")).toBeTruthy();
    expect(screen.getByLabelText("Ad")).toBeTruthy();
    expect(screen.getByLabelText("Temel URL")).toBeTruthy();
    expect(screen.getByLabelText("Kullanım şartları notları")).toBeTruthy();

    const kindSelect = screen.getByLabelText("Tür") as HTMLSelectElement;
    const kindValues = Array.from(kindSelect.options)
      .map((option) => option.value)
      .filter((value) => value !== "");
    expect(kindValues).toEqual(["rss_feed", "sitemap", "manual"]);

    const tierSelect = screen.getByLabelText(
      "Güven kademesi",
    ) as HTMLSelectElement;
    const tierValues = Array.from(tierSelect.options)
      .map((option) => option.value)
      .filter((value) => value !== "");
    expect(tierValues).toEqual([
      "official",
      "expert",
      "reputable",
      "general",
      "reference_only",
    ]);

    expect(
      (screen.getByLabelText("Yerel ayar") as HTMLInputElement).defaultValue,
    ).toBe("tr-TR");
    expect(
      (screen.getByLabelText("Pazar") as HTMLInputElement).defaultValue,
    ).toBe("TR");
    expect(screen.getByText(/otomatik olarak taramaz/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Kaynak kaydet" })).toBeTruthy();
  });

  it("shows a bounded error notice from the redirect param", async () => {
    await renderPage({ error: "conflict" });

    // The error text lives in the shared notices module; assert on the
    // bounded error banner's tone rather than its exact wording.
    const status = screen.getByRole("status");
    expect(status.getAttribute("data-tone")).toBe("bad");
    expect(status.textContent).toBeTruthy();
  });

  it("shows no giant JSON textareas or non-functional kinds", async () => {
    await renderPage();
    const names = Array.from(document.querySelectorAll("[name]")).map((el) =>
      el.getAttribute("name"),
    );
    expect(names).not.toContain("metadata");
    expect(names).not.toContain("discovery_config");
    expect(names).not.toContain("fetch_policy");
  });
});
