import { NextResponse } from "next/server";
import { getCanonicalCompareModelOptions } from "@/lib/compare-canonical-data";

// Public browse endpoint for the first step of Compare. This intentionally
// returns models only; trims are loaded lazily after a model is selected.
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const models = await getCanonicalCompareModelOptions();
    return NextResponse.json({ models }, { headers: { "Cache-Control": "public, max-age=300" } });
  } catch (error) {
    console.error("compare model picker error", error);
    return NextResponse.json({ error: "could not load compare models" }, { status: 500 });
  }
}
