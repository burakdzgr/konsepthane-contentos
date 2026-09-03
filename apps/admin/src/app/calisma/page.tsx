import Link from "next/link";

import { fetchIntakeRuns, type IntakeRunView } from "@/lib/intake-api";
import { formatUtcTimestamp } from "@/lib/format";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../notices";
import { AutoRefresh } from "../kontrol/refresh";

// All intake runs, newest first: the durable history of every "start"
// the operator pressed, refresh- and restart-safe.
export const dynamic = "force-dynamic";

const STATUS_LABELS: Record<IntakeRunView["status"], string> = {
  running: "ÇALIŞIYOR",
  paused: "DURAKLATILDI",
  completed: "TAMAMLANDI",
  stopped: "DURDURULDU",
  failed: "BAŞARISIZ",
};

const STATUS_TONES: Record<IntakeRunView["status"], string> = {
  running: "run",
  paused: "warn",
  completed: "ok",
  stopped: "idle",
  failed: "bad",
};

export default async function RunsPage({
  searchParams,
}: {
  searchParams?: Promise<RawSearchParams>;
}) {
  const query = searchParams === undefined ? {} : await searchParams;
  const result = await fetchIntakeRuns();
  return (
    <section className="panel panel-wide" aria-labelledby="runs-title">
      <div className="kontrol-header">
        <div>
          <h1 id="runs-title">Çalışmalar</h1>
          <p className="muted">
            Otonom alım çalışmaları: keşif → ön filtre → sınırlı getirme →
            fırsat yükseltme. Geçmiş kalıcıdır; sayfa yenilemek hiçbir şey
            kaybettirmez.
          </p>
        </div>
        {result.kind === "ok" && (
          <AutoRefresh
            generatedAt={result.data.generated_at}
            intervalMs={10000}
          />
        )}
      </div>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={{}}
      />
      {result.kind !== "ok" && (
        <p role="status">Backend API&apos;ye şu anda erişilemiyor.</p>
      )}
      {result.kind === "ok" && result.data.runs.length === 0 && (
        <p className="empty-note">
          Henüz çalışma yok. <Link href="/sources">Kaynaklar</Link> sayfasından
          &quot;Keşfi başlat&quot; ile bir tane başlatın.
        </p>
      )}
      {result.kind === "ok" && result.data.runs.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Kaynak</th>
                <th>Durum</th>
                <th>Keşif</th>
                <th>Ön filtre</th>
                <th>Getirme</th>
                <th>Fırsat</th>
                <th>Başladı</th>
                <th>Son olay</th>
              </tr>
            </thead>
            <tbody>
              {result.data.runs.map((run) => (
                <tr key={run.id}>
                  <td>
                    <Link href={`/calisma/${run.id}`} className="cell-primary">
                      {run.source_name}
                    </Link>
                  </td>
                  <td>
                    <span
                      className="badge"
                      data-tone={STATUS_TONES[run.status]}
                    >
                      {STATUS_LABELS[run.status]}
                    </span>
                  </td>
                  <td>{run.discovered_new + run.rediscovered}</td>
                  <td>
                    {run.prefilter_accepted} uygun / {run.prefilter_rejected}{" "}
                    ret
                  </td>
                  <td>
                    {run.fetched}/{run.fetch_dispatched}
                    {run.fetch_failed > 0 && ` (${run.fetch_failed} hata)`}
                  </td>
                  <td>{run.opportunities_created}</td>
                  <td>{formatUtcTimestamp(run.created_at)}</td>
                  <td>
                    {run.last_event_at !== null
                      ? formatUtcTimestamp(run.last_event_at)
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
