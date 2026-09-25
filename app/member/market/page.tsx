import { getCanonicalBrands, getCanonicalModels } from "@/lib/canonical-data";
import { displayName } from "@/lib/display-name";
import { MarketWorkspace } from "./MarketWorkspace";

export const dynamic = "force-dynamic";

export default async function MemberMarketPage() {
  const [brandRows, modelRows] = await Promise.all([
    getCanonicalBrands(200),
    getCanonicalModels(700),
  ]);
  const models = (modelRows as any[])
    .filter((row) => row.status === "CURRENT")
    .map((row) => ({
      id: String(row.id),
      name: displayName(row),
      brandId: String(row.brands?.id || ""),
      brandName: displayName(row.brands),
      segment: row.segment || null,
      bodyType: row.body_type || null,
      powertrains: Array.isArray(row.powertrains) ? row.powertrains : [],
      // Already on the row: getCanonicalModels() spreads the canonical
      // payload directly (lib/canonical-data.ts's modelRow()), the same
      // payload.production_type/production_country/market_scope
      // lib/registration-analytics.ts reads to build oem_group/import_type/
      // origin_country/market_scope rows. No second query needed.
      importType: row.production_type || null,
      originCountry: row.production_country || null,
      marketScope: row.market_scope || null,
    }));
  const brands = (brandRows as any[]).map((row) => ({
    id: String(row.id),
    name: displayName(row),
    // Same as above: getCanonicalBrands() already spreads the brand payload,
    // which is exactly where oem_group/brand_origin come from.
    oemGroup: row.oem_group || null,
    brandOrigin: row.brand_origin || null,
  }));
  return <MarketWorkspace brands={brands} models={models} />;
}
