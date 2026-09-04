import Link from "next/link";

import { trLabel } from "@/lib/tr-labels";
import { notFound } from "next/navigation";

import {
  DISCOVERY_REJECTION_REASONS,
  fetchPipelineDetail,
  type PipelineDetail,
} from "@/lib/research-api";
import { formatUtcTimestamp } from "@/lib/format";
import {
  discoveryStateTone,
  duplicateOutcomeTone,
  fetchOutcomeTone,
  normalizationStatusTone,
} from "@/lib/pipeline-display";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { ControlNotice } from "../../notices";
import {
  acceptDiscoveryItemAction,
  rejectDiscoveryItemAction,
  requeueDiscoveryItemAction,
  startDiscoveryItemFetchAction,
} from "./actions";

// One DiscoveryItem's full pipeline history from durable state, at request
// time, plus the explicit operator decisions valid for its current state.
// No payload access, no article body, no pipeline-stage bypass.
export const dynamic = "force-dynamic";

const DETAIL_NOTICES: Record<string, string> = {
  accepted: "Öğe kabul edildi. Getirmeyi başlatmak ayrı bir eylemdir.",
  rejected: "Öğe reddedildi. Reddetme kalıcıdır.",
  requeued:
    "Öğe kabul edilmiş olarak yeniden kuyruğa alındı. Getirmeyi başlatmak ayrı bir eylemdir.",
  "fetch-queued":
    "Getirme kuyruğa alındı. Başarılı bir getirmeden sonra hat otomatik olarak devam eder.",
};

