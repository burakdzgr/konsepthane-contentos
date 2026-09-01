// URL search-param parsing for the read-only admin screens. Invalid values
// are silently dropped so a hand-edited URL degrades to the unfiltered view
// instead of erroring.

export type RawSearchParams = Record<string, string | string[] | undefined>;

const MAX_OFFSET = 1_000_000;
const MAX_SEARCH_TEXT = 100;
const MAX_URL_SEARCH_TEXT = 200;

export function firstParam(
  value: string | string[] | undefined,
): string | undefined {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
}

export function pickEnum<const T extends readonly string[]>(
  value: string | string[] | undefined,
  allowed: T,
): T[number] | undefined {
  const candidate = firstParam(value);
  if (
    candidate !== undefined &&
    (allowed as readonly string[]).includes(candidate)
  ) {
    return candidate as T[number];
  }
  return undefined;
}

export function parseOffset(value: string | string[] | undefined): number {
  const candidate = firstParam(value);
  if (candidate === undefined || !/^\d{1,7}$/.test(candidate)) {
    return 0;
  }
  return Math.min(Number(candidate), MAX_OFFSET);
}

export function parseSearchText(
  value: string | string[] | undefined,
  maxLength: number = MAX_SEARCH_TEXT,
): string | undefined {
  const candidate = firstParam(value)?.trim();
  if (!candidate) {
    return undefined;
  }
  return candidate.slice(0, maxLength);
}

export function parseUrlSearchText(
  value: string | string[] | undefined,
): string | undefined {
  return parseSearchText(value, MAX_URL_SEARCH_TEXT);
}

export function parseBooleanParam(
  value: string | string[] | undefined,
): boolean | undefined {
  const candidate = firstParam(value);
  if (candidate === "true") {
    return true;
  }
  if (candidate === "false") {
    return false;
  }
  return undefined;
}

export function buildPageQuery(
  params: Record<string, string | number | boolean | undefined>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const encoded = search.toString();
  return encoded === "" ? "" : `?${encoded}`;
}
