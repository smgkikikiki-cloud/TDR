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
 * The other half of "evidence-safe" is qualifiers. SpecLedger.resolved() is
 * keyed by (field_key, qualifier_key), not just field_key -- one trim can
 * carry more than one KNOWN fact for the same field (a WLTP range next to
 * an NEDC one on the same car). Row identity in lib/free-compare.ts
 * (compareGroupDefinitions/CompareRowKey) already turns each distinct
 * qualifier context into its own row before this module ever sees a value,
 * so "evaluate this row" never has to choose a basis: `contextForRow(key)`
 * says exactly which context the row is for, and only a KNOWN fact whose
 * own qualifiers resolve to that same context (qualifierContextKey)
 * participates. A WLTP range and an NEDC range are both "range", but they
 * land on two different rows and never produce a winner against each other.
 * Missing data works the same way on top: only a fact with value_state
 * KNOWN participates, an unknown boolean is never "false", and a field
 * needs at least two KNOWN values on the row's own basis before any index
 * can win.
 *
 * An exact tie is not a win either. Every known value agreeing (150 kW vs
 * 150 kW) leaves the row `comparable: true` but highlights nobody -- there
 * is no advantage to point at. A *partial* tie for best (204/180/204) is
 * different: the two 204s really do beat the 180, so both are highlighted.
 */
import {
  contextForRow, qualifierContextKey, registryFieldKeyForRow, resolvedSpecs,
  type CompareRowKey, type CompareSpecField, type FreeCompareTrim, type ResolvedSpec,
  type SpecDefinitionIndex,
} from "./free-compare.ts";

export type CompareWinnerMode = "QUANTITATIVE_WINNER" | "PRESENCE_ADVANTAGE" | "NEUTRAL";

export type CompareWinnerEvaluation = {
  comparisonMode: CompareWinnerMode;
  /** True only when at least two selected trims have a KNOWN value on this
   *  row's own qualifier context -- i.e. a winner *could* be shown, whether
   *  or not any index actually is one. False means the row must render
   *  exactly as it would have before this feature. */
  comparable: boolean;
  /** Indexes into the same trims array the row's `values` were built from.
   *  A partial tie for best lists every tied index; an exact tie across
   *  every known value (nobody actually ahead of anyone) and a
   *  presence field everyone agrees on both leave this empty even though
   *  `comparable` is true. Never populated when `comparable` is false. */
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

type KnownNumeric = { index: number; value: number };
type KnownBoolean = { index: number; value: boolean };

/** The one fact on this trim that belongs on this row -- KNOWN, and whose
 *  own qualifiers resolve to the exact context the row was generated for.
 *
 *  Ordinarily at most one can match: SpecLedger.resolved() already dedupes
 *  by (field_key, qualifier_key), so two facts sharing every
 *  comparisonQualifiers value would have to collide at that step. If a
 *  stale or hand-built payload still manages to carry two, picking one
 *  would be exactly the kind of guess this feature exists to avoid -- so
 *  that trim contributes no value to this row, same as having none at all,
 *  rather than the row failing for every other trim too. */
function knownFactForRow(trim: FreeCompareTrim, fieldKey: string, context: string,
                         qualifierNames: string[]): ResolvedSpec | null {
  const matches = resolvedSpecs(trim, fieldKey).filter((spec) =>
    spec.value_state === "KNOWN" && qualifierContextKey(spec.qualifiers, qualifierNames) === context);
  return matches.length === 1 ? matches[0] : null;
}

function knownNumericValues(trims: FreeCompareTrim[], fieldKey: string, context: string,
                            qualifierNames: string[]): KnownNumeric[] {
  const known: KnownNumeric[] = [];
  for (let index = 0; index < trims.length; index++) {
    const fact = knownFactForRow(trims[index], fieldKey, context, qualifierNames);
    if (!fact) continue;
    const value = typeof fact.value === "number" ? fact.value : Number(fact.value);
    if (!Number.isFinite(value)) continue;
    known.push({ index, value });
  }
  return known;
}

function evaluateQuantitative(trims: FreeCompareTrim[], fieldKey: string, context: string,
                              qualifierNames: string[],
                              definition: CompareSpecField): CompareWinnerEvaluation {
  const direction = definition.comparisonRule;
  if (direction !== "HIGHER_BETTER" && direction !== "LOWER_BETTER") return NOT_COMPARABLE;

  const known = knownNumericValues(trims, fieldKey, context, qualifierNames);
  if (known.length < 2) {
    return { comparisonMode: "QUANTITATIVE_WINNER", comparable: false, bestIndexes: [] };
  }

  // All known values agreeing exactly (150 vs 150) is not a comparative
  // advantage for anyone -- data is known and comparable, so the row stays
  // `comparable: true`, but nothing is highlighted. A partial tie (204,
  // 180, 204) is different: two of the three genuinely beat the third, so
  // both still win below.
  if (new Set(known.map((row) => row.value)).size === 1) {
    return { comparisonMode: "QUANTITATIVE_WINNER", comparable: true, bestIndexes: [] };
  }

  const best = direction === "HIGHER_BETTER"
    ? Math.max(...known.map((row) => row.value))
    : Math.min(...known.map((row) => row.value));
  const bestIndexes = known.filter((row) => row.value === best).map((row) => row.index);
  return { comparisonMode: "QUANTITATIVE_WINNER", comparable: true, bestIndexes };
}

function evaluatePresence(trims: FreeCompareTrim[], fieldKey: string, context: string,
                          qualifierNames: string[]): CompareWinnerEvaluation {
  const known: KnownBoolean[] = [];
  for (let index = 0; index < trims.length; index++) {
    const fact = knownFactForRow(trims[index], fieldKey, context, qualifierNames);
    if (!fact || typeof fact.value !== "boolean") continue; // never treat unknown/absent as "does not have"
    known.push({ index, value: fact.value });
  }
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
 *  upstream (which field backs this row, which qualifier context it's for,
 *  the registry's rule and qualifiers for it) comes from lib/free-compare.ts
 *  and the loaded registry -- this function adds no comparison metadata of
 *  its own beyond the two allowlists above. */
export function evaluateCompareWinner(trims: FreeCompareTrim[], key: CompareRowKey,
                                      definitions: SpecDefinitionIndex): CompareWinnerEvaluation {
  const fieldKey = registryFieldKeyForRow(key);
  if (!fieldKey) return NOT_COMPARABLE;
  const definition = definitions.get(fieldKey);
  if (!definition) return NOT_COMPARABLE;
  const context = contextForRow(key);
  const qualifierNames = definition.comparisonQualifiers || [];

  if (QUANTITATIVE_WINNER_FIELDS.has(fieldKey))
    return evaluateQuantitative(trims, fieldKey, context, qualifierNames, definition);
  if (PRESENCE_ADVANTAGE_FIELDS.has(fieldKey))
    return evaluatePresence(trims, fieldKey, context, qualifierNames);
  return NOT_COMPARABLE;
}
