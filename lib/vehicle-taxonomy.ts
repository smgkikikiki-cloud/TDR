/**
 * Canonical taxonomy value lists, mirrored from
 * automotive/vehicle_master/vehreg/taxonomy.py's Facet enums. BODY_TYPES and
 * SEGMENTS duplicate the same literal lists app/admin/input-actions.ts
 * already carries (that file predates this one and is out of scope to
 * touch); POWERTRAINS/DRIVETRAINS are new to the Canonical Vehicle Editor
 * and shared between its server actions (validation) and its pages (<select>
 * options), which is the drift this file exists to avoid.
 */
export const BODY_TYPES = [
  "HATCHBACK", "SEDAN", "CROSSOVER", "PPV", "OFFROAD", "COUPE",
  "MPV", "PICKUP", "WAGON", "VAN", "TRUCK", "OTHER",
] as const;

export const SEGMENTS = ["A", "B", "C", "D", "E", "F", "UNKNOWN"] as const;

/** MarketTrim.powertrain cannot be UNKNOWN (vehreg/entities.py's MarketTrim.validate). */
export const MARKET_TRIM_POWERTRAINS = ["ICE", "HEV", "PHEV", "REEV", "BEV", "FCEV"] as const;

export const DRIVETRAINS = ["FWD", "RWD", "AWD", "4WD", "UNKNOWN"] as const;
