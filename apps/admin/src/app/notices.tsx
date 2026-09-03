// Bounded operator-facing outcome banners driven by redirect query params.
// Only known codes render; unknown values are ignored silently.

export const CONTROL_ERROR_MESSAGES: Record<string, string> = {
  conflict:
    "İstek mevcut durumla çelişiyor. Sayfayı yeniden yükleyip tekrar deneyin.",
  invalid: "Gönderilen değerler geçerli değil.",
  "not-found": "Kayıt bulunamadı.",
  "queue-failed": "Görev kuyruğa alınamadı. Hiçbir şey değiştirilmedi.",
  unreachable: "Backend API'ye şu anda erişilemiyor.",
  malformed: "Backend API beklenmedik veri döndürdü.",
};

export function ControlNotice({
  notice,
  error,
  noticeMessages,
}: {
  notice: string | undefined;
  error: string | undefined;
  noticeMessages: Record<string, string>;
}) {
  if (error !== undefined && CONTROL_ERROR_MESSAGES[error] !== undefined) {
    return (
      <p className="notice" data-tone="bad" role="status">
        {CONTROL_ERROR_MESSAGES[error]}
      </p>
    );
  }
  if (notice !== undefined && noticeMessages[notice] !== undefined) {
    return (
      <p className="notice" data-tone="ok" role="status">
        {noticeMessages[notice]}
      </p>
    );
  }
  return null;
}
