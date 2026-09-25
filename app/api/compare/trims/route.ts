import { NextResponse } from "next/server";
import { getCanonicalCompareTrimOptions } from "@/lib/compare-canonical-data";

// Public: picking which vehicles to compare is browsing, same as any other
// catalogue page. Only the produced comparison itself (POST/GET
// /api/tools/compare) requires an account and consumes the Free tier's
// daily Compare quota.
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    // The picker deliberately reads a lightweight projection of every trim.
    // Rich compare payloads are fetched later, only for the <=4 selected IDs.
    const trims = (await getCanonicalCompareTrimOptions()) as any[];
    return NextResponse.json({ trims }, { headers: { "Cache-Control": "public, max-age=300" } });
  } catch (error) {
    console.error("compare trim picker error", error);
    return NextResponse.json({ error: "could not load compare vehicles" }, { status: 500 });
  }
}
