/** Pure logic behind the Home page's catalogue blocks (Vehicle Database + Compare Specs).
 *  Plain TypeScript so scripts/check-home.ts can test it under Node's type stripping.
 *  Nothing here touches the market engine: Home's market figures are blocked (GRAFT_PLAN blocker 11). */

export type HomeModel = {
  id: string;
  slug?: string | null;
  name_en?: string | null;
  name_th?: string | null;
  status?: unknown;
  body_type?: string | null;
  brand_id?: string | null;
  brands?: { slug?: string | null; name_en?: string | null; name_th?: string | null } | null;
  powertrains?: string[] | null;
  production_type?: string | null;
  market_position?: string | null;
  image_url?: string | null;
  retail_price_min?: number | null;
  retail_price_max?: number | null;
};
export type HomeTrim = { model_id?: string | null; price_baht?: number | null };
export type HomeBrand = { slug?: string | null; name_en?: string | null; name_th?: string | null };

/** The six body-family chips of the approved reference (DATA_MAP §Home). A family is a set of canonical body values and
 *  its count is the number of current models whose body_type is in the set; TRUCK is not a chip. `/models?body=` takes a
 *  single value today, so only a one-value family can link accurately; a multi-value family stays a plain chip until
 *  PR 6 gives /models a family filter. */
export const HOME_BODY_CHIPS = [
  { key: "sedan", label: "รถเก๋ง", values: ["SEDAN", "COUPE", "WAGON"], icon: "sedan" },
  { key: "suv", label: "SUV", values: ["CROSSOVER", "PPV", "OFFROAD"], icon: "suv" },
  { key: "hatchback", label: "แฮทช์แบ็ก", values: ["HATCHBACK"], icon: "hatchback" },
  { key: "pickup", label: "กระบะ", values: ["PICKUP"], icon: "pickup" },
  { key: "mpv", label: "MPV", values: ["MPV"], icon: "mpv" },
  { key: "van", label: "รถตู้", values: ["VAN"], icon: "van" },
] as const;
export type BodyIcon = (typeof HOME_BODY_CHIPS)[number]["icon"];

/** Where a family chip goes: the models list for a one-value family, nowhere for a multi-value one. */
export function bodyFamilyHref(values: readonly string[]): string | null {
  return values.length === 1 ? `/models?body=${values[0]}` : null;
}

export const HOME_BRAND_CHIP_LIMIT = 18;

/** Trims one comparison holds. Mirrors the four slots in app/compare/page.tsx; PR 8 (Compare) will share one constant. */
export const COMPARE_MAX_TRIMS = 4;

export type CompareExample = { key: string; brand: string; model: string; trims: number; min: number | null; max: number | null };
export type HomeCatalog = {
  models: number;
  trims: number;
  brands: number;
  bodies: { key: string; label: string; icon: BodyIcon; count: number; href: string | null }[];
  brandChips: { slug: string; name: string; count: number }[];
  compare: CompareExample[];
};

/** How complete a model's card can be: price, powertrain, body, mass position and local assembly rank it. */
export function modelScore(r: HomeModel): number {
  const price = r.retail_price_min || r.retail_price_max ? 4 : 0;
  const powertrain = (r.powertrains || []).length ? 2 : 0;
  const body = r.body_type ? 2 : 0;
  const mass = String(r.market_position || "").toLowerCase() === "mass" ? 2 : 0;
  const local = r.production_type === "CKD" || r.production_type === "SKD" ? 1 : 0;
  return price + powertrain + body + mass + local;
}

const brandName = (b: { name_en?: string | null; name_th?: string | null } | null | undefined) => (b?.name_en || b?.name_th || "").trim();
const modelName = (m: HomeModel) => (m.name_en || m.name_th || m.slug || "").trim();

export function priceRange(prices: number[]): { min: number | null; max: number | null } {
  const real = prices.filter((p) => Number.isFinite(p) && p > 0);
  return real.length ? { min: Math.min(...real), max: Math.max(...real) } : { min: null, max: null };
}

/** Two example cars for the compare block: the best-described current models that have at least two current
 *  trims and a price, so the block always shows a real comparison. Brand and model are text; no photo is
 *  chosen here (DESIGN §9: a photo needs a verified credit). */
export function pickCompareExamples(current: HomeModel[], trims: HomeTrim[], count = 2): CompareExample[] {
  const byModel = new Map<string, number[]>();
  for (const t of trims) {
    if (!t.model_id) continue;
    const list = byModel.get(t.model_id) || [];
    list.push(Number(t.price_baht));
    byModel.set(t.model_id, list);
  }
  const candidates = current
    .map((m) => ({ m, all: byModel.get(m.id) || [] }))
    .filter(({ all }) => all.length >= 2 && priceRange(all).min !== null)
    .sort((a, b) => modelScore(b.m) - modelScore(a.m) || modelName(a.m).localeCompare(modelName(b.m)));
  const picked: CompareExample[] = [];
  const usedBrands = new Set<string>();
  for (const { m, all } of candidates) {
    const brand = brandName(m.brands);
    if (usedBrands.has(brand)) continue; // two different brands make a comparison, not two trims of one
    usedBrands.add(brand);
    const { min, max } = priceRange(all);
    picked.push({ key: m.id, brand, model: modelName(m), trims: all.length, min, max });
    if (picked.length === count) break;
  }
  return picked;
}

/** Everything Home shows from the catalogue, from rows already filtered to current lifecycle. */
export function summarizeCatalog(current: HomeModel[], brands: HomeBrand[], currentTrims: HomeTrim[]): HomeCatalog {
  const perBrand = new Map<string, number>();
  for (const m of current) {
    const slug = m.brands?.slug;
    if (slug) perBrand.set(slug, (perBrand.get(slug) || 0) + 1);
  }
  const byslug = new Map(brands.map((b) => [b.slug || "", b]));
  const brandChips = [...perBrand.entries()]
    .map(([slug, count]) => ({ slug, count, name: brandName(byslug.get(slug)) || slug }))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
    .slice(0, HOME_BRAND_CHIP_LIMIT);
  return {
    models: current.length,
    trims: currentTrims.length,
    brands: perBrand.size,
    bodies: HOME_BODY_CHIPS.map((c) => ({
      key: c.key, label: c.label, icon: c.icon, href: bodyFamilyHref(c.values),
      count: current.filter((m) => (c.values as readonly string[]).includes(String(m.body_type))).length,
    })),
    brandChips,
    compare: pickCompareExamples(current, currentTrims),
  };
}
