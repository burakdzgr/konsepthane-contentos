"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { AppIcon } from "./icons";
import { logoutAction } from "./login/actions";

type HeaderChromeProps = {
  environment: string | null;
  health: "ok" | "bad" | "unknown";
  user: { displayName: string; roles: string[] } | null;
};

const SEARCH_DESTINATIONS = [
  { label: "Kontrol Merkezi", href: "/kontrol" },
  { label: "Aktif Çalışmalar", href: "/calisma" },
  { label: "Kaynaklar", href: "/sources" },
  { label: "Fırsatlar", href: "/firsatlar" },
  { label: "İçerikler", href: "/editorial" },
  { label: "Briefler", href: "/editorial?state=briefing" },
  { label: "Taslaklar", href: "/editorial?state=drafting" },
  {
    label: "Onay Bekleyenler",
    href: "/editorial?state=awaiting_human_review",
  },
  { label: "Yayınlananlar", href: "/editorial?state=published" },
  { label: "Motor Kontrolü", href: "/motor" },
  { label: "Araştırma", href: "/research" },
  { label: "Sistem Sağlığı", href: "/" },
] as const;

function normalizeSearch(value: string): string {
  return value
    .trim()
    .toLocaleLowerCase("tr-TR")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}

function routeTitle(pathname: string): string {
  if (pathname === "/kontrol") return "Kontrol Merkezi";
  if (pathname.startsWith("/calisma/")) return "Çalışma Detayı";
  if (pathname === "/calisma") return "Aktif Çalışmalar";
  if (pathname.startsWith("/sources")) return "Kaynaklar";
  if (pathname.startsWith("/firsatlar")) return "Fırsatlar";
  if (pathname.startsWith("/editorial")) return "İçerik Pipeline";
  if (pathname.startsWith("/motor")) return "Motor Kontrolü";
  if (pathname.startsWith("/research")) return "Araştırma";
  if (pathname === "/login") return "Giriş";
  return "Sistem Sağlığı";
}

function roleLabel(roles: string[]): string {
  if (roles.includes("operator")) return "Operatör";
  if (roles.includes("reviewer")) return "İncelemeci";
  return roles[0] ?? "Kullanıcı";
}

export function HeaderChrome({ environment, health, user }: HeaderChromeProps) {
  const pathname = usePathname() ?? "/";
  const router = useRouter();
  const [query, setQuery] = useState("");
  const currentTitle = routeTitle(pathname);
  const authenticated = user !== null;

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const wanted = normalizeSearch(query);
    if (wanted === "") return;
    const match = SEARCH_DESTINATIONS.find((item) =>
      normalizeSearch(item.label).includes(wanted),
    );
    if (match !== undefined) {
      router.push(match.href);
      setQuery("");
    }
  }

  return (
    <header className="app-header">
      <div className="app-header-location">
        {authenticated && pathname !== "/kontrol" ? (
          <Link
            href="/kontrol"
            className="header-back"
            aria-label="Kontrol Merkezine dön"
          >
            <AppIcon name="arrow-left" size={18} />
          </Link>
        ) : (
          <span
            className="header-status-dot"
            data-tone={health}
            aria-hidden="true"
          />
        )}
        <span className="header-route-title">{currentTitle}</span>
        {environment !== null && (
          <span className="header-environment">{environment}</span>
        )}
      </div>

      {authenticated && (
        <div className="app-header-tools">
          <form className="header-search" role="search" onSubmit={submitSearch}>
            <AppIcon name="search" size={16} />
            <input
              aria-label="Sayfalarda ara"
              list="contentos-destinations"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Ara..."
              value={query}
            />
            <datalist id="contentos-destinations">
              {SEARCH_DESTINATIONS.map((item) => (
                <option key={item.href} value={item.label} />
              ))}
            </datalist>
          </form>

          <nav className="header-shortcuts" aria-label="Hızlı erişim">
            <Link
              href="/kontrol"
              aria-label="Bekleyen kararlar"
              title="Bekleyen kararlar"
            >
              <AppIcon name="bell" size={17} />
            </Link>
            <Link
              href="/calisma"
              aria-label="Canlı çalışmalar"
              title="Canlı çalışmalar"
            >
              <AppIcon name="activity" size={17} />
            </Link>
            <Link href="/" aria-label="Sistem sağlığı" title="Sistem sağlığı">
              <AppIcon name="health" size={17} />
            </Link>
          </nav>

          <details className="user-menu">
            <summary>
              <span className="user-avatar">
                {user.displayName.slice(0, 1).toLocaleUpperCase("tr-TR")}
              </span>
              <span className="user-copy">
                <strong>{user.displayName}</strong>
                <small>{roleLabel(user.roles)}</small>
              </span>
              <AppIcon name="chevron-down" size={14} />
            </summary>
            <div className="user-menu-popover">
              <span>{user.displayName}</span>
              <small>{user.roles.join(", ")}</small>
              <form action={logoutAction}>
                <button type="submit">Çıkış yap</button>
              </form>
            </div>
          </details>
        </div>
      )}
    </header>
  );
}
