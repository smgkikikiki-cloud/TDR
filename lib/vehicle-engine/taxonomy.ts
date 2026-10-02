/**
 * Facet vocabularies and cross-facet rules, ported from
 * automotive/vehicle_master/vehreg/taxonomy.py (ENGINE_INVENTORY §4.1).
 *
 * Phase 0 step 4 parity port: same names, same values, same aliases, same
 * messages. The closed vocabularies are also checked by the master tables'
 * CHECK constraints (supabase/migration_v59_vehicle_engine_rules.sql); this
 * module is what turns raw input ("SUV", "e-power"…) into those values and
 * what the resolution-chain rules in ./entities.ts run on.
 *
 * Import-free on purpose: scripts/check-vehicle-engine-rules.ts loads it with
 * node --experimental-strip-types.
 */

export type FacetName =
  | "Segment" | "BodyType" | "CabType" | "MarketPosition" | "Powertrain" | "ImportType"
  | "BrandSegment" | "RegistrationType" | "RetailStatus" | "MarketScope" | "Drivetrain";

/** [member name, stored value] in declaration order (Python Enum order). */
const MEMBERS: Record<FacetName, ReadonlyArray<readonly [string, string]>> = {
  Segment: ["A", "B", "C", "D", "E", "F", "UNKNOWN"].map((v) => [v, v] as const),
  BodyType: ["HATCHBACK", "SEDAN", "CROSSOVER", "PPV", "OFFROAD", "COUPE", "MPV", "PICKUP",
    "WAGON", "VAN", "TRUCK", "OTHER"].map((v) => [v, v] as const),
  CabType: ["DOUBLE_CAB", "SINGLE_SMART", "SMART_CAB", "SINGLE_CAB", "NOT_APPLICABLE"]
    .map((v) => [v, v] as const),
  MarketPosition: ["ENTRY", "VOLUME", "UPPER", "LUXURY", "UNKNOWN"].map((v) => [v, v] as const),
  Powertrain: ["ICE", "HEV", "PHEV", "REEV", "BEV", "FCEV", "UNKNOWN"].map((v) => [v, v] as const),
  ImportType: ["CBU", "SKD", "CKD", "UNKNOWN"].map((v) => [v, v] as const),
  BrandSegment: ["BUDGET", "MASS", "PREMIUM_TECH", "PERFORMANCE", "PREMIUM_LUXURY", "UNKNOWN"]
    .map((v) => [v, v] as const),
  RegistrationType: ["RY1", "RY2", "RY3", "RY12", "OTHER"].map((v) => [v, v] as const),
  RetailStatus: ["CURRENT", "HISTORICAL", "UNVERIFIED"].map((v) => [v, v] as const),
  MarketScope: ["CORE", "NICHE", "GREY", "COMMERCIAL", "UNKNOWN"].map((v) => [v, v] as const),
  Drivetrain: [["FWD", "FWD"], ["RWD", "RWD"], ["AWD", "AWD"], ["FOURWD", "4WD"], ["UNKNOWN", "UNKNOWN"]],
};

