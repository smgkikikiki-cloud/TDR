import { unstable_cache } from "next/cache";
import { getPublicMarket } from "@/lib/public-market";

/**
 * Homepage market preview.
 *
 * This deliberately reuses the same public aggregate as /market but caches it
 * so the landing page never turns every visit into a fresh 12-month analytics
 * computation. It does not touch the member endpoint and therefore consumes no
 * anonymous/member market quota.
 */
export const getHomeMarket = unstable_cache(
  async () => getPublicMarket("brand"),
  ["tdr-home-market-brand-v1"],
  { revalidate: 1800 },
);
