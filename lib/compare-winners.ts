/**
 * Evidence-safe "which value wins" highlighting for Vehicle Compare.
 *
 * The comparable-spec registry (lib/spec-field-registry.ts) already carries
 * a `comparisonRule` per field -- HIGHER_BETTER, LOWER_BETTER, PRESENCE,
 * SET_DIFFERENCE, INFORMATION_ONLY -- and this module reuses it as the
 * source of comparison *intent*. It does not reuse it blindly, though: that
 * rule was authored for semantic comparison in general (the internal
 * battlecard engine, vehreg/battlecard.py, already ranks on it), not for
 * "should the public compare page paint this green". A few registry rows
 * are HIGHER_BETTER for reasons that are not a buying advantage -- more
 * seats or a longer wheelbase is a trade-off, not a win, and a lower excise
 * tax rate is not the car being better. So this module adds one small,
 * explicit allowlist on top: a field only ever gets winner highlighting if
 * it is named here. Everything else -- including every other
 * registry-HIGHER_BETTER or -PRESENCE field -- renders neutrally. That is
 * deliberate, not an oversight: start conservative, widen the allowlist
 * later with product sign-off, never the other way around.
 *
 * The other half of "evidence-safe" is qualifiers. A registry field can
 * declare which qualifier names matter for it (comparisonQualifiers, e.g.
 * `measurement_basis`, `range_scope`, `soc_from`/`soc_to`) -- two facts are
 * only on the same measurement basis if every one of those qualifiers
 * matches exactly. A WLTP range and an NEDC range are both "range", but
 * they are not the same claim, so they never produce a winner against each
 * other; they just both display. Missing data works the same way: only a
 * fact with value_state KNOWN participates, an unknown boolean is never
 * "false", and a field needs at least two KNOWN, same-basis values before
 * any index can win.
 */
import {
  registryFieldKeyForRow, resolvedSpec, type CompareRowKey, type CompareSpecField,
  type FreeCompareTrim, type SpecDefinitionIndex,
} from "./free-compare.ts";

export type CompareWinnerMode = "QUANTITATIVE_WINNER" | "PRESENCE_ADVANTAGE" | "NEUTRAL";

export type CompareWinnerEvaluation = {
  comparisonMode: CompareWinnerMode;
  /** True only when at least two selected trims have a KNOWN value on the
   *  same measurement basis for this field -- i.e. a winner *could* be
   *  shown, whether or not any index actually is one (a real tie is still
   *  `comparable: true` with every tied index in bestIndexes; a two-value
   *  presence field where both are true is `comparable: true` with an
   *  empty bestIndexes, since there is nothing to prefer). False means the
   *  row must render exactly as it would have before this feature. */
  comparable: boolean;
  /** Indexes into the same trims array the row's `values` were built from.
   *  Ties are listed in full. Never populated when `comparable` is false. */
  bestIndexes: number[];
};

const NOT_COMPARABLE: CompareWinnerEvaluation = {
  comparisonMode: "NEUTRAL", comparable: false, bestIndexes: [],
};

/** Section 4 of the feature spec, by real registry key -- maximum power,
 *  maximum torque, 0-100 acceleration, top speed, turning radius, EV range,
 *  combined/urban/extra-urban fuel consumption, energy consumption,
 *  AC/DC charging power, DC charging time, cargo capacity, and the two
 *  battery warranty fields. Direction (higher/lower better) is deliberately
 *  NOT duplicated here -- it is read from the registry's own
 *  `comparisonRule` at evaluation time, so this file has exactly one
 *  opinion (which fields are winner-eligible) and the registry keeps the
 *  other (which direction wins). */
export const QUANTITATIVE_WINNER_FIELDS: ReadonlySet<string> = new Set([
  "powertrain.max_power_kw",
  "powertrain.max_torque_nm",
  "performance.acceleration_0_100_s",
  "performance.top_speed_kmh",
  "vehicle.turning_radius_m",
  "ev.rated_range_km",
  "efficiency.fuel_consumption_l_100km",
  "efficiency.fuel_consumption_urban_l_100km",
  "efficiency.fuel_consumption_extra_urban_l_100km",
  "ev.energy_consumption_wh_km",
  "charging.ac_max_kw",
  "charging.dc_max_kw",
  "charging.dc_time_min",
  "vehicle.cargo_volume_l",
  "battery.warranty_years",
  "battery.warranty_km",
]);

/** Section 5 of the feature spec, by real registry key -- ABS, ESC, AEB,
 *  forward collision warning, lane departure warning, lane keep assist,
 *  blind-spot monitoring, rear cross-traffic alert, side/curtain/knee
 *  airbags, 360-degree camera, HUD, ventilated front seats, smartphone
 *  mirroring, heat pump, V2L. Deliberately NOT every PRESENCE field the
 *  registry has: panoramic roof, connected services and OTA update are
 *  PRESENCE too, but section 6 calls them out as neutral trade-offs/
 *  lifestyle choices, not a defensible "advantage" -- so they are left out
 *  of this allowlist rather than special-cased as an exclusion, keeping
 *  this one list the single source of truth. */
