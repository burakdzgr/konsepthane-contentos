import { fetchBackendReadiness } from "@/lib/contentos-api";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { loginAction } from "./actions";

// The ONLY unauthenticated page. It shows the backend foundation status so
// an operator can tell an outage from a credential problem before signing
// in — and so the deployment smoke check keeps its truthful signal.
export const dynamic = "force-dynamic";

const ERRORS: Record<string, string> = {
  invalid: "Invalid credentials.",
  expired: "Your session has expired or was revoked. Sign in again.",
  unreachable: "The backend cannot be reached right now. Try again.",
};

const NOTICES: Record<string, string> = {
  "logged-out": "You have been signed out.",
};

export default async function LoginPage({
  searchParams,
}: {
  searchParams?: Promise<RawSearchParams>;
}) {
  const query = searchParams === undefined ? {} : await searchParams;
  const error = firstParam(query.error);
  const notice = firstParam(query.notice);
  const readiness = await fetchBackendReadiness();
  const operational =
    readiness.kind === "ok" && readiness.data.status === "ready";

  return (
    <section className="panel" aria-labelledby="login-title">
      <h1 id="login-title">Sign in</h1>
      <p className="muted">
        Foundation Status:{" "}
        <span className="badge" data-tone={operational ? "ok" : "bad"}>
          {operational ? "Operational" : "Unavailable"}
        </span>
      </p>
      {error !== undefined && ERRORS[error] !== undefined && (
        <p role="alert">{ERRORS[error]}</p>
      )}
      {notice !== undefined && NOTICES[notice] !== undefined && (
        <p role="status">{NOTICES[notice]}</p>
      )}
      <form action={loginAction} className="control-form">
        <input
          type="text"
          name="username"
          required
          maxLength={64}
          autoComplete="username"
          placeholder="username"
          aria-label="Username"
        />
        <input
          type="password"
          name="password"
          required
          maxLength={256}
          autoComplete="current-password"
          placeholder="password"
          aria-label="Password"
        />
        <button type="submit">Sign in</button>
      </form>
      <p className="muted">
        Accounts are provisioned by an administrator; there is no
        self-registration.
      </p>
    </section>
  );
}
