/**
 * Normalizes one published trim row into the editor's state, once.
 *
 * The production projection nests: `current_market_trims.payload` is
 * `ProductMaster.detail()` (vehreg/product.py), so MarketTrim's own columns
 * live under `payload.specs`, and the resolved comparable-spec facts -- with
 * their qualifiers -- live under `payload.comparable_specs`. Code that reached
 * for `payload.drivetrain` found undefined and silently rendered an empty box
 * over a trim that had a value.
 *
 * So nothing else guesses at the nesting. This module reads the row once and
 * returns a flat object keyed by the UI field keys in lib/trim-editor-fields.ts,
 * and the page, the diff, the server action and the validator all read that
 * same object. If the shape ever changes again, it changes here.
 *
 * It is also the fan-IN that matches the fan-OUT: a concept stored in both
 * backends (Seats is MarketTrim `seats` and a `vehicle.seats` fact) is read
 * back as one value, preferring the spec fact because only it carries a
 * value_state and qualifiers, and falling back to the MarketTrim column, which
 * for most trims today is the only one populated.
 *
 * No "@/" alias imports: scripts/check-trim-editor-fields.ts executes this.
 */
import { fieldAppliesTo, type TrimEditorField } from "./trim-editor-fields.ts";

export type SpecFactValueState = "KNOWN" | "UNKNOWN" | "NOT_AVAILABLE" | "NOT_APPLICABLE";

export type EditableField = {
  /** Form-ready text; "" when nothing is known. */
  value: string;
  valueState: SpecFactValueState;
  qualifiers: Record<string, string>;
  /** Which backend the displayed value came from. "none" means untouched. */
  origin: "spec" | "trim" | "none";
};

export type ResolvedSpecFact = {
  fieldKey: string;
  valueState: SpecFactValueState;
  value: unknown;
  unit: string;
  qualifiers: Record<string, string>;
};

const EMPTY: EditableField = { value: "", valueState: "UNKNOWN", qualifiers: {}, origin: "none" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/**
 * MarketTrim's own columns out of a published trim payload.
 *
 * `payload.specs` is the production shape and is tried first. The bare payload
 * is accepted as a fallback so a row written by an older projection, or a test
 * fixture built by hand, still opens instead of rendering a blank form; the
 * fallback only applies when `specs` is absent, never as a merge, so a
 * production row can never pick up a stray top-level key.
 */
export function marketTrimFieldsFromPayload(payload: unknown): Record<string, unknown> {
  if (!isRecord(payload)) return {};
  if (isRecord(payload.specs)) return payload.specs;
  return payload;
}

function asQualifiers(raw: unknown): Record<string, string> {
  if (!isRecord(raw)) return {};
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (value === null || value === undefined || value === "") continue;
    result[key] = String(value);
  }
  return result;
}

function asValueState(raw: unknown): SpecFactValueState {
  const text = String(raw || "").toUpperCase();
  return text === "KNOWN" || text === "NOT_AVAILABLE" || text === "NOT_APPLICABLE"
    ? text : "UNKNOWN";
}

/**
 * The resolved comparable-spec facts for a trim, keyed by field_key.
 *
 * `payload.comparable_specs` is `SpecLedger.resolved()` as of the release, so
 * it is already one fact per (field, qualifier context) and is the same list
 * `current_spec_facts` is projected from. `extraFacts` lets a caller pass that
 * table's rows for a projection old enough not to embed them.
 */
export function resolvedSpecsFromPayload(
  payload: unknown,
  extraFacts: Array<Record<string, unknown>> = [],
): Map<string, ResolvedSpecFact> {
  const rows: Array<Record<string, unknown>> = [];
  if (isRecord(payload) && Array.isArray(payload.comparable_specs)) {
    for (const row of payload.comparable_specs) if (isRecord(row)) rows.push(row);
  }
  if (!rows.length) {
    for (const row of extraFacts) if (isRecord(row)) rows.push(row);
  }
  const result = new Map<string, ResolvedSpecFact>();
  for (const row of rows) {
    const fieldKey = String(row.field_key || "");
    if (!fieldKey) continue;
    result.set(fieldKey, {
      fieldKey,
      valueState: asValueState(row.value_state),
      value: row.value ?? null,
      unit: String(row.unit || ""),
      qualifiers: asQualifiers(row.qualifiers),
    });
  }
  return result;
}

