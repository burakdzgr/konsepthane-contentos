import Link from "next/link";

import { TRUST_TIERS } from "@/lib/research-api";
import { REGISTRABLE_SOURCE_KINDS } from "@/lib/research-control-api";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../../notices";
import { registerSourceAction } from "../actions";

export const dynamic = "force-dynamic";

export default async function NewSourcePage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  const params = await searchParams;
  return (
    <section className="panel" aria-labelledby="new-source-title">
      <h1 id="new-source-title">Register source</h1>
      <p className="muted">
        A source is a governed research origin. Registering a source does not
        automatically crawl it: discovery and fetching are separate explicit
        actions.
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
          Name
          <input type="text" name="name" required maxLength={200} />
        </label>
        <label>
          Kind
          <select name="kind" required defaultValue="">
            <option value="" disabled>
              Choose a kind…
            </option>
            {REGISTRABLE_SOURCE_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {kind}
              </option>
            ))}
          </select>
        </label>
        <label>
          Base URL
          <input
            type="url"
            name="base_url"
            required
            maxLength={500}
            placeholder="https://example.com/feed"
          />
        </label>
        <label>
          Trust tier
          <select name="trust_tier" required defaultValue="">
            <option value="" disabled>
              Choose a tier…
            </option>
            {TRUST_TIERS.map((tier) => (
              <option key={tier} value={tier}>
                {tier}
              </option>
            ))}
          </select>
        </label>
        <label>
          Locale
          <input
            type="text"
            name="locale"
            defaultValue="tr-TR"
            maxLength={20}
          />
        </label>
        <label>
          Market
          <input type="text" name="market" defaultValue="TR" maxLength={2} />
        </label>
        <label>
          Terms notes
          <textarea
            name="terms_notes"
            rows={3}
            maxLength={4000}
            placeholder="Terms-of-use / licensing observations for this source"
          />
        </label>
        <button type="submit">Register source</button>
      </form>
      <p className="muted">
        <Link href="/sources">← Back to Sources</Link>
      </p>
    </section>
  );
}
