/**
 * The one field catalog behind the trim editor.
 *
 * An admin edits a *trim*, which in their eyes is one complete vehicle
 * specification: Drivetrain, Battery capacity, Seats, Range. Behind that, this
 * repo stores a given concept in up to two unrelated places -- MarketTrim's own
 * columns (vehreg/entities.py) and the comparable-spec fact ledger
 * (vehreg/comparable_specs.py). Both are real, both are read by different
 * downstream consumers, and neither is going away.
 *
 * That duplication is a storage detail, and it used to leak: the editor
 * rendered `drivetrain` and `powertrain.drivetrain` as two separate boxes, and
 * `seats` beside `vehicle.seats`, so the admin had to know which backend a
 * number lived in and keep the two in sync by hand. This module is the adapter
 * that ends it. One concept is one entry here, and that entry declares every
 * backend representation it compiles to:
 *
 *     { key: "seats", targets: { trimField: "seats", specKey: "vehicle.seats" } }
 *
 * so entering Seats = 5 once emits both MarketTrim `seats: 5` and a
 * `vehicle.seats` fact of 5, and they cannot drift. Adding a field means adding
 * one row here; there is nowhere else a second box could come from.
 *
 * Metadata that already exists canonically is not copied. Unit, value type,
 * qualifier keys and powertrain applicability are read at resolve time from
 * the real registry.json through lib/spec-field-registry.ts -- the same file
 * APPEND_SPEC validates against -- so UI validation and writer validation are
 * the same constraint, not two that agree today. Only what the registry cannot
 * know (the MarketTrim column a concept also lands in, and MarketTrim's own
 * stricter rules, e.g. seats must be a positive integer where the registry
 * would accept 0) lives here.
 *
 * Deliberately pure: it takes the registry as an argument rather than reading
 * it, so it carries no `node:fs` import and the editor form -- a client
 * component -- can validate with the very same function the server action
 * runs. lib/spec-field-registry.ts owns reading the file and exposes
 * trimEditorFields(year) on top of this. No "@/" alias imports either, so
 * scripts/check-trim-editor.ts executes this under
 * node --experimental-strip-types.
 */
import type { SpecFieldDefinition } from "./spec-field-registry.ts";

/** The categories the editor renders, in order. One trim is one form; these
 * are headings inside that form, never separate steps or separate saves. */
export const TRIM_CATEGORIES = [
  { id: "identity", labelEn: "Identity", labelTh: "ข้อมูลพื้นฐาน" },
  { id: "powertrain", labelEn: "Powertrain & performance", labelTh: "ระบบขับเคลื่อนและสมรรถนะ" },
  { id: "energy", labelEn: "Battery, charging & range", labelTh: "แบตเตอรี่ การชาร์จ และระยะทาง" },
  { id: "dimensions", labelEn: "Dimensions & weight", labelTh: "ขนาดและน้ำหนัก" },
  { id: "chassis", labelEn: "Wheels, tyres & chassis", labelTh: "ล้อ ยาง และช่วงล่าง" },
  { id: "safety", labelEn: "Safety & ADAS", labelTh: "ความปลอดภัยและ ADAS" },
  { id: "comfort", labelEn: "Comfort & technology", labelTh: "ความสะดวกสบายและเทคโนโลยี" },
  { id: "manufacturing", labelEn: "Manufacturing & other", labelTh: "การผลิตและอื่น ๆ" },
] as const;

export type TrimCategoryId = (typeof TRIM_CATEGORIES)[number]["id"];

/** MarketTrim's own editable columns (vehreg/entities.py's MarketTrim). */
export type MarketTrimFieldName =
  | "name" | "powertrain" | "drivetrain" | "engine_code" | "engine_cc"
  | "battery_kwh" | "transmission" | "seats" | "length_mm" | "width_mm"
  | "height_mm" | "wheelbase_mm" | "tire_front" | "tire_rear"
  | "wheel_front" | "wheel_rear" | "notes";

export type TrimFieldInput = "text" | "number" | "enum" | "boolean";

/**
 * Every backend representation one UI field compiles to. A concept may have
 * one, the other, or both; `both` is the case this module exists for.
 */