/** taxonomy.FACET_ALIASES: input key -> member NAME. */
const ALIASES: Partial<Record<FacetName, Record<string, string>>> = {
  BodyType: {
    SUV: "CROSSOVER", MONOCOQUE_SUV: "CROSSOVER", UNIBODY_SUV: "CROSSOVER",
    PPV_SUV: "PPV", PICKUP_DERIVED_SUV: "PPV",
    SUV_BOF: "OFFROAD", BODY_ON_FRAME_SUV: "OFFROAD",
    LADDER_FRAME_SUV: "OFFROAD", OFFROAD_SUV: "OFFROAD",
    OFFROAD_LADDER_FRAME: "OFFROAD",
    MINIVAN: "MPV", CONVERTIBLE: "COUPE",
    CABRIOLET: "COUPE", ESTATE: "WAGON", PICK_UP: "PICKUP",
  },
  CabType: {
    CAB4: "DOUBLE_CAB", "4_DOOR": "DOUBLE_CAB", CREW_CAB: "DOUBLE_CAB",
    SPACE_CAB: "SMART_CAB", EXTENDED_CAB: "SMART_CAB",
    HALF_CAB: "SMART_CAB", OPEN_CAB: "SMART_CAB",
    STANDARD_CAB: "SINGLE_CAB", CHASSIS: "SINGLE_CAB",
    SINGLE_SMART_CAB: "SINGLE_SMART", CAB: "SINGLE_SMART",
    RY3_CAB: "SINGLE_SMART", NA: "NOT_APPLICABLE",
    NONE: "NOT_APPLICABLE",
  },
  Powertrain: {
    EV: "BEV", ELECTRIC: "BEV", HYBRID: "HEV", FULL_HYBRID: "HEV",
    MHEV: "ICE", MILD_HYBRID: "ICE", MILD_HEV: "ICE",
    EQ_BOOST: "ICE", "48V": "ICE",
    PLUG_IN_HYBRID: "PHEV", PLUGIN: "PHEV",
    EREV: "REEV", GASOLINE: "ICE",
    PETROL: "ICE", DIESEL: "ICE", HYDROGEN: "FCEV",
  },
  ImportType: { IMPORTED: "CBU", LOCAL: "CKD", ASSEMBLED: "CKD" },
  // Verbatim, including "4WD": that is the member's value, not its name
  // (FOURWD), so Python's cls[...] raises KeyError for 4X4 / FOUR_WD. The
  // port keeps that rejection (ENGINE_RULES.md, finding F1).
  Drivetrain: { "2WD": "FWD", FF: "FWD", FR: "RWD", "4X4": "4WD", "4X2": "RWD", FOUR_WD: "4WD" },
  RegistrationType: {
    RY_1: "RY1", "1": "RY1", "รย.1": "RY1",
    RY_2: "RY2", "2": "RY2", "รย.2": "RY2",
    RY_3: "RY3", "3": "RY3", "รย.3": "RY3",
  },
  MarketScope: {
    MAIN: "CORE", OFFICIAL: "CORE", EXOTIC: "NICHE",
    SUPERCAR: "NICHE", IMPORT: "GREY",
    GREY_MARKET: "GREY", "เกรย์": "GREY",
    TRUCK: "COMMERCIAL", FLEET: "COMMERCIAL",
  },
  BrandSegment: {
    LUXURY: "PREMIUM_LUXURY", PREMIUM: "PREMIUM_LUXURY",
    TECH: "PREMIUM_TECH", SPORT: "PERFORMANCE",
    ECONOMY: "BUDGET", VALUE: "BUDGET",
  },
};

/** pythonType says which exception Python raises (ValueError, or KeyError for an alias to a non-name). */
export class FacetError extends Error {
  pythonType: "ValueError" | "KeyError";
  constructor(message: string, pythonType: "ValueError" | "KeyError" = "ValueError") {
    super(message);
    this.pythonType = pythonType;
  }
}

/**
 * Python `str(raw)` for the values a JSON payload can carry. A JS number
 * cannot say whether it was written 1 or 1.0, so a float that is a whole
 * number reads as the integer (the only gap; no facet input uses floats).
 */
export function pyStr(raw: unknown): string {
  if (raw === null || raw === undefined) return "None";
  if (raw === true) return "True";
  if (raw === false) return "False";
  return String(raw);
}

function pyRepr(raw: unknown): string {
  if (typeof raw === "string") return `'${raw}'`;
  return pyStr(raw);
}

export function facetValues(facet: FacetName): string[] {
  return MEMBERS[facet].map(([, value]) => value);
}

/** Facet.parse: member name, then member value, then FACET_ALIASES. */
export function parseFacet(facet: FacetName, raw: unknown): string {
  const key = pyStr(raw).trim().toUpperCase().replaceAll("-", "_").replaceAll(" ", "_");
  const members = MEMBERS[facet];
  const byName = members.find(([name]) => name === key);
  if (byName) return byName[1];
  const byValue = members.find(([, value]) => value.toUpperCase() === key);
  if (byValue) return byValue[1];
  const alias = ALIASES[facet]?.[key];
  if (alias) {
    const target = members.find(([name]) => name === alias);
    if (!target) throw new FacetError(`'${alias}'`, "KeyError");
    return target[1];
  }
  throw new FacetError(`${facet}: unknown value ${pyRepr(raw)}`);
}

/** catalog._facet: blank -> default, else parse. */
export function facetOrDefault(facet: FacetName, raw: unknown, fallback: string): string {
  return raw === null || raw === undefined || raw === "" ? fallback : parseFacet(facet, raw);
}

const PRICE_BAND_EDGES: ReadonlyArray<readonly [number, string]> = [
  [500_000, "ENTRY"], [1_000_000, "VOLUME"], [1_800_000, "UPPER"],
];

export function marketPositionForPrice(price: number | null | undefined): string {
  if (price === null || price === undefined) return "UNKNOWN";
  if (price < 0) throw new FacetError("price_thb must not be negative");
  for (const [edge, band] of PRICE_BAND_EDGES) if (price < edge) return band;
  return "LUXURY";
}

