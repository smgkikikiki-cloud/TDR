/** Pure logic behind /models (design/PAGES.md P02): URL params, filtering, facet counts, sorting and the
 *  12-at-a-time load step. Plain TypeScript with relative imports only, so scripts/check-models.ts can test it
 *  under Node's type stripping. Nothing here touches the market engine or the registration tables. */
import { bodyMatches, parseBodyParam } from "../body-families.ts";
import { byRelevance } from "../relevance.ts";
import { displayName } from "../display-name.ts";

/** The filter keys /models has always accepted; existing URLs keep working. */
export const FILTER_KEYS = ["body", "powertrain", "segment", "position", "production", "brand"] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];

export type ModelListRow = {
  id: string;
  slug?: string | null;
  name_en?: string | null;
  name_th?: string | null;
  body_type?: string | null;
  segment?: string | null;
  market_position?: string | null;
  production_type?: string | null;
  powertrains?: string[] | null;
  seats?: number | string | null;
  brands?: { slug?: string | null; name_en?: string | null; name_th?: string | null } | null;
  retail_price_min?: number | null;
  retail_price_max?: number | null;
  launch_year?: number | string | null;
  launch_quarter?: number | string | null;
};

export type ModelsParams = Partial<Record<FilterKey | "sort" | "page" | "tab" | "q", string>>;

/** Next hands searchParams over as string | string[]; a repeated key uses its first value. */
export function normalizeParams(raw: Record<string, string | string[] | undefined>): ModelsParams {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw || {})) {
    const first = Array.isArray(value) ? value[0] : value;
    if (typeof first === "string" && first !== "") out[key] = first;
  }
  return out as ModelsParams;
}

/* ---------- sort ---------- */

export const SORTS = [
  { value: "new", label: "ใหม่ล่าสุด" },
  { value: "price_asc", label: "ราคาต่ำ → สูง" },
  { value: "price_desc", label: "ราคาสูง → ต่ำ" },
  { value: "name", label: "ชื่อ A–Z" },
] as const;
export type SortValue = (typeof SORTS)[number]["value"];
export const DEFAULT_SORT: SortValue = "new";

export function parseSort(param: string | null | undefined): SortValue {
  return SORTS.some((s) => s.value === param) ? (param as SortValue) : DEFAULT_SORT;
}

/** The price a model is sorted by: its lowest current retail price, else its highest, else none. */
export function sortPrice(r: ModelListRow): number | null {
  const min = Number(r.retail_price_min);
  if (Number.isFinite(min) && min > 0) return min;
  const max = Number(r.retail_price_max);
  return Number.isFinite(max) && max > 0 ? max : null;
}

/** Order a list. A model with no price goes last under both price sorts (it is neither cheapest nor dearest).
 *  Ties fall back to the name, then to the incoming order, so the grid is stable. */
export function sortModels<T extends ModelListRow>(rows: readonly T[], sort: SortValue): T[] {
  const list = [...rows];
  const byName = (a: T, b: T) => displayName(a).localeCompare(displayName(b), "en");
  if (sort === "name") return list.sort(byName);
  if (sort === "price_asc" || sort === "price_desc") {
    const dir = sort === "price_asc" ? 1 : -1;
    return list
      .map((m, i) => ({ m, i, p: sortPrice(m) }))
      .sort((a, b) => {
        if (a.p === null && b.p === null) return byName(a.m, b.m) || a.i - b.i;
        if (a.p === null) return 1;
        if (b.p === null) return -1;
        return (a.p - b.p) * dir || byName(a.m, b.m) || a.i - b.i;
      })
      .map((x) => x.m);
  }
  // "ใหม่ล่าสุด": the catalogue's recency ordering (launch freshness; no registration data).
  return byRelevance(list, new Map()) as T[];
}

/* ---------- 12 at a time ---------- */

export const PAGE_SIZE = 12;

/** `?page=` counts load steps: page 1 shows the first 12, page 2 the first 24, and so on. */
export function parsePage(param: string | null | undefined): number {
  const n = Number.parseInt(String(param ?? ""), 10);
  return Number.isFinite(n) && n >= 1 ? n : 1;
}

export function pageWindow<T>(rows: readonly T[], page: number, size = PAGE_SIZE) {
  const shown = Math.min(rows.length, Math.max(1, page) * size);
  return { items: rows.slice(0, shown), shown, total: rows.length, hasMore: shown < rows.length, nextPage: Math.max(1, page) + 1 };
}

/* ---------- filtering ---------- */

export function facetHit(r: ModelListRow, key: FilterKey, value: string): boolean {
  if (key === "body") return r.body_type === value;
  if (key === "powertrain") return (r.powertrains || []).includes(value);
  if (key === "segment") return r.segment === value;
  if (key === "position") return r.market_position === value;
  if (key === "production") return r.production_type === value;
  return r.brands?.slug === value;
}

/** The catalogue predicate. `skip` leaves one facet out so its option counts read against every OTHER active filter.
 *  `body` takes the comma list from lib/body-families.ts; a single value behaves exactly as before. */
