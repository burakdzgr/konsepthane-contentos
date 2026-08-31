// Health of the Next.js admin process only. This route must never depend on
// the FastAPI backend, PostgreSQL, or Redis; backend readiness lives on the
// backend's own /health/ready endpoint.

export function GET(): Response {
  return Response.json({ status: "ok", service: "contentos-admin" });
}