export type TrimFieldTargets = {
  /** Patched into the trim row of UPSERT_MODEL_BUNDLE. */
  trimField?: MarketTrimFieldName;
  /** Written as an APPEND_SPEC comparable-spec fact. */
  specKey?: string;
};

type FieldConcept = {
  key: string;
  category: TrimCategoryId;
  labelEn: string;
  labelTh: string;
  targets: TrimFieldTargets;
  /** Only needed when the concept has no specKey to read it from. */
  input?: TrimFieldInput;
  unit?: string;
  options?: readonly string[];
  /** Free-text field with a canonical vocabulary worth offering. */
  suggestions?: readonly string[];
  /** MarketTrim.validate() rejects 0 for these; the spec registry alone would not. */
  integer?: boolean;
  positive?: boolean;
  max?: number;
  /** Part of the trim's identity: chosen when the trim is created, then frozen
   * (changing it would fork a new canonical_id rather than edit this trim). */
  identityLocked?: boolean;
  placeholder?: string;
  help?: string;
};

/**
 * THE MAPPING TABLE.
 *
 * Every row where `targets` has both a `trimField` and a `specKey` is a pair
 * that used to render as two boxes. They are listed together here on purpose:
 * this table is the reason a duplicate cannot come back, so it is meant to be
 * read as a whole rather than scattered across the page component.
 *
 *   UI field            MarketTrim column   comparable-spec key
 *   ------------------  ------------------  ---------------------------
 *   Powertrain          powertrain          identity.powertrain
 *   Drivetrain          drivetrain          powertrain.drivetrain
 *   Engine displacement engine_cc           engine.displacement_cc
 *   Transmission        transmission        powertrain.transmission
 *   Battery capacity    battery_kwh         battery.catalog_capacity_kwh
 *   Seats               seats               vehicle.seats
 *   Length              length_mm           vehicle.length_mm
 *   Width               width_mm            vehicle.width_mm
 *   Height              height_mm           vehicle.height_mm
 *   Wheelbase           wheelbase_mm        vehicle.wheelbase_mm
 *   Front tyre          tire_front          fitment.tyre_front
 *   Rear tyre           tire_rear           fitment.tyre_rear
 */
