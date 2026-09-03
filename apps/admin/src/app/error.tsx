"use client";

export default function RouteError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <section className="panel" role="alert">
      <h1>Bir şeyler ters gitti</h1>
      <p>
        Kontrol paneli beklenmedik bir hatayla karşılaştı. Güvenlik nedeniyle
        teknik ayrıntılar burada gösterilmiyor.
      </p>
      <button type="button" onClick={() => reset()}>
        Tekrar dene
      </button>
    </section>
  );
}