/** Form text for a canonical value. Booleans stay "true"/"false" so they
 * round-trip through a select without becoming the string "on". */
export function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

/**
 * A MarketTrim column counts as "set" only when it holds real content. The
 * canonical empty representations differ by column -- "" for text, null for
 * numbers, and "UNKNOWN" for the drivetrain enum -- and none of them is a
 * value an admin entered.
 */
function marketTrimValue(raw: unknown): string {
  if (raw === null || raw === undefined) return "";
  if (typeof raw === "string") {
    const text = raw.trim();
    return text === "UNKNOWN" ? "" : text;
  }
  if (typeof raw === "number") return Number.isFinite(raw) ? String(raw) : "";
  if (typeof raw === "boolean") return raw ? "true" : "false";
  return "";
}

export type NormalizedTrim = {
  canonicalId: string;
  generationId: string;
  name: string;
  powertrain: string;
  /** MarketTrim's own columns, flat, read from payload.specs. */
  marketTrimFields: Record<string, unknown>;
  /** One entry per applicable UI field key. THE editor state. */
  editableSpecs: Record<string, EditableField>;
  sourceRefs: Record<string, string[]>;
};

export function normalizeTrimForEditor(args: {
  payload: unknown;
  fields: TrimEditorField[];
  /** current_spec_facts rows, used only if the payload embeds none. */
  extraFacts?: Array<Record<string, unknown>>;
  canonicalId?: string;
  generationId?: string;
  name?: string;
  powertrain?: string;
  sourceRefs?: Record<string, string[]>;
}): NormalizedTrim {
  const marketTrimFields = marketTrimFieldsFromPayload(args.payload);
  const specs = resolvedSpecsFromPayload(args.payload, args.extraFacts || []);
  const powertrain = String(args.powertrain || marketTrimFields.powertrain || "");

  const editableSpecs: Record<string, EditableField> = {};
  for (const field of args.fields) {
    if (!fieldAppliesTo(field, powertrain)) continue;
    const fact = field.targets.specKey ? specs.get(field.targets.specKey) : undefined;
    if (fact && fact.valueState !== "UNKNOWN") {
      editableSpecs[field.key] = {
        value: fact.valueState === "KNOWN" ? displayValue(fact.value) : "",
        valueState: fact.valueState,
        qualifiers: fact.qualifiers,
        origin: "spec",
      };
      continue;
    }
    const column = field.targets.trimField
      ? marketTrimValue(marketTrimFields[field.targets.trimField]) : "";
    editableSpecs[field.key] = column
      ? { value: column, valueState: "KNOWN", qualifiers: {}, origin: "trim" }
      : { ...EMPTY };
  }

  const sourceRefsRaw = args.sourceRefs ?? marketTrimFields.source_refs;
  const sourceRefs: Record<string, string[]> = {};
  if (isRecord(sourceRefsRaw)) {
    for (const [kind, urls] of Object.entries(sourceRefsRaw)) {
      if (Array.isArray(urls)) sourceRefs[kind] = urls.map(String);
    }
  }

  return {
    canonicalId: String(args.canonicalId || marketTrimFields.id || ""),
    generationId: String(args.generationId || marketTrimFields.generation_id || ""),
    name: String(args.name || marketTrimFields.name || ""),
    powertrain,
    marketTrimFields,
    editableSpecs,
    sourceRefs,
  };
}

/** The local segment of a trim's canonical_id, which is what
 * UPSERT_MODEL_BUNDLE wants back in the trim row's `id` so the writer updates
 * this trim instead of deriving a new identity from its (possibly renamed)
 * name. Returns "" for a trim that does not exist yet. */
export function trimLocalId(canonicalId: string): string {
  const marker = ".trim.";
  const at = String(canonicalId || "").lastIndexOf(marker);
  return at === -1 ? "" : canonicalId.slice(at + marker.length);
}
