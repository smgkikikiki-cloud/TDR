export type CoverageRowLike = {
  period?: string | null;
  total_registrations?: number | string | null;
  mapped_unit_pct?: number | string | null;
};

export const PROVISIONAL_RATIO = 0.40;
export const PROVISIONAL_BASELINE_MONTHS = 6;

export function periodKey(value: unknown): string {
  return String(value || "").slice(0, 7);
}

export function provisionalMarketPeriods(rows: CoverageRowLike[]): Set<string> {
  const ordered = rows
    .map((row) => ({ period: periodKey(row.period), units: Number(row.total_registrations || 0) }))
    .filter((row) => /^\d{4}-\d{2}$/.test(row.period))
    .sort((a, b) => a.period.localeCompare(b.period));
  const out = new Set<string>();
  for (let index = PROVISIONAL_BASELINE_MONTHS; index < ordered.length; index++) {
    const baselineRows = ordered.slice(index - PROVISIONAL_BASELINE_MONTHS, index)
      .map((row) => row.units)
      .sort((a, b) => a - b);
    if (!baselineRows.length) continue;
    const middle = Math.floor(baselineRows.length / 2);
    const baseline = baselineRows.length % 2
      ? baselineRows[middle]
      : (baselineRows[middle - 1] + baselineRows[middle]) / 2;
    if (baseline > 0 && ordered[index].units < baseline * PROVISIONAL_RATIO) out.add(ordered[index].period);
  }
  return out;
}

export function defaultMarketPeriod(rows: CoverageRowLike[]): string | null {
  const provisional = provisionalMarketPeriods(rows);
  const periods = rows.map((row) => periodKey(row.period)).filter((period) => /^\d{4}-\d{2}$/.test(period)).sort();
  const settled = periods.filter((period) => !provisional.has(period));
  return settled.at(-1) || periods.at(-1) || null;
}

export function coverageForPeriod(rows: CoverageRowLike[], period: string): CoverageRowLike | null {
  return rows.find((row) => periodKey(row.period) === periodKey(period)) || null;
}
