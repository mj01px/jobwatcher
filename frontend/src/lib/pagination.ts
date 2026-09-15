export const ELLIPSIS = "…";
export type PageEntry = number | typeof ELLIPSIS;

const MAX_SIMPLE_PAGES = 7;
const SIBLING_COUNT = 2;

/**
 * Contextual, sliding window page sequence. Page 1 and the last page are always present. Near either
 * edge the window widens so the same number of pages stays visible, and the
 * ellipsis only appears where at least one page is really hidden.
 */
export function pageSequence(current: number, total: number): PageEntry[] {
  if (total <= 0) return [];

  const clamped = Math.max(1, Math.min(current, total));
  if (total <= MAX_SIMPLE_PAGES) return Array.from({ length: total }, (_, index) => index + 1);

  const rawStart = clamped - SIBLING_COUNT;
  const rawEnd = clamped + SIBLING_COUNT;
  let windowStart = rawStart;
  let windowEnd = rawEnd;

  if (rawStart <= 1) windowEnd = Math.max(windowEnd, 2 * SIBLING_COUNT + 2);
  if (rawEnd >= total) windowStart = Math.min(windowStart, total - (2 * SIBLING_COUNT + 1));

  windowStart = Math.max(windowStart, 1);
  windowEnd = Math.min(windowEnd, total);

  const shown = new Set<number>([1, total]);
  for (let page = windowStart; page <= windowEnd; page += 1) shown.add(page);
  const ordered = [...shown].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b);

  const sequence: PageEntry[] = [];
  let previous: number | null = null;
  for (const page of ordered) {
    if (previous !== null && page - previous > 1) sequence.push(ELLIPSIS);
    sequence.push(page);
    previous = page;
  }
  return sequence;
}

/** Normalizes the requested page from the URL: invalid values fall back to 1, overflow to the last page. */
export function normalizePage(rawPage: unknown, totalPages: number): number {
  const parsed = typeof rawPage === "number" ? rawPage : Number.parseInt(String(rawPage ?? ""), 10);
  let page = Number.isInteger(parsed) ? parsed : 1;
  if (page < 1) page = 1;
  if (!totalPages) return 1;
  if (page > totalPages) page = totalPages;
  return page;
}
