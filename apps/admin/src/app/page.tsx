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
    return { label: "Operational", tone: "ok" };
  }
  if (liveness.kind === "unreachable") {
    return { label: "Unavailable", tone: "bad" };
  }
  return { label: "Unknown", tone: "unknown" };
}

function componentStatus(
  readiness: BackendResult<BackendReadiness>,
  component: keyof BackendReadiness["checks"],
): StatusDisplay {
  if (readiness.kind !== "ok") {
    return { label: "Unknown", tone: "unknown" };
  }
  const state = readiness.data.checks[component];
  if (state === "ok") {
    return { label: "Operational", tone: "ok" };
  }
  if (state === "failed") {
    return { label: "Not ready", tone: "bad" };
  }
  return { label: "Unknown", tone: "unknown" };
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
      <h1 id="status-title">Foundation Status</h1>
      <p className="muted">
        Live state as reported by the ContentOS backend at request time.
      </p>
      {liveness.kind === "unreachable" && (
        <p role="status">The backend API cannot be reached right now.</p>
      )}
      {liveness.kind === "malformed" && (
        <p role="status">The backend API returned unexpected data.</p>
      )}
      {readiness.kind !== "ok" && (
        <p className="muted" role="note">
          Infrastructure states are unknown because backend readiness could not
          be read.
        </p>
      )}
      <dl className="status-list">
        <StatusRow name="API process" status={apiProcessStatus(liveness)} />
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
          <dt>Service</dt>
          <dd>{liveness.kind === "ok" ? liveness.data.service : "Unknown"}</dd>
        </div>
        <div className="status-row">
          <dt>Version</dt>
          <dd>{liveness.kind === "ok" ? liveness.data.version : "Unknown"}</dd>
        </div>
      </dl>
    </section>
  );
}
