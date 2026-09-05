"use client";

import { useState } from "react";

import { trLabel } from "@/lib/tr-labels";

// "Tür" + "Temel URL" together, because the address the backend expects
// depends on the kind: for an RSS source the backend fetches `base_url`
// itself AS THE FEED, so the operator must enter the feed address, not the
// homepage; for a sitemap source, the sitemap address. The hint is always
// visible; the placeholder follows the chosen kind.

const PLACEHOLDERS: Record<string, string> = {
  rss_feed: "https://site.com/feed",
  sitemap: "https://site.com/sitemap.xml",
  manual: "https://site.com/",
};

const KIND_HINTS: Record<string, string> = {
  rss_feed:
    "RSS için sitenin ana sayfasını değil, besleme adresini yazın; sistem bu adresi doğrudan besleme olarak okur.",
  sitemap: "Site haritası için sitemap.xml adresini yazın.",
  manual:
    "Elle kaynak için sitenin temel adresi yeterlidir; sayfalar tek tek eklenir.",
};

export const ADDRESS_HINT =
  "RSS kaynağı için besleme adresini girin (örn. https://site.com/feed); site haritası için sitemap adresini (örn. https://site.com/sitemap.xml).";

export function SourceAddressFields({ kinds }: { kinds: readonly string[] }) {
  const [kind, setKind] = useState("");
  return (
    <>
      <label>
        Tür
        <select
          name="kind"
          required
          value={kind}
          onChange={(event) => setKind(event.target.value)}
        >
          <option value="" disabled>
            Tür seç…
          </option>
          {kinds.map((value) => (
            <option key={value} value={value}>
              {trLabel(value)}
            </option>
          ))}
        </select>
      </label>
      <label>
        Temel URL
        <input
          type="url"
          name="base_url"
          required
          maxLength={500}
          placeholder={PLACEHOLDERS[kind] ?? "https://site.com/feed"}
        />
      </label>
      <p className="muted purpose-hint" id="base-url-hint">
        {ADDRESS_HINT}
        {KIND_HINTS[kind] !== undefined && ` ${KIND_HINTS[kind]}`}
      </p>
    </>
  );
}
