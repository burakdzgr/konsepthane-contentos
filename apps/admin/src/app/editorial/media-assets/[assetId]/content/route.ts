import { requestBackend } from "@/lib/contentos-api";
import { isUuid } from "@/lib/research-api";

// Authenticated byte proxy: the browser never talks to the backend
// directly, and the internal URL/storage layout never leave the server.
// The middleware already gates this path on the session cookie.

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ assetId: string }> },
): Promise<Response> {
  const { assetId } = await params;
  if (!isUuid(assetId)) {
    return new Response("Not found", { status: 404 });
  }
  const backend = await requestBackend(
    `/internal/editorial/media-assets/${encodeURIComponent(assetId)}/content`,
  );
  if (
    backend === null ||
    backend.status !== 200 ||
    backend.arrayBuffer === undefined
  ) {
    return new Response("Media content is not available", { status: 404 });
  }
  const data = await backend.arrayBuffer();
  return new Response(data, {
    headers: {
      "Content-Type":
        backend.headers.get("content-type") ?? "application/octet-stream",
      "Cache-Control": "private, max-age=300",
    },
  });
}
