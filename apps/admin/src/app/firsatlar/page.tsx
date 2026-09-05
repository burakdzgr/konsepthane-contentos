import Link from "next/link";

import { fetchWorkQueue, type WorkQueueRow } from "@/lib/editorial-api";
import { formatUtcTimestamp } from "@/lib/format";
import {
  fetchRefreshOpportunities,
  fetchStrategySuggestions,
  type RefreshOpportunity,
  type StrategySuggestion,
} from "@/lib/performance-api";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { trLabel, trList } from "@/lib/tr-labels";
import { ControlNotice } from "../notices";
import { AutoRefresh } from "../kontrol/refresh";
import {
  commissionOpportunityAction,
  rejectOpportunityAction,
} from "../editorial/[id]/actions";
import { RefreshCard, SuggestionCard } from "../performans/cards";
import { bulkCommissionAction, bulkRejectAction } from "./actions";
import { OpportunityIntelligence, RECOMMENDATION } from "./intelligence";
import {
  INBOX_GROUP_HINTS,
  INBOX_GROUP_LABELS,
  INBOX_GROUPS,
  inboxGroupOf,
  matchesInboxFilters,
  parseInboxFilters,
  RECOMMENDATION_FILTER_LABELS,
  RECOMMENDATION_FILTERS,
  type InboxFilters,
  type InboxGroup,
} from "./filters";

// The human inbox. Four genuine decisions and nothing mechanical: the
// production decision ("should Konsepthane produce content on this
// topic?", asked only after the machine finished discovery, prefilter,
// fetch, normalization, deduplication and explainable scoring), the final
// publication approval, the refresh decision on declining content, and the
// strategy suggestion. The three later groups appear above the inbox only
// while they have something to decide.
export const dynamic = "force-dynamic";

const NOTICES: Record<string, string> = {};

const BULK_FORM_ID = "toplu-islem";

// Why the backend would refuse commissioning right now. The card mirrors
// the domain gate (`commission_eligible`) instead of guessing from the
// recommendation badge, so an operator never meets a 409 after clicking.
function commissionBlockedNote(row: WorkQueueRow): string {
  if (row.disposition !== "open" || row.current_state !== "idea_scoring") {
    return "Üretim kararı bu aşamada verilemez.";
  }
  if (row.score_eligibility === null) {
    return (
      "Üretim onayı kapalı: kaynak tabanı henüz puanlanmadı. Skor olmadan " +
      "görevlendirme yapılamaz."
    );
  }
  const missing =
    row.score_missing_signals.length > 0
      ? ` Eksik sinyaller: ${trList(row.score_missing_signals)}.`
      : "";
  return (
    `Üretim onayı kapalı: kaynak tabanı ${trLabel(row.score_band)} / ` +
    `${trLabel(row.score_eligibility)}.${missing} ` +
    "Bu skor konunun değerini değil kaynak kalitesini ölçer (güncellik, " +
    "kaynak sayısı, kaynak güveni, kanıt). Yeni araştırma girdisi ve " +
    "yeniden değerlendirme gerekir."
  );
}

