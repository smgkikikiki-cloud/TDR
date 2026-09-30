/** Pure helpers behind the design components (components/design/). Plain TypeScript so
 *  scripts/check-design-components.ts can test them under Node's type stripping. */

export type Tier = "free" | "member" | "pro" | "enterprise";

/** Badge labels. "free" is the plan/quota; "member" is a report readable by any signed-in
 *  member (analysis_reports.required_tier = MEMBER). The two are never interchangeable. */
export const TIER_LABEL: Record<Tier, string> = { free: "Free", member: "สมาชิก", pro: "Pro", enterprise: "Enterprise" };
export const TIER_CLASS: Record<Tier, string> = {
  free: "tdr-tier--free",
  member: "tdr-tier--member",
  pro: "tdr-tier--pro",
  enterprise: "tdr-tier--enterprise",
};

/** Report tier (DB: MEMBER | PRO | ENTERPRISE) → badge. FREE is not a report tier. */
export function tierForReport(required: "MEMBER" | "PRO" | "ENTERPRISE"): Tier {
  return required === "MEMBER" ? "member" : required === "PRO" ? "pro" : "enterprise";
}

export type DeltaUnit = "pp" | "%";
export type DeltaDirection = "up" | "down" | "zero" | "na";
export type DeltaView = { direction: DeltaDirection; text: string };

/** DESIGN §8: a percentage change needs a base of at least 30, otherwise it is shown as "–". */
export const MIN_PERCENT_BASE = 30;
const MINUS = "−";

/** Formats a change with its arrow and sign so it never relies on colour alone (DESIGN §3):
 *  up "▲ +1.2 pp", down "▼ −0.8 pp" (U+2212), rounds-to-zero "0.0 pp" with no arrow, missing or
 *  disallowed "–". `base` is the value the change is measured against: for unit "%" it is required
 *  and must be ≥ 30; for "pp" it only gates when given. */
export function formatDelta(
  value: number | null | undefined,
  opts: { unit?: DeltaUnit; base?: number | null; digits?: number } = {},
): DeltaView {
  const unit = opts.unit ?? "pp";
  const digits = opts.digits ?? 1;
  const na: DeltaView = { direction: "na", text: "–" };
  if (value == null || !Number.isFinite(value)) return na;
  if (unit === "%" && (opts.base == null || !(opts.base >= MIN_PERCENT_BASE))) return na;
  if (unit === "pp" && opts.base != null && !(opts.base >= MIN_PERCENT_BASE)) return na;
  const factor = 10 ** digits;
  const rounded = Math.round(Math.abs(value) * factor) / factor;
  const body = new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(rounded);
  if (rounded === 0) return { direction: "zero", text: `${body} ${unit}` };
  return value > 0
    ? { direction: "up", text: `▲ +${body} ${unit}` }
    : { direction: "down", text: `▼ ${MINUS}${body} ${unit}` };
}

/** Whole numbers get thousands separators (DESIGN §4); strings pass through untouched. */
export function formatNumber(value: number | string): string {
  return typeof value === "number" ? new Intl.NumberFormat("en-US").format(value) : value;
}

/** Clamps a 1-based step to 1..total for StageBar / ConfidenceMeter. */
export function clampStep(step: number, total: number): number {
  if (!Number.isFinite(step)) return 0;
  return Math.min(Math.max(Math.round(step), 0), total);
}
