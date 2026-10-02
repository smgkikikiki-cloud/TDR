/**
 * Comparable specs: the rules that need the field registry, ported from
 * automotive/vehicle_master/vehreg/comparable_specs.py (ENGINE_INVENTORY §4.7,
 * §5.5).
 *
 * VEHICLE_DB_V3 §3 keeps the field registry in lib/spec-field-registry.ts, so
 * the rules that depend on it live here, next to it:
 *   - registry validation (SpecRegistry.load / validate),
 *   - a fact's field must be registered, its value must fit the field's
 *     value_type / canonical_unit, its qualifiers must be the field's
 *     comparison_qualifiers, and the field must apply to the trim's powertrain.
 * The registry-independent fact rules (required ids, non-KNOWN => null value,
 * observed_at, source rules, dates, price-word guard) and the same-start
 * conflict rule are enforced by the master tables (migration_v59).
 *
 * Kept as in the engine for Phase 0 parity (not v3 Phase 1 semantics):
 * value_state UNKNOWN and NOT_AVAILABLE are valid (ENGINE_INVENTORY §9.9).
 */
import type { SpecFieldDefinition } from "../spec-field-registry.ts";

type Row = Record<string, any>;

export class ComparableSpecError extends Error {}

const VALUE_TYPES = ["NUMBER", "BOOLEAN", "ENUM", "TEXT", "SET"];
const COMPARISON_RULES = ["HIGHER_BETTER", "LOWER_BETTER", "PRESENCE", "SET_DIFFERENCE", "INFORMATION_ONLY"];
const REGISTRY_KEYS = new Set(["key", "group", "label_th", "label_en", "value_type", "comparison_rule",
  "canonical_unit", "applicable_powertrains", "comparison_qualifiers", "display_precision"]);
export const PRICE_WORDS = ["price", "msrp", "thb", "baht", "cost", "ราคา"];

export function isPriceField(key: string, canonicalUnit = ""): boolean {
  const lowered = `${key} ${canonicalUnit}`.toLowerCase();
  return PRICE_WORDS.some((word) => lowered.includes(word));
}

/**
 * SpecRegistry.load + validate over the raw registry.json / profiles.json
 * payloads. Returns the problems Python reports (load errors are thrown, as
 * in Python).
 */
export function validateSpecRegistry(registry: unknown, profiles?: unknown): string[] {
  const reg = registry as Row;
  if (!reg || reg.schema_version !== 1 || !Array.isArray(reg.fields)) {
    throw new ComparableSpecError("invalid registry schema");
  }
  const seen = new Set<string>();
  const problems: string[] = [];
  const fields: Row[] = [];
  for (const raw of reg.fields) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw) || Object.keys(raw).some((k) => !REGISTRY_KEYS.has(k))) {
      throw new ComparableSpecError("invalid field definition");
    }
    if (!VALUE_TYPES.includes(String(raw.value_type))) throw new ComparableSpecError(`unknown value_type '${raw.value_type}'`);
    if (!COMPARISON_RULES.includes(String(raw.comparison_rule))) throw new ComparableSpecError(`unknown comparison_rule '${raw.comparison_rule}'`);
    const key = String(raw.key || "");
    if (seen.has(key)) throw new ComparableSpecError(`duplicate spec field ${key}`);
    seen.add(key);
    fields.push(raw);
  }
  for (const def of fields) {
    const key = String(def.key || "");
    const unit = String(def.canonical_unit || "");
    if (!key || !/^[a-z][a-z0-9_.]*$/.test(key)) problems.push(`invalid field key '${key}'`);
    if (isPriceField(key, unit)) problems.push(`${key}: prices belong in PriceLedger, not the spec registry`);
    if (!def.group || !def.label_th || !def.label_en) problems.push(`${key}: group and labels are required`);
    if (def.value_type === "NUMBER" && !unit) problems.push(`${key}: numeric field requires canonical_unit`);
    const precision = def.display_precision;
    if (precision !== null && precision !== undefined && (!Number.isInteger(precision) || typeof precision !== "number" || precision < 0)) {
      problems.push(`${key}: invalid display_precision`);
    }
  }
  if (profiles !== undefined) {
    const prof = profiles as Row;
    if (!prof || prof.schema_version !== 1) throw new ComparableSpecError("invalid profile schema");
    for (const profile of prof.profiles || []) {
      const id = String(profile?.id || "");
      const keys = profile?.fields;
      if (!id || !Array.isArray(keys) || !keys.every((k: unknown) => typeof k === "string")) {
        throw new ComparableSpecError("invalid profile");
      }
      const unknown = keys.filter((k: string) => !seen.has(k));
      if (unknown.length) problems.push(`profile ${id}: unknown fields [${unknown.map((k: string) => `'${k}'`).join(", ")}]`);
      if (new Set(keys).size !== keys.length) problems.push(`profile ${id}: duplicate fields`);
    }
  }
  return problems;
}

