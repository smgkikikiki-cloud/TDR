export type FreeCompareTrim = {
  id: string;
  brand_name?: string | null;
  model_name?: string | null;
  name?: string | null;
  model_slug?: string | null;
  segment?: string | null;
  body_type?: string | null;
  powertrain?: string | null;
  drivetrain?: string | null;
  transmission?: string | null;
  engine_cc?: number | string | null;
  battery_kwh?: number | string | null;
  horsepower_ps?: number | string | null;
  motor_kw?: number | string | null;
  power_kw?: number | string | null;
  torque_nm?: number | string | null;
  length_mm?: number | string | null;
  width_mm?: number | string | null;
  height_mm?: number | string | null;
  wheelbase_mm?: number | string | null;
  ground_clearance_mm?: number | string | null;
  seats?: number | string | null;
  model_seats?: number | string | null;
  published_range_km?: number | string | null;
  published_range_cycle?: string | null;
  production_type?: string | null;
  production_country?: string | null;
  /** Model-layer field, only ever meaningful when body_type is PICKUP -- see
   *  PICKUP_BODY_TYPE in lib/body-labels.ts. NOT_APPLICABLE (or absent) on
   *  every other body type reads as no value, same as everywhere else. */
  cab_type?: string | null;
  /** RetailStatus (CURRENT/HISTORICAL/UNVERIFIED) -- header metadata, not a
   *  comparable row (see FREE_COMPARE_GROUPS' doc comment). */
  retail_status?: string | null;
  /** Header metadata, not a comparable row. Year precision, from the
   *  canonical model's current generation launch date. */
  launch_year?: number | string | null;
  launch_quarter?: number | string | null;
  warranty?: string | null;
  vehicle_warranty?: string | null;
  price_baht?: number | string | null;
  campaign_quote?: any;
  /** `payload.comparable_specs` as the release published it: SpecLedger.resolved(),
   *  one row per field that has a fact. Absent on a trim nobody has filed specs
   *  for yet, which is most of them until an import runs. */
  comparable_specs?: ResolvedSpec[] | null;
};

/** One resolved fact, exactly as vehreg/comparable_specs.py writes it. */
export type ResolvedSpec = {
  field_key?: string | null;
  value?: unknown;
  value_state?: string | null;
  unit?: string | null;
  qualifiers?: Record<string, unknown> | null;
};

export type BuiltinCompareRowKey =
  | "price"
  | "campaign"
  | "segment"
  | "body_type"
  | "powertrain"
  | "engine_cc"
  | "battery_kwh"
  | "power"
  | "torque_nm"
  | "drivetrain"
  | "transmission"
  | "range"
  | "length_mm"
  | "width_mm"
  | "height_mm"
  | "wheelbase_mm"
  | "ground_clearance_mm"
  | "seats"
  | "production_type"
  | "production_country"
  | "cab_type"
  | "warranty";

/** A row is either one of the built-in rows above -- which draw on model-level
 *  and price data the spec ledger does not carry -- or a comparable-spec field,
 *  named by its registry key. */
export type CompareRowKey = BuiltinCompareRowKey | `spec:${string}`;

export type CompareRowDefinition = {
  key: CompareRowKey;
  label: string;
};

export type CompareGroupDefinition = {
  title: string;
  rows: CompareRowDefinition[];
};

