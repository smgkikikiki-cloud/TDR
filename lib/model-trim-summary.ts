import {
  specGroupsForTrim,
  type CompareSpecField,
  type FreeCompareTrim,
} from "./free-compare.ts";

export type TrimSummarySpec = {
  key: string;
  label: string;
  value: string;
};

/**
 * Model pages should answer "what is different about this trim?" without
 * becoming a second full spec sheet. The trim page remains the exhaustive
 * view; this selector only picks a compact, stable set of useful facts from
 * the exact same formatted spec groups the trim page already uses.
 */
const PRIORITY = [
  "power",
  "torque_nm",
  "drivetrain",
  "range",
  "battery_kwh",
  "engine_cc",
  "spec:safety.airbag_count",
  "seats",
  "spec:fitment.tyre_size",
  "spec:charging.dc_max_kw",
  "spec:performance.acceleration_0_100_s",
] as const;

/** Already visible elsewhere on the model page or too bulky/repetitive for a
 * compact trim preview. They still remain on the full trim page. */
const FALLBACK_EXCLUDE = new Set([
  "price",
  "campaign",
  "segment",
  "body_type",
  "powertrain",
  "length_mm",
  "width_mm",
  "height_mm",
  "wheelbase_mm",
  "production_type",
  "production_country",
]);

function baseKey(key: string) {
  const at = key.indexOf("::");
  return at === -1 ? key : key.slice(0, at);
}

export function trimSummarySpecs(
  trim: FreeCompareTrim,
  fields: CompareSpecField[] = [],
  limit = 6,
): TrimSummarySpec[] {
  if (limit <= 0) return [];

  const rows = specGroupsForTrim(trim, fields)
    .flatMap((group) => group.rows)
    .map((row) => ({ ...row, key: String(row.key) }))
    .filter((row): row is { key: string; label: string; value: string } => Boolean(row.value));

  const selected: TrimSummarySpec[] = [];
  const usedKeys = new Set<string>();

  const add = (row: { key: string; label: string; value: string }) => {
    if (selected.length >= limit || usedKeys.has(row.key)) return;
    selected.push({ key: row.key, label: row.label, value: row.value });
    usedKeys.add(row.key);
  };

  // Prefer buyer-useful differentiators in a predictable order. Contextual
  // variants (for example WLTP/NEDC range rows) keep their existing labels.
  for (const wanted of PRIORITY) {
    for (const row of rows) {
      if (baseKey(row.key) === wanted) add(row);
      if (selected.length >= limit) return selected;
    }
  }

  // If a sparse trim still has room, fill with other real facts rather than
  // rendering empty boxes. Common model-level dimensions stay excluded.
  for (const row of rows) {
    if (selected.length >= limit) break;
    if (FALLBACK_EXCLUDE.has(baseKey(row.key))) continue;
    add(row);
  }

  return selected;
}
