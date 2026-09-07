"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { AppIcon } from "./icons";
import { logoutAction } from "./login/actions";

type HeaderChromeProps = {
  environment: string | null;
  health: "ok" | "bad" | "unknown";
  user: { displayName: string; roles: string[] } | null;
};

const SEARCH_DESTINATIONS = [
  { label: "İçerik Botu", href: "/bot" },
  { label: "Yayına Hazır", href: "/yayina-hazir" },
  { label: "Kontrol Merkezi", href: "/kontrol" },
  { label: "Nasıl Kullanırım?", href: "/baslangic" },
  { label: "Çalışmalar", href: "/calisma" },
  { label: "Kaynaklar", href: "/sources" },
  { label: "Fikirler", href: "/fikirler" },
  { label: "Benden Bekleyenler", href: "/firsatlar" },
  { label: "İçerikler", href: "/editorial" },
  { label: "Strateji", href: "/strateji" },
  { label: "Performans", href: "/performans" },
  { label: "Entegrasyonlar", href: "/entegrasyonlar" },
  { label: "Canlı Operasyon", href: "/operasyon" },
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

function roleLabel(roles: string[]): string {
  if (roles.includes("operator")) return "Operatör";
  if (roles.includes("reviewer")) return "İncelemeci";
  return roles[0] ?? "Kullanıcı";
}

export function HeaderChrome({ user }: HeaderChromeProps) {
  const router = useRouter();
  const [query, setQuery] = useState("");
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
        <form className="header-search" role="search" onSubmit={submitSearch}>
          <AppIcon name="search" size={19} />
          <input
            aria-label="Sayfalarda ara"
            list="contentos-destinations"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="İçerik, kaynak, fikir ara..."
            value={query}
          />
          <kbd>Ctrl + K</kbd>
          <datalist id="contentos-destinations">
            {SEARCH_DESTINATIONS.map((item) => (
              <option key={item.href} value={item.label} />
            ))}
          </datalist>
        </form>
      </div>

      {authenticated && (
        <div className="app-header-tools">
          <span className="production-pill">
            <span />
            Üretim Ortamı
            <AppIcon name="chevron-down" size={13} />
          </span>

          <nav className="header-shortcuts" aria-label="Hızlı erişim">
            <Link
              href="/yayina-hazir"
              aria-label="Yayına hazır içerikler"
              title="Yayına hazır içerikler"
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
