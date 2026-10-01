/** Pure logic behind the brand index (design/PAGES.md P05) and brand pages (P06): which brands are listed, with how
 *  many current models and what price range, grouped by initial letter for the A–Z jump bar, and the client filter.
 *  Brands are text; nothing here reads a logo. Plain TypeScript with relative imports only (scripts/check-brands-search.ts
 *  runs it under Node's type stripping). */
import { displayName } from "../display-name.ts";

export type BrandRow = { slug: string; name: string; count: number; min: number | null; max: number | null };
export type BrandGroup = { letter: string; rows: BrandRow[] };

type BrandIn = { slug?: string | null; name_en?: string | null; name_th?: string | null };
type ModelIn = {
  brands?: { slug?: string | null } | null;
  retail_price_min?: number | null; retail_price_max?: number | null;
};

const positive = (n: unknown): number | null => { const v = Number(n); return Number.isFinite(v) && v > 0 ? v : null; };

/** One row per brand that has at least one current model (the same set the "แบรนด์" KPI counts), A to Z by name.
 *  `models` must already be filtered to current lifecycle. Price range = lowest and highest stored retail price. */
export function buildBrandIndex(brands: readonly BrandIn[], models: readonly ModelIn[]): BrandRow[] {
  const agg = new Map<string, { count: number; min: number | null; max: number | null }>();
  for (const m of models) {
    const slug = m.brands?.slug;
    if (!slug) continue;
    const a = agg.get(slug) || { count: 0, min: null, max: null };
    a.count += 1;
    for (const p of [positive(m.retail_price_min), positive(m.retail_price_max)]) {
      if (p === null) continue;
      a.min = a.min === null ? p : Math.min(a.min, p);
      a.max = a.max === null ? p : Math.max(a.max, p);
    }
    agg.set(slug, a);
  }
  const bySlug = new Map(brands.map((b) => [String(b.slug || ""), b]));
  return [...agg.entries()]
    .map(([slug, a]) => ({ slug, name: displayName(bySlug.get(slug) || { slug }) || slug, ...a }))
    .sort((x, y) => x.name.localeCompare(y.name, "en", { sensitivity: "base" }) || x.slug.localeCompare(y.slug));
}

/** Initial letter for grouping: A–Z for a Latin name, "#" for anything else (digit, Thai, symbol). */
export function initialOf(name: string): string {
  const c = name.trim().charAt(0).toUpperCase();
  return /^[A-Z]$/.test(c) ? c : "#";
}

/** Rows grouped by initial, A–Z first and "#" last; each group keeps the incoming (A–Z) order. */
export function groupByInitial(rows: readonly BrandRow[]): BrandGroup[] {
  const groups = new Map<string, BrandRow[]>();
  for (const r of rows) {
    const l = initialOf(r.name);
    groups.set(l, [...(groups.get(l) || []), r]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a === "#" ? 1 : b === "#" ? -1 : a.localeCompare(b)))
    .map(([letter, rs]) => ({ letter, rows: rs }));
}

export const JUMP_LETTERS = [..."ABCDEFGHIJKLMNOPQRSTUVWXYZ", "#"] as const;

/** Case-insensitive, whitespace-tolerant match on the brand name or slug. An empty query matches everything. */
export function filterBrands(rows: readonly BrandRow[], query: string): BrandRow[] {
  const q = query.trim().toLowerCase().replace(/\s+/g, " ");
  if (!q) return [...rows];
  return rows.filter((r) => r.name.toLowerCase().includes(q) || r.slug.toLowerCase().includes(q.replace(/ /g, "-")) || r.slug.toLowerCase().includes(q));
}

/** The three KPIs of a brand page, from that brand's CURRENT models and the CURRENT-trim counts per model
 *  (lib/canonical-data.ts getCurrentTrimCountsByModel). `models` must already be this brand's current models.
 *  The price range is the lowest and highest stored retail price; no stored price means null, never a made-up range. */
export function brandKpis(models: readonly (ModelIn & { id: string })[], trimCountsByModel: ReadonlyMap<string, number>) {
  let min: number | null = null, max: number | null = null;
  for (const m of models) for (const p of [positive(m.retail_price_min), positive(m.retail_price_max)]) {
    if (p === null) continue;
    min = min === null ? p : Math.min(min, p);
    max = max === null ? p : Math.max(max, p);
  }
  return { models: models.length, trims: models.reduce((n, m) => n + (trimCountsByModel.get(m.id) || 0), 0), min, max };
}
