/**
 * ECO homologation evidence input, ported from
 * automotive/vehicle_master/vehreg/homologation.py (ECOStickerSpecStore.add_payload).
 * ENGINE_INVENTORY §4.8.
 *
 * Only the parse step lives here (strings stripped, powertrain aliases
 * resolved). ECOStickerSpec.validate, the price-key guard, the base-catalog
 * trim rule and the cross-check against the MarketTrim are enforced by the
 * master tables (migration_v59).
 */
import { parseFacet } from "./taxonomy.ts";

type Row = Record<string, any>;

const strip = (value: unknown) => (value === null || value === undefined || value === false || value === 0 || value === "" ? "" : String(value)).trim();

/** The stored row (to_jsonable(ECOStickerSpec)) for one raw ECO spec row. */
export function parseEcoSpec(raw: Row): Row {
  return {
    trim_id: strip(raw.trim_id),
    source_ref: strip(raw.source_ref),
    approval_at: strip(raw.approval_at),
    powertrain: parseFacet("Powertrain", raw.powertrain || "UNKNOWN"),
    seats: raw.seats ?? null,
    tire_size: strip(raw.tire_size),
    chassis_code: strip(raw.chassis_code),
    battery_chemistry: strip(raw.battery_chemistry),
    battery_supplier: strip(raw.battery_supplier),
    battery_voltage_v: raw.battery_voltage_v ?? null,
    declared_total_weight_kg: raw.declared_total_weight_kg ?? null,
    factory: strip(raw.factory),
    rated_range_km: raw.rated_range_km ?? null,
  };
}
