// Bounded operator-facing outcome banners driven by redirect query params.
// Only known codes render; unknown values are ignored silently.

export const CONTROL_ERROR_MESSAGES: Record<string, string> = {
  conflict:
    "The request conflicts with the current state. Reload the page and try again.",
  invalid: "The submitted values were not valid.",
  "not-found": "The record was not found.",
  "queue-failed": "Queueing the task failed. Nothing was changed.",
  unreachable: "The backend API cannot be reached right now.",
  malformed: "The backend API returned unexpected data.",
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
