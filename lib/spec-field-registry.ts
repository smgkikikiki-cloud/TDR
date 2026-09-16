/**
 * Reads the comparable-spec field definitions straight from the canonical
 * Vehicle Master data tree (automotive/vehicle_master/vehreg/data/<year>/
 * product/comparable_specs/registry.json — see vehreg/comparable_specs.py's
 * SpecRegistry). This is the same file APPEND_SPEC / SpecLedger validate
 * against, so the admin spec form can never drift from what the canonical
 * writer actually accepts: there is exactly one place a field is defined.
 *
 * No "@/" alias imports here on purpose — scripts/check-vehicle-editor.ts
 * loads this module directly with node --experimental-strip-types, the same
 * convention every other scripts/check-*.ts test relies on.
 */
import fs from "node:fs";
import path from "node:path";

export type SpecValueType = "NUMBER" | "BOOLEAN" | "ENUM" | "TEXT" | "SET";
export type SpecComparisonRule =
  | "HIGHER_BETTER" | "LOWER_BETTER" | "PRESENCE" | "SET_DIFFERENCE" | "INFORMATION_ONLY";

export type SpecFieldDefinition = {
  key: string;
  group: string;
  labelTh: string;
  labelEn: string;
  valueType: SpecValueType;
  comparisonRule: SpecComparisonRule;
  canonicalUnit: string;
  applicablePowertrains: string[];
  comparisonQualifiers: string[];
  displayPrecision: number | null;
};

function registryPath(year: number): string {
  return path.join(
    process.cwd(), "automotive", "vehicle_master", "vehreg", "data",
    String(year), "product", "comparable_specs", "registry.json",
  );
}

function dataYears(): number[] {
  const root = path.join(process.cwd(), "automotive", "vehicle_master", "vehreg", "data");
  try {
    return fs.readdirSync(root)
      .filter((name) => /^\d{4}$/.test(name))
      .map((name) => Number(name))
      .sort((a, b) => b - a);
  } catch {
    return [];
  }
}

/** Nearest year at or below `year` that actually has a registry file. Older
 * catalog years predate the comparable-spec registry; falling forward to the
 * newest available definition is safer than fabricating fields or hard-failing
 * the whole editor page. */
function resolveRegistryYear(year: number): number | null {
  if (fs.existsSync(registryPath(year))) return year;
  const candidates = dataYears().filter((y) => fs.existsSync(registryPath(y)));
  if (!candidates.length) return null;
  const below = candidates.filter((y) => y <= year);
  return (below.length ? below[0] : candidates[candidates.length - 1]);
}

const cache = new Map<number, SpecFieldDefinition[]>();

export function loadSpecFieldRegistry(year: number): SpecFieldDefinition[] {
  const resolvedYear = resolveRegistryYear(year);
  if (resolvedYear === null) return [];
  const cached = cache.get(resolvedYear);
  if (cached) return cached;

  const raw = JSON.parse(fs.readFileSync(registryPath(resolvedYear), "utf8"));
  if (raw?.schema_version !== 1 || !Array.isArray(raw?.fields)) return [];
  const fields: SpecFieldDefinition[] = raw.fields.map((row: any) => ({
    key: String(row.key || ""),
    group: String(row.group || ""),
    labelTh: String(row.label_th || ""),
    labelEn: String(row.label_en || ""),
    valueType: row.value_type,
    comparisonRule: row.comparison_rule,
    canonicalUnit: String(row.canonical_unit || ""),
    applicablePowertrains: Array.isArray(row.applicable_powertrains) ? row.applicable_powertrains.map(String) : [],
    comparisonQualifiers: Array.isArray(row.comparison_qualifiers) ? row.comparison_qualifiers.map(String) : [],
    displayPrecision: typeof row.display_precision === "number" ? row.display_precision : null,
  })).filter((field: SpecFieldDefinition) => field.key && field.group);
  cache.set(resolvedYear, fields);
  return fields;
}

export function specFieldByKey(year: number, key: string): SpecFieldDefinition | null {
  return loadSpecFieldRegistry(year).find((field) => field.key === key) || null;
}

/** A field with no applicablePowertrains list is universal (e.g. seats, dimensions). */
export function fieldAppliesToPowertrain(field: SpecFieldDefinition, powertrain: string): boolean {
  return !field.applicablePowertrains.length || field.applicablePowertrains.includes(powertrain);
}

export function groupSpecFields(fields: SpecFieldDefinition[]): Map<string, SpecFieldDefinition[]> {
  const groups = new Map<string, SpecFieldDefinition[]>();
  for (const field of fields) {
    const bucket = groups.get(field.group) || [];
    bucket.push(field);
    groups.set(field.group, bucket);
  }
  return groups;
}
