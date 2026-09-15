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
  type ResolvedAssertion,
  type UnresolvedAssertion,
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

const MECHANISM_A_MATCH_BASIS =
  "release-build crosswalk (name/alias match or reviewed override in integration_data/crosswalk_overrides.json; exact method is not persisted past release build into the serving projection)";

/**
 * Mechanism A only ever asserts a mapping that exists — a canonical brand or
 * model with a non-null `tdr_*_id`. There is no live-observable "Mechanism A
 * looked at this legacy ID and could not match it" state: the release
 * builder's own unmatched/ambiguous candidates (tdr_bridge/release.py's
 * `review` list) are never written to Supabase — they exist only in the
 * release JSON artifact. Rows with a null tdr id are therefore skipped
 * entirely, not turned into an "unmatched" assertion; skip them.
 *
 * Every Mechanism A assertion is, by construction, `resolved` + `derived` —
 * that is encoded in the return type, not just documented.
 */
export function assertionsFromMechanismABrands(rows: MechanismABrandRow[]): ResolvedAssertion[] {
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
        matchBasis: MECHANISM_A_MATCH_BASIS,
        verifiedBy: null,
        verifiedAt: null,
        notes: null,
      },
    }));
}

export function assertionsFromMechanismAModels(rows: MechanismAModelRow[]): ResolvedAssertion[] {
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
        matchBasis: MECHANISM_A_MATCH_BASIS,
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

/**
 * Raised when a Mechanism B row cannot become a valid assertion under this
 * contract's invariant. Fail-closed and visible: the caller must handle
 * this explicitly (see `assertionsFromMechanismBRows`, which never lets one
 * bad row silently vanish or get misclassified) rather than the adapter
 * quietly manufacturing an ID or downgrading the row to `unmatched`.
 */
export class InvalidMechanismBRowError extends Error {
  readonly row: MechanismBRow;
  readonly reason: "verified_with_null_canonical_id";

  constructor(row: MechanismBRow) {
    super(
      `mechanism B: a 'verified' row must have a non-null canonical_id ` +
        `(source_table=${row.source_table}, source_id=${row.source_id}, ` +
        `canonical_entity_type=${row.canonical_entity_type}). This is an invalid source row — ` +
        `refusing to manufacture an id or silently downgrade it to unmatched.`,
    );
    this.name = "InvalidMechanismBRowError";
    this.row = row;
    this.reason = "verified_with_null_canonical_id";
  }
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

/**
 * Convert one Mechanism B row into an assertion. Throws
 * `InvalidMechanismBRowError` for a `verified` row with a null
 * `canonical_id` — that combination cannot exist per
 * `canonical_object_map`'s own check constraint
 * (`(status = 'verified' and canonical_id is not null ...) or status <> 'verified'`
 * in `supabase/migration_v12_canonical_write_pipeline.sql`), so encountering
 * it live would mean the constraint was bypassed or the row is otherwise
 * corrupt; this adapter must not paper over that.
 */
export function assertionFromMechanismBRow(row: MechanismBRow): ExternalIdentityAssertion {
  const externalEntityType = SOURCE_TABLE_TO_EXTERNAL_ENTITY_TYPE[row.source_table];
  if (!externalEntityType) {
    throw new Error(`mechanism B: unrecognized source_table "${row.source_table}"`);
  }

  const provenance = {
    mechanism: "mechanism_b_canonical_object_map" as const,
    matchBasis: describeMatchBasis(row.match_basis),
    verifiedBy: row.verified_by ?? null,
    verifiedAt: row.verified_at ?? null,
    notes: row.notes ?? null,
  };

  if (row.status === "verified") {
    if (row.canonical_id == null) {
      throw new InvalidMechanismBRowError(row);
    }
    const resolved: ResolvedAssertion = {
      namespace: "legacy_tdr",
      externalEntityType,
      externalId: row.source_id,
      canonicalEntityType: row.canonical_entity_type,
      mappingState: "resolved",
      canonicalId: row.canonical_id,
      trustLevel: "verified",
      provenance,
    };
    return resolved;
  }

  // ambiguous | retired | unmatched (an unrecognized status also lands here
  // — see the exhaustive switch below — rather than ever being read as
  // resolved). canonicalId is passed through as-is: it is contextual/
  // historical data only (most relevant for `retired`) and never implies a
  // resolution. See UnresolvedAssertion's doc comment in types.ts.
  let mappingState: UnresolvedAssertion["mappingState"];
  switch (row.status) {
    case "ambiguous":
      mappingState = "ambiguous";
      break;
    case "retired":
      mappingState = "retired";
      break;
    case "unmatched":
      mappingState = "unmatched";
      break;
    default:
      // Any status this contract does not recognize is treated as
      // "unmatched" rather than silently promoted to "resolved".
      mappingState = "unmatched";
      break;
  }

  const unresolved: UnresolvedAssertion = {
    namespace: "legacy_tdr",
    externalEntityType,
    externalId: row.source_id,
    canonicalEntityType: row.canonical_entity_type,
    mappingState,
    canonicalId: row.canonical_id,
    trustLevel: "none",
    provenance,
  };
  return unresolved;
}

export interface InvalidMechanismBRow {
  reason: "verified_with_null_canonical_id";
  row: MechanismBRow;
}

export interface MechanismBAdapterResult {
  assertions: ExternalIdentityAssertion[];
  /**
   * Rows that could not become an assertion at all — fail-closed and
   * visible. Never silently dropped, never turned into an `unmatched`
   * assertion, never allowed to abort the whole batch (one bad row must not
   * hide every other row's result from an audit report).
   */
  invalidRows: InvalidMechanismBRow[];
}

/**
 * Batch conversion. Unlike a plain `rows.map(assertionFromMechanismBRow)`,
 * this never lets one invalid row (see `InvalidMechanismBRowError`) abort
 * the whole read — it is routed to `invalidRows` instead, deterministically,
 * in input order, and every other row is still converted normally.
 */
export function assertionsFromMechanismBRows(rows: MechanismBRow[]): MechanismBAdapterResult {
  const assertions: ExternalIdentityAssertion[] = [];
  const invalidRows: InvalidMechanismBRow[] = [];
  for (const row of rows) {
    try {
      assertions.push(assertionFromMechanismBRow(row));
    } catch (error) {
      if (error instanceof InvalidMechanismBRowError) {
        invalidRows.push({ reason: error.reason, row: error.row });
        continue;
      }
      throw error;
    }
  }
  return { assertions, invalidRows };
}
