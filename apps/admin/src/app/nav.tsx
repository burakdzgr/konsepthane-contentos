"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AppIcon, type AppIconName } from "./icons";

// The sidebar navigation: every entry points at a REAL page or a real
// filtered view; capabilities that do not exist yet (distribution,
// analytics) are honestly marked unavailable instead of dead links.
// Count badges come from the layout's live dashboard reads.

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

const NAV_SECTIONS: NavSection[] = [
  {
    title: "Çalışma Alanı",
    entries: [
      { href: "/kontrol", label: "Kontrol Merkezi", icon: "home" },
      {
        href: "/calisma",
        label: "Çalışmalar",
        icon: "activity",
        badge: "calisma",
      },
      { href: "/sources", label: "Kaynaklar", icon: "source" },
    ],
  },
  {
    title: "İçerik",
    entries: [
      {
        href: "/firsatlar",
        label: "Benden Bekleyenler",
        icon: "spark",
        badge: "firsatlar",
      },
      { href: "/editorial", label: "İçerikler", icon: "content" },
      { href: "/strateji", label: "Strateji", icon: "spark" },
    ],
  },
  {
    title: "Sistem",
    entries: [
      { href: "/", label: "Sistem Sağlığı", icon: "health" },
      { href: "/motor", label: "Gelişmiş Motor", icon: "motor" },
      { href: "/research", label: "Teknik Görünümler", icon: "research" },
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
      {NAV_SECTIONS.map((section) => (
        <div key={section.title} className="nav-section">
          <span className="nav-section-title">{section.title}</span>
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
        </div>
      ))}
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
