/**
 * HUMAN workflow sidecars: the action-level rules, ported from
 * automotive/vehicle_master/vehreg/retail_lifecycle_review.py,
 * vehreg/current_retail.py and vehreg/model_operational_state.py
 * (ENGINE_INVENTORY §4.9).
 *
 * The stored rows' own rules (named HUMAN reviewer, http(s)-or-empty
 * source_ref, unique non-blank approved ids, approved ids are base-catalog
 * trims of the model, an approved member never carries a HISTORICAL decision)
 * are enforced by the master tables (migration_v59). What depends on the
 * action being taken -- which actions exist, the bootstrap path, the
 * parent-model rule, the approved-set carve-out -- is planned here.
 */

type Row = Record<string, any>;

export class SidecarError extends Error {}

const leapYear = (y: number) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
const daysIn = (y: number, m: number) => [31, leapYear(y) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];
const iso = (d: Date) => d.toISOString().slice(0, 10);

/**
 * Python 3.11+ `date.fromisoformat(text).isoformat()`, which the sidecar
 * validators call without a format check first: YYYY-MM-DD, YYYYMMDD and ISO
 * week dates (YYYY-Www[-D], YYYYWww[D]) are accepted and normalized.
 */
export function pyFromIsoformatDate(text: string): string | null {
  let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text) || /^(\d{4})(\d{2})(\d{2})$/.exec(text);
  if (m) {
    const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
    if (y < 1 || mo < 1 || mo > 12 || d < 1 || d > daysIn(y, mo)) return null;
    return `${m[1]}-${m[2]}-${m[3]}`;
  }
  m = /^(\d{4})-W(\d{2})(?:-(\d))?$/.exec(text) || /^(\d{4})W(\d{2})(\d)?$/.exec(text);
  if (!m) return null;
  const [y, w, d] = [Number(m[1]), Number(m[2]), m[3] === undefined ? 1 : Number(m[3])];
  const jan4 = new Date(Date.UTC(y, 0, 4));
  const week1Monday = Date.UTC(y, 0, 4 - ((jan4.getUTCDay() + 6) % 7));
  const dec28 = new Date(Date.UTC(y, 11, 28));
  const weeksInYear = Math.round((Date.UTC(y, 11, 28 - ((dec28.getUTCDay() + 6) % 7)) - week1Monday) / 604_800_000) + 1;
  if (y < 1 || w < 1 || w > weeksInYear || d < 1 || d > 7) return null;
  return iso(new Date(week1Monday + ((w - 1) * 7 + (d - 1)) * 86_400_000));
}

function isoDate(value: unknown, label: string): string {
  const normalized = pyFromIsoformatDate(String(value ?? ""));
  if (normalized === null) throw new SidecarError(`${label} must be YYYY-MM-DD`);
  return normalized;
}

function human(value: unknown, message: string): string {
  const reviewer = String(value ?? "").trim();
  if (!reviewer || ["system", "agent", "agent-proposed"].includes(reviewer.toLowerCase())) throw new SidecarError(message);
  return reviewer;
}

function sourceRef(value: unknown, required: boolean): string {
  const ref = String(value ?? "").trim();
  if (!ref) {
    if (required) throw new SidecarError("source_ref must be an http(s) URL");
    return "";
  }
  if (!ref.startsWith("https://") && !ref.startsWith("http://")) throw new SidecarError("source_ref must be an http(s) URL");
  return ref;
}

export type TrimLifecycleContext = {
  /** The trim is in the base catalog (Catalog.trims). */
  trimExists: boolean;
  /** Parent model's catalog retail_status (payload.retail_status), "" if unknown. */
  parentRetailStatus: string;
  /** The parent model's approved CURRENT set, or null when it has none. */
  approvedSet: ReadonlySet<string> | null;
};

export type TrimLifecyclePlan =
  | { kind: "upsert"; row: Row }
  | { kind: "remove"; trimId: string };

/**
 * retail_lifecycle_review._upsert (ordinary path: bootstrap = false;
 * Retail Lineup Bootstrap path: bootstrap = true).
 */