function OpportunityCard({ row }: { row: WorkQueueRow }) {
  const recommendation =
    row.recommendation !== null
      ? (RECOMMENDATION[row.recommendation] ?? null)
      : null;
  const decidable =
    row.opportunity_id !== null && row.recommendation !== "continue_research";
  return (
    <article
      className="opportunity-card"
      data-commission-eligible={row.commission_eligible ? "true" : "false"}
    >
      <header className="agent-card-header">
        {decidable && (
          <input
            type="checkbox"
            name="secili"
            value={row.opportunity_id ?? ""}
            form={BULK_FORM_ID}
            className="opportunity-select"
            aria-label={`${row.title_working_label} toplu işlem için seç`}
          />
        )}
        <h3>
          <Link href={`/editorial/${row.work_item_id}`}>
            {row.title_working_label}
          </Link>
        </h3>
        {recommendation !== null ? (
          <span className="badge" data-tone={recommendation.tone}>
            {recommendation.label}
          </span>
        ) : (
          <span className="badge">DEĞERLENDİRİLİYOR</span>
        )}
        <span
          className="badge"
          data-tone={row.commission_eligible ? "ok" : "neutral"}
        >
          {row.commission_eligible
            ? "ONAYLANABİLİR"
            : row.commission_override_possible
              ? "GEREKÇEYLE ÜRETİLEBİLİR"
              : "ONAY KAPALI"}
        </span>
      </header>
      {row.topic_summary !== null && <p>{row.topic_summary}</p>}
      {row.intelligence !== null ? (
        // The header badge IS the system recommendation; the sections
        // explain it and the "Neden?" sentence names the concrete bases.
        <OpportunityIntelligence
          intelligence={row.intelligence}
          showVerdict={false}
        />
      ) : (
        <p className="muted">
          Fırsat istihbaratı henüz hesaplanmadı; değerlendirme tamamlandığında
          bölümler burada görünür.
        </p>
      )}
      <p className="muted">
        Kaynak tabanı:{" "}
        <strong title="Güncellik, kaynak sayısı, kaynak güveni ve kanıt miktarından hesaplanan deterministik skor; konunun değerini değil kaynak kalitesini ölçer. Görevlendirme kapısı yalnızca buna bakar.">
          {row.score_eligibility === null
            ? "Henüz yok"
            : `${trLabel(row.score_band)} / ${trLabel(row.score_eligibility)}`}
        </strong>{" "}
        · {row.inspiration_signal_count} kaynak sinyali ·{" "}
        {row.inspiration_concept_count} gruplanmış fikir · Değerlendirildi:{" "}
        {row.score_evaluated_at !== null
          ? formatUtcTimestamp(row.score_evaluated_at)
          : "henüz değil"}
      </p>
      {row.score_risk_flags.length > 0 && (
        <p className="muted">Risk işaretleri: {trList(row.score_risk_flags)}</p>
      )}
      {recommendation !== null && (
        <p className="muted">{recommendation.hint}</p>
      )}
      <div className="opportunity-actions">
        <Link href={`/editorial/${row.work_item_id}`}>İncele</Link>
        {decidable && row.opportunity_id !== null && (
          <>
            {row.commission_eligible ? (
              <form
                action={commissionOpportunityAction}
                className="control-form"
              >
                <input
                  type="hidden"
                  name="work_item_id"
                  value={row.work_item_id}
                />
                <input
                  type="hidden"
                  name="opportunity_id"
                  value={row.opportunity_id}
                />
                <input
                  type="text"
                  name="reason"
                  required
                  placeholder="üretim gerekçesi"
                  aria-label={`${row.title_working_label} üretim gerekçesi`}
                />
                <button type="submit">İçerik üretimini onayla</button>
              </form>
            ) : (
              <p className="muted" role="note">
                {commissionBlockedNote(row)}
              </p>
            )}
            {!row.commission_eligible && row.commission_override_possible && (
              // ADR 0010: the human is the topic judge. The override is an
              // explicit, reasoned, recorded decision — never the default.
              <form
                action={commissionOpportunityAction}
                className="control-form"
              >
                <input
                  type="hidden"
                  name="work_item_id"
                  value={row.work_item_id}
                />
                <input
                  type="hidden"
                  name="opportunity_id"
                  value={row.opportunity_id}
                />
                <input type="hidden" name="override_gate" value="true" />
                <input
                  type="text"
                  name="reason"
                  required
                  placeholder="konu neden buna değer (kapı aşımı gerekçesi)"
                  aria-label={`${row.title_working_label} kapı aşımı gerekçesi`}
                />
                <button type="submit">Yine de içerik üret</button>
                <span className="muted">
                  Kaynak tabanı kapısını gerekçeyle aşar; aşım karar geçmişine
                  kaydedilir.
                </span>
              </form>
            )}
            <form action={rejectOpportunityAction} className="control-form">
              <input
                type="hidden"
                name="work_item_id"
                value={row.work_item_id}
              />
              <input
                type="hidden"
                name="opportunity_id"
                value={row.opportunity_id}
              />
              <input
                type="text"
                name="reason"
                required
                placeholder="ret gerekçesi"
                aria-label={`${row.title_working_label} ret gerekçesi`}
              />
              <button type="submit">Reddet</button>
            </form>
          </>
        )}
      </div>
    </article>
  );
}

type GroupCounts = Record<InboxGroup, number>;

type OtherDecisions = {
  approvals: WorkQueueRow[] | null;
  refreshes: RefreshOpportunity[] | null;
  suggestions: StrategySuggestion[] | null;
};

