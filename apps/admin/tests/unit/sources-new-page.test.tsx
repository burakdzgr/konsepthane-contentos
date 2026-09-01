import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NewSourcePage from "@/app/sources/new/page";

async function renderPage(params: Record<string, string> = {}) {
  render(await NewSourcePage({ searchParams: Promise.resolve(params) }));
}

describe("Register source page", () => {
  it("renders the minimal registration form with functional kinds only", async () => {
    await renderPage();

    expect(
      screen.getByRole("heading", { name: "Register source" }),
    ).toBeTruthy();
    expect(screen.getByLabelText("Slug")).toBeTruthy();
    expect(screen.getByLabelText("Name")).toBeTruthy();
    expect(screen.getByLabelText("Base URL")).toBeTruthy();
    expect(screen.getByLabelText("Terms notes")).toBeTruthy();

    const kindSelect = screen.getByLabelText("Kind") as HTMLSelectElement;
    const kindValues = Array.from(kindSelect.options)
      .map((option) => option.value)
      .filter((value) => value !== "");
    expect(kindValues).toEqual(["rss_feed", "sitemap", "manual"]);

    const tierSelect = screen.getByLabelText("Trust tier") as HTMLSelectElement;
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
      (screen.getByLabelText("Locale") as HTMLInputElement).defaultValue,
    ).toBe("tr-TR");
    expect(
      (screen.getByLabelText("Market") as HTMLInputElement).defaultValue,
    ).toBe("TR");
    expect(screen.getByText(/does not\s+automatically crawl it/i)).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Register source" }),
    ).toBeTruthy();
  });

  it("shows a bounded error notice from the redirect param", async () => {
    await renderPage({ error: "conflict" });

    expect(screen.getByRole("status").textContent).toMatch(
      /conflicts with the current state/i,
    );
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