export function planTrimLifecycleReview(input: {
  trimId: string; action: string; reviewer: string; reviewedAt: string; sourceRef?: string; notes?: string; bootstrap?: boolean;
}, context: TrimLifecycleContext): TrimLifecyclePlan {
  const action = String(input.action || "").trim().toLowerCase();
  if (input.bootstrap && action !== "historical" && action !== "reopen") {
    throw new SidecarError("bootstrap lifecycle action must be historical or reopen; CURRENT membership belongs to current_retail");
  }
  if (!["current", "historical", "reopen"].includes(action)) {
    throw new SidecarError("trim lifecycle action must be current, historical or reopen");
  }
  const trimId = String(input.trimId || "").trim();
  if (!context.trimExists) throw new SidecarError(`unknown MarketTrim '${trimId}'`);
  const reviewer = human(input.reviewer, "trim lifecycle review requires explicit HUMAN reviewer");
  const reviewedAt = isoDate(input.reviewedAt, "reviewed_at");
  const ref = action === "reopen" ? "" : sourceRef(input.sourceRef, !input.bootstrap);
  if (action !== "reopen") {
    const parent = String(context.parentRetailStatus || "UNVERIFIED").trim().toUpperCase();
    if (parent !== "CURRENT") {
      const approved = parent === "HISTORICAL" ? null : context.approvedSet;
      if (approved === null || action !== "historical") {
        throw new SidecarError("parent model must be canonical CURRENT before trim lifecycle review");
      }
      if (approved.has(trimId)) {
        throw new SidecarError("trim is a member of the approved current-retail set; cannot record a contradictory historical disposition");
      }
    }
  }
  if (action === "reopen") return { kind: "remove", trimId };
  return {
    kind: "upsert",
    row: { trim_id: trimId, status: action.toUpperCase(), reviewer, reviewed_at: reviewedAt, source_ref: ref, notes: String(input.notes ?? "").trim() },
  };
}

/**
 * current_retail.replace_current_retail_set: the whole approved set for one
 * model, normalized as stored (ids stripped and sorted). Existence,
 * membership and the HISTORICAL-decision exclusion are database rules.
 */
export function planCurrentRetailSet(input: {
  modelId: string; trimIds: unknown; reviewer: string; reviewedAt: string; sourceRef?: string; notes?: string;
}): Row {
  const modelId = String(input.modelId || "").trim();
  if (!Array.isArray(input.trimIds) || !input.trimIds.length) {
    throw new SidecarError(`current_retail ${modelId}: trim_ids must be a nonempty array`);
  }
  const seen = new Set<string>();
  const trimIds: string[] = [];
  for (const raw of input.trimIds) {
    const id = String(raw ?? "").trim();
    if (!id) throw new SidecarError(`current_retail ${modelId}: trim_ids entries must be nonempty`);
    if (seen.has(id)) throw new SidecarError(`current_retail ${modelId}: duplicate trim_id '${id}'`);
    seen.add(id);
    trimIds.push(id);
  }
  return {
    model_id: modelId,
    trim_ids: [...trimIds].sort(),
    reviewer: human(input.reviewer, "current-retail-set approval requires an explicit HUMAN/owner actor"),
    reviewed_at: isoDate(input.reviewedAt, "reviewed_at"),
    source_ref: sourceRef(input.sourceRef, false),
    notes: String(input.notes ?? "").trim(),
  };
}

/** model_operational_state.upsert_model_operational_state */
export function planModelOperationalState(input: {
  modelId: string; action: string; reviewer: string; reviewedAt: string; sourceRef?: string; notes?: string;
}, modelExists: boolean): { kind: "upsert"; row: Row } | { kind: "remove"; modelId: string } {
  const action = String(input.action || "").trim().toLowerCase();
  if (action !== "under_maintenance" && action !== "normal") {
    throw new SidecarError("model operational state action must be under_maintenance or normal");
  }
  const modelId = String(input.modelId || "").trim();
  if (!modelExists) throw new SidecarError(`unknown Model '${modelId}'`);
  const reviewer = human(input.reviewer, "model operational state requires explicit HUMAN reviewer");
  const reviewedAt = isoDate(input.reviewedAt, "reviewed_at");
  if (action === "normal") return { kind: "remove", modelId };
  return {
    kind: "upsert",
    row: { model_id: modelId, status: "UNDER_MAINTENANCE", reviewer, reviewed_at: reviewedAt,
      source_ref: String(input.sourceRef ?? "").trim(), notes: String(input.notes ?? "").trim() },
  };
}
