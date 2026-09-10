import { adminDb } from "@/lib/supabase";
import type {
  MarketDimension,
  MarketPeriodWindow,
  MarketSliceFilters,
  MarketSliceRow,
} from "@/lib/registration-market";

export {
  compareMarketSliceRows,
  comparisonMarketWindow,
  isMarketComparison,
  isMarketDimension,
  isMarketWindow,
  missingReportPeriods,
  normalizeReportPeriod,
  previousMarketWindow,
  reportPeriods,
  resolveMarketWindow,
  shiftReportPeriod,
} from "@/lib/registration-market";
export type {
  MarketComparison,
  MarketDimension,
  MarketMovementRow,
  MarketPeriodWindow,
  MarketSliceFilters,
  MarketSliceRow,
  MarketWindow,
} from "@/lib/registration-market";

export type RegistrationDimension =
  | "coverage"
  | "brand"
  | "model"
  | "mom"
  | "segment"
  | "powertrain"
  | "chinese-bev";

const ACTIVE_STATUSES = new Set(["ACTIVE", "TRIALING", "GRACE"]);

const VIEW_CONFIG: Record<RegistrationDimension, { table: string; order: string; ascending?: boolean }> = {
  coverage: { table: "registration_analytics_coverage", order: "period", ascending: true },
  brand: { table: "registration_brand_share", order: "market_rank", ascending: true },
  model: { table: "registration_model_share", order: "market_rank", ascending: true },
  mom: { table: "registration_model_mom", order: "mom_delta", ascending: false },
  segment: { table: "registration_monthly_segment", order: "segment_rank", ascending: true },
  powertrain: { table: "registration_monthly_powertrain", order: "powertrain_rank", ascending: true },
  "chinese-bev": { table: "registration_chinese_bev_rank", order: "bev_rank", ascending: true },
};

export class RegistrationAccessError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function isRegistrationDimension(value: string | null): value is RegistrationDimension {
  return Boolean(value && value in VIEW_CONFIG);
}

async function requireRegistrationEntitlement(accessToken: string) {
  const db = adminDb();
  if (!db) throw new RegistrationAccessError(503, "registration analytics database is not configured");

  const { data: userData, error: userError } = await db.auth.getUser(accessToken);
  if (userError || !userData.user) {
    throw new RegistrationAccessError(401, "invalid or expired member session");
  }

  const { data: entitlement, error: entitlementError } = await db
    .from("tdr_entitlements")
    .select("status,valid_until")
    .eq("user_id", userData.user.id)
    .eq("product", "registration_full")
    .maybeSingle();

  if (entitlementError) {
    throw new RegistrationAccessError(503, "could not verify registration entitlement");
  }

  const validUntil = entitlement?.valid_until ? new Date(entitlement.valid_until) : null;
  const expired = validUntil ? validUntil.getTime() <= Date.now() : false;
  if (!entitlement || !ACTIVE_STATUSES.has(entitlement.status) || expired) {
    throw new RegistrationAccessError(403, "registration analytics entitlement required");
  }

  return db;
}

export async function getRegistrationAnalytics(args: {
  accessToken: string;
  dimension: RegistrationDimension;
  period?: string | null;
  limit?: number;
}) {
  const db = await requireRegistrationEntitlement(args.accessToken);
  const config = VIEW_CONFIG[args.dimension];
  const limit = Math.min(Math.max(args.limit ?? 100, 1), 500);

  let query = db.from(config.table).select("*");
  if (args.period) query = query.eq("period", args.period);
  query = query.order(config.order, { ascending: config.ascending ?? true }).limit(limit);

  const { data, error } = await query;
  if (error) throw new RegistrationAccessError(500, `registration analytics query failed: ${error.message}`);

  return data ?? [];
}

export async function getRegistrationAvailablePeriods(accessToken: string): Promise<string[]> {
  const db = await requireRegistrationEntitlement(accessToken);
  const { data, error } = await db
    .from("registration_analytics_coverage")
    .select("period")
    .order("period", { ascending: true });
  if (error) throw new RegistrationAccessError(500, `registration period query failed: ${error.message}`);
  return (data ?? [])
    .map((row: any) => String(row.period).slice(0, 10))
    .filter(Boolean);
}

export async function getRegistrationMarketSlice(args: {
  accessToken: string;
  dimension: MarketDimension;
  window: MarketPeriodWindow;
  filters?: MarketSliceFilters;
  includeUnmapped?: boolean;
  limit?: number;
}): Promise<MarketSliceRow[]> {
  const db = await requireRegistrationEntitlement(args.accessToken);
  const limit = Math.min(Math.max(args.limit ?? 100, 1), 500);
  const filters = args.filters || {};
  const { data, error } = await db.rpc("registration_market_slice", {
    p_period_from: args.window.from,
    p_period_to: args.window.to,
    p_dimension: args.dimension,
    p_registration_types: filters.registrationTypes || null,
    p_brand_ids: filters.brandIds || null,
    p_model_ids: filters.modelIds || null,
    p_segments: filters.segments || null,
    p_body_types: filters.bodyTypes || null,
    p_powertrains: filters.powertrains || null,
    p_oem_groups: filters.oemGroups || null,
    p_market_positions: filters.marketPositions || null,
    p_import_types: filters.importTypes || null,
    p_origin_countries: filters.originCountries || null,
    p_brand_origins: filters.brandOrigins || null,
    p_market_scopes: filters.marketScopes || null,
    p_include_unmapped: Boolean(args.includeUnmapped),
    p_limit: limit,
  });
  if (error) throw new RegistrationAccessError(500, `registration market slice failed: ${error.message}`);
  return (data ?? []) as MarketSliceRow[];
}