export const FREE_COMPARE_GROUPS: CompareGroupDefinition[] = [
  {
    title: "รุ่นและราคา",
    rows: [
      { key: "price", label: "ราคาปัจจุบัน" },
      { key: "campaign", label: "แคมเปญปัจจุบัน" },
      { key: "segment", label: "Segment" },
      { key: "body_type", label: "ตัวถัง" },
    ],
  },
  {
    title: "เครื่องยนต์และระบบขับเคลื่อน",
    rows: [
      { key: "powertrain", label: "Powertrain" },
      { key: "engine_cc", label: "ความจุเครื่องยนต์" },
      { key: "battery_kwh", label: "ความจุแบตเตอรี่" },
      { key: "power", label: "กำลังสูงสุด" },
      { key: "torque_nm", label: "แรงบิดสูงสุด" },
      { key: "drivetrain", label: "ระบบขับเคลื่อน" },
      { key: "transmission", label: "ระบบส่งกำลัง" },
      { key: "range", label: "ระยะทางที่ผู้ผลิตประกาศ" },
    ],
  },
  {
    title: "ขนาดและการใช้งาน",
    rows: [
      { key: "length_mm", label: "ความยาว" },
      { key: "width_mm", label: "ความกว้าง" },
      { key: "height_mm", label: "ความสูง" },
      { key: "wheelbase_mm", label: "ฐานล้อ" },
      { key: "ground_clearance_mm", label: "ระยะใต้ท้อง" },
      { key: "seats", label: "จำนวนที่นั่ง" },
    ],
  },
  {
    title: "แหล่งผลิตและการรับประกัน",
    rows: [
      { key: "production_type", label: "นำเข้า / ประกอบ (ระดับรุ่น)" },
      { key: "production_country", label: "ประเทศที่ผลิต (ระดับรุ่น)" },
      // Only ever has a value when every/any selected trim is a pickup --
      // rowHasAnyValue() (below) drops this row entirely from the table when
      // nobody selected is one, so it never shows up "against" another body
      // type; a pickup alongside a sedan just leaves the sedan's cell as the
      // ordinary missing-value dash.
      { key: "cab_type", label: "รูปแบบห้องโดยสาร (กระบะ)" },
      { key: "warranty", label: "การรับประกันรถ" },
    ],
  },
];

// retail_status and launch_year/launch_quarter are deliberately NOT rows
// here -- the product call is header metadata (a status badge, a launch
// year under the trim name), not another line in the spec table. See
// FreeCompareTrim's doc comments and app/compare/page.tsx's <thead>.

