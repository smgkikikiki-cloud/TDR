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
  type MarketPeriodWindow,
  type MarketSliceFilters,
  type MarketSliceRow,
} from "@/lib/registration-analytics";
import { normalizeRequestedMarketScopes } from "@/lib/market-scope";
import { adminDb } from "@/lib/supabase";
import {
  getActiveMarketPriceState,
  MARKET_PRICE_BANDS,
  MARKET_PRICE_MIN_COVERAGE_PCT,
  priceStateModelCoverage,
  resolveModelPriceBand,
  type MarketPriceBand,
  type MarketPriceState,
} from "@/lib/market-price-state";

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
    marketScopes: normalizeRequestedMarketScopes(values(request, "market_scope")),
  };
}

type PriceCoverage = {
  basis: "canonical_model_count";
  priced_models: number;
  mixed_models: number;
  total_models: number;
  coverage_pct: number;
  minimum_required_pct: number;
};

async function priceCoverage(state: MarketPriceState | null, period: string): Promise<PriceCoverage> {
  const db = adminDb();
  let totalModels = 0;
  if (db) {
    const { count, error } = await db.from("current_vehicle_models").select("*", { count: "exact", head: true });
    if (error) throw new Error(`canonical model count query failed: ${error.message}`);
    totalModels = Number(count || 0);
  }
  const summary = priceStateModelCoverage(state, period);
  return {
    basis: "canonical_model_count",
    priced_models: summary.pricedModels,
    mixed_models: summary.mixedModels,
    total_models: totalModels,
    coverage_pct: totalModels ? Math.round((1000 * summary.pricedModels) / totalModels) / 10 : 0,
    minimum_required_pct: MARKET_PRICE_MIN_COVERAGE_PCT,
  };
}

function intersectModelFilter(filters: MarketSliceFilters, eligible: Set<string>, dimension: string): MarketSliceFilters {
  if (dimension === "model") return filters;
  const requested = filters.modelIds?.length ? new Set(filters.modelIds) : null;
  const modelIds = [...eligible].filter((id) => !requested || requested.has(id));
  return { ...filters, modelIds };
}

function rerankModelRows(rows: MarketSliceRow[], eligible: Set<string>): MarketSliceRow[] {
  const kept = rows
    .filter((row) => eligible.has(String(row.entity_key)))
    .sort((a, b) => Number(b.registrations || 0) - Number(a.registrations || 0)
      || String(a.entity_key).localeCompare(String(b.entity_key)));
  const total = kept.reduce((sum, row) => sum + Number(row.registrations || 0), 0);
  return kept.map((row, index) => ({
    ...row,
    market_total: total,
    market_share_pct: total ? Math.round((10000 * Number(row.registrations || 0)) / total) / 100 : 0,
    market_rank: index + 1,
  }));
}

function eligibleModels(state: MarketPriceState | null, period: string, band: MarketPriceBand): Set<string> {
  const eligible = new Set<string>();
  if (!state) return eligible;
  for (const modelId of state.trimsByModel.keys()) {
    if (resolveModelPriceBand(state, modelId, period) === band) eligible.add(modelId);
  }
  return eligible;
}