function Row({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="status-row">
      <dt>{name}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function TruncationNote({
  shown,
  total,
  noun,
}: {
  shown: number;
  total: number;
  noun: string;
}) {
  if (total <= shown) {
    return null;
  }
  return (
    <p className="muted" role="note">
      {total} {noun} içinden en son {shown} tanesi gösteriliyor.
    </p>
  );
}

function DiscoverySection({ detail }: { detail: PipelineDetail }) {
  const item = detail.discovery_item;
  return (
    <section aria-labelledby="detail-discovery">
      <h2 id="detail-discovery">Keşif</h2>
      <dl className="status-list">
        <Row name="Durum">
          <span
            className="badge"
            data-tone={discoveryStateTone(item.lifecycle_state)}
          >
            {trLabel(item.lifecycle_state)}
          </span>
        </Row>
        <Row name="Kaynak">
          {detail.source.name}{" "}
          <span className="mono muted">({detail.source.slug})</span>
        </Row>
        <Row name="Kanonik URL">
          <span className="cell-url" title={item.canonical_url}>
            {item.canonical_url}
          </span>
        </Row>
        {item.discovered_url !== item.canonical_url && (
          <Row name="Keşfedilen URL">
            <span className="cell-url" title={item.discovered_url}>
              {item.discovered_url}
            </span>
          </Row>
        )}
        <Row name="Yöntem">{item.discovery_method}</Row>
        {item.title_hint !== null && (
          <Row name="Başlık ipucu (güvenilmez)">{item.title_hint}</Row>
        )}
        {item.rejection_reason !== null && (
          <Row name="Reddetme">
            {item.rejection_reason}
            {item.rejection_note !== null ? ` — ${item.rejection_note}` : ""}
          </Row>
        )}
        <Row name="Keşfedilme zamanı">
          {formatUtcTimestamp(item.discovered_at)}
        </Row>
        <Row name="Son görülme">{formatUtcTimestamp(item.last_seen_at)}</Row>
        {item.external_published_at !== null && (
          <Row name="Kaynağın beyan ettiği yayın tarihi">
            {formatUtcTimestamp(item.external_published_at)}
          </Row>
        )}
        <Row name="Öğe kimliği">
          <span className="mono muted">{item.id}</span>
        </Row>
      </dl>
    </section>
  );
}

function FetchSection({ detail }: { detail: PipelineDetail }) {
  return (
    <section aria-labelledby="detail-fetch">
      <h2 id="detail-fetch">Getirme geçmişi</h2>
      {detail.fetch_attempts.length === 0 && (
        <p className="empty-note">Kayıtlı getirme denemesi yok.</p>
      )}
      {detail.fetch_attempts.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Getirildi</th>
                <th scope="col">Sonuç</th>
                <th scope="col">Durum</th>
                <th scope="col">Tür</th>
                <th scope="col">Boyut</th>
                <th scope="col">Robots</th>
                <th scope="col">Yeniden deneme</th>
                <th scope="col">Ayrıntı</th>
              </tr>
            </thead>
            <tbody>
              {detail.fetch_attempts.map((attempt) => (
                <tr key={attempt.id}>
                  <td>{formatUtcTimestamp(attempt.fetched_at)}</td>
                  <td>
                    <span
                      className="badge"
                      data-tone={fetchOutcomeTone(attempt.fetch_outcome)}
                    >
                      {trLabel(attempt.fetch_outcome)}
                    </span>
                  </td>
                  <td>{attempt.status_code ?? "—"}</td>
                  <td>{attempt.content_type ?? "—"}</td>
                  <td>
                    {attempt.body_size_bytes !== null
                      ? `${attempt.body_size_bytes} B`
                      : "—"}
                  </td>
                  <td>{trLabel(attempt.robots_decision)}</td>
                  <td>{trLabel(attempt.retry_classification)}</td>
                  <td>{attempt.failure_detail ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <TruncationNote
        shown={detail.fetch_attempts.length}
        total={detail.total_fetch_attempts}
        noun="getirme denemesi"
      />
    </section>
  );
}

function NormalizationSection({ detail }: { detail: PipelineDetail }) {
  return (
    <section aria-labelledby="detail-normalization">
      <h2 id="detail-normalization">Normalleştirme geçmişi</h2>
      {detail.normalization_attempts.length === 0 && (
        <p className="empty-note">Kayıtlı normalleştirme denemesi yok.</p>
      )}
      {detail.normalization_attempts.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Normalleştirildi</th>
                <th scope="col">Durum</th>
                <th scope="col">Çıkarıcı</th>
                <th scope="col">Başlık</th>
                <th scope="col">Yazar</th>
                <th scope="col">Yayınlanma</th>
                <th scope="col">Hata</th>
              </tr>
            </thead>
            <tbody>
              {detail.normalization_attempts.map((attempt) => (
                <tr key={attempt.id}>
                  <td>{formatUtcTimestamp(attempt.normalized_at)}</td>
                  <td>
                    <span
                      className="badge"
                      data-tone={normalizationStatusTone(
                        attempt.normalization_status,
                      )}
                    >
                      {trLabel(attempt.normalization_status)}
                    </span>
                  </td>
                  <td className="mono">
                    {attempt.extractor_name}/{attempt.extractor_version}
                  </td>
                  <td>{attempt.title ?? "—"}</td>
                  <td>{attempt.author_name ?? "—"}</td>
                  <td>{formatUtcTimestamp(attempt.external_published_at)}</td>
                  <td>
                    {attempt.failure_code ?? "—"}
                    {attempt.failure_detail !== null
                      ? ` — ${attempt.failure_detail}`
                      : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <TruncationNote
        shown={detail.normalization_attempts.length}
        total={detail.total_normalization_attempts}
        noun="normalleştirme denemesi"
      />
    </section>
  );
}

function DuplicateSection({ detail }: { detail: PipelineDetail }) {
  return (
    <section aria-labelledby="detail-duplicates">
      <h2 id="detail-duplicates">Kopya kararları</h2>
      {detail.duplicate_decisions.length === 0 && (
        <p className="empty-note">Kayıtlı kopya kararı yok.</p>
      )}
      {detail.duplicate_decisions.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Değerlendirildi</th>
                <th scope="col">Karar</th>
                <th scope="col">Motor</th>
                <th scope="col">Gerekçe</th>
                <th scope="col">Eşleşmeler</th>
                <th scope="col">Doküman</th>
              </tr>
            </thead>
            <tbody>
              {detail.duplicate_decisions.map((decision) => (
                <tr key={decision.id}>
                  <td>{formatUtcTimestamp(decision.evaluated_at)}</td>
                  <td>
                    <span
                      className="badge"
                      data-tone={duplicateOutcomeTone(decision.decision)}
                    >
                      {trLabel(decision.decision)}
                    </span>
                  </td>
                  <td className="mono">
                    {decision.engine_name}/{decision.engine_version}
                  </td>
                  <td>
                    {decision.rationale_codes.length > 0
                      ? decision.rationale_codes.join(", ")
                      : "—"}
                  </td>
                  <td>{decision.match_count}</td>
                  <td className="mono muted">
                    {decision.normalized_document_id}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <TruncationNote
        shown={detail.duplicate_decisions.length}
        total={detail.total_duplicate_decisions}
        noun="kopya kararı"
      />
    </section>
  );
}

function EvidenceSection({ detail }: { detail: PipelineDetail }) {
  const evidence = detail.evidence;
  return (
    <section aria-labelledby="detail-evidence">
      <h2 id="detail-evidence">Kanıt özeti</h2>
      <p className="muted">
        Yalnızca sayılar: kanıt ifadeleri ve alıntılar burada gösterilmez.
      </p>
      <dl className="status-list">
        <Row name="Toplam kanıt">{evidence.total}</Row>
        <Row name="Doğrulama durumuna göre">
          {Object.entries(evidence.by_verification_status)
            .map(([status, count]) => `${status}: ${count}`)
            .join(" · ") || "—"}
        </Row>
        <Row name="Kanıt türüne göre">
          {Object.entries(evidence.by_evidence_type)
            .map(([type, count]) => `${type}: ${count}`)
            .join(" · ") || "—"}
        </Row>
        <Row name="En yeni kanıt">
          {formatUtcTimestamp(evidence.latest_extracted_at)}
        </Row>
      </dl>
    </section>
  );
}

function ActionPanel({ detail }: { detail: PipelineDetail }) {
  const item = detail.discovery_item;
  const state = item.lifecycle_state;
  return (
    <section aria-labelledby="detail-actions">
      <h2 id="detail-actions">Operatör eylemleri</h2>
      {state === "discovered" && (
        <div className="control-stack">
          <form action={acceptDiscoveryItemAction} className="control-form">
            <input type="hidden" name="discovery_item_id" value={item.id} />
            <button type="submit">Kabul et</button>
            <span className="muted">
              Kabul, öğeyi getirme için onaylar; getirme ayrı bir eylem olarak
              kalır.
            </span>
          </form>
          <form action={rejectDiscoveryItemAction} className="control-form">
            <input type="hidden" name="discovery_item_id" value={item.id} />
            <select
              name="reason"
              required
              defaultValue=""
              aria-label="Reddetme gerekçesi"
            >
              <option value="" disabled>
                Reddetme gerekçesi…
              </option>
              {DISCOVERY_REJECTION_REASONS.map((reason) => (
                <option key={reason} value={reason}>
                  {trLabel(reason)}
                </option>
              ))}
            </select>
            <input
              type="text"
              name="note"
              maxLength={2000}
              placeholder="isteğe bağlı not"
              aria-label="Reddetme notu"
            />
            <button type="submit">Reddet</button>
          </form>
        </div>
      )}
      {state === "accepted" && (
        <form action={startDiscoveryItemFetchAction} className="control-form">
          <input type="hidden" name="discovery_item_id" value={item.id} />
          <button type="submit">Getirmeyi başlat</button>
          <span className="muted">
            Başarılı bir getirmeden sonra hat otomatik olarak devam eder:
            normalleştirme → kopya denetimi → kanıt.
          </span>
        </form>
      )}
      {state === "fetch_failed" && (
        <form action={requeueDiscoveryItemAction} className="control-form">
          <input type="hidden" name="discovery_item_id" value={item.id} />
          <input
            type="text"
            name="reason"
            required
            maxLength={1000}
            placeholder="yeniden kuyruğa alma gerekçesi"
            aria-label="Yeniden kuyruğa alma gerekçesi"
          />
          <button type="submit">Yeniden kuyruğa al</button>
          <span className="muted">
            Yeniden kuyruğa alma öğeyi kabul edilmiş durumuna döndürür;
            getirmeyi başlatmaz.
          </span>
        </form>
      )}
      {state === "fetched" && (
        <p className="muted">
          Bu öğe getirildi; hat, öğenin anlık görüntüsünden çalıştı. Burada
          kullanılabilir eylem yok.
        </p>
      )}
      {state === "rejected" && (
        <p className="muted">
          Bu öğe reddedildi. Reddetme kalıcıdır; kullanılabilir eylem yok.
        </p>
      )}
    </section>
  );
}

export default async function ResearchDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams?: Promise<RawSearchParams>;
}) {
  const { id } = await params;
  const query = searchParams === undefined ? {} : await searchParams;
  const result = await fetchPipelineDetail(id);

  if (result.kind === "not_found") {
    notFound();
  }
  if (result.kind === "unreachable") {
    return (
      <section className="panel" aria-labelledby="detail-title">
        <h1 id="detail-title">Keşif öğesi</h1>
        <p role="status">Arka uç API&apos;sine şu anda ulaşılamıyor.</p>
      </section>
    );
  }
  if (result.kind === "malformed") {
    return (
      <section className="panel" aria-labelledby="detail-title">
        <h1 id="detail-title">Keşif öğesi</h1>
        <p role="status">Arka uç API&apos;si beklenmeyen veri döndürdü.</p>
      </section>
    );
  }

  const detail = result.data;
  return (
    <section className="panel panel-wide" aria-labelledby="detail-title">
      <h1 id="detail-title">Keşif öğesi</h1>
      <p className="muted">
        <Link href="/research">← Araştırma Hattına dön</Link>
      </p>
      <ControlNotice
        notice={firstParam(query.notice)}
        error={firstParam(query.error)}
        noticeMessages={DETAIL_NOTICES}
      />
      <DiscoverySection detail={detail} />
      <ActionPanel detail={detail} />
      <FetchSection detail={detail} />
      <NormalizationSection detail={detail} />
      <DuplicateSection detail={detail} />
      <EvidenceSection detail={detail} />
    </section>
  );
}
