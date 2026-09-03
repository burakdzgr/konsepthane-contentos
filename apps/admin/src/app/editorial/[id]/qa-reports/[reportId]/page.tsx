import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchQaReportDetail, type QaReportDetail } from "@/lib/editorial-api";
import { draftStatusTone } from "@/lib/editorial-display";
import { formatUtcTimestamp } from "@/lib/format";

// One durable QA report in full: gate results exactly as persisted
// (unsatisfied and UNKNOWN are never softened), the versioned gate policy,
// audited waivers, and the supersession audit. Read-only: commands live on
// the work-item page.
export const dynamic = "force-dynamic";

function Row({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="status-row">
      <dt>{name}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function gateTone(result: string): "ok" | "warn" | "bad" | "neutral" | "info" {
  if (result === "pass" || result === "not_applicable" || result === "none") {
    return "ok";
  }
  if (result === "waived_by_human" || result === "pending") {
    return "info";
  }
  if (result === "unsatisfied") {
    return "warn";
  }
  if (result === "fail") {
    return "bad";
  }
  return "neutral";
}

function gateDetailText(detail: unknown): string {
  if (detail === null || typeof detail !== "object") {
    return "—";
  }
  return Object.entries(detail as Record<string, unknown>)
    .filter(([key]) => key !== "result")
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(" ");
}

function SummarySection({ detail }: { detail: QaReportDetail }) {
  const report = detail.report;
  return (
    <section aria-labelledby="qa-summary">
      <h2 id="qa-summary">Rapor sürümü</h2>
      <dl className="status-list">
        <Row name="Sürüm">v{report.version}</Row>
        <Row name="Sonuç">
          <span
            className="badge"
            data-tone={
              report.outcome === "ready_for_human_review" ? "ok" : "warn"
            }
          >
            {report.outcome}
          </span>{" "}
          <span className="muted">
            {String(detail.gate_policy_snapshot["version"] ?? "BİLİNMİYOR")}{" "}
            tarafından deterministik olarak hesaplandı
          </span>
        </Row>
        <Row name="Durum">
          <span className="badge" data-tone={draftStatusTone(report.status)}>
            {report.status}
          </span>
          {report.superseded_by_report_id !== null && (
            <>
              {" "}
              <Link
                href={`/editorial/${report.work_item_id}/qa-reports/${report.superseded_by_report_id}`}
              >
                daha yeni sürümle geçersiz kılındı
              </Link>
            </>
          )}
        </Row>
        <Row name="Değerlendirilen paket">
          <Link
            href={`/editorial/${report.work_item_id}/drafts/${report.content_draft_id}`}
          >
            taslak
          </Link>{" "}
          ·{" "}
          <Link
            href={`/editorial/${report.work_item_id}/reviews/${report.editorial_review_id}`}
          >
            editör değerlendirmesi
          </Link>
        </Row>
        <Row name="Motor">
          <span className="mono">
            {report.engine_name}/{report.engine_version}
          </span>
        </Row>
        <Row name="İçerik hash'i">
          <span className="mono">{report.content_hash}</span>
        </Row>
        <Row name="Oluşturuldu">{formatUtcTimestamp(report.created_at)}</Row>
      </dl>
    </section>
  );
}

function GatesSection({ detail }: { detail: QaReportDetail }) {
  const entries = Object.entries(detail.gate_results);
  return (
    <section aria-labelledby="qa-gates">
      <h2 id="qa-gates">Katı kapılar</h2>
      <p className="muted">
        Her kapı açık bir sonuç bildirir; sonucun yokluğu asla geçer sayılmaz.
        Vazgeçmeler kapsamı dürüstçe sınırlar — ihtiyaçlar görünür kalır.
      </p>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Kapı</th>
              <th scope="col">Sonuç</th>
              <th scope="col">Detay</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([gate, gateDetail]) => {
              const result =
                gateDetail !== null &&
                typeof gateDetail === "object" &&
                typeof (gateDetail as Record<string, unknown>)["result"] ===
                  "string"
                  ? String((gateDetail as Record<string, unknown>)["result"])
                  : "BİLİNMİYOR";
              return (
                <tr key={gate}>
                  <td className="mono">{gate}</td>
                  <td>
                    <span className="badge" data-tone={gateTone(result)}>
                      {result}
                    </span>
                  </td>
                  <td className="mono muted">{gateDetailText(gateDetail)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function WaiversSection({ detail }: { detail: QaReportDetail }) {
  return (
    <section aria-labelledby="qa-waivers">
      <h2 id="qa-waivers">Denetlenen vazgeçmeler</h2>
      {detail.waivers.length === 0 && (
        <p className="empty-note">Bu iş öğesi için vazgeçme yok.</p>
      )}
      {detail.waivers.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Kapı</th>
                <th scope="col">Gerekçe</th>
                <th scope="col">Ne zaman</th>
              </tr>
            </thead>
            <tbody>
              {detail.waivers.map((waiver) => (
                <tr key={waiver.id}>
                  <td className="mono">{waiver.gate_key}</td>
                  <td>{waiver.reason}</td>
                  <td>{formatUtcTimestamp(waiver.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function AuditSection({ detail }: { detail: QaReportDetail }) {
  return (
    <section aria-labelledby="qa-audit">
      <h2 id="qa-audit">Geçersiz kılma denetimi</h2>
      {detail.status_events.length === 0 && (
        <p className="empty-note">Kayıtlı durum değişikliği yok.</p>
      )}
      {detail.status_events.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Ne zaman</th>
                <th scope="col">Değişiklik</th>
                <th scope="col">Aktör</th>
                <th scope="col">Gerekçe</th>
                <th scope="col">Yerine geçen</th>
              </tr>
            </thead>
            <tbody>
              {detail.status_events.map((event) => (
                <tr key={event.id}>
                  <td>{formatUtcTimestamp(event.occurred_at)}</td>
                  <td>
                    {event.from_status} → {event.to_status}
                  </td>
                  <td>{event.actor_origin}</td>
                  <td>{event.reason}</td>
                  <td className="mono">{event.replacement_report_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default async function QaReportDetailPage({
  params,
}: {
  params: Promise<{ id: string; reportId: string }>;
}) {
  const { id, reportId } = await params;
  const result = await fetchQaReportDetail(reportId);

  if (result.kind === "not_found") {
    notFound();
  }
  if (result.kind === "unreachable") {
    return (
      <section className="panel" aria-labelledby="qa-detail-title">
        <h1 id="qa-detail-title">QA raporu</h1>
        <p role="status">Arka uç API&apos;sine şu anda ulaşılamıyor.</p>
      </section>
    );
  }
  if (result.kind === "malformed") {
    return (
      <section className="panel" aria-labelledby="qa-detail-title">
        <h1 id="qa-detail-title">QA raporu</h1>
        <p role="status">Arka uç API&apos;si beklenmedik veri döndürdü.</p>
      </section>
    );
  }

  const detail = result.data;
  return (
    <section className="panel panel-wide" aria-labelledby="qa-detail-title">
      <h1 id="qa-detail-title">QA raporu</h1>
      <p className="muted">
        <Link href={`/editorial/${id}`}>← İş öğesine dön</Link>
      </p>
      <SummarySection detail={detail} />
      <GatesSection detail={detail} />
      <WaiversSection detail={detail} />
      <AuditSection detail={detail} />
    </section>
  );
}