const CONCEPTS: readonly FieldConcept[] = [
  // ---- Identity -----------------------------------------------------------
  {
    key: "name", category: "identity", labelEn: "Trim name", labelTh: "ชื่อรุ่นย่อย",
    targets: { trimField: "name" }, input: "text",
    placeholder: "Comfort / Private Use",
  },
  {
    key: "powertrain", category: "identity", labelEn: "Powertrain", labelTh: "ประเภทระบบขับเคลื่อน",
    targets: { trimField: "powertrain", specKey: "identity.powertrain" },
    input: "enum", options: ["ICE", "HEV", "PHEV", "REEV", "BEV", "FCEV"],
    identityLocked: true,
    help: "กำหนดตอนสร้างรุ่นย่อย และเป็นส่วนหนึ่งของ canonical_id จึงแก้ภายหลังไม่ได้",
  },

  // ---- Powertrain & performance ------------------------------------------
  {
    key: "drivetrain", category: "powertrain", labelEn: "Drivetrain", labelTh: "ระบบขับเคลื่อนล้อ",
    targets: { trimField: "drivetrain", specKey: "powertrain.drivetrain" },
    input: "enum", options: ["FWD", "RWD", "AWD", "4WD"],
  },
  {
    key: "engine_cc", category: "powertrain", labelEn: "Engine displacement", labelTh: "ความจุกระบอกสูบ",
    targets: { trimField: "engine_cc", specKey: "engine.displacement_cc" },
    integer: true, positive: true,
  },
  {
    key: "engine_code", category: "powertrain", labelEn: "Engine code", labelTh: "รหัสเครื่องยนต์",
    targets: { trimField: "engine_code" }, input: "text", placeholder: "2AR-FE",
    // MarketTrim.validate() rejects a combustion engine on a BEV.
    help: "ใช้กับรถที่มีเครื่องยนต์สันดาปเท่านั้น",
  },
  {
    key: "transmission", category: "powertrain", labelEn: "Transmission", labelTh: "ระบบส่งกำลัง",
    targets: { trimField: "transmission", specKey: "powertrain.transmission" },
    input: "enum",
    // vehreg/comparable_specs.py's TRANSMISSION_FAMILIES: the canonical
    // families the ingest folds free-text gearbox prose into. Choosing the
    // family here means the hand-entered value and the ingested one compare.
    options: ["AUTOMATIC", "CVT", "MANUAL", "OTHER"],
  },
  { key: "motor_type", category: "powertrain", labelEn: "Motor type", labelTh: "ชนิดมอเตอร์", targets: { specKey: "powertrain.motor_type" }, placeholder: "PMSM" },
  { key: "max_power_kw", category: "powertrain", labelEn: "Max power", labelTh: "กำลังสูงสุด", targets: { specKey: "powertrain.max_power_kw" } },
  { key: "max_torque_nm", category: "powertrain", labelEn: "Max torque", labelTh: "แรงบิดสูงสุด", targets: { specKey: "powertrain.max_torque_nm" } },
  { key: "acceleration_0_100_s", category: "powertrain", labelEn: "0-100 km/h", labelTh: "อัตราเร่ง 0-100 กม./ชม.", targets: { specKey: "performance.acceleration_0_100_s" } },
  { key: "top_speed_kmh", category: "powertrain", labelEn: "Top speed", labelTh: "ความเร็วสูงสุด", targets: { specKey: "performance.top_speed_kmh" } },
  { key: "co2_g_km", category: "powertrain", labelEn: "CO2 emissions", labelTh: "การปล่อย CO2", targets: { specKey: "emissions.co2_g_km" } },

  // ---- Battery, charging & range -----------------------------------------
  {
    key: "battery_kwh", category: "energy", labelEn: "Battery capacity", labelTh: "ความจุแบตเตอรี่",
    targets: { trimField: "battery_kwh", specKey: "battery.catalog_capacity_kwh" },
    positive: true,
  },
  { key: "battery_gross_kwh", category: "energy", labelEn: "Battery capacity (gross)", labelTh: "ความจุแบตเตอรี่ (รวม)", targets: { specKey: "battery.gross_capacity_kwh" } },
  { key: "battery_usable_kwh", category: "energy", labelEn: "Battery capacity (usable)", labelTh: "ความจุแบตเตอรี่ (ใช้งานได้)", targets: { specKey: "battery.usable_capacity_kwh" } },
  {
    key: "battery_chemistry", category: "energy", labelEn: "Battery chemistry", labelTh: "เคมีแบตเตอรี่",
    targets: { specKey: "battery.chemistry" }, input: "enum",
    // vehreg/comparable_specs.py's CHEMISTRY_FAMILIES.
    options: ["LFP", "NMC", "NCA", "LTO", "LI_ION_UNSPECIFIED", "OTHER"],
  },
  {
    // Requirement: this is battery.supplier, the field that already exists --
    // not a new one. It sits immediately after chemistry because that is where
    // an admin reading a spec sheet expects it.
    key: "battery_supplier", category: "energy",
    labelEn: "Battery manufacturer / supplier", labelTh: "ผู้ผลิตแบตเตอรี่",
    targets: { specKey: "battery.supplier" }, placeholder: "CATL",
  },
  { key: "battery_voltage_v", category: "energy", labelEn: "Nominal voltage", labelTh: "แรงดันไฟฟ้าระบุ", targets: { specKey: "battery.nominal_voltage_v" } },
  { key: "rated_range_km", category: "energy", labelEn: "Rated driving range", labelTh: "ระยะทางวิ่งที่ประกาศ", targets: { specKey: "ev.rated_range_km" } },
  { key: "energy_consumption_wh_km", category: "energy", labelEn: "Energy consumption", labelTh: "อัตราสิ้นเปลืองพลังงาน", targets: { specKey: "ev.energy_consumption_wh_km" } },
  { key: "charging_ac_kw", category: "energy", labelEn: "AC charging (max)", labelTh: "ชาร์จ AC สูงสุด", targets: { specKey: "charging.ac_max_kw" } },
  { key: "charging_dc_kw", category: "energy", labelEn: "DC charging (max)", labelTh: "ชาร์จ DC สูงสุด", targets: { specKey: "charging.dc_max_kw" } },
  { key: "charging_dc_time_min", category: "energy", labelEn: "DC charging time", labelTh: "เวลาชาร์จ DC", targets: { specKey: "charging.dc_time_min" } },

  // ---- Dimensions & weight ------------------------------------------------
  { key: "seats", category: "dimensions", labelEn: "Seats", labelTh: "จำนวนที่นั่ง", targets: { trimField: "seats", specKey: "vehicle.seats" }, integer: true, positive: true, max: 100 },
  { key: "length_mm", category: "dimensions", labelEn: "Length", labelTh: "ความยาว", targets: { trimField: "length_mm", specKey: "vehicle.length_mm" }, integer: true, positive: true },
  { key: "width_mm", category: "dimensions", labelEn: "Width", labelTh: "ความกว้าง", targets: { trimField: "width_mm", specKey: "vehicle.width_mm" }, integer: true, positive: true },
  { key: "height_mm", category: "dimensions", labelEn: "Height", labelTh: "ความสูง", targets: { trimField: "height_mm", specKey: "vehicle.height_mm" }, integer: true, positive: true },
  { key: "wheelbase_mm", category: "dimensions", labelEn: "Wheelbase", labelTh: "ระยะฐานล้อ", targets: { trimField: "wheelbase_mm", specKey: "vehicle.wheelbase_mm" }, integer: true, positive: true },
  { key: "ground_clearance_mm", category: "dimensions", labelEn: "Ground clearance", labelTh: "ระยะต่ำสุดจากพื้น", targets: { specKey: "vehicle.ground_clearance_mm" } },
  { key: "curb_weight_kg", category: "dimensions", labelEn: "Curb weight", labelTh: "น้ำหนักรถเปล่า", targets: { specKey: "vehicle.curb_weight_kg" } },
  { key: "declared_total_weight_kg", category: "dimensions", labelEn: "Declared total weight", labelTh: "น้ำหนักรวมที่ประกาศ", targets: { specKey: "vehicle.declared_total_weight_kg" } },
  { key: "cargo_volume_l", category: "dimensions", labelEn: "Cargo volume", labelTh: "ความจุห้องสัมภาระ", targets: { specKey: "vehicle.cargo_volume_l" } },
  { key: "turning_radius_m", category: "dimensions", labelEn: "Turning radius", labelTh: "รัศมีวงเลี้ยว", targets: { specKey: "vehicle.turning_radius_m" } },

  // ---- Wheels, tyres & chassis -------------------------------------------
  { key: "tire_front", category: "chassis", labelEn: "Front tyre", labelTh: "ยางหน้า", targets: { trimField: "tire_front", specKey: "fitment.tyre_front" }, placeholder: "215/55 R17" },
  { key: "tire_rear", category: "chassis", labelEn: "Rear tyre", labelTh: "ยางหลัง", targets: { trimField: "tire_rear", specKey: "fitment.tyre_rear" }, placeholder: "215/55 R17" },
  { key: "wheel_front", category: "chassis", labelEn: "Front wheel", labelTh: "ล้อหน้า", targets: { trimField: "wheel_front" }, input: "text", placeholder: "17x7.0J" },
  { key: "wheel_rear", category: "chassis", labelEn: "Rear wheel", labelTh: "ล้อหลัง", targets: { trimField: "wheel_rear" }, input: "text", placeholder: "17x7.0J" },

  // ---- Manufacturing & other ---------------------------------------------
  { key: "model_year", category: "manufacturing", labelEn: "Model year", labelTh: "ปีรุ่น", targets: { specKey: "vehicle.model_year" } },
  { key: "factory", category: "manufacturing", labelEn: "Plant / factory", labelTh: "โรงงานผลิต", targets: { specKey: "manufacturing.factory" } },
  { key: "notes", category: "manufacturing", labelEn: "Internal note", labelTh: "บันทึกภายใน", targets: { trimField: "notes" }, input: "text" },
] as const;

