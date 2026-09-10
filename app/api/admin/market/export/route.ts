import { NextRequest, NextResponse } from "next/server";
import { isAdmin } from "@/lib/admin-auth";
import { getAdminRegistrationCoverage, getAdminRegistrationMarketSlice } from "@/lib/admin-registration-market";
import {
  isMarketDimension,
  isMarketWindow,
  missingReportPeriods,
  normalizeReportPeriod,
  resolveMarketWindow,
  type MarketSliceFilters,
} from "@/lib/registration-market";

export const dynamic = "force-dynamic";
function one(request: NextRequest, key: string) { return String(request.nextUrl.searchParams.get(key) || "").trim(); }
function active(value: string) { return value && value !== "ALL" ? [value] : undefined; }
function csv(value: unknown) { const text = String(value ?? ""); return /[",\n]/.test(text) ? `"${text.replaceAll('"','""')}"` : text; }

export async function GET(request: NextRequest) {
  if (!(await isAdmin())) return NextResponse.json({ error: "admin session required" }, { status: 401 });
  const period = normalizeReportPeriod(one(request, "period"));
  const dimensionRaw = one(request, "dimension") || "model";
  const windowRaw = one(request, "window") || "month";
  if (!period || !isMarketDimension(dimensionRaw) || !isMarketWindow(windowRaw)) {
    return NextResponse.json({ error: "invalid period/dimension/window" }, { status: 400 });
  }
  const allScopes = ["1","true","yes","on"].includes(one(request, "all_scopes").toLowerCase());
  const includeUnmapped = ["1","true","yes","on"].includes(one(request, "include_unmapped").toLowerCase());
  const filters: MarketSliceFilters = {
    registrationTypes: active(one(request, "registration_type")), brandIds: active(one(request, "brand")),
    modelIds: active(one(request, "model")), segments: active(one(request, "segment")), bodyTypes: active(one(request, "body_type")),
    powertrains: active(one(request, "powertrain")), oemGroups: active(one(request, "oem_group")),
    marketPositions: active(one(request, "market_position")), importTypes: active(one(request, "import_type")),
    originCountries: active(one(request, "origin_country")), brandOrigins: active(one(request, "brand_origin")),
    marketScopes: allScopes ? undefined : ["CORE", "MIXED"],
  };
  const resolved = resolveMarketWindow(period, windowRaw);
  const coverage = await getAdminRegistrationCoverage();
  const available = coverage.map((row: any) => String(row.period).slice(0,10));
  const missing = missingReportPeriods(resolved, available);
  if (missing.length) return NextResponse.json({ error: "registration market window is incomplete", missing_periods: missing }, { status: 409 });
  const rows = await getAdminRegistrationMarketSlice({ dimension: dimensionRaw, window: resolved, filters, includeUnmapped, limit: 500 });
  const header = ["rank","entity_key","entity","registrations","market_total","market_share_pct","mapping_coverage_pct"];
  const lines = [header.join(","), ...rows.map((row) => [row.market_rank,row.entity_key,row.entity_label,row.registrations,row.market_total,row.market_share_pct,row.window_mapping_coverage_pct].map(csv).join(","))];
  const body = "\ufeff" + lines.join("\n");
  return new NextResponse(body, { status: 200, headers: {
    "Content-Type": "text/csv; charset=utf-8",
    "Content-Disposition": `attachment; filename="tdr-admin-market-${dimensionRaw}-${String(period).slice(0,7)}.csv"`,
    "Cache-Control": "private, no-store",
  }});
}
