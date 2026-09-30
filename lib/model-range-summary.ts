type RangeFact = {
  field_key?: string | null;
  value?: unknown;
  value_state?: string | null;
  qualifiers?: Record<string, unknown> | null;
};

export type RangeTrim = {
  published_range_km?: number | string | null;
  published_range_cycle?: string | null;
  comparable_specs?: RangeFact[] | null;
};

export type PublishedRange = {
  value: number;
  cycle: string;
};

export type ModelRangeSummary = {
  range: string;
  cycle: string;
};

const RANGE_FIELD = "ev.rated_range_km";
const BASIS_PRIORITY = ["NEDC", "WLTP", "WLTC", "CLTC", "EPA", "ECO_STICKER_TH", ""] as const;
const SCOPE_PRIORITY = ["FULL", "ELECTRIC_ONLY", ""] as const;

function positiveNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function normalized(value: unknown): string {
  return String(value ?? "").trim().toUpperCase();
}

function basisRank(basis: string) {
  const index = BASIS_PRIORITY.indexOf(basis as (typeof BASIS_PRIORITY)[number]);
  return index === -1 ? BASIS_PRIORITY.length : index;
}

function cycleLabel(basis: string) {
  return basis === "ECO_STICKER_TH" ? "ECO Sticker TH" : basis;
}

/**
 * One deterministic value per measurement basis for one trim.
 *
 * The canonical spec ledger can legitimately carry the same range under
 * FULL/ELECTRIC_ONLY scopes (especially on BEVs) or alongside a generic
 * ECO Sticker observation. Prefer FULL, then ELECTRIC_ONLY, then an
 * unscoped fact, but never guess when the chosen scope itself contains
 * conflicting values.
 *
 * Legacy flat published_range_* columns are fallback only. A ledger-backed
 * value wins whenever the release carries one.
 */
function rangeChoices(trim: RangeTrim): Map<string, number> {
  const ledgerRows = Array.isArray(trim.comparable_specs)
    ? trim.comparable_specs.filter((fact) =>
        fact?.field_key === RANGE_FIELD
        && fact.value_state === "KNOWN"
        && positiveNumber(fact.value) !== null)
    : [];

  if (ledgerRows.length) {
    const byBasis = new Map<string, RangeFact[]>();
    for (const fact of ledgerRows) {
      const basis = normalized(fact.qualifiers?.measurement_basis);
      const bucket = byBasis.get(basis) || [];
      bucket.push(fact);
      byBasis.set(basis, bucket);
    }

    const choices = new Map<string, number>();
    for (const [basis, facts] of byBasis) {
      for (const scope of SCOPE_PRIORITY) {
        const scoped = facts.filter((fact) => normalized(fact.qualifiers?.range_scope) === scope);
        if (!scoped.length) continue;
        const values = [...new Set(scoped.map((fact) => positiveNumber(fact.value)).filter((v): v is number => v !== null))];
        if (values.length === 1) choices.set(basis, values[0]);
        break;
      }
    }
    return choices;
  }

  const legacy = positiveNumber(trim.published_range_km);
  if (legacy === null) return new Map();
  return new Map([[normalized(trim.published_range_cycle), legacy]]);
}

export function preferredRangeForTrim(trim: RangeTrim): PublishedRange | null {
  const choices = rangeChoices(trim);
  if (!choices.size) return null;
  const basis = [...choices.keys()].sort((a, b) => basisRank(a) - basisRank(b) || a.localeCompare(b))[0];
  return { value: choices.get(basis)!, cycle: cycleLabel(basis) };
}

/**
 * Summarise a model without ever mixing incompatible measurement standards.
 *
 * If every trim that has a range shares at least one basis, use the basis
 * with the broadest coverage (deterministic priority breaks ties) and show
 * the min-max across those trims. If ranged trims have only incompatible
 * standards, return null instead of manufacturing a misleading mixed range.
 */
export function modelRangeSummary(trims: RangeTrim[]): ModelRangeSummary | null {
  const perTrim = trims.map(rangeChoices);
  const ranged = perTrim.filter((choices) => choices.size > 0);
  if (!ranged.length) return null;

  const coverage = new Map<string, number>();
  for (const choices of ranged) {
    for (const basis of choices.keys()) coverage.set(basis, (coverage.get(basis) || 0) + 1);
  }

  const maxCoverage = Math.max(...coverage.values());
  if (maxCoverage !== ranged.length) return null;

  const basis = [...coverage.entries()]
    .filter(([, count]) => count === maxCoverage)
    .map(([key]) => key)
    .sort((a, b) => basisRank(a) - basisRank(b) || a.localeCompare(b))[0];
  const values = ranged.map((choices) => choices.get(basis)!).filter((value) => value !== undefined);
  if (!values.length) return null;

  const min = Math.min(...values);
  const max = Math.max(...values);
  const format = (n: number) => `${Math.round(n).toLocaleString()} km`;
  return {
    range: min === max ? format(min) : `${format(min)} – ${format(max)}`,
    cycle: cycleLabel(basis),
  };
}