export function registrationTypeFor(body: unknown, cab: unknown): string {
  const b = parseFacet("BodyType", body);
  const c = parseFacet("CabType", cab);
  if (b === "PICKUP") return c === "DOUBLE_CAB" ? "RY1" : "RY3";
  if (b === "TRUCK") return "RY3";
  return "RY1";
}

/** taxonomy.normalize_country */
export function normalizeCountry(code: unknown): string {
  if (!truthy(code)) return "UNKNOWN";
  return String(code).trim().toUpperCase();
}

/** Python truthiness of a JSON value. */
export function truthy(value: unknown): boolean {
  if (value === null || value === undefined || value === false || value === 0 || value === "") return false;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value as object).length > 0;
  return true;
}

const FLEET_BODIES = new Set(["VAN", "TRUCK"]);
const PLUGGABLE = new Set(["PHEV", "REEV", "BEV"]);
const LOCALLY_ASSEMBLED = new Set(["SKD", "CKD"]);

export function checkRegistration(body: unknown, cab: unknown, reg: unknown): string[] {
  const expected = registrationTypeFor(body, cab);
  const r = parseFacet("RegistrationType", reg);
  if (r === "RY2") return [];
  if (FLEET_BODIES.has(parseFacet("BodyType", body))) return [];
  if (r !== expected) {
    return [`${parseFacet("BodyType", body)}/${parseFacet("CabType", cab)} is registered ${expected}, not ${r}`];
  }
  return [];
}

export function checkBodySegment(body: unknown, cab: unknown, segment: unknown): string[] {
  const problems: string[] = [];
  const b = parseFacet("BodyType", body);
  const c = parseFacet("CabType", cab);
  const s = parseFacet("Segment", segment);
  if (b === "PICKUP" && c === "NOT_APPLICABLE") problems.push("pickup must declare a cab_type");
  if (b !== "PICKUP" && c !== "NOT_APPLICABLE") problems.push(`cab_type is only valid for PICKUP, got body=${b}`);
  if (b === "PICKUP" && s !== "F") problems.push("owner scheme: every pickup is segment F");
  if (s === "F" && b !== "PICKUP") problems.push("segment F is reserved for pickups in the owner scheme");
  return problems;
}

export function checkPowertrain(pt: unknown, batteryKwh: unknown, engineCc: unknown): string[] {
  const problems: string[] = [];
  const p = parseFacet("Powertrain", pt);
  if (p === "BEV" && truthy(engineCc)) problems.push("BEV must not declare engine_cc");
  if (p === "ICE" && truthy(batteryKwh)) problems.push("plain ICE must not declare a traction battery");
  if (PLUGGABLE.has(p) && p !== "BEV" && !truthy(engineCc)) problems.push(`${p} needs engine_cc`);
  if ((p === "BEV" || p === "PHEV" || p === "REEV") && !truthy(batteryKwh)) problems.push(`${p} needs battery_kwh`);
  return problems;
}

export function checkOrigin(importType: unknown, originCountry: unknown): string[] {
  const it = parseFacet("ImportType", importType);
  const country = normalizeCountry(originCountry);
  if (LOCALLY_ASSEMBLED.has(it) && country !== "TH") {
    return [`${it} means assembled in Thailand, but origin_country=${country}`];
  }
  return [];
}

const POWERTRAIN_GROUP: Record<string, string> = {
  ICE: "COMBUSTION", HEV: "HYBRID", PHEV: "HYBRID", REEV: "HYBRID",
  BEV: "ZERO_EMISSION", FCEV: "ZERO_EMISSION", UNKNOWN: "UNKNOWN",
};
const MARKET_POWERTRAIN: Record<string, string> = {
  ICE: "FUEL", HEV: "HYBRID", REEV: "REEV", PHEV: "PLUGIN", BEV: "ELECTRIC", FCEV: "ELECTRIC", UNKNOWN: "UNKNOWN",
};

export const powertrainGroup = (pt: unknown) => POWERTRAIN_GROUP[parseFacet("Powertrain", pt)];
export const marketPowertrain = (pt: unknown) => MARKET_POWERTRAIN[parseFacet("Powertrain", pt)];
export const isElectrified = (pt: unknown) => ["HEV", "PHEV", "REEV", "BEV", "FCEV"].includes(parseFacet("Powertrain", pt));
export const isPlugIn = (pt: unknown) => PLUGGABLE.has(parseFacet("Powertrain", pt));
export function isLocallyAssembled(importType: unknown, originCountry: unknown): boolean {
  const it = parseFacet("ImportType", importType);
  return LOCALLY_ASSEMBLED.has(it) || (it === "CBU" && String(originCountry || "").toUpperCase() === "TH");
}
