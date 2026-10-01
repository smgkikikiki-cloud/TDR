/** Pure search over the canonical catalogue (design/PAGES.md P07). The overlay's live suggestions and the /search page
 *  rank the same way: a name that starts with the query first, then a word that starts with it, then any other match.
 *  Matching still covers name_en, name_th, slug and canonical_id (the old contract), so every query that found
 *  something before still does. Plain TypeScript with relative imports only (run by scripts/check-brands-search.ts). */
import { isCurrentLifecycleStatus } from "../canonical-trim-status.ts";
import { displayName } from "../display-name.ts";

export const QUERY_MAX = 80;
export const SUGGEST_MODELS = 6;
export const SUGGEST_BRANDS = 4;
export const PAGE_MODELS = 24;
export const PAGE_BRANDS = 12;

/** Trim, collapse whitespace, cap the length. Anything that is not a string is the empty query. */
export function normalizeQuery(raw: unknown): string {
  if (typeof raw !== "string") return "";
  return raw.replace(/\s+/g, " ").trim().slice(0, QUERY_MAX);
}

type Row = { status?: unknown; slug?: string | null; canonical_id?: string | null; name_en?: string | null; name_th?: string | null; brands?: { name_en?: string | null; name_th?: string | null; slug?: string | null } | null };

function rank(row: Row, q: string): number | null {
  const term = q.toLocaleLowerCase();
  const fields = [row.name_en, row.name_th, row.slug, row.canonical_id].map((v) => String(v || "").toLocaleLowerCase());
  if (!fields.some((f) => f.includes(term))) return null;
  const name = displayName(row).toLocaleLowerCase();
  if (name.startsWith(term)) return 0;
  if (name.split(/[\s\-_/]+/).some((w) => w.startsWith(term))) return 1;
  // "brand model" typed as one phrase
  const full = `${displayName(row.brands)} ${displayName(row)}`.toLocaleLowerCase();
  if (full.startsWith(term)) return 1;
  return 2;
}

function pick<T extends Row>(rows: readonly T[], q: string, limit: number): T[] {
  return rows
    .map((r, i) => ({ r, i, k: rank(r, q) }))
    .filter((x): x is { r: T; i: number; k: number } => x.k !== null)
    .sort((a, b) => a.k - b.k || displayName(a.r).localeCompare(displayName(b.r), "en") || a.i - b.i)
    .slice(0, limit)
    .map((x) => x.r);
}

/** THE catalogue search (the overlay's suggestions, /search and `searchCanonicalCatalog` all run this one function).
 *  Only models whose lifecycle is CURRENT can be found (HISTORICAL and UNVERIFIED identities never appear), and a brand can
 *  only be found while it has at least one such model, the same rule as the brand index. */
export function searchCatalog<M extends Row, B extends Row>(models: readonly M[], brands: readonly B[], rawQuery: unknown, limits = { models: PAGE_MODELS, brands: PAGE_BRANDS }) {
  const q = normalizeQuery(rawQuery);
  if (!q) return { q, models: [] as M[], brands: [] as B[] };
  const current = models.filter((m) => isCurrentLifecycleStatus(m.status));
  const live = new Set(current.map((m) => m.brands?.slug).filter(Boolean));
  return { q, models: pick(current, q, limits.models), brands: pick(brands.filter((b) => live.has(b.slug)), q, limits.brands) };
}

/** The most-listed brands, for the empty-search suggestions. */
export function popularBrands<M extends { brands?: { slug?: string | null; name_en?: string | null; name_th?: string | null } | null }>(models: readonly M[], n = 8): { slug: string; name: string; count: number }[] {
  const per = new Map<string, { name: string; count: number }>();
  for (const m of models) {
    const slug = m.brands?.slug;
    if (!slug) continue;
    const e = per.get(slug) || { name: displayName(m.brands), count: 0 };
    e.count += 1;
    per.set(slug, e);
  }
  return [...per.entries()].map(([slug, e]) => ({ slug, ...e })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "en")).slice(0, n);
}
