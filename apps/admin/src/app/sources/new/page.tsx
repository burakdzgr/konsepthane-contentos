import Link from "next/link";

import { TRUST_TIERS } from "@/lib/research-api";
import { REGISTRABLE_SOURCE_KINDS } from "@/lib/research-control-api";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../../notices";
import { registerSourceAction } from "../actions";
import { SourceAddressFields } from "../address-fields";
import { PurposeFields } from "../purpose-fields";

export const dynamic = "force-dynamic";

export default async function NewSourcePage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  const params = await searchParams;
  return (
    <section className="panel" aria-labelledby="new-source-title">
      <h1 id="new-source-title">Kaynak kaydet</h1>
      <p className="muted">
        Kaynak, yönetilen bir araştırma kökenidir. Kaynak kaydetmek onu otomatik
        olarak taramaz: keşif ve getirme ayrı, açıkça başlatılan işlemlerdir.
      </p>
      <ControlNotice
        notice={undefined}
        error={firstParam(params.error)}
        noticeMessages={{}}
      />
      <form action={registerSourceAction} className="stacked-form">
        <label>
          Slug
          <input
            type="text"
            name="slug"
            required
            maxLength={100}
            pattern="[a-z0-9][a-z0-9-]*"
            placeholder="ornek-kaynak"
          />
        </label>
        <label>
          Ad
          <input type="text" name="name" required maxLength={200} />
        </label>
        <SourceAddressFields kinds={REGISTRABLE_SOURCE_KINDS} />
        <label>
          Güven kademesi
          <select name="trust_tier" required defaultValue="">
            <option value="" disabled>
              Kademe seç…
            </option>
            {TRUST_TIERS.map((tier) => (
              <option key={tier} value={tier}>
                {tier}
              </option>
            ))}
          </select>
        </label>
        <PurposeFields />
        <label>
          Yerel ayar
          <input
            type="text"
            name="locale"
            defaultValue="tr-TR"
            maxLength={20}
          />
        </label>
        <label>
          Pazar
          <input type="text" name="market" defaultValue="TR" maxLength={2} />
        </label>
        <label>
          Kullanım şartları notları
          <textarea
            name="terms_notes"
            rows={3}
            maxLength={4000}
            placeholder="Bu kaynak için kullanım şartları / lisans gözlemleri"
          />
        </label>
        <button type="submit">Kaynak kaydet</button>
      </form>
      <p className="muted">
        <Link href="/sources">← Kaynaklara dön</Link>
      </p>
    </section>
  );
}
