/**
 * Offline BASIC-identity boundary for the existing Structural Identity Writer.
 *
 * This module describes/serializes a future governed structural RPC call. It is
 * deliberately not a database transport and has no production write route.
 * The live v57-v64 schema cannot truthfully store the writer's BASIC rows yet.
 */
import { structuralHash, type Batch, type Change, type Plan } from "./structural-writer.ts";

export type SchemaObjectState = "DEPLOYED" | "REPOSITORY_ONLY" | "ABSENT_FROM_OWNER_SNAPSHOT";
export type BasicSchemaCapability = {
  modelStatusNullable: boolean;
  modelServedAsOfNullable: boolean;
  modelSeedReleaseNullable: boolean;
  explicitIdentityLevel: boolean;
  basicExcludedFromCatalogServing: boolean;
  structuralObservationField: boolean;
  governedStructuralRpc: boolean;
  scopedCrosswalkTable: boolean;
  revisionCanRepresentStructuralWrite: boolean;
};

/** Facts transcribed from the owner-supplied SELECT-only 2026-10-13 snapshot.
 * Not a fresh DB introspection and not an assertion that production was queried
 * by this code. Keep this separate from repo migration inventory below. */
export const OWNER_SNAPSHOT_BASIC_CAPABILITIES: BasicSchemaCapability = Object.freeze({
  modelStatusNullable: false,
  modelServedAsOfNullable: false,
  modelSeedReleaseNullable: false,
  explicitIdentityLevel: false,
  basicExcludedFromCatalogServing: false,
  structuralObservationField: false,
  governedStructuralRpc: false,
  scopedCrosswalkTable: false,
  revisionCanRepresentStructuralWrite: false,
});

export const REPOSITORY_MIGRATION_STATES = Object.freeze({
  v57: "DEPLOYED" as SchemaObjectState,
  v58: "DEPLOYED" as SchemaObjectState,
  v59: "DEPLOYED" as SchemaObjectState,
  v60: "DEPLOYED" as SchemaObjectState,
  v63: "DEPLOYED" as SchemaObjectState,
  v64: "DEPLOYED" as SchemaObjectState,
  v65: "REPOSITORY_ONLY" as SchemaObjectState,
  v66: "REPOSITORY_ONLY" as SchemaObjectState,
});

export const BASIC_SCHEMA_BLOCKERS = Object.freeze([
  "BASIC_MODEL_REQUIRED_COLUMNS_NOT_NULL",
  "BASIC_MODEL_LEVEL_AND_CATALOG_SERVING_FILTER_MISSING",
  "STRUCTURAL_OBSERVATION_FIELD_NOT_DEPLOYED",
  "GOVERNED_STRUCTURAL_RPC_NOT_DEPLOYED",
  "REVISION_LEDGER_REQUIRES_RETIRED_COMMAND_FK",
] as const);
export const SCOPED_CROSSWALK_GOVERNANCE_BLOCKER = "SCOPED_CROSSWALK_NOT_DEPLOYED" as const;

export function basicSchemaBlockers(capabilities: BasicSchemaCapability): string[] {
  const blockers: string[] = [];
  if (!capabilities.modelStatusNullable || !capabilities.modelServedAsOfNullable || !capabilities.modelSeedReleaseNullable)
    blockers.push(BASIC_SCHEMA_BLOCKERS[0]);
  if (!capabilities.explicitIdentityLevel || !capabilities.basicExcludedFromCatalogServing)
    blockers.push(BASIC_SCHEMA_BLOCKERS[1]);
  if (!capabilities.structuralObservationField) blockers.push(BASIC_SCHEMA_BLOCKERS[2]);
  if (!capabilities.governedStructuralRpc) blockers.push(BASIC_SCHEMA_BLOCKERS[3]);
  if (!capabilities.revisionCanRepresentStructuralWrite) blockers.push(BASIC_SCHEMA_BLOCKERS[4]);
  return blockers;
}