function PublicationApprovals({ rows }: { rows: WorkQueueRow[] }) {
  return (
    <section
      id="yayin-onayi"
      className="decision-group"
      aria-labelledby="yayin-onayi-baslik"
    >
      <h2 id="yayin-onayi-baslik">Yayın onayı bekleyen ({rows.length})</h2>
      <p className="muted">
        Hazırlanan paket yayınlansın mı? Nihai onay yalnızca adlandırılmış bir
        insandan gelir; içerik onaysız yayınlanmaz.
      </p>
      <ul className="plain-list">
        {rows.map((row) => (
          <li key={row.work_item_id}>
            <Link href={`/editorial/${row.work_item_id}`}>
              {row.title_working_label}
            </Link>{" "}
            <span className="muted">
              · {trLabel(row.current_state)} ·{" "}
              {formatUtcTimestamp(row.current_state_entered_at)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RefreshDecisions({ rows }: { rows: RefreshOpportunity[] }) {
  return (
    <section
      id="guncelleme"
      className="decision-group"
      aria-labelledby="guncelleme-baslik"
    >
      <h2 id="guncelleme-baslik">Güncelleme kararı bekleyen ({rows.length})</h2>
      <p className="muted">
        Düşen ya da eskiyen yayınlar için teşhis ve öneri. Onay yalnızca yeniden
        araştırmayı başlatır; yayın kararı yine ayrıca sorulur.
      </p>
      {rows.map((row) => (
        <RefreshCard key={row.id} row={row} returnTo="/firsatlar" />
      ))}
    </section>
  );
}

function StrategyDecisions({ rows }: { rows: StrategySuggestion[] }) {
  return (
    <section
      id="strateji"
      className="decision-group"
      aria-labelledby="strateji-baslik"
    >
      <h2 id="strateji-baslik">Strateji önerileri ({rows.length})</h2>
      <p className="muted">
        Gerçek performans verisinden türetilen öneriler. Strateji yalnızca sizin
        kararınızla değişir.
      </p>
      {rows.map((row) => (
        <SuggestionCard key={row.id} row={row} returnTo="/firsatlar" />
      ))}
    </section>
  );
}

function OtherDecisionGroups({ other }: { other: OtherDecisions }) {
  const approvals = other.approvals ?? [];
  const refreshes = other.refreshes ?? [];
  const suggestions = other.suggestions ?? [];
  if (
    approvals.length === 0 &&
    refreshes.length === 0 &&
    suggestions.length === 0
  ) {
    return null;
  }
  return (
    <div className="decision-groups">
      {approvals.length > 0 && <PublicationApprovals rows={approvals} />}
      {refreshes.length > 0 && <RefreshDecisions rows={refreshes} />}
      {suggestions.length > 0 && <StrategyDecisions rows={suggestions} />}
    </div>
  );
}

function GroupTabs({
  filters,
  counts,
  other,
}: {
  filters: InboxFilters;
  counts: GroupCounts;
  other: OtherDecisions;
}) {
  const extra: Array<{ href: string; label: string; count: number }> = [
    {
      href: "#yayin-onayi",
      label: "Yayın onayı",
      count: other.approvals?.length ?? 0,
    },
    {
      href: "#guncelleme",
      label: "Güncelleme kararı",
      count: other.refreshes?.length ?? 0,
    },
    {
      href: "#strateji",
      label: "Strateji önerisi",
      count: other.suggestions?.length ?? 0,
    },
  ].filter((entry) => entry.count > 0);
  return (
    <nav className="inbox-tabs" aria-label="Fırsat grupları">
      {extra.map((entry) => (
        <Link key={entry.href} href={`/firsatlar${entry.href}`}>
          {entry.label} ({entry.count})
        </Link>
      ))}
      {INBOX_GROUPS.map((group) => {
        const href =
          `/firsatlar?durum=${group}` +
          (filters.oneri !== undefined ? `&oneri=${filters.oneri}` : "");
        return (
          <Link
            key={group}
            href={href}
            aria-current={filters.durum === group ? "page" : undefined}
            title={INBOX_GROUP_HINTS[group]}
          >
            {INBOX_GROUP_LABELS[group]} ({counts[group]})
          </Link>
        );
      })}
    </nav>
  );
}

function FilterForm({ filters }: { filters: InboxFilters }) {
  return (
    <form
      className="filter-form"
      method="get"
      action="/firsatlar"
      aria-label="Fırsat filtreleri"
    >
      <input type="hidden" name="durum" value={filters.durum} />
      <label>
        Sistem önerisi
        <select name="oneri" defaultValue={filters.oneri ?? ""}>
          <option value="">Tümü</option>
          {RECOMMENDATION_FILTERS.map((value) => (
            <option key={value} value={value}>
              {RECOMMENDATION_FILTER_LABELS[value]}
            </option>
          ))}
        </select>
      </label>
      <button type="submit">Filtrele</button>
      {filters.oneri !== undefined && (
        <Link href={`/firsatlar?durum=${filters.durum}`}>
          Öneri filtresini temizle
        </Link>
      )}
    </form>
  );
}

// One shared reason, one explicit scope, two explicit decisions. The
// checkboxes on the cards belong to this form via the `form` attribute, so
// the whole thing works without client JavaScript.
function BulkActionForm({
  rows,
  filters,
}: {
  rows: WorkQueueRow[];
  filters: InboxFilters;
}) {
  const decidable = rows.filter(
    (row) =>
      row.opportunity_id !== null && row.recommendation !== "continue_research",
  );
  const eligible = decidable.filter((row) => row.commission_eligible);
  const overridable = decidable.filter(
    (row) => !row.commission_eligible && row.commission_override_possible,
  );
  return (
    <form
      id={BULK_FORM_ID}
      className="control-form bulk-form"
      aria-label="Toplu işlem"
    >
      <input type="hidden" name="durum" value={filters.durum} />
      <input type="hidden" name="oneri" value={filters.oneri ?? ""} />
      {decidable.map((row) => (
        <input
          key={row.opportunity_id}
          type="hidden"
          name="listelenen"
          value={row.opportunity_id ?? ""}
        />
      ))}
      {eligible.map((row) => (
        <input
          key={row.opportunity_id}
          type="hidden"
          name="onaylanabilir"
          value={row.opportunity_id ?? ""}
        />
      ))}
      {overridable.map((row) => (
        <input
          key={row.opportunity_id}
          type="hidden"
          name="asilabilir"
          value={row.opportunity_id ?? ""}
        />
      ))}
      {overridable.map((row) => (
        <input
          key={row.opportunity_id}
          type="hidden"
          name="asilabilir"
          value={row.opportunity_id ?? ""}
        />
      ))}
      <strong>Toplu işlem</strong>
      <label>
        <input type="radio" name="kapsam" value="secili" defaultChecked />{" "}
        Yalnızca işaretlediğim kartlar
      </label>
      <label>
        <input type="radio" name="kapsam" value="listelenen" /> Listelenen{" "}
        {decidable.length} kartın tümü
      </label>
      <input
        type="text"
        name="reason"
        required
        maxLength={1000}
        placeholder="ortak gerekçe (her karara kaydedilir)"
        aria-label="Toplu işlem gerekçesi"
      />
      <button type="submit" formAction={bulkRejectAction}>
        Seçilenleri reddet
      </button>
      <button
        type="submit"
        formAction={bulkCommissionAction}
        disabled={eligible.length === 0 && overridable.length === 0}
        title={
          eligible.length === 0 && overridable.length === 0
            ? "Listelenen kartların hiçbiri puanlanmış değil."
            : undefined
        }
      >
        Seçilenleri onayla ({eligible.length} uygun
        {overridable.length > 0 ? `, ${overridable.length} aşımla` : ""})
      </button>
      {overridable.length > 0 && (
        <label>
          <input type="checkbox" name="override_gate" value="true" /> Kaynak
          tabanı kapısını gerekçeyle aş (aşım karar geçmişine kaydedilir)
        </label>
      )}
      <span className="muted">
        Her kart ayrı ayrı, aynı gerekçeyle karara bağlanır; onay yalnızca
        görevlendirilebilir skoru olan kartlara, kapı aşımı işaretliyse
        puanlanmış diğer kartlara da gönderilir.
      </span>
    </form>
  );
}

function BulkOutcomeNotice({ query }: { query: RawSearchParams }) {
  const kind = firstParam(query.toplu);
  if (kind !== "ret" && kind !== "onay") {
    return null;
  }
  const count = (name: string): number => {
    const raw = firstParam(query[name]);
    return raw !== undefined && /^\d{1,3}$/.test(raw) ? Number(raw) : 0;
  };
  const verb = kind === "ret" ? "reddedildi" : "onaylandı";
  const parts = [`${count("basarili")} fırsat ${verb}`];
  if (count("atlanan") > 0) {
    parts.push(
      `${count("atlanan")} kart görevlendirilebilir skoru olmadığı için atlandı (kapı aşımı işaretlenmedi ya da kart puanlanmamış)`,
    );
  }
  if (count("celisen") > 0) {
    parts.push(
      `${count("celisen")} kart arka uçtaki güncel durumla çeliştiği için reddedildi`,
    );
  }
  if (count("hatali") > 0) {
    parts.push(`${count("hatali")} kartta hata oluştu`);
  }
  const tone = count("celisen") + count("hatali") > 0 ? "bad" : "ok";
  return (
    <p className="notice" data-tone={tone} role="status">
      Toplu işlem tamamlandı: {parts.join("; ")}.
    </p>
  );
}

export default async function OpportunityReviewPage({
  searchParams,
}: {
  searchParams?: Promise<RawSearchParams>;
}) {
  const query = searchParams === undefined ? {} : await searchParams;
  const filters = parseInboxFilters(query);
  const [result, approvalsResult, refreshResult, suggestionResult] =
    await Promise.all([
      fetchWorkQueue({
        workflowState: "idea_scoring",
        opportunityDisposition: "open",
        limit: 50,
      }),
      fetchWorkQueue({ workflowState: "awaiting_human_review", limit: 50 }),
      fetchRefreshOpportunities("proposed"),
      fetchStrategySuggestions("proposed"),
    ]);
  const other: OtherDecisions = {
    approvals:
      approvalsResult.kind === "ok"
        ? approvalsResult.data.items.filter(
            (row) => row.current_state === "awaiting_human_review",
          )
        : null,
    refreshes:
      refreshResult.kind === "ok"
        ? refreshResult.data.filter((row) => row.status === "proposed")
        : null,
    suggestions:
      suggestionResult.kind === "ok"
        ? suggestionResult.data.filter((row) => row.status === "proposed")
        : null,
  };
  const decidable =
    result.kind === "ok"
      ? result.data.items.filter(
          (row) =>
            row.inspiration_evaluation_id !== null &&
            row.recommendation !== "continue_research",
        )
      : null;
  const rows =
    decidable === null
      ? null
      : decidable.filter((row) => matchesInboxFilters(row, filters));
  const counts: GroupCounts = { karar: 0, orta: 0, elenecek: 0, hepsi: 0 };
  for (const row of decidable ?? []) {
    counts[inboxGroupOf(row)] += 1;
    counts.hepsi += 1;
  }
  const pendingScore =
    result.kind === "ok"
      ? result.data.items.filter(
          (row) => row.inspiration_evaluation_id === null,
        ).length
      : 0;
  const continuedResearch =
    result.kind === "ok"
      ? result.data.items.filter(
          (row) => row.recommendation === "continue_research",
        ).length
      : 0;
  return (
    <section className="panel panel-wide" aria-labelledby="firsatlar-title">
      <div className="kontrol-header">
        <div>
          <p className="eyebrow">Gerçek editoryal kararlar</p>
          <h1 id="firsatlar-title">Benden Bekleyenler</h1>
          <p className="muted">
            Yalnızca sizden karar bekleyen işler: üretim kararı, yayın onayı,
            güncelleme kararı ve strateji önerisi. Makine keşfetti, filtreledi,
            getirdi ve skorladı — karar sizin ve gerekçesiyle kayda geçer.
          </p>
        </div>
        <AutoRefresh
          generatedAt={new Date().toISOString()}
          intervalMs={30000}
        />
      </div>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={NOTICES}
      />
      <BulkOutcomeNotice query={query} />
      {result.kind !== "ok" && (
        <p role="status">Backend API&apos;ye şu anda erişilemiyor.</p>
      )}
      <OtherDecisionGroups other={other} />
      {decidable !== null && (
        <>
          <GroupTabs filters={filters} counts={counts} other={other} />
          <p className="muted inbox-hint">{INBOX_GROUP_HINTS[filters.durum]}</p>
          <FilterForm filters={filters} />
        </>
      )}
      {rows !== null && pendingScore > 0 && (
        <p className="muted">
          {pendingScore} fırsatı ContentOS değerlendiriyor; karar gerektirirse
          burada belirir.
        </p>
      )}
      {rows !== null && continuedResearch > 0 && (
        <p className="muted">
          {continuedResearch} fırsat için sistem otomatik olarak araştırmayı
          sürdürüyor; sizden karar beklenmiyor.
        </p>
      )}
      {rows !== null && rows.length === 0 && filters.durum === "karar" && (
        <p className="empty-note">
          ContentOS çalışıyor, şu anda sizden karar bekleyen bir iş yok.
          {counts.elenecek + counts.orta > 0
            ? ` ${counts.elenecek + counts.orta} açık fırsatın kaynak tabanı görevlendirilebilir değil; bunları "Elenecekler" ve "Orta kaynak tabanı" gruplarından yönetebilirsiniz.`
            : " Süreci Çalışmalar alanından izleyebilirsiniz."}{" "}
          <Link href="/calisma">Çalışmalar</Link>
        </p>
      )}
      {rows !== null && rows.length === 0 && filters.durum !== "karar" && (
        <p className="empty-note">
          Bu grupta fırsat yok.{" "}
          <Link href="/firsatlar">Karar bekleyenlere dön</Link>.
        </p>
      )}
      {rows !== null && rows.length > 0 && (
        <>
          <BulkActionForm rows={rows} filters={filters} />
          <div className="opportunity-grid">
            {rows.map((row) => (
              <OpportunityCard key={row.work_item_id} row={row} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
