/** Body families: the one UI definition of how canonical `body_type` values group into the six buyer-facing
 *  categories (design/DATA_MAP.md §Home, "Body chips + counts"). Home, /models, brand pages and search all read this.
 *
 *  A family is a SET of canonical body values; it is never collapsed to one value. TRUCK belongs to no family
 *  (it is not a chip), and the raw values stay available for the filter rail.
 *
 *  URL representation of the `body` filter (backward compatible): a comma-separated list of canonical values.
 *    /models?body=PICKUP                 one value, exactly the URL that has always worked
 *    /models?body=SEDAN,COUPE,WAGON      a family (or any hand-picked set)
 *  Matching is "the model's body_type is any of the listed values". A one-value list behaves exactly as before.
 *
 *  Plain TypeScript with no imports so scripts/check-models.ts can test it under Node's type stripping. */

export type BodyIconName = "sedan" | "suv" | "pickup" | "mpv" | "hatchback" | "van";

export type BodyFamily = {
  key: string;
  /** Thai label shown on tiles and chips. */
  label: string;
  values: readonly string[];
  icon: BodyIconName;
};

/** Order = the order of the approved reference (models_v1.html tiles). */
export const BODY_FAMILIES: readonly BodyFamily[] = [
  { key: "sedan", label: "รถเก๋ง", values: ["SEDAN", "COUPE", "WAGON"], icon: "sedan" },
  { key: "suv", label: "SUV", values: ["CROSSOVER", "PPV", "OFFROAD"], icon: "suv" },
  { key: "pickup", label: "กระบะ", values: ["PICKUP"], icon: "pickup" },
  { key: "mpv", label: "MPV", values: ["MPV"], icon: "mpv" },
  { key: "hatchback", label: "แฮทช์แบ็ก", values: ["HATCHBACK"], icon: "hatchback" },
  { key: "van", label: "รถตู้", values: ["VAN"], icon: "van" },
];

/** The family a canonical body value belongs to, or null (TRUCK, OTHER, unknown). */
export function familyOfBody(value: string | null | undefined): BodyFamily | null {
  if (!value) return null;
  return BODY_FAMILIES.find((f) => f.values.includes(value)) || null;
}

/** `?body=` -> the list of canonical values it names. Empty / missing -> []. Values are kept exactly as written
 *  (no case folding), so an unknown value simply matches nothing, as a single unknown value always did. */
export function parseBodyParam(param: string | null | undefined): string[] {
  if (!param) return [];
  const seen = new Set<string>();
  for (const part of param.split(",")) {
    const value = part.trim();
    if (value) seen.add(value);
  }
  return [...seen];
}

/** The inverse: values -> the `body` param, or null when nothing is selected. */
export function bodyParam(values: readonly string[]): string | null {
  return values.length ? values.join(",") : null;
}

/** The param a family chip / tile links to. */
export function familyParam(family: BodyFamily): string {
  return family.values.join(",");
}

/** Does a model with this body_type pass a `body` filter? No filter passes everything. */
export function bodyMatches(bodyType: string | null | undefined, selected: readonly string[]): boolean {
  if (!selected.length) return true;
  return !!bodyType && selected.includes(bodyType);
}

/** The family whose value set is exactly `selected` (order does not matter), or null. */
export function familyForSelection(selected: readonly string[]): BodyFamily | null {
  if (!selected.length) return null;
  const set = new Set(selected);
  return BODY_FAMILIES.find((f) => f.values.length === set.size && f.values.every((v) => set.has(v))) || null;
}

/** Toggle one canonical value in a selection (the filter rail's checkbox). */
export function toggleBodyValue(selected: readonly string[], value: string): string[] {
  return selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value];
}

/** Number of models in `bodies` (a list of body_type values) that fall in the family. */
export function countInFamily(bodies: readonly (string | null | undefined)[], family: BodyFamily): number {
  return bodies.filter((b) => !!b && family.values.includes(b)).length;
}