export type StructuralRpcDraftRequest = {
  rpc: "vm_apply_structural_changes";
  contract_version: "basic-identity-draft-v1";
  batch_id: string;
  payload_hash: string;
  expected_revisions: Array<{ entity_type: string; entity_id: string; revision: number }>;
  intents: Array<{
    operation: "CREATE_BRAND" | "CREATE_MODEL_BASIC" | "UPDATE_MODEL_ALIAS";
    canonical_id?: string;
    brand_id?: string;
    name_en?: string;
    aliases?: string[];
    identity_evidence?: Batch["intents"][number]["identity_evidence"];
    expected_revision: number;
  }>;
  raw_evidence?: Batch["raw_evidence"];
  provenance: { source_ref: string; observed_at: string; reason: string; source_hash: string };
};

/** Serialize an existing writer plan as one future atomic RPC envelope. The DB
 * actor/admin capability is intentionally omitted and must come from its
 * authenticated server session. R6/class links are outside this adapter. */
export function buildStructuralRpcDraftRequest(batch: Batch, plan: Plan): StructuralRpcDraftRequest {
  if (plan.requires_r6 || batch.intents.some(i => i.operation === "LINK_ICE_MODEL_GROUP_BY_REG_TYPE"))
    throw new Error("R6_LINK_OUTSIDE_BASIC_IDENTITY_ADAPTER");
  if (plan.holds.length) throw new Error("STRUCTURAL_PLAN_HAS_HOLDS");
  if (!batch.intents.length || batch.intents.some(i => !["CREATE_BRAND", "CREATE_MODEL_BASIC", "UPDATE_MODEL_ALIAS"].includes(i.operation)))
    throw new Error("UNSUPPORTED_STRUCTURAL_RPC_OPERATION");
  for (const change of plan.changes) {
    if (change.entity_type === "vehicle_models" && change.after.identity_level !== "BASIC"
        && change.field === "CREATE_MODEL_BASIC") throw new Error("BASIC_IDENTITY_LEVEL_REQUIRED");
    if (change.entity_type === "vehicle_models" && change.field === "CREATE_MODEL_BASIC"
        && (change.after.generation_id != null || change.after.status != null || change.after.segment != null
          || change.after.body_type != null || change.after.retail_price_min != null || change.after.retail_price_max != null))
      throw new Error("UNKNOWN_BASIC_FIELDS_MUST_REMAIN_NULL");
  }
  const sourceHash = structuralHash({ source_ref: batch.source_ref, raw_evidence: batch.raw_evidence ?? null,
    intents: batch.intents.map(({ expected_revision: _revision, ...intent }) => intent) });
  return {
    rpc: "vm_apply_structural_changes",
    contract_version: "basic-identity-draft-v1",
    batch_id: batch.batch_id,
    payload_hash: structuralHash({ batch, plan: plan.batch_hash }),
    expected_revisions: plan.changes.map((change: Change) => ({
      entity_type: change.entity_type, entity_id: change.entity_id, revision: change.before_revision,
    })),
    intents: batch.intents.map(intent => ({ ...intent })) as StructuralRpcDraftRequest["intents"],
    raw_evidence: batch.raw_evidence,
    provenance: { source_ref: batch.source_ref, observed_at: batch.observed_at, reason: batch.reason, source_hash: sourceHash },
  };
}

/** Interface for the future DB RPC boundary. Implementations must make exactly
 * one transaction-owning RPC call and must not split it into table mutations. */
export interface StructuralRpcTransport {
  call(name: "vm_apply_structural_changes", request: StructuralRpcDraftRequest): Promise<unknown>;
}

/** Current DB adapter stays fail-closed, independent of caller role, credential,
 * environment variables or admin flags. It can only produce a blocker report. */
export class BasicIdentityDbAdapter {
  readonly capabilities: BasicSchemaCapability;
  constructor(capabilities: BasicSchemaCapability = OWNER_SNAPSHOT_BASIC_CAPABILITIES) { this.capabilities = capabilities; }
  async submit(_transport: StructuralRpcTransport, _request: StructuralRpcDraftRequest): Promise<never> {
    const blockers = basicSchemaBlockers(this.capabilities);
    throw new Error(`BASIC_IDENTITY_DB_APPLY_DISABLED:${blockers.length ? blockers.join(",") : "GOVERNANCE_NOT_ACTIVATED"}`);
  }
}
