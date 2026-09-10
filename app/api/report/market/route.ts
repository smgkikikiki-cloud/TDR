import { NextRequest, NextResponse } from "next/server";
import {
  compareMarketSliceRows,
  comparisonMarketWindow,
  getRegistrationAvailablePeriods,
  getRegistrationMarketSlice,
  isMarketComparison,
  isMarketDimension,
  isMarketWindow,
  missingReportPeriods,
  normalizeReportPeriod,
  RegistrationAccessError,
  resolveMarketWindow,
  type MarketSliceFilters,
} from "@/lib/registration-analytics";

export const dynamic = "force-dynamic";

function values(request: NextRequest, name: string): string[] | undefined {
  const raw = request.nextUrl.searchParams.getAll(name)
    .flatMap((value) => value.split(","))
    .map((value) => value.trim())
    .filter(Boolean);
  return raw.length ? [...new Set(raw)] : undefined;
}

function filtersFromRequest(request: NextRequest): MarketSliceFilters {
  return {
    registrationTypes: values(request, "registration_type"),
    brandIds: values(request, "brand"),
    modelIds: values(request, "model"),
    segments: values(request, "segment"),
    bodyTypes: values(request, "body_type"),
    powertrains: values(request, "powertrain"),
    oemGroups: values(request, "oem_group"),
    marketPositions: values(request, "market_position"),
    importTypes: values(request, "import_type"),
    originCountries: values(request, "origin_country"),
    brandOrigins: values(request, "brand_origin"),
    marketScopes: values(request, "market_scope"),
  };
}

export async function GET(request: NextRequest) {
  const authorization = request.headers.get("authorization") || "";
  const match = /^Bearer\s+(.+)$/i.exec(authorization);
  if (!match) {
    return NextResponse.json({ error: "member bearer token required" }, { status: 401 });
  }

  const dimensionValue = request.nextUrl.searchParams.get("dimension") || "model";
  if (!isMarketDimension(dimensionValue)) {
    return NextResponse.json({ error: "unsupported market dimension" }, { status: 400 });
  }

  const requestedPeriod = request.nextUrl.searchParams.get("period");
  const period = normalizeReportPeriod(requestedPeriod);
  if (!requestedPeriod || !period) {
    return NextResponse.json(
      { error: "period is required and must be YYYY-MM or YYYY-MM-DD" },
      { status: 400 },
    );
  }

  const windowValue = request.nextUrl.searchParams.get("window") || "month";
  if (!isMarketWindow(windowValue)) {
    return NextResponse.json({ error: "unsupported market window" }, { status: 400 });
  }

  const compareValue = request.nextUrl.searchParams.get("compare");
  if (compareValue && !isMarketComparison(compareValue)) {
    return NextResponse.json({ error: "compare must be previous or yoy" }, { status: 400 });
  }

  const limitValue = Number(request.nextUrl.searchParams.get("limit") || "100");
  const limit = Number.isFinite(limitValue) ? Math.min(Math.max(Math.trunc(limitValue), 1), 500) : 100;
  const includeUnmapped = ["1", "true", "yes"].includes(
    String(request.nextUrl.searchParams.get("include_unmapped") || "").toLowerCase(),
  );
  const filters = filtersFromRequest(request);

  try {
    const available = await getRegistrationAvailablePeriods(match[1]);
    const currentWindow = resolveMarketWindow(period, windowValue);
    const missingCurrent = missingReportPeriods(currentWindow, available);
    if (missingCurrent.length) {
      return NextResponse.json({
        error: "registration market window is incomplete",
        window: currentWindow,
        missing_periods: missingCurrent,
      }, { status: 409 });
    }

    const rows = await getRegistrationMarketSlice({
      accessToken: match[1],
      dimension: dimensionValue,
      window: currentWindow,
      filters,
      includeUnmapped,
      limit,
    });

    let comparison = null;
    if (compareValue) {
      const previousWindow = comparisonMarketWindow(currentWindow, compareValue);
      const missingPrevious = missingReportPeriods(previousWindow, available);
      if (missingPrevious.length) {
        return NextResponse.json({
          error: "comparison registration window is incomplete",
          window: currentWindow,
          comparison_window: previousWindow,
          missing_periods: missingPrevious,
        }, { status: 409 });
      }
      const previousRows = await getRegistrationMarketSlice({
        accessToken: match[1],
        dimension: dimensionValue,
        window: previousWindow,
        filters,
        includeUnmapped,
        limit: 500,
      });
      comparison = {
        mode: compareValue,
        window: previousWindow,
        rows: previousRows,
        movement: compareMarketSliceRows(previousRows, rows),
      };
    }

    return NextResponse.json({
      dimension: dimensionValue,
      period,
      window: windowValue,
      period_from: currentWindow.from,
      period_to: currentWindow.to,
      filters,
      include_unmapped: includeUnmapped,
      rows,
      comparison,
    }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof RegistrationAccessError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("registration market report error", error);
    return NextResponse.json({ error: "registration market analytics unavailable" }, { status: 500 });
  }
}
