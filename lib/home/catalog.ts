import { cache } from "react";
import { getCanonicalBrands, getCanonicalCompareTrims, getCanonicalModels } from "@/lib/canonical-data";
import { isCurrentLifecycleStatus } from "@/lib/canonical-trim-status";
import { summarizeCatalog, type HomeCatalog } from "@/lib/home/catalog-logic";

/** Home's catalogue numbers, straight from the canonical catalogue (current models, current trims, brands with a
 *  current model). Deduplicated per request, so the Vehicle Database and Compare blocks share one read.
 *  It throws on a read failure: each block catches it and shows its own error state instead of blanking the page. */
export const getHomeCatalog = cache(async (): Promise<HomeCatalog> => {
  const [models, brands, trims] = await Promise.all([
    getCanonicalModels(600),
    getCanonicalBrands(150),
    getCanonicalCompareTrims(),
  ]);
  const current = (models as any[]).filter((row) => isCurrentLifecycleStatus(row.status));
  return summarizeCatalog(current, brands as any[], trims as any[]);
});