export function matchesFilters(r: ModelListRow, sp: ModelsParams, skip?: FilterKey): boolean {
  return (skip === "brand" || !sp.brand || r.brands?.slug === sp.brand)
    && (skip === "segment" || !sp.segment || r.segment === sp.segment)
    && (skip === "body" || bodyMatches(r.body_type, parseBodyParam(sp.body)))
    && (skip === "position" || !sp.position || r.market_position === sp.position)
    && (skip === "powertrain" || !sp.powertrain || (r.powertrains || []).includes(sp.powertrain))
    && (skip === "production" || !sp.production || r.production_type === sp.production);
}

/* ---------- URLs ---------- */

/** Rebuild <basePath>?... (default /models; a brand page passes its own path) with some keys changed. `null` removes a key. Any change other than `page` itself goes back
 *  to the first load step, so a new filter or sort never lands on page 4 of a different list. */
export function modelsHref(sp: ModelsParams, patch: Partial<Record<keyof ModelsParams, string | null>>, basePath = "/models"): string {
  const next = new URLSearchParams();
  const merged: Record<string, string | null | undefined> = { ...sp };
  const changesPage = "page" in patch;
  for (const [key, value] of Object.entries(patch)) merged[key] = value;
  if (!changesPage) delete merged.page;
  for (const [key, value] of Object.entries(merged)) if (value) next.set(key, value);
  const q = next.toString();
  return q ? `${basePath}?${q}` : basePath;
}

/* ---------- labels ---------- */

export const POWERTRAIN_LABEL: Record<string, string> = {
  ICE: "สันดาป", BEV: "ไฟฟ้าล้วน", HEV: "ไฮบริด", PHEV: "ปลั๊กอินไฮบริด", REEV: "REEV",
};
export const POWERTRAIN_OPTION_LABEL: Record<string, string> = {
  ICE: "ICE สันดาป", BEV: "BEV ไฟฟ้าล้วน", HEV: "HEV ไฮบริด", PHEV: "PHEV ปลั๊กอิน", REEV: "REEV",
};
export const PRODUCTION_LABEL: Record<string, string> = { CKD: "ประกอบในไทย (CKD)", SKD: "ประกอบในไทย (SKD)", CBU: "นำเข้า (CBU)" };

/** One rail option is shown when it selects at least one model, or when it is already active
 *  (so an active filter can always be undone). Zero-count options are hidden (DATA_MAP §/models). */
export function visibleOption(count: number, active: boolean): boolean {
  return active || count > 0;
}

/* ---------- card summary ---------- */

export type CardPriceText = { min: number | null; max: number | null };

export function priceBounds(r: ModelListRow): CardPriceText {
  const min = Number(r.retail_price_min), max = Number(r.retail_price_max);
  return { min: Number.isFinite(min) && min > 0 ? min : null, max: Number.isFinite(max) && max > 0 ? max : null };
}

/* ---------- picture credit ---------- */

/** A vehicle picture is shown only with a credit (DESIGN §9): an official-site asset whose source page is a real
 *  http(s) URL. Anything else gets the placeholder. The credit line names the source host. */
export function pictureCredit(source: { image_url?: string | null; image_source_url?: string | null; image_source_type?: string | null }):
  { src: string; href: string; host: string } | null {
  if (!source.image_url || source.image_source_type !== "official_site") return null;
  try {
    const url = new URL(String(source.image_source_url || ""));
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    return { src: source.image_url, href: url.toString(), host: url.hostname.replace(/^www\./, "") };
  } catch {
    return null;
  }
}

/** "฿629,900–659,900" for a range, "฿2,290,000" for one price, null when there is none. The ฿ is written once. */
export function bahtRangeText(min: number | null | undefined, max: number | null | undefined): string | null {
  const a = Number(min), b = Number(max);
  const lo = Number.isFinite(a) && a > 0 ? a : null;
  const hi = Number.isFinite(b) && b > 0 ? b : null;
  const f = (n: number) => n.toLocaleString("en-US");
  if (lo && hi && lo !== hi) return `฿${f(Math.min(lo, hi))}–${f(Math.max(lo, hi))}`;
  const one = lo ?? hi;
  return one ? `฿${f(one)}` : null;
}

/* ---------- compare hand-off ---------- */

/** Slots on /compare. Mirrors app/compare (and Home's COMPARE_MAX_TRIMS); PR 8 will share one constant. */
export const COMPARE_MAX = 4;

/** The /compare URL for ticked MODELS. A model is not a trim: /compare seeds its picker from `models` and waits for
 *  an explicit trim choice, so nothing is picked for the reader. (A known trim uses the older `?trims=` contract.) */
export function compareHref(modelIds: readonly string[]): string {
  const params = new URLSearchParams();
  for (const id of modelIds.slice(0, COMPARE_MAX)) params.append("models", id);
  const q = params.toString();
  return q ? `/compare?${q}` : "/compare";
}
