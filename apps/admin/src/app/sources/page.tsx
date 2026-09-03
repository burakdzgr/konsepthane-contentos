import Link from "next/link";

import {
  DISCOVERY_STRATEGIES,
  SOURCE_KINDS,
  SOURCE_LIFECYCLE_STATES,
  fetchResearchSources,
  type SourceListItem,
} from "@/lib/research-api";
import { formatUtcTimestamp } from "@/lib/format";
import {
  allowedLifecycleTargets,
  isDiscoveryEligible,
} from "@/lib/source-controls";
import {
  buildPageQuery,
  firstParam,
  parseOffset,
  parseSearchText,
  pickEnum,
  type RawSearchParams,
} from "@/lib/search-params";
import { ControlNotice } from "../notices";
import { startIntakeRunAction } from "../calisma/actions";
import { fetchIntakeRuns } from "@/lib/intake-api";
import { transitionSourceLifecycleAction } from "./actions";

const SOURCE_NOTICES: Record<string, string> = {
  "source-registered":
    "Kaynak kaydedildi. Kaynak kaydetmek onu otomatik olarak taramaz.",
  "source-existing": "Aynı kaynak zaten mevcuttu; hiçbir şey değiştirilmedi.",
  "lifecycle-updated": "Kaynak durumu güncellendi.",
  "discovery-queued": "Keşif kuyruğa alındı.",
};

// Operational registry data must reflect the moment of the request.
export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

type SourceFilterState = {
  state?: (typeof SOURCE_LIFECYCLE_STATES)[number];
  kind?: (typeof SOURCE_KINDS)[number];
  strategy?: (typeof DISCOVERY_STRATEGIES)[number];
  q?: string;
  offset: number;
};

function parseFilters(params: RawSearchParams): SourceFilterState {
  return {
    state: pickEnum(params.state, SOURCE_LIFECYCLE_STATES),
    kind: pickEnum(params.kind, SOURCE_KINDS),
    strategy: pickEnum(params.strategy, DISCOVERY_STRATEGIES),
    q: parseSearchText(params.q),
    offset: parseOffset(params.offset),
  };
}

function pageHref(filters: SourceFilterState, offset: number): string {
  return `/sources${buildPageQuery({
    state: filters.state,
    kind: filters.kind,
    strategy: filters.strategy,
    q: filters.q,
    offset: offset > 0 ? offset : undefined,
  })}`;
}

function itemCounts(source: SourceListItem): string {
  const parts: string[] = [];
  if (source.discovered_count > 0)
    parts.push(`${source.discovered_count} yeni`);
  if (source.accepted_count > 0)
    parts.push(`${source.accepted_count} kabul edildi`);
  if (source.fetched_count > 0) parts.push(`${source.fetched_count} getirildi`);
  if (source.fetch_failed_count > 0) {
    parts.push(`${source.fetch_failed_count} başarısız`);
  }
  if (source.rejected_count > 0)
    parts.push(`${source.rejected_count} reddedildi`);
  return parts.join(" · ");
}

function FilterForm({ filters }: { filters: SourceFilterState }) {
  return (
    <form className="filter-form" method="get" action="/sources">
      <label>
        Durum
        <select name="state" defaultValue={filters.state ?? ""}>
          <option value="">Tümü</option>
          {SOURCE_LIFECYCLE_STATES.map((state) => (
            <option key={state} value={state}>
              {state}
            </option>
          ))}
        </select>
      </label>
      <label>
        Tür
        <select name="kind" defaultValue={filters.kind ?? ""}>
          <option value="">Tümü</option>
          {SOURCE_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {kind}
            </option>
          ))}
        </select>
      </label>
      <label>
        Strateji
        <select name="strategy" defaultValue={filters.strategy ?? ""}>
          <option value="">Tümü</option>
          {DISCOVERY_STRATEGIES.map((strategy) => (
            <option key={strategy} value={strategy}>
              {strategy}
            </option>
          ))}
        </select>
      </label>
      <label>
        Ara
        <input
          type="text"
          name="q"
          defaultValue={filters.q ?? ""}
          maxLength={100}
          placeholder="slug veya ad"
        />
      </label>
      <button type="submit">Uygula</button>
    </form>
  );
}