export const PRESENCE_ADVANTAGE_FIELDS: ReadonlySet<string> = new Set([
  "safety.abs",
  "safety.esc",
  "safety.aeb",
  "safety.forward_collision_warning",
  "safety.lane_departure_warning",
  "safety.lane_keep_assist",
  "safety.blind_spot",
  "safety.rear_cross_traffic",
  "safety.side_airbag",
  "safety.curtain_airbag",
  "safety.knee_airbag",
  "technology.surround_view_camera",
  "technology.head_up_display",
  "comfort.ventilated_front_seats",
  "technology.smartphone_mirroring",
  "comfort.heat_pump",
  "charging.v2l_supported",
]);

type KnownNumeric = { index: number; value: number; context: string };
type KnownBoolean = { index: number; value: boolean };

/** One string per known value's qualifier context, built only from the
 *  qualifier names the field itself declares as relevant. A field with no
 *  declared qualifiers (e.g. AC charging power) always resolves to the
 *  same empty context, which is correct: there is nothing about its
 *  measurement basis that could disagree. A qualifier the fact does not
 *  carry defaults to "", so a fact missing `range_scope` never silently
 *  matches one that states it explicitly -- the same fallback
 *  SpecFact.qualifier_key() uses on the Python side (comparable_specs.py). */
function qualifierContext(qualifiers: Record<string, unknown> | null | undefined,
                          qualifierNames: string[]): string {
  return qualifierNames.map((name) => `${name}=${String(qualifiers?.[name] ?? "")}`).join("|");
}

function knownNumericValues(trims: FreeCompareTrim[], fieldKey: string,
                            qualifierNames: string[]): KnownNumeric[] {
  const known: KnownNumeric[] = [];
  trims.forEach((trim, index) => {
    const spec = resolvedSpec(trim, fieldKey);
    if (!spec || spec.value_state !== "KNOWN") return; // UNKNOWN/NOT_AVAILABLE/NOT_APPLICABLE/no fact at all
    const value = typeof spec.value === "number" ? spec.value : Number(spec.value);
    if (!Number.isFinite(value)) return;
    known.push({ index, value, context: qualifierContext(spec.qualifiers, qualifierNames) });
  });
  return known;
}

function evaluateQuantitative(trims: FreeCompareTrim[], fieldKey: string,
                              definition: CompareSpecField): CompareWinnerEvaluation {
  const direction = definition.comparisonRule;
  if (direction !== "HIGHER_BETTER" && direction !== "LOWER_BETTER") return NOT_COMPARABLE;

  const known = knownNumericValues(trims, fieldKey, definition.comparisonQualifiers || []);
  if (known.length < 2) return { comparisonMode: "QUANTITATIVE_WINNER", comparable: false, bestIndexes: [] };

  // Every known value must be on the same measurement basis, or nobody can
  // honestly be called the winner -- a 30-minute DC charge from 10-80% is
  // not "slower" than a 25-minute one from 30-80%.
  const contexts = new Set(known.map((row) => row.context));
  if (contexts.size > 1) return { comparisonMode: "QUANTITATIVE_WINNER", comparable: false, bestIndexes: [] };

  const best = direction === "HIGHER_BETTER"
    ? Math.max(...known.map((row) => row.value))
    : Math.min(...known.map((row) => row.value));
  const bestIndexes = known.filter((row) => row.value === best).map((row) => row.index);
  return { comparisonMode: "QUANTITATIVE_WINNER", comparable: true, bestIndexes };
}

function evaluatePresence(trims: FreeCompareTrim[], fieldKey: string): CompareWinnerEvaluation {
  const known: KnownBoolean[] = [];
  trims.forEach((trim, index) => {
    const spec = resolvedSpec(trim, fieldKey);
    if (!spec || spec.value_state !== "KNOWN") return; // never treat unknown as "does not have"
    if (typeof spec.value !== "boolean") return;
    known.push({ index, value: spec.value });
  });
  if (known.length < 2) return { comparisonMode: "PRESENCE_ADVANTAGE", comparable: false, bestIndexes: [] };

  const hasTrue = known.some((row) => row.value === true);
  const hasFalse = known.some((row) => row.value === false);
  // Data is known either way, so this is a comparable row -- but every known
  // trim agreeing (all have it, or none do) is not an advantage for anyone,
  // same as an exact numeric tie implying no winner.
  const bestIndexes = hasTrue && hasFalse ? known.filter((row) => row.value).map((row) => row.index) : [];
  return { comparisonMode: "PRESENCE_ADVANTAGE", comparable: true, bestIndexes };
}

/** The one entry point the compare API route calls per row. Everything
 *  upstream (which field backs this row, the registry's rule and
 *  qualifiers for it) comes from lib/free-compare.ts and the loaded
 *  registry -- this function adds no comparison metadata of its own beyond
 *  the two allowlists above. */
export function evaluateCompareWinner(trims: FreeCompareTrim[], key: CompareRowKey,
                                      definitions: SpecDefinitionIndex): CompareWinnerEvaluation {
  const fieldKey = registryFieldKeyForRow(key);
  if (!fieldKey) return NOT_COMPARABLE;
  const definition = definitions.get(fieldKey);
  if (!definition) return NOT_COMPARABLE;

  if (QUANTITATIVE_WINNER_FIELDS.has(fieldKey)) return evaluateQuantitative(trims, fieldKey, definition);
  if (PRESENCE_ADVANTAGE_FIELDS.has(fieldKey)) return evaluatePresence(trims, fieldKey);
  return NOT_COMPARABLE;
}
