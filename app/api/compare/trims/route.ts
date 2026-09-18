import { NextResponse } from "next/server";
import { getCanonicalCompareTrims } from "@/lib/canonical-data";

// Public: picking which vehicles to compare is browsing, same as any other
// catalogue page. Only the produced comparison itself (POST/GET
// /api/tools/compare) requires an account and consumes the Free tier's
// daily Compare quota.
export const dynamic = "force-dynamic";

export async function GET() {
  // No limit: a car missing from the picker is a car a reader cannot compare.
  const trims = (await getCanonicalCompareTrims()) as any[];
  // model_id and powertrain travel with each trim so the picker can be the
  // two steps a person actually takes -- which car, then which version of it --
  // rather than one list of every trim in the country.
  const slim = trims.map((trim) => ({
    id: trim.id,
    model_id: trim.model_id,
    brand_name: trim.brand_name,
    model_name: trim.model_name,
    name: trim.name,
    powertrain: trim.powertrain ?? null,
    price_baht: trim.price_baht ?? null,
  }));
  return NextResponse.json({ trims: slim }, { headers: { "Cache-Control": "public, max-age=300" } });
}
