import Link from "next/link";

import {
  DISCOVERY_STRATEGIES,
  SOURCE_KINDS,
  SOURCE_LIFECYCLE_STATES,
  fetchResearchSources,
  type SourceListItem,
} from "@/lib/research-api";
import { trLabel } from "@/lib/tr-labels";
import { capabilityLabel, roleLabel } from "@/lib/source-purpose";
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
import {
  transitionSourceLifecycleAction,
  updateSourcePurposeAction,
} from "./actions";
import { PurposeFields } from "./purpose-fields";

const SOURCE_NOTICES: Record<string, string> = {
  "source-registered":
    "Kaynak kaydedildi. Kaynak kaydetmek onu otomatik olarak taramaz.",
  "source-existing": "Aynı kaynak zaten mevcuttu; hiçbir şey değiştirilmedi.",
  "lifecycle-updated": "Kaynak durumu güncellendi.",
  "purpose-updated": "Kaynağın amacı güncellendi.",
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
              {trLabel(state)}
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
              {trLabel(kind)}
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
              {trLabel(strategy)}
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
              {trLabel(state)}
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
      <details className="purpose-editor">
        <summary>Amacı düzenle</summary>
        <form action={updateSourcePurposeAction} className="stacked-form">
          <input type="hidden" name="source_id" value={source.id} />
          <PurposeFields
            primaryRole={source.primary_role}
            capabilities={source.capabilities}
            label={source.slug}
          />
          <button type="submit">Amacı kaydet</button>
        </form>
      </details>
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
  const selectedSource =
    result.kind === "ok"
      ? (result.data.items.find(
          (source) => source.slug === "karas-party-ideas",
        ) ?? result.data.items[0])
      : undefined;

  return (
    <section className="source-page" aria-labelledby="sources-title">
      <header className="page-heading source-heading">
        <div>
          <h1 id="sources-title">Kaynaklar</h1>
          <p>
            İlham veren, trendleri yakalayan ve pazar sinyalleri sunan içerik
            kaynaklarını yönetin.
          </p>
        </div>
        <Link className="button-link source-add-button" href="/sources/new">
          ＋ Kaynak Ekle
        </Link>
      </header>
      <ControlNotice
        notice={firstParam(params.notice)}
        error={firstParam(params.error)}
        noticeMessages={SOURCE_NOTICES}
      />
      <div className="source-toolbar">
        <FilterForm filters={filters} />
      </div>
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
          <div className="source-workspace">
            <div className="table-scroll source-table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Kaynak</th>
                    <th scope="col">Tür</th>
                    <th scope="col">Roller</th>
                    <th scope="col">Durum</th>
                    <th scope="col">Sinyaller</th>
                    <th scope="col">İşlemler</th>
                  </tr>
                </thead>
                <tbody>
                  {result.data.items.map((source) => (
                    <tr
                      key={source.id}
                      className={
                        source.id === selectedSource?.id
                          ? "source-row-selected"
                          : undefined
                      }
                    >
                      <td>
                        <span className="source-monogram" aria-hidden="true">
                          {source.name.slice(0, 2).toLocaleUpperCase("tr-TR")}
                        </span>
                        <span className="source-name-copy">
                          <span className="cell-primary">{source.name}</span>
                          <span className="mono muted cell-secondary">
                            {source.slug}
                          </span>
                        </span>
                      </td>
                      <td>◉ {trLabel(source.kind)}</td>
                      <td>
                        <span className="badge" data-tone="info">
                          {roleLabel(source.primary_role)}
                        </span>
                        <span className="purpose-badges">
                          {source.capabilities.map((capability) => (
                            <span
                              key={capability}
                              className="badge purpose-badge"
                              data-tone="idle"
                            >
                              {capabilityLabel(capability)}
                            </span>
                          ))}
                        </span>
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
                          {trLabel(source.lifecycle_state)}
                        </span>
                      </td>
                      <td>
                        <Link href={`/research?source=${source.id}`}>
                          <strong className="source-signal-count">
                            ▥ {source.total_discovery_items} öğe
                          </strong>
                        </Link>
                        {source.total_discovery_items > 0 && (
                          <span className="muted cell-secondary">
                            {itemCounts(source)}
                          </span>
                        )}
                      </td>
                      <td>
                        <details className="source-actions">
                          <summary aria-label={`${source.name} işlemleri`}>
                            •••
                          </summary>
                          <div className="source-actions-popover">
                            <SourceControls
                              source={source}
                              liveRunId={liveRuns.get(source.id) ?? null}
                            />
                          </div>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(() => {
              const source = selectedSource!;
              return (
                <aside className="source-detail-card">
                  <div className="source-detail-head">
                    <span className="source-monogram source-monogram-large">
                      {source.name.slice(0, 2).toLocaleUpperCase("tr-TR")}
                    </span>
                    <div>
                      <h2>{source.name}</h2>
                      <a
                        href={source.base_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {source.base_url} ↗
                      </a>
                    </div>
                  </div>
                  <p>
                    Konsepthane için fikir, eğilim ve içerik sinyalleri sağlayan
                    araştırma kaynağı.
                  </p>
                  <div className="purpose-badges">
                    <span className="badge" data-tone="info">
                      {roleLabel(source.primary_role)}
                    </span>
                    {source.capabilities.map((capability) => (
                      <span
                        key={capability}
                        className="badge purpose-badge"
                        data-tone="ok"
                      >
                        {capabilityLabel(capability)}
                      </span>
                    ))}
                  </div>
                  <div className="source-detail-stats">
                    <span>
                      <strong>{source.total_discovery_items}</strong>Toplam
                      sinyal
                    </span>
                    <span>
                      <strong>{source.fetched_count}</strong>Getirilen
                    </span>
                    <span>
                      <strong>{source.accepted_count}</strong>Kabul edilen
                    </span>
                  </div>
                  <dl className="source-facts">
                    <div>
                      <dt>Kaynak türü</dt>
                      <dd>{trLabel(source.kind)}</dd>
                    </div>
                    <div>
                      <dt>Tarama yöntemi</dt>
                      <dd>{trLabel(source.discovery_strategy)}</dd>
                    </div>
                    <div>
                      <dt>Durum</dt>
                      <dd>
                        <span
                          className="badge"
                          data-tone={
                            source.lifecycle_state === "active" ? "ok" : "warn"
                          }
                        >
                          {trLabel(source.lifecycle_state)}
                        </span>
                      </dd>
                    </div>
                    <div>
                      <dt>Son güncelleme</dt>
                      <dd>{formatUtcTimestamp(source.updated_at)}</dd>
                    </div>
                    <div>
                      <dt>Pazar</dt>
                      <dd>
                        {source.locale} / {source.market}
                      </dd>
                    </div>
                    <div>
                      <dt>Güven</dt>
                      <dd>{trLabel(source.trust_tier)}</dd>
                    </div>
                  </dl>
                  <div className="source-detail-actions">
                    <Link
                      className="button-link"
                      href={`/research?source=${source.id}`}
                    >
                      Sinyalleri incele
                    </Link>
                    {liveRuns.get(source.id) !== undefined && (
                      <Link href={`/calisma/${liveRuns.get(source.id)}`}>
                        Aktif çalışmayı aç
                      </Link>
                    )}
                  </div>
                </aside>
              );
            })()}
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
