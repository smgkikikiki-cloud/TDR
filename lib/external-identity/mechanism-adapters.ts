/**
 * Phase 1A mechanism adapters — pure row-shape -> ExternalIdentityAssertion
 * conversion. No Supabase import here; these take plain objects shaped like
 * the rows the live mechanisms actually produce, so they can be exercised
 * with synthetic fixtures in tests and reused by the live CLI unchanged.
 *
 * These adapters do not read, write, or validate against a database. They
 * only normalize already-fetched rows into the shared contract in types.ts.
 */
import {
  type CanonicalEntityType,
  type ExternalEntityType,
  type ExternalIdentityAssertion,
  type MappingState,
  type TrustLevel,
} from "./types.ts";

// ---------------------------------------------------------------------------
// Mechanism A — release-build crosswalk, read live from the `current_*`
// views defined in supabase/migration_v15_canonical_vehicle_release.sql.
// Columns selected here match canonical_brand_projection/
// canonical_model_projection exactly (see tdr_bridge/release.py for how
// tdr_brand_id/tdr_model_id are produced upstream).
// ---------------------------------------------------------------------------

export interface MechanismABrandRow {
  canonical_id: string;
  tdr_brand_id: string | null;
}

export interface MechanismAModelRow {
  canonical_id: string;
  tdr_model_id: string | null;
}

/**
 * Mechanism A only ever asserts a mapping that exists — a canonical brand or
 * model with a non-null `tdr_*_id`. There is no live-observable "Mechanism A
 * looked at this legacy ID and could not match it" state: the release
 * builder's own unmatched/ambiguous candidates (tdr_bridge/release.py's
 * `review` list) are never written to Supabase — they exist only in the
 * release JSON artifact. Rows with a null tdr id are therefore skipped
 * entirely, not turned into an "unmatched" assertion; skip them.
 */
export function assertionsFromMechanismABrands(rows: MechanismABrandRow[]): ExternalIdentityAssertion[] {
  return rows
    .filter((row): row is MechanismABrandRow & { tdr_brand_id: string } => Boolean(row.tdr_brand_id))
    .map((row) => ({
      namespace: "legacy_tdr" as const,
      externalEntityType: "brand" as const,
      externalId: row.tdr_brand_id,
      canonicalEntityType: "brand" as const,
      canonicalId: row.canonical_id,
      mappingState: "resolved" as const,
      trustLevel: "derived" as const,
      provenance: {
        mechanism: "mechanism_a_release_crosswalk" as const,
        matchBasis:
          "release-build crosswalk (name/alias match or reviewed override in integration_data/crosswalk_overrides.json; exact method is not persisted past release build into the serving projection)",
        verifiedBy: null,
        verifiedAt: null,
        notes: null,
      },
    }));
}

export function assertionsFromMechanismAModels(rows: MechanismAModelRow[]): ExternalIdentityAssertion[] {
  return rows
    .filter((row): row is MechanismAModelRow & { tdr_model_id: string } => Boolean(row.tdr_model_id))
    .map((row) => ({
      namespace: "legacy_tdr" as const,
      externalEntityType: "model" as const,
      externalId: row.tdr_model_id,
      canonicalEntityType: "model" as const,
      canonicalId: row.canonical_id,
      mappingState: "resolved" as const,
      trustLevel: "derived" as const,
      provenance: {
        mechanism: "mechanism_a_release_crosswalk" as const,
        matchBasis:
          "release-build crosswalk (name/alias match or reviewed override in integration_data/crosswalk_overrides.json; exact method is not persisted past release build into the serving projection)",
        verifiedBy: null,
        verifiedAt: null,
        notes: null,
      },
    }));
}

// ---------------------------------------------------------------------------
// Mechanism B — canonical_object_map, read live from Supabase. Column names
// and check-constraint values match
// supabase/migration_v12_canonical_write_pipeline.sql exactly.
// ---------------------------------------------------------------------------

export type MechanismBSourceTable = "brands" | "models" | "model_powertrains" | "trims";
export type MechanismBStatus = "verified" | "ambiguous" | "unmatched" | "retired";

export interface MechanismBRow {
  source_table: MechanismBSourceTable;
  source_id: string;
  canonical_entity_type: CanonicalEntityType;
  canonical_id: string | null;
  status: MechanismBStatus;
  match_basis?: unknown;
  verified_by?: string | null;
  verified_at?: string | null;
  notes?: string | null;
}

/**
 * `canonical_object_map.source_table` reuses TDR's own Supabase table names.
 * This contract normalizes them to singular external-entity-type nouns so a
 * future namespace isn't forced onto TDR's table-naming convention. Document
 * this mapping wherever it is used — see EXTERNAL_IDENTITY_CONTRACT.md.
 */
export const SOURCE_TABLE_TO_EXTERNAL_ENTITY_TYPE: Record<MechanismBSourceTable, ExternalEntityType> = {
  brands: "brand",
  models: "model",
  model_powertrains: "model_powertrain",
  trims: "trim",
};

function mappingStateForStatus(status: MechanismBStatus): MappingState {
  switch (status) {
    case "verified":
      return "resolved";
    case "ambiguous":
      return "ambiguous";
    case "retired":
      return "retired";
    case "unmatched":
    default:
      // Any status this contract does not recognize is treated as
      // "unmatched" rather than silently promoted to "resolved" — an
      // unrecognized status must never read as a resolved mapping.
      return "unmatched";
  }
}

function trustLevelForStatus(status: MechanismBStatus): TrustLevel {
  // Only an explicit 'verified' status carries verified trust. Every other
  // status — including any future status this contract does not yet know
  // about — carries none. This is the write-authority gate's own rule
  // (lib/canonical-write-shadow.ts checks status === 'verified' exactly),
  // mirrored here rather than reinterpreted.
  return status === "verified" ? "verified" : "none";
}

function describeMatchBasis(matchBasis: unknown): string | null {
  if (matchBasis === undefined || matchBasis === null) return null;
  if (typeof matchBasis === "string") return matchBasis || null;
  try {
    const text = JSON.stringify(matchBasis);
    return text && text !== "{}" ? text : null;
  } catch {
    return null;
  }
}

export function assertionFromMechanismBRow(row: MechanismBRow): ExternalIdentityAssertion {
  const externalEntityType = SOURCE_TABLE_TO_EXTERNAL_ENTITY_TYPE[row.source_table];
  if (!externalEntityType) {
    throw new Error(`mechanism B: unrecognized source_table "${row.source_table}"`);
  }
  const mappingState = mappingStateForStatus(row.status);
  const trustLevel = trustLevelForStatus(row.status);
  return {
    namespace: "legacy_tdr",
    externalEntityType,
    externalId: row.source_id,
    canonicalEntityType: row.canonical_entity_type,
    // Passed through as-is, independent of mappingState/trustLevel above —
    // an unmatched/ambiguous/retired row is never reinterpreted as
    // "resolved to null"; its canonicalId is just data, its mappingState
    // governs classification.
    canonicalId: row.canonical_id,
    mappingState,
    trustLevel,
    provenance: {
      mechanism: "mechanism_b_canonical_object_map",
      matchBasis: describeMatchBasis(row.match_basis),
      verifiedBy: row.verified_by ?? null,
      verifiedAt: row.verified_at ?? null,
      notes: row.notes ?? null,
    },
  };
}

export function assertionsFromMechanismBRows(rows: MechanismBRow[]): ExternalIdentityAssertion[] {
  return rows.map(assertionFromMechanismBRow);
}
