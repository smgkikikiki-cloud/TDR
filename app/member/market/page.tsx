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
    .filter((row) => String(row.status || "current").toLowerCase() !== "discontinued")
    .map((row) => ({
      id: String(row.id),
      name: displayName(row),
      brandId: String(row.brands?.id || ""),
      brandName: displayName(row.brands),
      segment: row.segment || null,
      bodyType: row.body_type || null,
      powertrains: Array.isArray(row.powertrains) ? row.powertrains : [],
    }));
  const brands = (brandRows as any[]).map((row) => ({ id: String(row.id), name: displayName(row) }));
  return <MarketWorkspace brands={brands} models={models} />;
}
