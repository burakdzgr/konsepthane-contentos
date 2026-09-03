import { fetchBackendReadiness } from "@/lib/contentos-api";
import { firstParam, type RawSearchParams } from "@/lib/search-params";
import { loginAction } from "./actions";

// The ONLY unauthenticated page. It shows the backend foundation status so
// an operator can tell an outage from a credential problem before signing
// in — and so the deployment smoke check keeps its truthful signal.
export const dynamic = "force-dynamic";

const ERRORS: Record<string, string> = {
  invalid: "Kullanıcı adı veya parola hatalı.",
  expired:
    "Oturumunuzun süresi doldu veya oturum iptal edildi. Yeniden giriş yapın.",
  unreachable: "Backend'e şu anda erişilemiyor. Tekrar deneyin.",
};

const NOTICES: Record<string, string> = {
  "logged-out": "Çıkış yaptınız.",
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
      <h1 id="login-title">Giriş yap</h1>
      <p className="muted">
        Sistem Durumu:{" "}
        <span className="badge" data-tone={operational ? "ok" : "bad"}>
          {operational ? "Çalışıyor" : "Erişilemiyor"}
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
          placeholder="kullanıcı adı"
          aria-label="Kullanıcı adı"
        />
        <input
          type="password"
          name="password"
          required
          maxLength={256}
          autoComplete="current-password"
          placeholder="parola"
          aria-label="Parola"
        />
        <button type="submit">Giriş yap</button>
      </form>
      <p className="muted">
        Hesaplar bir yönetici tarafından oluşturulur; kendi kendine kayıt
        yoktur.
      </p>
    </section>
  );
}
