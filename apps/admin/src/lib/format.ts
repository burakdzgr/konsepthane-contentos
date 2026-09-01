// Deterministic server-side timestamp formatting: rendered once on the
// server in UTC, so output never depends on viewer timezone, ICU data, or
// hydration timing.

const EMPTY_PLACEHOLDER = "—";

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export function formatUtcTimestamp(iso: string | null | undefined): string {
  if (!iso) {
    return EMPTY_PLACEHOLDER;
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return EMPTY_PLACEHOLDER;
  }
  return (
    `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-` +
    `${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:` +
    `${pad(date.getUTCMinutes())} UTC`
  );
}

export function formatCount(
  value: number,
  singular: string,
  plural: string,
): string {
  return `${value} ${value === 1 ? singular : plural}`;
}
