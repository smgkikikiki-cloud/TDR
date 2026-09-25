import { NextRequest, NextResponse } from "next/server";
import {
  areMarketFiltersAllowed,
  getPolicy,
  historyWindowStart,
  isMarketComparisonAllowed,
  isMarketDimensionAllowed,
  isMarketWindowAllowed,
} from "@/lib/access-policy";
import {
  assertMarketSliceAllowed,
  compareMarketSliceRows,
  comparisonMarketWindow,
  consumeMarketReportQuota,
  getRegistrationAvailablePeriods,
  isMarketComparison,
  isMarketDimension,
  isMarketWindow,
  loadRegistrationFactSpan,
  missingReportPeriods,
  normalizeReportPeriod,
  RegistrationAccessError,
  resolveMarketWindow,
  resolveRegistrationAccess,
  sliceLoadedFacts,
  type AccessContext,
  type CanonicalRegistrationFact,
  type MarketDimension,
  type MarketPeriodWindow,
  type MarketSliceFilters,
  type MarketSliceRow,
} from "@/lib/registration-analytics";
import { normalizeRequestedMarketScopes } from "@/lib/market-scope";
import { adminDb } from "@/lib/supabase";
import { recordEvent } from "@/lib/telemetry";
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

// Canonicalizes a filters object for fingerprinting: sorts each filter
// array's values (query-parameter ordering, e.g. ?brand=A&brand=B vs
// ?brand=B&brand=A, must not make an otherwise-identical request
// fingerprint differently and pay twice) and sorts the object's own keys
// for a stable JSON.stringify output.
function canonicalFilterFingerprint(filters: MarketSliceFilters): string {
  const sortedEntries = Object.keys(filters).sort().map((key) => {
    const value = (filters as unknown as Record<string, unknown>)[key];
    return [key, Array.isArray(value) ? [...value].sort() : value] as const;
  });
  return JSON.stringify(Object.fromEntries(sortedEntries));
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

// Quota-free: the caller (GET below) has already paid for this whole
// request via consumeMarketReportQuota() exactly once. This may be called
// several times per request (current window, comparison window, trend
// months) and none of those calls pay again -- see
// lib/registration-analytics.ts::loadRegistrationFactSpan.
//
// `facts` is the whole request's registration facts, already fetched and
// canonicalized ONCE for the union of every window this request needs (see
// GET below) -- this function only gates the specific (dimension, window)
// combination it was called for and slices the shared facts down to it, in
// memory. It never fetches anything itself.
async function marketSliceWithPrice(args: {
  ctx: AccessContext;
  dimension: MarketDimension;
  window: MarketPeriodWindow;
  filters: MarketSliceFilters;
  includeUnmapped: boolean;
  limit: number;
  priceBand: MarketPriceBand | null;
  priceState: MarketPriceState | null;
  facts: CanonicalRegistrationFact[];
}) {
  await assertMarketSliceAllowed(args.ctx, args.dimension, args.window, args.filters);
  const eligible = args.priceBand ? eligibleModels(args.priceState, args.window.to, args.priceBand) : null;
  const filters = eligible ? intersectModelFilter(args.filters, eligible, args.dimension) : args.filters;
  const rows = sliceLoadedFacts({
    facts: args.facts,
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
  // How many trailing months of "Market Size Trend" sparkline data to
  // return alongside the main ranking, folded into this same response so
  // the client makes exactly ONE request per "Update market" click instead
  // of the old up-to-6 separate client-side fetches.
  const trendMonths = Math.min(Math.max(Number(request.nextUrl.searchParams.get("trend_months") || "6") || 0, 0), 12);

  try {
    const ctx = await resolveRegistrationAccess(match[1]);

    // The aggregation window and the comparison period are depth, the same as
    // the dimension is, so they are checked against the plan here -- before a
    // row is read and regardless of what the controls offered.
    if (!isMarketWindowAllowed(windowValue, ctx.tier)) {
      return NextResponse.json({
        error: `ช่วงเวลานี้อยู่ในแพ็กเกจแบบเสียค่าบริการ`,
        upgrade_required: true,
      }, { status: 403 });
    }
    if (comparisonMode && !isMarketComparisonAllowed(comparisonMode, ctx.tier)) {
      return NextResponse.json({
        error: `การเทียบแบบนี้อยู่ในแพ็กเกจแบบเสียค่าบริการ`,
        upgrade_required: true,
      }, { status: 403 });
    }

    const available = await getRegistrationAvailablePeriods(ctx);
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

    // The ONE quota-consuming call for this entire request -- everything
    // below (current window, comparison window, trend months) reuses this
    // same ctx and pays nothing further, regardless of how many internal
    // slices that takes. The fingerprint must cover every output-changing
    // request parameter, not just the filters/window/dimension: `limit` and
    // `trend_months` both change what the response actually contains, so
    // two requests that differ only in those must not be treated as the
    // same request and coalesce.
    const quota = await consumeMarketReportQuota(ctx, [
      dimensionValue, windowValue, currentWindow.from, currentWindow.to,
      comparisonMode ?? "", priceBand ?? "", includeUnmapped,
      limit, trendMonths,
      canonicalFilterFingerprint(filters),
    ]);

    // Every window this request could need, resolved up front -- before any
    // registration-fact fetch -- so the underlying facts (paginated fact
    // rows, canonical model/brand/alias lookups, historical model state) can
    // be loaded once for their union span and sliced per window in memory,
    // instead of once per window (up to 8 per "Update market" click: current
    // + comparison + up to 6 trend months, each re-running the full
    // fetch-and-canonicalize pipeline from scratch against the same data).
    let previousWindow: MarketPeriodWindow | null = null;
    let previousPriceCoverage: PriceCoverage | null = null;
    if (comparisonMode) {
      previousWindow = comparisonMarketWindow(currentWindow, comparisonMode);
      const missingPrevious = missingReportPeriods(previousWindow, available);
      if (missingPrevious.length) {
        return NextResponse.json({
          error: "comparison registration window is incomplete",
          window: currentWindow,
          comparison_window: previousWindow,
          missing_periods: missingPrevious,
        }, { status: 409 });
      }
      previousPriceCoverage = await priceCoverage(priceState, previousWindow.to);
      if (priceBand && previousPriceCoverage.coverage_pct < MARKET_PRICE_MIN_COVERAGE_PCT) {
        return NextResponse.json({
          error: "comparison price cohort does not have enough verified canonical LIST_PRICE coverage",
          price_band: priceBand,
          comparison_window: previousWindow,
          price_coverage: previousPriceCoverage,
        }, { status: 409 });
      }
    }
    // market_total is the same number whichever dimension it is grouped by
    // -- it is a sum over the filtered scope, not a slice of it -- so
    // "oem_group" here is just one arbitrary, always-open dimension (unlike
    // "model", which needs a tier check) rather than the ranked dimension:
    // every selected filter still applies, so market_total remains the true
    // scope total for each trailing month regardless of what is being ranked.
    const trendPeriods = trendMonths > 0 ? available.filter((p) => p <= currentWindow.to).slice(-trendMonths) : [];
    const trendWindows = trendPeriods.map((trendPeriod) => resolveMarketWindow(trendPeriod, "month"));

    const spanWindows = [currentWindow, ...(previousWindow ? [previousWindow] : []), ...trendWindows];
    const span: MarketPeriodWindow = {
      from: spanWindows.reduce((min, w) => (w.from < min ? w.from : min), spanWindows[0].from),
      to: spanWindows.reduce((max, w) => (w.to > max ? w.to : max), spanWindows[0].to),
    };
    const dimensionsNeeded: MarketDimension[] = trendWindows.length
      ? [dimensionValue, "oem_group"] : [dimensionValue];
    const facts = await loadRegistrationFactSpan({ ctx, span, filters, dimensionsNeeded });

    // A comparison must be calculated from the full competitive set, not the
    // display limit. Otherwise rank 11 becomes a fake zero merely because the
    // caller asked to render a top-10 table.
    const queryLimit = comparisonMode ? 500 : limit;
    const currentRows = await marketSliceWithPrice({
      ctx,
      dimension: dimensionValue,
      window: currentWindow,
      filters,
      includeUnmapped,
      limit: queryLimit,
      priceBand,
      priceState,
      facts,
    });

    let comparison = null;
    if (comparisonMode && previousWindow && previousPriceCoverage) {
      const previousRows = await marketSliceWithPrice({
        ctx,
        dimension: dimensionValue,
        window: previousWindow,
        filters,
        includeUnmapped,
        limit: 500,
        priceBand,
        priceState,
        facts,
      });
      comparison = {
        mode: comparisonMode,
        window: previousWindow,
        rows: previousRows.slice(0, limit),
        movement: compareMarketSliceRows(previousRows, currentRows),
        price_coverage: previousPriceCoverage,
      };
    }

    // Trend sparkline, computed server-side within this same paid request,
    // now sliced from the already-loaded `facts` rather than fetching again
    // per month. Each month still gates and slices independently (and still
    // silently drops on failure) so one month outside this account's history
    // window does not blank the whole sparkline.
    const trendFilters = { ...filters };
    const points = await Promise.all(trendPeriods.map(async (trendPeriod, index) => {
      try {
        const rows = await marketSliceWithPrice({
          ctx,
          dimension: "oem_group",
          window: trendWindows[index],
          filters: trendFilters,
          includeUnmapped,
          limit: 1,
          priceBand: null,
          priceState,
          facts,
        });
        return { period: trendPeriod, total: Number(rows[0]?.market_total || 0) };
      } catch {
        return null;
      }
    }));
    const trend = points.filter(Boolean) as Array<{ period: string; total: number }>;

    await recordEvent({ eventName: "sales_run", userId: ctx.userId, props: { dimension: dimensionValue, window: windowValue, compare: comparisonMode } });

    return NextResponse.json({
      // What this account may ask for, so the controls can say which options
      // cost money instead of offering them and then failing. The checks above
      // are the enforcement; this is only how the page explains itself.
      plan: {
        tier: ctx.tier,
        model_grain: isMarketDimensionAllowed("model", ctx.tier, null),
        windows: getPolicy(ctx.tier).marketWindows,
        comparisons: getPolicy(ctx.tier).marketComparisons,
        filters: areMarketFiltersAllowed(ctx.tier),
        history_from: historyWindowStart(ctx.tier),
      },
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
      trend,
      quota,
    }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof RegistrationAccessError) {
      if (error.status === 429) {
        const db = adminDb();
        const { data: userData } = db ? await db.auth.getUser(match[1]) : { data: null };
        await recordEvent({ eventName: "sales_quota_hit", userId: userData?.user?.id ?? null });
      }
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    console.error("registration market report error", error);
    return NextResponse.json({ error: "registration market analytics unavailable" }, { status: 500 });
  }
}
