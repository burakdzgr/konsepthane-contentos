import Link from "next/link";

import { fetchWorkQueue, type WorkQueueRow } from "@/lib/editorial-api";
import { trLabel } from "@/lib/tr-labels";
import {
  OpportunityIntelligence,
  RECOMMENDATION,
} from "../firsatlar/intelligence";
import { AutoRefresh } from "../kontrol/refresh";
import {
  IDEA_GROUP_HINTS,
  IDEA_GROUP_LABELS,
  IDEA_GROUPS,
  ideaGroupOf,
  type IdeaGroup,
} from "./groups";

// Fikirler: what the system found. Every open opportunity still being
// scored AND every commissioned one that is on its way to a brief, grouped
// by what the intelligence says about it — strong, needs a look, still
// researching, eliminated — with the Turkish explanation sections behind
// each verdict. Read-only: the production decision stays on
// "Benden Bekleyenler"; this page explains, it does not ask.
export const dynamic = "force-dynamic";

const IDEA_STATES = [
  "idea_scoring",
  "evidence_building",
  "seo_research",
  "briefing",
] as const;

function IdeaCard({ row }: { row: WorkQueueRow }) {
  const recommendation =
    row.recommendation !== null
      ? (RECOMMENDATION[row.recommendation] ?? null)
      : null;
  const decisionOpen =
    row.disposition === "open" &&
    row.current_state === "idea_scoring" &&
    row.commission_eligible;
  return (
    <article className="opportunity-card" data-idea-group={ideaGroupOf(row)}>
      <header className="agent-card-header">
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
        <span className="badge" data-tone="info">
          {trLabel(row.current_state)}
        </span>
        {row.disposition === "commissioned" && (
          <span className="badge" data-tone="ok">
            ÜRETİMDE
          </span>
        )}
      </header>
      {row.selected_idea_title !== null && (
        <p>
          <strong>Seçilen fikir:</strong> {row.selected_idea_title}
          {row.selected_idea_originality !== null && (
            <>
              {" "}
              <span className="badge" data-tone="neutral">
                Özgünlük: {trLabel(row.selected_idea_originality)}
              </span>
            </>
          )}
        </p>
      )}
      {row.topic_summary !== null && <p>{row.topic_summary}</p>}
      {row.intelligence !== null ? (
        <OpportunityIntelligence intelligence={row.intelligence} />
      ) : (
        <p className="muted">
          Fırsat istihbaratı henüz hesaplanmadı; değerlendirme tamamlandığında
          İçerik Değeri, Arama İstihbaratı, Konsepthane Verisi ve Araştırma
          bölümleri burada görünür.
        </p>
      )}
      <p className="muted">
        {row.inspiration_signal_count} kaynak sinyali ·{" "}
        {row.inspiration_concept_count} gruplanmış fikir
      </p>
      <div className="opportunity-actions">
        <Link href={`/editorial/${row.work_item_id}`}>İncele</Link>
        {decisionOpen && <Link href="/firsatlar">Üretim kararını ver →</Link>}
      </div>
    </article>
  );
}

type GroupCounts = Record<IdeaGroup, number>;

function GroupTabs({ counts }: { counts: GroupCounts }) {
  return (
    <nav className="inbox-tabs" aria-label="Fikir grupları">
      {IDEA_GROUPS.map((group) => (
        <Link
          key={group}
          href={`/fikirler#${group}`}
          title={IDEA_GROUP_HINTS[group]}
        >
          {IDEA_GROUP_LABELS[group]} ({counts[group]})
        </Link>
      ))}
    </nav>
  );
}

function GroupSection({
  group,
  rows,
}: {
  group: IdeaGroup;
  rows: WorkQueueRow[];
}) {
  const headingId = `fikirler-${group}`;
  return (
    <section id={group} className="idea-group" aria-labelledby={headingId}>
      <h2 id={headingId}>
        {IDEA_GROUP_LABELS[group]} ({rows.length})
      </h2>
      <p className="muted">{IDEA_GROUP_HINTS[group]}</p>
      {rows.length === 0 ? (
        <p className="empty-note">Bu grupta fikir yok.</p>
      ) : (
        <div className="opportunity-grid">
          {rows.map((row) => (
            <IdeaCard key={row.work_item_id} row={row} />
          ))}
        </div>
      )}
    </section>
  );
}

export default async function IdeasPage() {
  const results = await Promise.all(
    IDEA_STATES.map((state) =>
      fetchWorkQueue({ workflowState: state, limit: 50 }),
    ),
  );
  const readable = results.filter((result) => result.kind === "ok");
  const rowsById = new Map<string, WorkQueueRow>();
  for (const result of results) {
    if (result.kind !== "ok") {
      continue;
    }
    for (const row of result.data.items) {
      // Open ideas still being scored, and commissioned ideas on their way
      // to a brief; a rejected opportunity is not an idea any more.
      if (row.disposition === "rejected") {
        continue;
      }
      rowsById.set(row.work_item_id, row);
    }
  }
  const rows = [...rowsById.values()];
  const grouped: Record<IdeaGroup, WorkQueueRow[]> = {
    guclu: [],
    incelenmeli: [],
    arastirma: [],
    elenen: [],
  };
  for (const row of rows) {
    grouped[ideaGroupOf(row)].push(row);
  }
  const counts: GroupCounts = {
    guclu: grouped.guclu.length,
    incelenmeli: grouped.incelenmeli.length,
    arastirma: grouped.arastirma.length,
    elenen: grouped.elenen.length,
  };
  return (
    <section className="panel panel-wide" aria-labelledby="fikirler-title">
      <div className="kontrol-header">
        <div>
          <p className="eyebrow">Sistemin bulduğu fikirler</p>
          <h1 id="fikirler-title">Fikirler</h1>
          <p className="muted">
            Kaynaklardan çıkarılan, gruplanan ve değerlendirilen fikirler.
            Hangileri güçlü, neden güçlü, arama ve trend verisi ne diyor,
            Konsepthane&apos;nin kendi geçmişi ne söylüyor — hepsi burada.
            Üretim kararı <Link href="/firsatlar">Benden Bekleyenler</Link>
            &apos;de verilir.
          </p>
        </div>
        <AutoRefresh
          generatedAt={new Date().toISOString()}
          intervalMs={30000}
        />
      </div>
      {readable.length === 0 && (
        <p role="status">Backend API&apos;ye şu anda erişilemiyor.</p>
      )}
      {readable.length > 0 && readable.length < results.length && (
        <p className="notice" data-tone="warn" role="status">
          Bazı aşamalar şu anda okunamıyor; liste eksik olabilir.
        </p>
      )}
      {readable.length > 0 && (
        <>
          <GroupTabs counts={counts} />
          {rows.length === 0 && (
            <p className="empty-note">
              Henüz değerlendirilen fikir yok. Bir kaynaktan keşif başlatın:{" "}
              <Link href="/sources">Kaynaklar</Link>.
            </p>
          )}
          {rows.length > 0 && (
            <div className="idea-groups">
              {IDEA_GROUPS.map((group) => (
                <GroupSection key={group} group={group} rows={grouped[group]} />
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