/**
 * Registry keys the editor deliberately does not render, because another UI
 * field already owns the concept and a second box for it is exactly what this
 * module exists to prevent.
 *
 * `*_as_declared` hold the source's own wording beside the canonical family
 * (see CHEMISTRY_FAMILIES in vehreg/comparable_specs.py). They are written by
 * the ECO sticker ingest, which knows what the document literally said; a hand
 * editor has no better answer than the canonical value it already entered.
 *
 * `fitment.tyre_size` is the pre-split single-size key. Front and rear tyres
 * own that concept here.
 */
export const UNSURFACED_SPEC_KEYS: readonly string[] = [
  "battery.chemistry_as_declared",
  "powertrain.transmission_as_declared",
  "fitment.tyre_size",
];

/** Which category an unmapped registry field lands in, by its registry group.
 * Every registry field reaches the form through this, so a field added to
 * registry.json shows up without a code change here. */
const CATEGORY_OF_GROUP: Record<string, TrimCategoryId> = {
  identity: "identity",
  powertrain: "powertrain",
  performance: "powertrain",
  battery: "energy",
  charging: "energy",
  efficiency: "energy",
  dimensions: "dimensions",
  utility: "dimensions",
  chassis: "chassis",
  safety: "safety",
  comfort: "comfort",
  technology: "comfort",
  manufacturing: "manufacturing",
};