function SourceControls({
  source,
  liveRunId,
}: {
  source: SourceListItem;
  liveRunId: string | null;
}) {
  return (
    <div className="control-stack">
      <form action={transitionSourceLifecycleAction} className="control-form">
        <input type="hidden" name="source_id" value={source.id} />
        <select
          name="new_state"
          required
          defaultValue=""
          aria-label={`${source.slug} için yeni yaşam döngüsü durumu`}
        >
          <option value="" disabled>
            Yeni durum…
          </option>
          {allowedLifecycleTargets(source.lifecycle_state).map((state) => (
            <option key={state} value={state}>
              {state}
            </option>
          ))}
        </select>
        <input
          type="text"
          name="reason"
          required
          maxLength={1000}
          placeholder="gerekçe"
          aria-label={`${source.slug} değişikliği için gerekçe`}
        />
        <button type="submit">Durumu uygula</button>
      </form>
      {liveRunId !== null ? (
        <p className="run-live-link">
          <Link href={`/calisma/${liveRunId}`}>● Aktif çalışmayı aç</Link>
        </p>
      ) : (
        isDiscoveryEligible(source) && (
          <form action={startIntakeRunAction} className="control-form">
            <input type="hidden" name="source_id" value={source.id} />
            <input type="hidden" name="back_to" value="/sources" />
            <button type="submit">Keşfi başlat</button>
          </form>
        )
      )}
    </div>
  );
}

export default async function SourcesPage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>;
}) {
  const params = await searchParams;
  const filters = parseFilters(params);
  const result = await fetchResearchSources({
    lifecycleState: filters.state,
    kind: filters.kind,
    discoveryStrategy: filters.strategy,
    search: filters.q,
    limit: PAGE_SIZE,
    offset: filters.offset,
  });
  const runsResult = await fetchIntakeRuns();
  const liveRuns = new Map<string, string>();
  if (runsResult.kind === "ok") {
    for (const run of runsResult.data.runs) {
      if (run.status === "running" || run.status === "paused") {
        liveRuns.set(run.source_id, run.id);
      }
    }
  }

  return (
    <section className="panel" aria-labelledby="sources-title">
      <h1 id="sources-title">Kaynaklar</h1>
      <p className="muted">
        Yönetilen araştırma kaynakları ve keşif öğesi sayıları.{" "}
        <Link href="/sources/new">Kaynak kaydet</Link>
      </p>
      <ControlNotice
        notice={firstParam(params.notice)}
        error={firstParam(params.error)}
        noticeMessages={SOURCE_NOTICES}
      />
      <FilterForm filters={filters} />
      {result.kind === "unreachable" && (
        <p role="status">Arka uç API&apos;sine şu anda ulaşılamıyor.</p>
      )}
      {result.kind === "malformed" && (
        <p role="status">Arka uç API&apos;si beklenmeyen veri döndürdü.</p>
      )}
      {result.kind === "ok" && result.data.items.length === 0 && (
        <p className="empty-note" role="status">
          Geçerli görünümle eşleşen kaynak yok.
        </p>
      )}
      {result.kind === "ok" && result.data.items.length > 0 && (
        <>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Kaynak</th>
                  <th scope="col">Tür / Strateji</th>
                  <th scope="col">Durum</th>
                  <th scope="col">Güven</th>
                  <th scope="col">Yerel ayar</th>
                  <th scope="col">Keşif öğeleri</th>
                  <th scope="col">Temel URL</th>
                  <th scope="col">Güncellendi</th>
                  <th scope="col">Kontroller</th>
                </tr>
              </thead>
              <tbody>
                {result.data.items.map((source) => (
                  <tr key={source.id}>
                    <td>
                      <span className="cell-primary">{source.name}</span>
                      <span className="mono muted cell-secondary">
                        {source.slug}
                      </span>
                    </td>
                    <td>
                      {source.kind} / {source.discovery_strategy}
                    </td>
                    <td>
                      <span
                        className="badge"
                        data-tone={
                          source.lifecycle_state === "active"
                            ? "ok"
                            : source.lifecycle_state === "blocked"
                              ? "bad"
                              : "warn"
                        }
                      >
                        {source.lifecycle_state}
                      </span>
                    </td>
                    <td>{source.trust_tier}</td>
                    <td>
                      {source.locale} / {source.market}
                    </td>
                    <td>
                      <Link href={`/research?source=${source.id}`}>
                        {source.total_discovery_items} öğe
                      </Link>
                      {source.total_discovery_items > 0 && (
                        <span className="muted cell-secondary">
                          {itemCounts(source)}
                        </span>
                      )}
                    </td>
                    <td className="cell-url" title={source.base_url}>
                      {source.base_url}
                    </td>
                    <td>{formatUtcTimestamp(source.updated_at)}</td>
                    <td>
                      <SourceControls
                        source={source}
                        liveRunId={liveRuns.get(source.id) ?? null}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav className="pagination" aria-label="Kaynaklar sayfalama">
            <span className="muted">
              {filters.offset + 1}–{filters.offset + result.data.items.length} /{" "}
              {result.data.total} gösteriliyor
            </span>
            {filters.offset > 0 && (
              <Link
                href={pageHref(
                  filters,
                  Math.max(filters.offset - PAGE_SIZE, 0),
                )}
              >
                Önceki
              </Link>
            )}
            {filters.offset + result.data.items.length < result.data.total && (
              <Link href={pageHref(filters, filters.offset + PAGE_SIZE)}>
                Sonraki
              </Link>
            )}
          </nav>
        </>
      )}
    </section>
  );
}