/** SpecFieldDefinition.validate_value */
export function validateValue(def: SpecFieldDefinition, state: string, value: unknown, unit: string): string[] {
  const problems: string[] = [];
  if (state !== "KNOWN") {
    if (value !== null && value !== undefined) problems.push("non-KNOWN value_state requires null value");
    return problems;
  }
  if (value === null || value === undefined) return ["KNOWN requires a value"];
  if (def.valueType === "NUMBER") {
    if (typeof value !== "number" || !Number.isFinite(value)) problems.push("numeric field requires a finite number");
    else if (value < 0) problems.push("numeric field cannot be negative");
    if (unit !== def.canonicalUnit) problems.push(`unit must be '${def.canonicalUnit}'`);
  } else if (unit) {
    problems.push("non-numeric field cannot carry a unit");
  }
  if (def.valueType === "BOOLEAN" && typeof value !== "boolean") problems.push("boolean field requires true or false");
  if ((def.valueType === "ENUM" || def.valueType === "TEXT") && (typeof value !== "string" || !value.trim())) {
    problems.push("text/enum field requires nonempty text");
  }
  if (def.valueType === "SET" && (!Array.isArray(value) || !value.length
    || !value.every((v) => typeof v === "string" && v.trim()))) {
    problems.push("set field requires a nonempty string array");
  }
  return problems;
}

/**
 * The registry-dependent part of SpecLedger._validate_fact, in Python's order.
 * `trimPowertrain` is the base-catalog trim's powertrain, or null when the
 * trim is not known (the database then rejects the fact on its own).
 */
export function validateFactAgainstRegistry(fact: Row, registry: ReadonlyMap<string, SpecFieldDefinition>,
  trimPowertrain: string | null): string[] {
  const problems: string[] = [];
  const def = registry.get(String(fact.field_key || ""));
  if (!def) {
    problems.push("unknown field_key");
  } else {
    problems.push(...validateValue(def, String(fact.value_state), fact.value ?? null, String(fact.unit ?? "")));
    const qualifiers = Object.keys(fact.qualifiers || {});
    const unknown = qualifiers.filter((q) => !def.comparisonQualifiers.includes(q)).sort();
    if (unknown.length) problems.push(`unknown qualifiers [${unknown.map((q) => `'${q}'`).join(", ")}]`);
  }
  if (def && def.applicablePowertrains.length && trimPowertrain !== null && !def.applicablePowertrains.includes(trimPowertrain)) {
    problems.push(`field does not apply to ${trimPowertrain}`);
  }
  return problems;
}

/** json.dumps(value, sort_keys=True, ensure_ascii=False): the value identity used for conflicts. */
export function canonicalJson(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(", ")}]`;
  if (typeof value === "object") {
    return `{${Object.keys(value as object).sort().map((k) => `${JSON.stringify(k)}: ${canonicalJson((value as Row)[k])}`).join(", ")}}`;
  }
  return JSON.stringify(value);
}

const factStart = (f: Row): string | null => f.effective_from || f.observed_at || null;

function qualifierKey(f: Row, def: SpecFieldDefinition): string {
  return JSON.stringify(def.comparisonQualifiers.map((k) => [k, String((f.qualifiers || {})[k] ?? "")]));
}

/**
 * SpecLedger.resolved(trim, as_of): VERIFIED facts started by as_of, grouped
 * by (field, qualifier context); latest start; active on as_of; conflicting
 * values throw; the highest fact_id wins; sorted by (field, qualifiers).
 */
export function resolvedFacts(facts: Row[], registry: ReadonlyMap<string, SpecFieldDefinition>, trimId: string,
  asOf: string, includeProvisional = false): Row[] {
  const candidates = facts.filter((f) => f.trim_id === trimId
    && (includeProvisional || (f.verification_status ?? "VERIFIED") === "VERIFIED")
    && (!factStart(f) || factStart(f)! <= asOf));
  const groups = new Map<string, Row[]>();
  for (const fact of candidates) {
    const def = registry.get(fact.field_key);
    if (!def) throw new ComparableSpecError(`unknown field ${fact.field_key}`);
    const key = `${fact.field_key}\u0000${qualifierKey(fact, def)}`;
    groups.set(key, [...(groups.get(key) || []), fact]);
  }
  const resolved: Row[] = [];
  for (const group of groups.values()) {
    const latestStart = group.map((f) => factStart(f) || "0001-01-01").reduce((a, b) => (b > a ? b : a));
    const latest = group.filter((f) => (factStart(f) || "0001-01-01") === latestStart);
    const active = latest.filter((f) => (!factStart(f) || factStart(f)! <= asOf) && (!f.effective_to || f.effective_to >= asOf));
    const values = new Set(active.map((f) => `${f.value_state}\u0000${canonicalJson(f.value ?? null)}`));
    if (values.size > 1) throw new ComparableSpecError(`${trimId}: conflicting ${latest[0].field_key} at ${latestStart}`);
    if (active.length) resolved.push([...active].sort((a, b) => (a.fact_id < b.fact_id ? -1 : a.fact_id > b.fact_id ? 1 : 0)).at(-1)!);
  }
  return resolved.sort((a, b) => {
    if (a.field_key !== b.field_key) return a.field_key < b.field_key ? -1 : 1;
    const qa = qualifierKey(a, registry.get(a.field_key)!);
    const qb = qualifierKey(b, registry.get(b.field_key)!);
    return qa < qb ? -1 : qa > qb ? 1 : 0;
  });
}
