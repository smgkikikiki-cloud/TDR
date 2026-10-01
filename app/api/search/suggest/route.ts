import { NextRequest, NextResponse } from "next/server";
import { getCanonicalBrands, getCanonicalModels } from "@/lib/canonical-data";
import { displayName } from "@/lib/display-name";
import { SUGGEST_BRANDS, SUGGEST_MODELS, normalizeQuery, searchCatalog } from "@/lib/search/catalog";

// Live suggestions for the header search overlay (P07). Public, read-only, canonical catalogue only, through the same
// public (anon) client as every catalogue page and the same searchCatalog() that /search uses (CURRENT models and live
// brands only). No service-role client is involved anywhere in this path. The catalogue read is kept for a minute per server instance so typing does
// not re-read it on every keystroke.
export const dynamic = "force-dynamic";

let cache: { at: number; models: any[]; brands: any[] } | null = null;
const TTL_MS = 60_000;

async function catalogue() {
  if (cache && Date.now() - cache.at < TTL_MS) return cache;
  const [brands, models] = await Promise.all([getCanonicalBrands(250), getCanonicalModels(600)]);
  cache = { at: Date.now(), brands, models: models as any[] };
  return cache;
}

export async function GET(request: NextRequest) {
  const q = normalizeQuery(request.nextUrl.searchParams.get("q"));
  if (!q) return NextResponse.json({ q, models: [], brands: [] }, { headers: { "Cache-Control": "no-store" } });
  try {
    const { models, brands } = await catalogue();
    const found = searchCatalog(models, brands, q, { models: SUGGEST_MODELS, brands: SUGGEST_BRANDS });
    return NextResponse.json({
      q,
      models: found.models.map((m: any) => ({ slug: m.slug, name: displayName(m), brand: displayName(m.brands) })),
      brands: found.brands.map((b: any) => ({ slug: b.slug, name: displayName(b) })),
    }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    console.error("search suggest error", error);
    return NextResponse.json({ error: "search unavailable" }, { status: 500 });
  }
}
