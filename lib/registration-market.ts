export type MarketDimension =
  | "brand"
  | "model"
  | "segment"
  | "body_type"
  | "powertrain"
  | "oem_group"
  | "market_position"
  | "import_type"
  | "origin_country"
  | "brand_origin"
  | "registration_type"
  | "market_scope";

export type MarketWindow = "month" | "rolling3" | "rolling6" | "rolling12" | "ytd";
export type MarketComparison = "previous" | "yoy";

export type MarketPeriodWindow = {
  from: string;
  to: string;
};

export type MarketSliceFilters = {
  registrationTypes?: string[];
  brandIds?: string[];
  modelIds?: string[];
  segments?: string[];
  bodyTypes?: string[];
  powertrains?: string[];
  oemGroups?: string[];
  marketPositions?: string[];
  importTypes?: string[];
  originCountries?: string[];
  brandOrigins?: string[];
  marketScopes?: string[];
};

export type MarketSliceRow = {
  entity_key: string;
  entity_label: string;
  registrations: number | string;
  market_total: number | string;
  market_share_pct: number | string;
  market_rank: number | string;
  window_raw_units: number | string;
  window_mapped_units: number | string;
  window_mapping_coverage_pct: number | string;
};

export type MarketMovementRow = {
  entity_key: string;
  entity_label: string;
  units_previous: number;
  units_current: number;
  units_change: number;
  share_previous_pct: number;
  share_current_pct: number;
  share_change_pp: number;
  rank_previous: number | null;
  rank_current: number | null;
  rank_change: number | null;
};

const MARKET_DIMENSIONS = new Set<MarketDimension>([
  "brand",
  "model",
  "segment",
  "body_type",
  "powertrain",
  "oem_group",
  "market_position",
  "import_type",
  "origin_country",
  "brand_origin",
  "registration_type",
  "market_scope",
]);

const MARKET_WINDOWS = new Set<MarketWindow>(["month", "rolling3", "rolling6", "rolling12", "ytd"]);
const MARKET_COMPARISONS = new Set<MarketComparison>(["previous", "yoy"]);

export function isMarketDimension(value: string | null): value is MarketDimension {
  return Boolean(value && MARKET_DIMENSIONS.has(value as MarketDimension));
}

export function isMarketWindow(value: string | null): value is MarketWindow {
  return Boolean(value && MARKET_WINDOWS.has(value as MarketWindow));
}

export function isMarketComparison(value: string | null): value is MarketComparison {
  return Boolean(value && MARKET_COMPARISONS.has(value as MarketComparison));
}

export function normalizeReportPeriod(value: string | null): string | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})(?:-\d{2})?$/.exec(value);
  if (!match) return null;
  const month = Number(match[2]);
  if (month < 1 || month > 12) return null;
  return `${match[1]}-${match[2]}-01`;
}

function periodIndex(value: string): number {
  const normalized = normalizeReportPeriod(value);
  if (!normalized) throw new Error(`invalid report period: ${value}`);
  const year = Number(normalized.slice(0, 4));
  const month = Number(normalized.slice(5, 7));
  return year * 12 + month - 1;
}

function periodFromIndex(value: number): string {
  const year = Math.floor(value / 12);
  const month = (value % 12) + 1;
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-01`;
}

export function shiftReportPeriod(value: string, months: number): string {
  return periodFromIndex(periodIndex(value) + Math.trunc(months));
}

export function resolveMarketWindow(period: string, window: MarketWindow): MarketPeriodWindow {
  const normalized = normalizeReportPeriod(period);
  if (!normalized) throw new Error(`invalid report period: ${period}`);
  if (window === "month") return { from: normalized, to: normalized };
  if (window === "ytd") return { from: `${normalized.slice(0, 4)}-01-01`, to: normalized };
  const months = window === "rolling3" ? 3 : window === "rolling6" ? 6 : 12;
  return { from: shiftReportPeriod(normalized, -(months - 1)), to: normalized };
}

export function previousMarketWindow(window: MarketPeriodWindow): MarketPeriodWindow {
  const width = periodIndex(window.to) - periodIndex(window.from) + 1;
  if (width < 1) throw new Error("market window end precedes start");
  const previousTo = shiftReportPeriod(window.from, -1);
  return { from: shiftReportPeriod(previousTo, -(width - 1)), to: previousTo };
}

export function comparisonMarketWindow(
  window: MarketPeriodWindow,
  comparison: MarketComparison,
): MarketPeriodWindow {
  if (comparison === "previous") return previousMarketWindow(window);
  return { from: shiftReportPeriod(window.from, -12), to: shiftReportPeriod(window.to, -12) };
}

export function reportPeriods(window: MarketPeriodWindow): string[] {
  const first = periodIndex(window.from);
  const last = periodIndex(window.to);
  if (last < first) throw new Error("market window end precedes start");
  return Array.from({ length: last - first + 1 }, (_, index) => periodFromIndex(first + index));
}

export function missingReportPeriods(window: MarketPeriodWindow, available: Iterable<string>): string[] {
  const known = new Set(Array.from(available, (period) => normalizeReportPeriod(period)).filter(Boolean));
  return reportPeriods(window).filter((period) => !known.has(period));
}

export function compareMarketSliceRows(
  previousRows: MarketSliceRow[],
  currentRows: MarketSliceRow[],
): MarketMovementRow[] {
  const previous = new Map(previousRows.map((row) => [row.entity_key, row]));
  const current = new Map(currentRows.map((row) => [row.entity_key, row]));
  const keys = new Set([...previous.keys(), ...current.keys()]);
  const rows: MarketMovementRow[] = [];

  for (const key of keys) {
    const left = previous.get(key);
    const right = current.get(key);
    const unitsPrevious = Number(left?.registrations || 0);
    const unitsCurrent = Number(right?.registrations || 0);
    const sharePrevious = Number(left?.market_share_pct || 0);
    const shareCurrent = Number(right?.market_share_pct || 0);
    const rankPrevious = left?.market_rank == null ? null : Number(left.market_rank);
    const rankCurrent = right?.market_rank == null ? null : Number(right.market_rank);
    rows.push({
      entity_key: key,
      entity_label: right?.entity_label || left?.entity_label || key,
      units_previous: unitsPrevious,
      units_current: unitsCurrent,
      units_change: unitsCurrent - unitsPrevious,
      share_previous_pct: sharePrevious,
      share_current_pct: shareCurrent,
      share_change_pp: shareCurrent - sharePrevious,
      rank_previous: rankPrevious,
      rank_current: rankCurrent,
      rank_change: rankPrevious != null && rankCurrent != null ? rankPrevious - rankCurrent : null,
    });
  }

  return rows.sort((a, b) =>
    b.share_change_pp - a.share_change_pp
    || b.units_current - a.units_current
    || a.entity_key.localeCompare(b.entity_key)
  );
}
