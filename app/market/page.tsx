import { getCanonicalBrands, getCanonicalModels } from "@/lib/canonical-data";
import { displayName } from "@/lib/display-name";
import { MarketExperience } from "./MarketExperience";
import { PublicMarketPreview } from "./PublicMarketPreview";

export const dynamic = "force-dynamic";

export default async function PublicMarketPage() {
  const [brandRows, modelRows] = await Promise.all([
    getCanonicalBrands(200),
    getCanonicalModels(700),
  ]);

  const brands = (brandRows as any[]).map((row) => ({
    id: String(row.id),
    name: displayName(row),
  }));
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

  return (
    <MarketExperience
      brands={brands}
      models={models}
      publicPreview={<PublicMarketPreview />}
      freePreview={<PublicMarketPreview loggedIn />}
    />
  );
}
