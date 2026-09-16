import { NextResponse } from "next/server";
import { getCanonicalCompareTrims } from "@/lib/canonical-data";

// Public: picking which vehicles to compare is browsing, same as any other
// catalogue page. Only the produced comparison itself (POST/GET
// /api/tools/compare) requires an account and consumes the Free tier's
// daily Compare quota.
export const dynamic = "force-dynamic";

export async function GET() {
  const trims = (await getCanonicalCompareTrims(600)) as any[];
  const slim = trims.map((trim) => ({
    id: trim.id,
    brand_name: trim.brand_name,
    model_name: trim.model_name,
    name: trim.name,
  }));
  return NextResponse.json({ trims: slim }, { headers: { "Cache-Control": "public, max-age=300" } });
}
