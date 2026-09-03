"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense } from "react";

// The sidebar navigation: every entry points at a REAL page or a real
// filtered view; capabilities that do not exist yet (distribution,
// analytics) are honestly marked unavailable instead of dead links.

type NavEntry = {
  href: string;
  label: string;
  disabled?: boolean;
};

type NavSection = {
  title: string;
  entries: NavEntry[];
};

const NAV_SECTIONS: NavSection[] = [
  {
    title: "Komuta",
    entries: [
      { href: "/kontrol", label: "Kontrol Merkezi" },
      { href: "/calisma", label: "Çalışmalar" },
      { href: "/firsatlar", label: "Fırsat İncelemesi" },
      { href: "/motor", label: "Motor" },
    ],
  },
  {
    title: "İçerik Hattı",
    entries: [
      { href: "/sources", label: "Kaynaklar" },
      { href: "/editorial", label: "Editoryal" },
      { href: "/editorial?state=drafting", label: "Writer" },
      { href: "/editorial?state=editing", label: "Editor" },
      { href: "/editorial?state=qa_review", label: "QA" },
      { href: "/editorial?state=awaiting_human_review", label: "İnsan Onayı" },
    ],
  },
  {
    title: "Yayın & Sistem",
    entries: [
      { href: "/kontrol#yayin-kuyrugu", label: "Yayın Kuyruğu" },
      { href: "/kontrol#agentlar", label: "Agentlar" },
      { href: "/kontrol#motor-kontrolu", label: "Motor Kontrolü" },
      { href: "/research", label: "Araştırma (gelişmiş)" },
      { href: "/", label: "Sistem" },
      { href: "", label: "Dağıtım (mevcut değil)", disabled: true },
      { href: "", label: "Analitik (mevcut değil)", disabled: true },
    ],
  },
];

function isCurrent(
  entry: NavEntry,
  pathname: string,
  stateParam: string | null,
): boolean {
  const [path, query] = entry.href.split("?");
  const hashless = (path ?? "").split("#")[0] ?? "";
  if (hashless === "" || entry.disabled) {
    return false;
  }
  if (hashless === "/") {
    return pathname === "/";
  }
  const pathMatches =
    pathname === hashless || pathname.startsWith(`${hashless}/`);
  if (!pathMatches) {
    return false;
  }
  // Filtered editorial entries are current only for their exact filter.
  if (hashless === "/editorial") {
    const wanted = query?.startsWith("state=")
      ? query.slice("state=".length)
      : null;
    return wanted === stateParam;
  }
  return !entry.href.includes("#");
}

function SidebarLinks() {
  const pathname = usePathname() ?? "/";
  const searchParams = useSearchParams();
  const stateParam = searchParams?.get("state") ?? null;
  return (
    <nav className="app-nav" aria-label="Birincil">
      {NAV_SECTIONS.map((section) => (
        <div key={section.title} className="nav-section">
          <span className="nav-section-title">{section.title}</span>
          {section.entries.map((entry) =>
            entry.disabled ? (
              <span key={entry.label} className="nav-entry-disabled">
                {entry.label}
              </span>
            ) : (
              <Link
                key={entry.href}
                href={entry.href}
                aria-current={
                  isCurrent(entry, pathname, stateParam) ? "page" : undefined
                }
              >
                {entry.label}
              </Link>
            ),
          )}
        </div>
      ))}
    </nav>
  );
}

export function AppNav() {
  // useSearchParams requires a Suspense boundary during prerender.
  return (
    <Suspense fallback={<nav className="app-nav" aria-label="Birincil" />}>
      <SidebarLinks />
    </Suspense>
  );
}