export type QualifierDefinition = {
  key: string;
  labelEn: string;
  labelTh: string;
  input: "text" | "number" | "enum";
  options?: readonly string[];
};

/**
 * The qualifiers the registry names in `comparison_qualifiers`. A qualifier is
 * not decoration: it is part of the fact's comparison key
 * (SpecFact.qualifier_key), so "442 km" and "442 km NEDC" are different facts.
 * Dropping the NEDC makes a range that cannot honestly be compared with a
 * WLTP one, which is why the editor renders these beside the value.
 */
export const QUALIFIERS: Record<string, QualifierDefinition> = {
  measurement_basis: {
    key: "measurement_basis", labelEn: "Test cycle / measurement basis", labelTh: "มาตรฐานการวัด",
    input: "enum", options: ["NEDC", "CLTC", "WLTP", "EPA", "MLIT", "MANUFACTURER", "OTHER"],
  },
  range_scope: {
    key: "range_scope", labelEn: "Range scope", labelTh: "ขอบเขตระยะทาง",
    input: "enum", options: ["COMBINED", "ELECTRIC_ONLY", "CITY", "HIGHWAY"],
  },
  output_scope: {
    key: "output_scope", labelEn: "Output scope", labelTh: "ขอบเขตกำลัง",
    input: "enum", options: ["SYSTEM", "ENGINE", "MOTOR", "FRONT_MOTOR", "REAR_MOTOR"],
  },
  rating_basis: {
    key: "rating_basis", labelEn: "Rating basis", labelTh: "เกณฑ์การระบุค่า",
    input: "enum", options: ["PEAK", "CONTINUOUS", "MANUFACTURER", "OTHER"],
  },
  load_state: {
    key: "load_state", labelEn: "Load state", labelTh: "สภาพบรรทุก",
    input: "enum", options: ["UNLADEN", "LADEN"],
  },
  seat_configuration: {
    key: "seat_configuration", labelEn: "Seat configuration", labelTh: "การจัดที่นั่ง",
    input: "text",
  },
  soc_from: { key: "soc_from", labelEn: "From SoC (%)", labelTh: "จากระดับแบต (%)", input: "number" },
  soc_to: { key: "soc_to", labelEn: "To SoC (%)", labelTh: "ถึงระดับแบต (%)", input: "number" },
  charger_power_kw: { key: "charger_power_kw", labelEn: "Charger power (kW)", labelTh: "กำลังตู้ชาร์จ (kW)", input: "number" },
  program: { key: "program", labelEn: "NCAP programme", labelTh: "โครงการ NCAP", input: "enum", options: ["ASEAN_NCAP", "EURO_NCAP", "ANCAP", "C_NCAP", "GLOBAL_NCAP", "OTHER"] },
  protocol: { key: "protocol", labelEn: "Protocol / year", labelTh: "โปรโตคอล/ปี", input: "text" },
  tested_variant: { key: "tested_variant", labelEn: "Tested variant", labelTh: "รุ่นที่ทดสอบ", input: "text" },
  market: { key: "market", labelEn: "Market", labelTh: "ตลาด", input: "text" },
};

