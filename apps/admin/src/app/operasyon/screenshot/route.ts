import { requestBackend } from "@/lib/contentos-api";

// Authenticated byte proxy for the gateway's live browser frame: the
// browser polls this path; the backend fetches the JPEG from the gateway
// with the admin token, which never leaves the server side. The middleware
// gates this path on the session cookie like every other page.

export async function GET(): Promise<Response> {
  const backend = await requestBackend("/internal/operations/screenshot");
  if (
    backend === null ||
    backend.status !== 200 ||
    backend.arrayBuffer === undefined
  ) {
    return new Response("Browser frame is not available", { status: 503 });
  }
  const data = await backend.arrayBuffer();
  return new Response(data, {
    headers: {
      "Content-Type": backend.headers.get("content-type") ?? "image/jpeg",
      "Cache-Control": "no-store",
    },
  });
}
