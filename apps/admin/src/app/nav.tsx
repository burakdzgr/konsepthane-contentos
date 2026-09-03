"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Every target page is force-dynamic, so navigation always fetches fresh
// operational data; this client component exists only to mark the current
// page for assistive technology.

const NAV_LINKS = [
  { href: "/motor", label: "Motor" },
  { href: "/", label: "Durum" },
  { href: "/sources", label: "Kaynaklar" },
  { href: "/research", label: "Araştırma Hattı" },
  { href: "/editorial", label: "Editoryal" },
] as const;

function isCurrent(href: string, pathname: string): boolean {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppNav() {
  const pathname = usePathname() ?? "/";
  return (
    <nav className="app-nav" aria-label="Birincil">
      {NAV_LINKS.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          aria-current={isCurrent(link.href, pathname) ? "page" : undefined}
        >
          {link.label}
        </Link>
      ))}
    </nav>
  );
}