function qualifierFor(key: string): QualifierDefinition {
  return QUALIFIERS[key] || { key, labelEn: key, labelTh: key, input: "text" };
}

/** One UI field, fully resolved: the concept joined with whatever the
 * canonical registry says about its spec key. This is what the page renders,
 * what the action validates, and what the builder compiles -- one object, so
 * they cannot disagree. */
export type TrimEditorField = {
  key: string;
  category: TrimCategoryId;
  labelEn: string;
  labelTh: string;
  input: TrimFieldInput;
  unit: string;
  options: readonly string[];
  qualifiers: QualifierDefinition[];
  targets: TrimFieldTargets;
  /** Empty means every powertrain. */
  powertrains: readonly string[];
  integer: boolean;
  positive: boolean;
  max: number | null;
  identityLocked: boolean;
  placeholder: string;
  help: string;
};

function inputForValueType(valueType: SpecFieldDefinition["valueType"]): TrimFieldInput {
  if (valueType === "NUMBER") return "number";
  if (valueType === "BOOLEAN") return "boolean";
  return "text";
}

function resolve(concept: FieldConcept, definition: SpecFieldDefinition | null): TrimEditorField {
  const input = concept.input
    || (definition ? inputForValueType(definition.valueType) : "text");
  return {
    key: concept.key,
    category: concept.category,
    labelEn: concept.labelEn,
    labelTh: concept.labelTh,
    input: concept.options?.length ? "enum" : input,
    unit: concept.unit ?? definition?.canonicalUnit ?? "",
    options: concept.options || [],
    qualifiers: (definition?.comparisonQualifiers || []).map(qualifierFor),
    targets: concept.targets,
    powertrains: definition?.applicablePowertrains || [],
    integer: Boolean(concept.integer),
    positive: Boolean(concept.positive),
    max: concept.max ?? null,
    identityLocked: Boolean(concept.identityLocked),
    placeholder: concept.placeholder || "",
    help: concept.help || "",
  };
}

/**
 * Every UI field, in category order: the mapped concepts above first, then any
 * remaining registry field the table has not claimed, placed by its registry
 * group. A registry key never appears twice, because a key claimed by a
 * concept is removed before the long tail is appended -- that single filter is
 * what makes "one field per concept" structural rather than a thing someone
 * has to remember.
 */
export function resolveTrimEditorFields(registry: SpecFieldDefinition[]): TrimEditorField[] {
  const byKey = new Map(registry.map((field) => [field.key, field]));
  const claimed = new Set<string>(UNSURFACED_SPEC_KEYS);

  const fields: TrimEditorField[] = [];
  for (const concept of CONCEPTS) {
    const specKey = concept.targets.specKey;
    if (specKey) {
      if (claimed.has(specKey)) {
        throw new Error(`trim-editor-fields: ${specKey} is claimed twice; one concept, one field`);
      }
      claimed.add(specKey);
    }
    fields.push(resolve(concept, specKey ? byKey.get(specKey) || null : null));
  }

  for (const definition of registry) {
    if (claimed.has(definition.key)) continue;
    fields.push(resolve({
      key: definition.key.replace(/\./g, "_"),
      category: CATEGORY_OF_GROUP[definition.group] || "manufacturing",
      labelEn: definition.labelEn || definition.key,
      labelTh: definition.labelTh || definition.labelEn || definition.key,
      targets: { specKey: definition.key },
    }, definition));
  }

  const order = new Map(TRIM_CATEGORIES.map((category, index) => [category.id, index]));
  const stable = fields.map((field, index) => ({ field, index }));
  stable.sort((a, b) =>
    (order.get(a.field.category)! - order.get(b.field.category)!) || (a.index - b.index));
  return stable.map((row) => row.field);
}

/** A field applies to a trim when the registry says its spec key does. Fields
 * with no spec key (engine_code, wheel_front, notes) are universal except
 * where MarketTrim itself forbids them. */
export function fieldAppliesTo(field: TrimEditorField, powertrain: string): boolean {
  // MarketTrim.validate(): "BEV cannot have a combustion engine".
  if (field.key === "engine_code" && powertrain === "BEV") return false;
  if (!field.powertrains.length) return true;
  return field.powertrains.includes(powertrain);
}