async function marketSliceWithPrice(args: {
  accessToken: string;
  dimension: Parameters<typeof getRegistrationMarketSlice>[0]["dimension"];
  window: MarketPeriodWindow;
  filters: MarketSliceFilters;
  includeUnmapped: boolean;
  limit: number;
  priceBand: MarketPriceBand | null;
  priceState: MarketPriceState | null;
}) {
  const eligible = args.priceBand ? eligibleModels(args.priceState, args.window.to, args.priceBand) : null;
  const filters = eligible ? intersectModelFilter(args.filters, eligible, args.dimension) : args.filters;
  const rows = await getRegistrationMarketSlice({
    accessToken: args.accessToken,
    dimension: args.dimension,
    window: args.window,
    filters,
    includeUnmapped: args.includeUnmapped,
    limit: args.dimension === "model" && eligible ? 500 : args.limit,
  });
  return args.dimension === "model" && eligible ? rerankModelRows(rows, eligible).slice(0, args.limit) : rows;
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
  const comparisonMode = compareValue && isMarketComparison(compareValue) ? compareValue : null;

  const requestedPriceBand = String(request.nextUrl.searchParams.get("price_band") || "").trim().toUpperCase();
  const priceBand = requestedPriceBand && MARKET_PRICE_BANDS.includes(requestedPriceBand as MarketPriceBand)
    ? requestedPriceBand as MarketPriceBand
    : null;
  if (requestedPriceBand && !priceBand) {
    return NextResponse.json({ error: "price_band must be ENTRY, VOLUME, UPPER or LUXURY" }, { status: 400 });
  }
  if (priceBand && windowValue !== "month") {
    return NextResponse.json({
      error: "price-band filtering is currently month-grain only; rolling/YTD cohorts stay disabled until dated ledger coverage supports fact-month slicing",
    }, { status: 400 });
  }

  const limitValue = Number(request.nextUrl.searchParams.get("limit") || "100");
  const limit = Number.isFinite(limitValue) ? Math.min(Math.max(Math.trunc(limitValue), 1), 500) : 100;
  const includeUnmapped = ["1", "true", "yes"].includes(
    String(request.nextUrl.searchParams.get("include_unmapped") || "").toLowerCase(),
  );
  const filters = filtersFromRequest(request);

  try {
    // Entitlement is checked before privileged canonical-price metadata is read.
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

    const db = adminDb();
    const priceState = db ? await getActiveMarketPriceState(db) : null;
    const currentPriceCoverage = await priceCoverage(priceState, currentWindow.to);
    if (priceBand && currentPriceCoverage.coverage_pct < MARKET_PRICE_MIN_COVERAGE_PCT) {
      return NextResponse.json({
        error: "verified canonical LIST_PRICE coverage is too low for a paid price cohort",
        price_band: priceBand,
        price_coverage: currentPriceCoverage,
      }, { status: 409 });
    }

    // A comparison must be calculated from the full competitive set, not the
    // display limit. Otherwise rank 11 becomes a fake zero merely because the
    // caller asked to render a top-10 table.
    const queryLimit = comparisonMode ? 500 : limit;
    const currentRows = await marketSliceWithPrice({
      accessToken: match[1],
      dimension: dimensionValue,
      window: currentWindow,
      filters,
      includeUnmapped,
      limit: queryLimit,
      priceBand,
      priceState,
    });

    let comparison = null;
    if (comparisonMode) {
      const previousWindow = comparisonMarketWindow(currentWindow, comparisonMode);
      const missingPrevious = missingReportPeriods(previousWindow, available);
      if (missingPrevious.length) {
        return NextResponse.json({
          error: "comparison registration window is incomplete",
          window: currentWindow,
          comparison_window: previousWindow,
          missing_periods: missingPrevious,
        }, { status: 409 });
      }
      const previousPriceCoverage = await priceCoverage(priceState, previousWindow.to);
      if (priceBand && previousPriceCoverage.coverage_pct < MARKET_PRICE_MIN_COVERAGE_PCT) {
        return NextResponse.json({
          error: "comparison price cohort does not have enough verified canonical LIST_PRICE coverage",
          price_band: priceBand,
          comparison_window: previousWindow,
          price_coverage: previousPriceCoverage,
        }, { status: 409 });
      }
      const previousRows = await marketSliceWithPrice({
        accessToken: match[1],
        dimension: dimensionValue,
        window: previousWindow,
        filters,
        includeUnmapped,
        limit: 500,
        priceBand,
        priceState,
      });
      comparison = {
        mode: comparisonMode,
        window: previousWindow,
        rows: previousRows.slice(0, limit),
        movement: compareMarketSliceRows(previousRows, currentRows),
        price_coverage: previousPriceCoverage,
      };
    }

    return NextResponse.json({
      dimension: dimensionValue,
      period,
      window: windowValue,
      period_from: currentWindow.from,
      period_to: currentWindow.to,
      filters,
      price_band: priceBand,
      price_coverage: currentPriceCoverage,
      include_unmapped: includeUnmapped,
      rows: currentRows.slice(0, limit),
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
