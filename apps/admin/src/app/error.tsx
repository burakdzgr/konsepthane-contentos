"use client";

export default function RouteError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <section className="panel" role="alert">
      <h1>Something went wrong</h1>
      <p>
        The control panel hit an unexpected error. No technical details are
        shown here for safety.
      </p>
      <button type="button" onClick={() => reset()}>
        Try again
      </button>
    </section>
  );
}