export function fieldsByCategory(fields: TrimEditorField[]): Array<{
  category: (typeof TRIM_CATEGORIES)[number];
  fields: TrimEditorField[];
}> {
  return TRIM_CATEGORIES
    .map((category) => ({ category, fields: fields.filter((f) => f.category === category.id) }))
    .filter((group) => group.fields.length > 0);
}

/** Form input names. One place, so the page and the server action cannot
 * disagree about what a box is called. They live here rather than beside the
 * action because a "use server" module may export nothing but async
 * functions. */
export const valueInputName = (fieldKey: string) => `f__${fieldKey}`;
export const naInputName = (fieldKey: string) => `na__${fieldKey}`;
export const qualifierInputName = (fieldKey: string, qualifierKey: string) =>
  `q__${fieldKey}__${qualifierKey}`;

/**
 * What the trim form gets back when a submission does not go through.
 *
 * A wrong number is an ordinary thing for a person to type, not a system
 * fault, so it comes back as data and the page re-renders with the message
 * beside the offending box and everything else still typed in. The error
 * boundary is left for what it is actually for: a bug or an outage.
 */
export type TrimEditState = {
  formError: string;
  fieldErrors: Record<string, string>;
};

export const EMPTY_TRIM_EDIT_STATE: TrimEditState = { formError: "", fieldErrors: {} };

export type FieldValidation = { ok: true; value: string | number | boolean | null } | { ok: false; message: string };

/**
 * The single constraint check. The page runs it to show an error beside the
 * box, the server action runs it again on submit, and both get the same answer
 * because it is the same function reading the same registry metadata -- which
 * is what stops the class of bug where the UI accepts battery_kwh = 0 and the
 * writer then rejects the whole batch.
 */
export function validateFieldValue(field: TrimEditorField, raw: string): FieldValidation {
  const text = String(raw ?? "").trim();
  if (!text) return { ok: true, value: null };

  if (field.input === "boolean") {
    if (text === "true") return { ok: true, value: true };
    if (text === "false") return { ok: true, value: false };
    return { ok: false, message: "ต้องเป็น true หรือ false" };
  }
  if (field.input === "number") {
    const value = Number(text);
    if (!Number.isFinite(value)) return { ok: false, message: "ต้องเป็นตัวเลข" };
    if (value < 0) return { ok: false, message: "ต้องไม่ติดลบ" };
    // MarketTrim.validate() rejects 0 for the columns it owns; the spec
    // registry alone would accept it. The stricter of the two wins, because
    // one value has to satisfy every backend it is written to.
    if (field.positive && value === 0) return { ok: false, message: "ต้องมากกว่า 0" };
    if (field.integer && !Number.isInteger(value)) return { ok: false, message: "ต้องเป็นจำนวนเต็ม" };
    if (field.max !== null && value > field.max) return { ok: false, message: `ต้องไม่เกิน ${field.max}` };
    return { ok: true, value };
  }
  if (field.input === "enum" && field.options.length && !field.options.includes(text)) {
    return { ok: false, message: `ต้องเป็นหนึ่งใน ${field.options.join(", ")}` };
  }
  return { ok: true, value: text };
}

/**
 * Cross-field rules MarketTrim enforces, which no single-field check can see.
 * Returned keyed by the field the admin should look at.
 */
export function validateTrimConsistency(
  values: Record<string, string | number | boolean | null>,
  powertrain: string,
): Record<string, string> {
  const problems: Record<string, string> = {};
  const wheelbase = values.wheelbase_mm;
  const length = values.length_mm;
  if (typeof wheelbase === "number" && typeof length === "number" && wheelbase >= length) {
    problems.wheelbase_mm = "ระยะฐานล้อต้องน้อยกว่าความยาวตัวรถ";
  }
  if (powertrain === "BEV") {
    if (typeof values.engine_cc === "number") problems.engine_cc = "รถ BEV ไม่มีเครื่องยนต์สันดาป";
    if (typeof values.engine_code === "string" && values.engine_code) {
      problems.engine_code = "รถ BEV ไม่มีเครื่องยนต์สันดาป";
    }
  }
  return problems;
}