function number(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function baht(value: unknown): string | null {
  const n = number(value);
  return n && n > 0 ? `฿${Math.round(n).toLocaleString("th-TH")}` : null;
}

function numericUnit(value: unknown, unit: string, digits = 0): string | null {
  const n = number(value);
  if (n === null || n <= 0) return null;
  return `${n.toLocaleString("th-TH", { maximumFractionDigits: digits })} ${unit}`;
}

function activeCampaign(trim: FreeCompareTrim): string | null {
  const options = Array.isArray(trim.campaign_quote?.campaign_options)
    ? trim.campaign_quote.campaign_options.filter((option: any) => option?.status_as_of === "ACTIVE")
    : [];
  if (!options.length) return null;
  const offer = options[0];
  const money = baht(offer.amount_thb) || (baht(offer.discount_thb) ? `ลด ${baht(offer.discount_thb)}` : null);
  return [offer.option_label || offer.campaign_name, money].filter(Boolean).join(" · ") || "มีแคมเปญ";
}

function power(trim: FreeCompareTrim): string | null {
  const ps = numericUnit(trim.horsepower_ps, "PS");
  if (ps) return ps;
  const kw = numericUnit(trim.motor_kw ?? trim.power_kw, "kW", 1);
  return kw;
}

/** Registry keys that say the same thing as a built-in row.
 *
 *  Both sources are real: the MarketTrim column is what the catalogue has
 *  always carried, and the ledger fact is what a dated, sourced observation
 *  put there. Showing both would print one car's engine size twice under two
 *  labels, so the ledger wins where it has an answer and the column is the
 *  fallback -- one row either way. */
const SPEC_BACKED_ROWS: Partial<Record<BuiltinCompareRowKey, string>> = {
  powertrain: "identity.powertrain",
  engine_cc: "engine.displacement_cc",
  battery_kwh: "battery.catalog_capacity_kwh",
  power: "powertrain.max_power_kw",
  torque_nm: "powertrain.max_torque_nm",
  drivetrain: "powertrain.drivetrain",
  transmission: "powertrain.transmission",
  range: "ev.rated_range_km",
  length_mm: "vehicle.length_mm",
  width_mm: "vehicle.width_mm",
  height_mm: "vehicle.height_mm",
  wheelbase_mm: "vehicle.wheelbase_mm",
  ground_clearance_mm: "vehicle.ground_clearance_mm",
  seats: "vehicle.seats",
};

/** The raw resolved fact behind a row, exactly as the ledger wrote it --
 *  unformatted, with its value_state and qualifiers intact. Winner
 *  highlighting (lib/compare-winners.ts) needs this, not the display string
 *  formatSpecValue produces: a qualifier-compatibility check can't be done
 *  on "150 kW (WLTP)" text. */
export function resolvedSpec(trim: FreeCompareTrim, fieldKey: string): ResolvedSpec | null {
  const rows = trim.comparable_specs;
  if (!Array.isArray(rows)) return null;
  return rows.find((row) => row && row.field_key === fieldKey) || null;
}

/** Every resolved fact for one field on one trim, not just the first.
 *
 *  SpecLedger.resolved() (vehreg/comparable_specs.py) is keyed by
 *  (field_key, qualifier_key), so a single trim can legitimately carry more
 *  than one fact for the same field under different measurement contexts --
 *  a WLTP range next to an NEDC one, two DC charging times for two SOC
 *  windows. resolvedSpec() above picks whichever comes first, which is fine
 *  for display (both wind up on screen somewhere), but winner highlighting
 *  (lib/compare-winners.ts) must see all of them: more than one KNOWN
 *  context on a single trim is exactly the ambiguity it fails closed on
 *  rather than silently picking one to rank. */
export function resolvedSpecs(trim: FreeCompareTrim, fieldKey: string): ResolvedSpec[] {
  const rows = trim.comparable_specs;
  if (!Array.isArray(rows)) return [];
  return rows.filter((row) => row && row.field_key === fieldKey);
}

/** The registry field key a row's value ultimately reads from, if any --
 *  the `spec:` prefix stripped for a pure registry row, or SPEC_BACKED_ROWS'
 *  mapping for a built-in one. Null for a built-in row with no ledger
 *  backing at all (price, campaign, cab_type, ...): there is no comparable
 *  spec fact behind those, so winner highlighting never applies to them. */
export function registryFieldKeyForRow(key: CompareRowKey): string | null {
  if (key.startsWith("spec:")) return key.slice(5);
  return SPEC_BACKED_ROWS[key as BuiltinCompareRowKey] || null;
}

/** A fact's value as a reader sees it, or null.
 *
 *  Only KNOWN carries a value. The other states are the ledger saying, on the
 *  record, that a field does not apply to this car or that nobody has found
 *  the number yet -- neither is a value, and printing "UNKNOWN" in a
 *  comparison cell is worse than leaving it blank, which already means
 *  "we do not have this". */
export function formatSpecValue(spec: ResolvedSpec | null,
                                definition?: { valueType?: string; canonicalUnit?: string;
                                               displayPrecision?: number | null } | null): string | null {
  if (!spec || (spec.value_state && spec.value_state !== "KNOWN")) return null;
  const value = spec.value;
  if (value === null || value === undefined || value === "") return null;

  let text: string;
  if (typeof value === "boolean") {
    text = value ? "มี" : "ไม่มี";
  } else if (Array.isArray(value)) {
    if (!value.length) return null;
    text = value.join(" · ");
  } else if (typeof value === "number") {
    // No definition means no rounding. Defaulting to whole numbers would turn
    // a 60.2 kWh battery into a 60 kWh one for any field this build's registry
    // does not describe -- quietly changing the figure rather than showing it.
    const digits = definition?.displayPrecision ?? 20;
    text = value.toLocaleString("th-TH", { maximumFractionDigits: digits });
    const unit = spec.unit || definition?.canonicalUnit || "";
    if (unit) text = `${text} ${unit}`;
  } else {
    text = String(value);
  }

  // A range measured on NEDC and a range measured on WLTP are not the same
  // claim, so the basis travels with the number rather than being dropped to
  // make the cell tidier.
  const basis = spec.qualifiers?.measurement_basis;
  if (basis) text = `${text} (${String(basis)})`;
  return text;
}

export function compareValue(trim: FreeCompareTrim, key: CompareRowKey,
                             definitions?: Map<string, { valueType?: string; canonicalUnit?: string;
                                                         displayPrecision?: number | null }>): string | null {
  if (key.startsWith("spec:")) {
    const fieldKey = key.slice(5);
    return formatSpecValue(resolvedSpec(trim, fieldKey), definitions?.get(fieldKey));
  }
  const backing = SPEC_BACKED_ROWS[key as BuiltinCompareRowKey];
  if (backing) {
    const fromLedger = formatSpecValue(resolvedSpec(trim, backing), definitions?.get(backing));
    if (fromLedger !== null) return fromLedger;
  }
  switch (key as BuiltinCompareRowKey) {
    case "price": return baht(trim.price_baht);
    case "campaign": return activeCampaign(trim);
    case "segment": return trim.segment || null;
    case "body_type": return trim.body_type || null;
    case "powertrain": return trim.powertrain || null;
    case "engine_cc": return numericUnit(trim.engine_cc, "cc");
    case "battery_kwh": return numericUnit(trim.battery_kwh, "kWh", 1);
    case "power": return power(trim);
    case "torque_nm": return numericUnit(trim.torque_nm, "Nm");
    case "drivetrain": return trim.drivetrain || null;
    case "transmission": return trim.transmission || null;
    case "range": {
      const value = numericUnit(trim.published_range_km, "km");
      return value ? `${value}${trim.published_range_cycle ? ` ${trim.published_range_cycle}` : ""}` : null;
    }
    case "length_mm": return numericUnit(trim.length_mm, "mm");
    case "width_mm": return numericUnit(trim.width_mm, "mm");
    case "height_mm": return numericUnit(trim.height_mm, "mm");
    case "wheelbase_mm": return numericUnit(trim.wheelbase_mm, "mm");
    case "ground_clearance_mm": return numericUnit(trim.ground_clearance_mm, "mm");
    case "seats": return numericUnit(trim.seats ?? trim.model_seats, "ที่นั่ง");
    case "production_type": return trim.production_type === "MIXED" ? "MIXED · ต่างกันตามรุ่นย่อย/ช่วงเวลา" : trim.production_type || null;
    case "production_country": return trim.production_country === "MIXED" ? "MIXED · ต่างกันตามรุ่นย่อย/ช่วงเวลา" : trim.production_country || null;
    case "cab_type":
      // "PICKUP" is BodyType.PICKUP's exact canonical string (vehreg/taxonomy.py)
      // -- this file stays import-free like lib/access-policy.ts, so it is
      // written out rather than imported from lib/body-labels.ts.
      return trim.body_type === "PICKUP" && trim.cab_type && trim.cab_type !== "NOT_APPLICABLE"
        ? trim.cab_type : null;
    case "warranty": return trim.vehicle_warranty || trim.warranty || null;
  }
}

export function rowHasAnyValue(trims: FreeCompareTrim[], key: CompareRowKey,
                               definitions?: SpecDefinitionIndex): boolean {
  return trims.some((trim) => compareValue(trim, key, definitions) !== null);
}

export function rowIsDifferent(trims: FreeCompareTrim[], key: CompareRowKey,
                               definitions?: SpecDefinitionIndex): boolean {
  if (trims.length < 2) return false;
  const values = trims.map((trim) => compareValue(trim, key, definitions) ?? "__MISSING__");
  return new Set(values).size > 1;
}

/** What a comparable-spec field needs to be rendered and grouped. Structurally
 *  the subset of lib/spec-field-registry.ts's SpecFieldDefinition this module
 *  uses, declared here so free-compare stays readable without fs access. */
export type CompareSpecField = {
  key: string;
  group: string;
  labelTh: string;
  labelEn?: string;
  valueType?: string;
  canonicalUnit?: string;
  displayPrecision?: number | null;
  /** The registry's own comparison intent (HIGHER_BETTER / LOWER_BETTER /
   *  PRESENCE / SET_DIFFERENCE / INFORMATION_ONLY) and the qualifier names
   *  that must match for two values to be on the same measurement basis.
   *  lib/compare-winners.ts reads both -- see its module doc for why an
   *  explicit UI allowlist sits on top rather than trusting every
   *  registry-comparable field to produce a green winner. */
  comparisonRule?: string;
  comparisonQualifiers?: string[];
};

export type SpecDefinitionIndex = Map<string, CompareSpecField>;

/** Registry group -> the heading a reader sees, in the order the table shows
 *  them. A group missing from here still appears, under its own name: a new
 *  field should show up in the comparison the day it is defined, not the day
 *  somebody remembers to translate its heading. */
const SPEC_GROUP_TITLES: Record<string, string> = {
  identity: "ระบบขับเคลื่อน",
  powertrain: "เครื่องยนต์และการส่งกำลัง",
  battery: "แบตเตอรี่",
  charging: "การชาร์จ",
  efficiency: "อัตราสิ้นเปลืองและมลพิษ",
  performance: "สมรรถนะ",
  dimensions: "ขนาดตัวถัง",
  utility: "การบรรทุก",
  chassis: "ช่วงล่าง ล้อ และยาง",
  safety: "ความปลอดภัยและ ADAS",
  comfort: "ความสะดวกสบาย",
  technology: "เทคโนโลยีและการเชื่อมต่อ",
  manufacturing: "ภาษีและการผลิต",
};

const SPEC_GROUP_ORDER = Object.keys(SPEC_GROUP_TITLES);

/** Every registry field that a built-in row already shows. */
const COVERED_BY_BUILTIN = new Set(Object.values(SPEC_BACKED_ROWS));

export function indexSpecFields(fields: CompareSpecField[]): SpecDefinitionIndex {
  return new Map(fields.map((field) => [field.key, field]));
}

/** The built-in groups, then one group per registry group.
 *
 *  The registry is the source of which fields exist and what they are called,
 *  so a field added to the canonical registry is comparable here without this
 *  file changing. Fields a built-in row already covers are skipped rather than
 *  printed twice. */
export function compareGroupDefinitions(fields: CompareSpecField[] = []): CompareGroupDefinition[] {
  const groups: CompareGroupDefinition[] = FREE_COMPARE_GROUPS.map((group) => ({
    ...group, rows: [...group.rows],
  }));
  const byGroup = new Map<string, CompareRowDefinition[]>();
  for (const field of fields) {
    if (COVERED_BY_BUILTIN.has(field.key)) continue;
    const bucket = byGroup.get(field.group) || [];
    bucket.push({ key: `spec:${field.key}`, label: field.labelTh || field.labelEn || field.key });
    byGroup.set(field.group, bucket);
  }
  const ordered = [
    ...SPEC_GROUP_ORDER.filter((name) => byGroup.has(name)),
    ...[...byGroup.keys()].filter((name) => !SPEC_GROUP_TITLES[name]).sort(),
  ];
  for (const name of ordered) {
    groups.push({ title: SPEC_GROUP_TITLES[name] || name, rows: byGroup.get(name) || [] });
  }
  return groups;
}

/** One trim's comparable specs, grouped and formatted the way the comparison
 *  shows them.
 *
 *  The trim page and the comparison are the same question asked of one car
 *  instead of four, so they share the grouping, the headings and the
 *  formatting rather than growing a second copy that drifts. Empty groups are
 *  dropped; a field with no fact is simply absent, which is what a blank cell
 *  already means everywhere else on the site. */
export function specGroupsForTrim(trim: FreeCompareTrim, fields: CompareSpecField[] = []) {
  const definitions = indexSpecFields(fields);
  return compareGroupDefinitions(fields)
    .map((group) => ({
      title: group.title,
      rows: group.rows
        .map((row) => ({ key: row.key, label: row.label,
                         value: compareValue(trim, row.key, definitions) }))
        .filter((row) => row.value !== null),
    }))
    .filter((group) => group.rows.length > 0);
}

export function visibleCompareGroups(trims: FreeCompareTrim[], differencesOnly = false,
                                     fields: CompareSpecField[] = []) {
  const definitions = indexSpecFields(fields);
  return compareGroupDefinitions(fields)
    .map((group) => ({
      ...group,
      rows: group.rows.filter((row) => rowHasAnyValue(trims, row.key, definitions)
        && (!differencesOnly || rowIsDifferent(trims, row.key, definitions))),
    }))
    .filter((group) => group.rows.length > 0);
}
