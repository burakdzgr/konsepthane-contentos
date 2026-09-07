"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AppIcon, type AppIconName } from "./icons";

// The sidebar navigation: every entry points at a REAL page. Count badges
// come from the layout's live dashboard reads; "Benden Bekleyenler" counts
// only genuine human decisions.

export type NavBadges = {
  calisma?: number;
  firsatlar?: number;
  onay?: number;
  yayin?: number;
};

type NavEntry = {
  href: string;
  label: string;
  icon: AppIconName;
  badge?: keyof NavBadges;
  disabled?: boolean;
};

type NavSection = {
  title: string;
  entries: NavEntry[];
};

// Keep the normal operator path deliberately flat. Technical implementation
// pages remain reachable from the System workspace, not from the main rail.
const NAV_SECTIONS: NavSection[] = [
  {
    title: "",
    entries: [
      { href: "/kontrol", label: "Kontrol Merkezi", icon: "home" },
      { href: "/sources", label: "Kaynaklar", icon: "source" },
      {
        href: "/calisma",
        label: "Araştırmalar",
        icon: "search",
        badge: "calisma",
      },
      { href: "/fikirler", label: "Fikirler", icon: "spark" },
      { href: "/firsatlar", label: "Fırsatlar", icon: "research" },
      { href: "/editorial", label: "İçerikler", icon: "content" },
      {
        href: "/yayina-hazir",
        label: "Onaylar",
        icon: "approval",
        badge: "onay",
      },
      { href: "/strateji", label: "Strateji", icon: "agents" },
      { href: "/performans", label: "Performans", icon: "activity" },
      { href: "/motor", label: "Ajanlar", icon: "agents" },
      { href: "/entegrasyonlar", label: "Entegrasyonlar", icon: "health" },
      { href: "/", label: "Sistem", icon: "settings" },
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

function SidebarLinks({ badges }: { badges: NavBadges }) {
  const pathname = usePathname() ?? "/";
  const searchParams = useSearchParams();
  const stateParam = searchParams?.get("state") ?? null;
  return (
    <nav className="app-nav" aria-label="Birincil">
      {NAV_SECTIONS.map((section) => {
        const Container = "div";
        return (
          <Container key={section.title} className="nav-section">
            {section.title !== "" && (
              <span className="nav-section-title">{section.title}</span>
            )}
            {section.entries.map((entry) => {
              if (entry.disabled) {
                return (
                  <span key={entry.label} className="nav-entry-disabled">
                    <AppIcon name={entry.icon} size={16} />
                    <span>{entry.label}</span>
                  </span>
                );
              }
              const count =
                entry.badge !== undefined ? (badges[entry.badge] ?? 0) : 0;
              return (
                <Link
                  key={entry.href}
                  href={entry.href}
                  aria-current={
                    isCurrent(entry, pathname, stateParam) ? "page" : undefined
                  }
                >
                  <AppIcon name={entry.icon} size={16} />
                  <span className="nav-entry-label">{entry.label}</span>
                  {count > 0 && <span className="nav-badge">{count}</span>}
                </Link>
              );
            })}
          </Container>
        );
      })}
    </nav>
  );
}

export function AppNav({ badges = {} }: { badges?: NavBadges }) {
  // useSearchParams requires a Suspense boundary during prerender.
  return (
    <Suspense fallback={<nav className="app-nav" aria-label="Birincil" />}>
      <SidebarLinks badges={badges} />
    </Suspense>
  );
}
