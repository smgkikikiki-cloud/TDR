import { NextRequest, NextResponse } from "next/server";
import {
  getCanonicalCompareTrimOptionsByIds,
  getCanonicalCompareTrimOptionsForModel,
} from "@/lib/compare-canonical-data";

// Public: picking which vehicles to compare is browsing, same as any other
// catalogue page. Only the produced comparison itself (POST/GET
// /api/tools/compare) requires an account and consumes the Free tier's
// daily Compare quota.
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const modelId = request.nextUrl.searchParams.get("model_id")?.trim() || "";
    const ids = [...new Set(request.nextUrl.searchParams.getAll("ids").filter(Boolean))].slice(0, 4);

    if (modelId) {
      const trims = await getCanonicalCompareTrimOptionsForModel(modelId);
      return NextResponse.json({ trims }, { headers: { "Cache-Control": "public, max-age=300" } });
    }

    if (ids.length) {
      const trims = await getCanonicalCompareTrimOptionsByIds(ids);
      return NextResponse.json({ trims }, { headers: { "Cache-Control": "public, max-age=300" } });
    }

    // Deliberately no "give me every trim" mode. The compare picker is
    // model-first, and deep links resolve at most four selected trim IDs.
    return NextResponse.json({ error: "model_id or ids is required" }, { status: 400 });
  } catch (error) {
    console.error("compare trim picker error", error);
    return NextResponse.json({ error: "could not load compare trims" }, { status: 500 });
  }
}
