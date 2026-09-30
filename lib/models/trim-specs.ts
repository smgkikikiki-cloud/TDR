/** The P04 spec table (design/PAGES.md): one trim's known facts in the seven approved groups, each row carrying the
 *  label and order of lib/spec-field-registry.ts, a source badge and an observed date.
 *
 *  Values, contexts (a WLTP range next to an NEDC one) and formatting are exactly the ones the comparison uses
 *  (lib/free-compare.ts); this file only regroups, relabels and attaches provenance. A field with no fact is not a row,
 *  and a group with no rows is not a group: nothing is ever printed as "-".
 *
 *  Plain TypeScript with relative imports only (scripts/check-models.ts runs it under Node's type stripping). */
import {
  compareGroupDefinitions, compareValue, contextForRow, indexSpecFields, qualifierContextKey,
  registryFieldKeyForRow, resolvedSpecs,
  type CompareSpecField, type FreeCompareTrim, type ResolvedSpec,
} from "../free-compare.ts";

/** The seven groups of P04 and the registry groups each one draws from, in display order. */
export const TRIM_SPEC_GROUPS = [
  { title: "ขนาดและน้ำหนัก", registry: ["dimensions", "utility"] },
  { title: "ระบบขับเคลื่อน", registry: ["identity", "powertrain", "performance", "efficiency"] },
  { title: "แบตเตอรี่และการชาร์จ", registry: ["battery", "charging"] },
  { title: "ล้อและยาง", registry: ["chassis"] },
  { title: "ความปลอดภัย", registry: ["safety"] },
  { title: "ความสะดวกและเทคโนโลยี", registry: ["comfort", "technology"] },
  { title: "ภาษีและกฎระเบียบ", registry: ["manufacturing"] },
] as const;

export type SpecSource = { label: string; known: boolean };
export type TrimSpecRow = { key: string; label: string; value: string; source: SpecSource; observedAt: string | null; sourceUrl: string | null };
export type TrimSpecGroup = { title: string; rows: TrimSpecRow[] };

const SOURCE_LABEL: Record<string, string> = {
  ecosticker: "ECO Sticker",
  oem_official_website: "OEM",
  admin: "TDR",
  third_party_automotive_press: "สื่อยานยนต์",
};

/** The badge for a fact. Facts with no recorded source (entered in admin without one) say so instead of guessing. */
export function sourceBadge(spec: { source?: unknown; fact_id?: unknown } | null | undefined): SpecSource {
  const source = String(spec?.source ?? "").trim();
  if (source && SOURCE_LABEL[source]) return { label: SOURCE_LABEL[source], known: true };
  if (source.startsWith("oem")) return { label: "OEM", known: true };
  if (!source && String(spec?.fact_id ?? "").startsWith("admin:")) return { label: "TDR", known: true };
  return { label: "ไม่ระบุที่มา", known: false };
}

const THAI_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."];

/** "2026-04-01" -> "1 เม.ย. 2569" (Buddhist era, DESIGN §4). Anything that is not an ISO date -> null. */
export function formatThaiDate(iso: unknown): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso ?? ""));
  if (!m) return null;
  const month = Number(m[2]);
  if (month < 1 || month > 12) return null;
  return `${Number(m[3])} ${THAI_MONTHS[month - 1]} ${Number(m[1]) + 543}`;
}

type RegistryField = CompareSpecField & { group: string };

/** Only http(s) links are ever rendered as links. */
function safeUrl(value: unknown): string | null {
  const s = String(value ?? "").trim();
  return /^https?:\/\//i.test(s) ? s : null;
}

export function trimSpecGroups(trim: FreeCompareTrim, fields: readonly RegistryField[]): TrimSpecGroup[] {
  const list = fields as CompareSpecField[];
  const definitions = indexSpecFields(list);
  const order = new Map(fields.map((f, i) => [f.key, i]));
  const groupOf = (registryGroup: string) => TRIM_SPEC_GROUPS.findIndex((g) => (g.registry as readonly string[]).includes(registryGroup));

  const buckets: TrimSpecRow[][] = TRIM_SPEC_GROUPS.map(() => []);
  const rank: number[][] = TRIM_SPEC_GROUPS.map(() => []);
  let sequence = 0;
  for (const group of compareGroupDefinitions([trim], list)) {
    for (const row of group.rows) {
      const fieldKey = registryFieldKeyForRow(row.key);
      const definition = fieldKey ? definitions.get(fieldKey) : undefined;
      if (!fieldKey || !definition) continue; // price / campaign / segment ... belong to the header, not the table
      const target = groupOf(definition.group);
      if (target < 0) continue;
      const value = compareValue(trim, row.key, definitions);
      if (value === null) continue;
      const context = contextForRow(row.key);
      const facts = resolvedSpecs(trim, fieldKey).filter((spec: ResolvedSpec) =>
        spec.value_state === "KNOWN" && qualifierContextKey(spec.qualifiers, definition.comparisonQualifiers || []) === context);
      const fact = (facts.length === 1 ? facts[0] : null) as (ResolvedSpec & { source?: unknown; fact_id?: unknown; observed_at?: unknown; source_ref?: unknown }) | null;
      const dash = row.label.indexOf(" — ");
      buckets[target].push({
        key: String(row.key),
        label: `${definition.labelTh || row.label}${dash >= 0 ? row.label.slice(dash) : ""}`,
        value,
        source: sourceBadge(fact),
        observedAt: formatThaiDate(fact?.observed_at),
        sourceUrl: safeUrl(fact?.source_ref),
      });
      rank[target].push((order.get(fieldKey) ?? 9999) * 1000 + sequence++ % 1000);
    }
  }
  return TRIM_SPEC_GROUPS.map((g, i) => ({
    title: g.title,
    rows: buckets[i].map((row, j) => ({ row, r: rank[i][j] })).sort((a, b) => a.r - b.r).map((x) => x.row),
  })).filter((g) => g.rows.length > 0);
}

/** Key facts strip: only the ones this trim actually has, in the fixed order of P04. */
export function keyFacts(trim: FreeCompareTrim & { price_baht?: number | string | null }, fields: readonly RegistryField[]) {
  const definitions = indexSpecFields(fields as CompareSpecField[]);
  const out: { key: string; label: string; value: string }[] = [];
  const add = (key: string, label: string, rowKey: string) => {
    const value = compareValue(trim, rowKey as never, definitions);
    if (value) out.push({ key, label, value });
  };
  add("price", "ราคาปัจจุบัน", "price");
  add("range", "ระยะทางที่ผู้ผลิตประกาศ", "range");
  add("battery", "แบตเตอรี่", "battery_kwh");
  add("power", "กำลังสูงสุด", "power");
  add("seats", "จำนวนที่นั่ง", "seats");
  return out;
}
