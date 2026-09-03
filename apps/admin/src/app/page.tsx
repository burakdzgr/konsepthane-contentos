import {
  fetchBackendLiveness,
  fetchBackendReadiness,
  type BackendLiveness,
  type BackendReadiness,
  type BackendResult,
} from "@/lib/contentos-api";

// Operational status must reflect the moment of the request, never the build.
export const dynamic = "force-dynamic";

type StatusTone = "ok" | "bad" | "unknown";

type StatusDisplay = {
  label: string;
  tone: StatusTone;
};

function apiProcessStatus(
  liveness: BackendResult<BackendLiveness>,
): StatusDisplay {
  if (liveness.kind === "ok") {
    return { label: "Çalışıyor", tone: "ok" };
  }
  if (liveness.kind === "unreachable") {
    return { label: "Erişilemiyor", tone: "bad" };
  }
  return { label: "Bilinmiyor", tone: "unknown" };
}

function componentStatus(
  readiness: BackendResult<BackendReadiness>,
  component: keyof BackendReadiness["checks"],
): StatusDisplay {
  if (readiness.kind !== "ok") {
    return { label: "Bilinmiyor", tone: "unknown" };
  }
  const state = readiness.data.checks[component];
  if (state === "ok") {
    return { label: "Çalışıyor", tone: "ok" };
  }
  if (state === "failed") {
    return { label: "Hazır değil", tone: "bad" };
  }
  return { label: "Bilinmiyor", tone: "unknown" };
}

function StatusRow({ name, status }: { name: string; status: StatusDisplay }) {
  return (
    <div className="status-row">
      <dt>{name}</dt>
      <dd className="status-value" data-tone={status.tone}>
        {status.label}
      </dd>
    </div>
  );
}

export default async function HomePage() {
  const [liveness, readiness] = await Promise.all([
    fetchBackendLiveness(),
    fetchBackendReadiness(),
  ]);

  return (
    <section className="panel" aria-labelledby="status-title">
      <h1 id="status-title">Sistem Durumu</h1>
      <p className="muted">
        ContentOS backend&apos;inin istek anında bildirdiği canlı durum.
      </p>
      {liveness.kind === "unreachable" && (
        <p role="status">Backend API&apos;ye şu anda erişilemiyor.</p>
      )}
      {liveness.kind === "malformed" && (
        <p role="status">Backend API beklenmedik veri döndürdü.</p>
      )}
      {readiness.kind !== "ok" && (
        <p className="muted" role="note">
          Backend hazırlık durumu okunamadığı için altyapı durumları bilinmiyor.
        </p>
      )}
      <dl className="status-list">
        <StatusRow name="API süreci" status={apiProcessStatus(liveness)} />
        <StatusRow
          name="PostgreSQL"
          status={componentStatus(readiness, "postgres")}
        />
        <StatusRow
          name="pgvector"
          status={componentStatus(readiness, "pgvector")}
        />
        <StatusRow name="Redis" status={componentStatus(readiness, "redis")} />
      </dl>
      <dl className="status-meta">
        <div className="status-row">
          <dt>Servis</dt>
          <dd>
            {liveness.kind === "ok" ? liveness.data.service : "Bilinmiyor"}
          </dd>
        </div>
        <div className="status-row">
          <dt>Sürüm</dt>
          <dd>
            {liveness.kind === "ok" ? liveness.data.version : "Bilinmiyor"}
          </dd>
        </div>
      </dl>
    </section>
  );
}
