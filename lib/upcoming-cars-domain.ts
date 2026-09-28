/** Editorial timing and labels; there are intentionally no canonical IDs here. */
export const UPCOMING_STATUSES = ["RUMORED", "CONFIRMED"] as const;
export const UPCOMING_CONFIDENCE = ["HIGH", "MEDIUM", "LOW"] as const;
export const RUMOR_HALVES = ["H1", "H2"] as const;
export const CONFIRMED_QUARTERS = ["Q1", "Q2", "Q3", "Q4"] as const;

export type UpcomingStatus = typeof UPCOMING_STATUSES[number];
export type UpcomingConfidence = typeof UPCOMING_CONFIDENCE[number];
export type RumorHalf = typeof RUMOR_HALVES[number];
export type ConfirmedQuarter = typeof CONFIRMED_QUARTERS[number];

export type UpcomingTiming = {
  status: UpcomingStatus;
  confidence: UpcomingConfidence;
  launchYear: number;
  rumorHalf: RumorHalf | null;
  confirmedQuarter: ConfirmedQuarter | null;
  confirmedMonth: number | null;
  confirmedDay: number | null;
};

export function isUpcomingTiming(value: UpcomingTiming): boolean {
  if (!UPCOMING_STATUSES.includes(value.status) || !UPCOMING_CONFIDENCE.includes(value.confidence)
    || !Number.isSafeInteger(value.launchYear) || value.launchYear < 1) return false;
  if (value.status === "RUMORED") {
    return RUMOR_HALVES.includes(value.rumorHalf as RumorHalf)
      && value.confirmedQuarter === null && value.confirmedMonth === null && value.confirmedDay === null;
  }
  if (value.rumorHalf !== null) return false;
  if (value.confirmedQuarter !== null && !CONFIRMED_QUARTERS.includes(value.confirmedQuarter)) return false;
  if (value.confirmedMonth !== null && (!Number.isInteger(value.confirmedMonth)
    || value.confirmedMonth < 1 || value.confirmedMonth > 12)) return false;
  if (value.confirmedDay !== null && (value.confirmedMonth === null
    || !Number.isInteger(value.confirmedDay) || value.confirmedDay < 1 || value.confirmedDay > 31)) return false;
  return value.confirmedMonth === null || value.confirmedQuarter === null
    || value.confirmedQuarter === `Q${Math.ceil(value.confirmedMonth / 3)}`;
}

/** Month precision already implies a quarter; editors never need to enter both. */
export function confirmedQuarterForDisplay(value: UpcomingTiming): ConfirmedQuarter | null {
  if (!isUpcomingTiming(value) || value.status !== "CONFIRMED") return null;
  return value.confirmedMonth === null
    ? value.confirmedQuarter
    : `Q${Math.ceil(value.confirmedMonth / 3)}` as ConfirmedQuarter;
}

export function displayUpcomingTiming(value: UpcomingTiming): string {
  if (!isUpcomingTiming(value)) throw new Error("Invalid upcoming car timing");
  if (value.status === "RUMORED") return `${value.rumorHalf} ${value.launchYear}`;
  if (value.confirmedMonth !== null) {
    const month = String(value.confirmedMonth).padStart(2, "0");
    return value.confirmedDay === null
      ? `${month}/${value.launchYear}`
      : `${String(value.confirmedDay).padStart(2, "0")}/${month}/${value.launchYear}`;
  }
  const quarter = confirmedQuarterForDisplay(value);
  return quarter ? `${quarter} ${value.launchYear}` : String(value.launchYear);
}
