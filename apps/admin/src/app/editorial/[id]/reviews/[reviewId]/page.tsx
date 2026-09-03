import Link from "next/link";
import { notFound } from "next/navigation";

import {
  fetchReviewDetail,
  type ReviewDetail,
  type ReviewFindingView,
} from "@/lib/editorial-api";
import {
  draftStatusTone,
  findingSeverityTone,
  generationStatusTone,
  reviewVerdictTone,
} from "@/lib/editorial-display";
import { formatUtcTimestamp } from "@/lib/format";

// One durable editor review in full: findings exactly as persisted (policy
// signals, never evidence), the deterministic integrity record including
// the writer-envelope recheck, policy snapshots, the supersession audit,
// and safe attempt metadata. Read-only: commands live on the work-item page.
export const dynamic = "force-dynamic";

function Row({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <div className="status-row">
      <dt>{name}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function envelopeEntries(detail: ReviewDetail): [string, string][] {
  const envelope = detail.integrity_gate_result["writer_envelope"];
  if (envelope === null || typeof envelope !== "object") {
    return [];
  }
  return Object.entries(envelope as Record<string, unknown>).map(
    ([key, value]) => [key, String(value)],
  );
}

function SummarySection({ detail }: { detail: ReviewDetail }) {
  const review = detail.review;
  const recomputed = review.writer_envelope_recomputed;
  return (
    <section aria-labelledby="review-summary">
      <h2 id="review-summary">Değerlendirme sürümü</h2>
      <dl className="status-list">
        <Row name="Sürüm">v{review.version}</Row>
        <Row name="Hüküm">
          <span className="badge" data-tone={reviewVerdictTone(review.verdict)}>
            {review.verdict}
          </span>{" "}
          <span className="muted">
            {String(detail.verdict_policy_snapshot["version"] ?? "BİLİNMİYOR")}{" "}
            tarafından hesaplandı; asla model yazımı değil
          </span>
        </Row>
        <Row name="Durum">
          <span className="badge" data-tone={draftStatusTone(review.status)}>
            {review.status}
          </span>
          {review.superseded_by_review_id !== null && (
            <>
              {" "}
              <Link
                href={`/editorial/${review.work_item_id}/reviews/${review.superseded_by_review_id}`}
              >
                daha yeni sürümle geçersiz kılındı
              </Link>
            </>
          )}
        </Row>
        <Row name="Değerlendirilen taslak">
          <Link
            href={`/editorial/${review.work_item_id}/drafts/${review.content_draft_id}`}
          >
            tam taslak sürümünü aç
          </Link>{" "}
          <span className="mono muted">{review.content_draft_id}</span>
        </Row>
        <Row name="Motor">
          <span className="mono">
            {review.engine_name}/{review.engine_version}
          </span>
        </Row>
        <Row name="Yazar zarfı yeniden kontrolü">
          <span
            className="badge"
            data-tone={recomputed === null ? "neutral" : "ok"}
          >
            {recomputed === null
              ? "BİLİNMİYOR"
              : recomputed
                ? "yeniden hesaplandı"
                : "yeniden hesaplanmadı"}
          </span>{" "}
          {envelopeEntries(detail).map(([key, value]) => (
            <span key={key} className="mono muted">
              {key}={value}{" "}
            </span>
          ))}
        </Row>
        <Row name="İçerik hash'i">
          <span className="mono">{review.content_hash}</span>
        </Row>
        <Row name="Oluşturuldu">{formatUtcTimestamp(review.created_at)}</Row>
      </dl>
    </section>
  );
}

function FindingsSection({ findings }: { findings: ReviewFindingView[] }) {
  return (
    <section aria-labelledby="review-findings">
      <h2 id="review-findings">Bulgular</h2>
      <p className="muted">
        Tam olarak bu taslağa dair politika sinyalleri — asla kanıt, asla olgu
        değildir. Deterministik kapı sonuçları drift- önekini taşır.
      </p>
      {findings.length === 0 && (
        <p className="empty-note">Bulgu yok: temiz bir geçiş.</p>
      )}
      {findings.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Anahtar</th>
                <th scope="col">Boyut</th>
                <th scope="col">Önem</th>
                <th scope="col">Köken</th>
                <th scope="col">Bağlantı noktası</th>
                <th scope="col">Açıklama</th>
                <th scope="col">Öneri</th>
              </tr>
            </thead>
            <tbody>
              {findings.map((finding) => (
                <tr key={finding.id}>
                  <td className="mono">{finding.finding_key}</td>
                  <td>{finding.dimension}</td>
                  <td>
                    <span
                      className="badge"
                      data-tone={findingSeverityTone(finding.severity)}
                    >
                      {finding.severity}
                    </span>
                  </td>
                  <td>{finding.origin}</td>
                  <td className="mono">
                    {finding.block_id ?? "—"}
                    {finding.claim_key !== null && (
                      <>
                        <br />
                        {finding.claim_key} ({finding.claim_kind})
                      </>
                    )}
                  </td>
                  <td>{finding.description}</td>
                  <td>{finding.recommendation ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function AuditSection({ detail }: { detail: ReviewDetail }) {
  return (
    <section aria-labelledby="review-audit">
      <h2 id="review-audit">Geçersiz kılma denetimi</h2>
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
                  <td className="mono">{event.replacement_review_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function AttemptsSection({ detail }: { detail: ReviewDetail }) {
  return (
    <section aria-labelledby="review-attempts">
      <h2 id="review-attempts">Editör üretim denemeleri</h2>
      <p className="muted">
        Yalnızca güvenli, kalıcı üstveriler — başarısız denemeler görünür kalır;
        istemler ve ham model çıktısı asla saklanmaz ve asla gösterilmez.
      </p>
      {detail.generation_attempts.length === 0 && (
        <p className="empty-note">
          Bu iş öğesi için editör üretim denemesi yok.
        </p>
      )}
      {detail.generation_attempts.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Durum</th>
                <th scope="col">Yeniden deneme</th>
                <th scope="col">Sağlayıcı / model</th>
                <th scope="col">Şema</th>
                <th scope="col">Ne zaman</th>
              </tr>
            </thead>
            <tbody>
              {detail.generation_attempts.map((attempt) => (
                <tr key={attempt.id}>
                  <td>
                    <span
                      className="badge"
                      data-tone={generationStatusTone(attempt.status)}
                    >
                      {attempt.status}
                    </span>
                    {attempt.error_class !== null
                      ? ` (${attempt.error_class})`
                      : ""}
                  </td>
                  <td>{attempt.retry_number}</td>
                  <td className="mono">
                    {attempt.provider}/{attempt.model_name}
                  </td>
                  <td className="mono">
                    {attempt.schema_name}/{attempt.schema_version}
                  </td>
                  <td>{formatUtcTimestamp(attempt.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default async function ReviewDetailPage({
  params,
}: {
  params: Promise<{ id: string; reviewId: string }>;
}) {
  const { id, reviewId } = await params;
  const result = await fetchReviewDetail(reviewId);

  if (result.kind === "not_found") {
    notFound();
  }
  if (result.kind === "unreachable") {
    return (
      <section className="panel" aria-labelledby="review-detail-title">
        <h1 id="review-detail-title">Editör değerlendirmesi</h1>
        <p role="status">Arka uç API&apos;sine şu anda ulaşılamıyor.</p>
      </section>
    );
  }
  if (result.kind === "malformed") {
    return (
      <section className="panel" aria-labelledby="review-detail-title">
        <h1 id="review-detail-title">Editör değerlendirmesi</h1>
        <p role="status">Arka uç API&apos;si beklenmedik veri döndürdü.</p>
      </section>
    );
  }

  const detail = result.data;
  return (
    <section className="panel panel-wide" aria-labelledby="review-detail-title">
      <h1 id="review-detail-title">Editör değerlendirmesi</h1>
      <p className="muted">
        <Link href={`/editorial/${id}`}>← İş öğesine dön</Link>
      </p>
      <SummarySection detail={detail} />
      <FindingsSection findings={detail.findings} />
      <AuditSection detail={detail} />
      <AttemptsSection detail={detail} />
    </section>
  );
}
