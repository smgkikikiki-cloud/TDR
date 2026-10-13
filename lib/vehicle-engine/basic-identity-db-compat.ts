/**
 * Offline BASIC-identity boundary for the existing Structural Identity Writer.
 *
 * This module describes/serializes a future governed structural RPC call. It is
 * deliberately not a database transport and has no production write route.
 * The live v57-v64 schema cannot truthfully store the writer's BASIC rows yet.
 */
import { structuralHash, type Batch, type Intent, type Plan } from "./structural-writer.ts";

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
  batch_hash: string;
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

type JsonRecord = Record<string, unknown>;
type IntentEvidence = NonNullable<Intent["identity_evidence"]>;
type SupportedIntent =
  | { operation: "CREATE_BRAND"; canonical_id: string; name_en: string; aliases?: string[]; expected_revision: number }
  | { operation: "CREATE_MODEL_BASIC"; canonical_id: string; brand_id: string; name_en: string; aliases?: string[]; expected_revision: number; identity_evidence: IntentEvidence }
  | { operation: "UPDATE_MODEL_ALIAS"; canonical_id: string; aliases: string[]; expected_revision: number };
type OperationBinding = { operation: SupportedIntent["operation"]; entity: string; id: string; revision: number; intent: SupportedIntent };
function fail(code: string): never { throw new Error(code); }
function record(value: unknown, code: string): JsonRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) return fail(code);
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) return fail(code);
  for (const key of Reflect.ownKeys(value)) {
    if (typeof key !== "string") return fail(code);
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor || !descriptor.enumerable || descriptor.get || descriptor.set) return fail(code);
  }
  return value as JsonRecord;
}
function exactKeys(value: JsonRecord, allowed: string[], code: string): void {
  if (Object.keys(value).some(key => !allowed.includes(key))) fail(code);
}
function stringField(value: unknown, code: string): string {
  if (typeof value !== "string" || !value.trim()) return fail(code);
  return value;
}
function revisionField(value: unknown): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) return fail("INVALID_INTENT_REVISION");
  return value as number;
}
function aliasesField(value: unknown, optional: boolean): string[] {
  if (value === undefined && optional) return [];
  if (!Array.isArray(value) || value.some(alias => typeof alias !== "string" || !alias.trim())) return fail("INVALID_ALIAS_SET");
  return [...new Set((value as string[]).map(alias => alias.trim()))].sort();
}
function originalAliases(value: unknown, optional: boolean): string[] | undefined {
  aliasesField(value, optional);
  return value === undefined ? undefined : [...value as string[]];
}
function validateEvidence(value: unknown): IntentEvidence {
  const evidence = record(value, "INVALID_IDENTITY_EVIDENCE");
  exactKeys(evidence, ["granularity", "model_name", "references"], "UNKNOWN_IDENTITY_EVIDENCE_FIELD");
  if (evidence.granularity !== "MODEL" && evidence.granularity !== "MODEL_REGISTRATION_CLASS") fail("INVALID_IDENTITY_EVIDENCE_GRANULARITY");
  const modelName = stringField(evidence.model_name, "INVALID_IDENTITY_EVIDENCE_NAME");
  if (!Array.isArray(evidence.references) || evidence.references.length === 0
      || evidence.references.some(reference => typeof reference !== "string" || !reference.trim())) fail("INVALID_IDENTITY_EVIDENCE_REFERENCES");
  return { granularity: evidence.granularity, model_name: modelName, references: [...evidence.references] as string[] };
}
function validateBatchForRpc(value: Batch): { batch: JsonRecord; intents: SupportedIntent[]; bindings: OperationBinding[] } {
  const batch = record(value, "INVALID_BATCH");
  exactKeys(batch, ["batch_id", "reason", "source_ref", "observed_at", "intents", "raw_evidence"], "UNKNOWN_BATCH_FIELD");
  stringField(batch.batch_id, "INVALID_BATCH_METADATA");
  stringField(batch.reason, "INVALID_BATCH_METADATA");
  stringField(batch.source_ref, "INVALID_BATCH_METADATA");
  const observedAt = stringField(batch.observed_at, "INVALID_BATCH_METADATA");
  if (!/(Z|[+-]\d\d:\d\d)$/.test(observedAt) || !Number.isFinite(Date.parse(observedAt))) fail("INVALID_BATCH_METADATA");
  if (!Array.isArray(batch.intents) || batch.intents.length === 0 || batch.intents.length > 500) fail("INVALID_BATCH_INTENTS");

  const intents: SupportedIntent[] = [];
  const bindings: OperationBinding[] = [];
  const seen = new Set<string>();
  for (const rawIntent of batch.intents) {
    const intent = record(rawIntent, "INVALID_INTENT");
    const rawOperation = intent.operation;
    if (rawOperation === "LINK_ICE_MODEL_GROUP_BY_REG_TYPE") fail("R6_LINK_OUTSIDE_BASIC_IDENTITY_ADAPTER");
    if (rawOperation !== "CREATE_BRAND" && rawOperation !== "CREATE_MODEL_BASIC" && rawOperation !== "UPDATE_MODEL_ALIAS")
      fail("UNSUPPORTED_STRUCTURAL_RPC_OPERATION");
    const operation = rawOperation as SupportedIntent["operation"];
    const commonKeys = ["operation", "canonical_id", "expected_revision"];
    const allowed = operation === "CREATE_BRAND" ? [...commonKeys, "name_en", "aliases"]
      : operation === "CREATE_MODEL_BASIC" ? [...commonKeys, "brand_id", "name_en", "aliases", "identity_evidence"]
        : [...commonKeys, "aliases"];
    exactKeys(intent, allowed, "UNKNOWN_STRUCTURAL_INTENT_FIELD");
    const id = stringField(intent.canonical_id, "INVALID_CANONICAL_ID");
    const expectedRevision = revisionField(intent.expected_revision);
    if (operation === "CREATE_BRAND" || operation === "CREATE_MODEL_BASIC") {
      stringField(intent.name_en, "EMPTY_IDENTITY_NAME");
      aliasesField(intent.aliases, true);
    } else aliasesField(intent.aliases, false);

    if (operation === "CREATE_BRAND" && !/^[a-z0-9]+(?:_[a-z0-9]+)*$/.test(id)) fail("INVALID_BRAND_ID");
    if (operation === "CREATE_MODEL_BASIC") {
      const brandId = stringField(intent.brand_id, "INVALID_BRAND_ID");
      if (!id.startsWith(brandId + ".") || !/^[a-z0-9]+(?:_[a-z0-9]+)*$/.test(id.slice(brandId.length + 1))) fail("INVALID_MODEL_ID");
    }
    const normalizedIntent: SupportedIntent = operation === "CREATE_BRAND" ? {
      operation, canonical_id: id, name_en: intent.name_en as string,
      ...(intent.aliases === undefined ? {} : { aliases: originalAliases(intent.aliases, true) }), expected_revision: expectedRevision,
    } : operation === "CREATE_MODEL_BASIC" ? {
      operation, canonical_id: id, brand_id: intent.brand_id as string, name_en: intent.name_en as string,
      ...(intent.aliases === undefined ? {} : { aliases: originalAliases(intent.aliases, true) }), expected_revision: expectedRevision,
      identity_evidence: validateEvidence(intent.identity_evidence),
    } : {
      operation, canonical_id: id, aliases: originalAliases(intent.aliases, false)!, expected_revision: expectedRevision,
    };
    const entity = operation === "CREATE_BRAND" ? "vehicle_brands" : "vehicle_models";
    const key = `${entity}\0${id}`;
    if (seen.has(key)) fail("DUPLICATE_STRUCTURAL_TARGET");
    seen.add(key);
    intents.push(normalizedIntent);
    bindings.push({ operation, entity, id, revision: expectedRevision, intent: normalizedIntent });
  }
  return { batch, intents, bindings };
}

function plannedAfter(binding: OperationBinding, before: JsonRecord | null): JsonRecord {
  const intent = binding.intent;
  if (intent.operation === "CREATE_BRAND" || intent.operation === "CREATE_MODEL_BASIC") {
    const name = (intent.name_en as string).trim();
    const aliases = aliasesField(intent.aliases, true);
    const after: JsonRecord = { canonical_id: binding.id, slug: binding.id.replaceAll(".", "-"), name_en: name, aliases,
      revision: 1, deleted_at: null, payload: { id: binding.id, name_en: name, aliases } };
    if (intent.operation === "CREATE_MODEL_BASIC") {
      const evidence = intent.identity_evidence!;
      Object.assign(after, { brand_id: intent.brand_id, identity_level: "BASIC", status: null, generation_id: null,
        segment: null, body_type: null, classification_evidence_ref: null });
      Object.assign(after.payload as JsonRecord, { brand_id: intent.brand_id, identity_level: "BASIC", incomplete: true,
        body_type: null, segment: null, cab_type: null, identity_evidence: evidence });
    }
    return after;
  }
  if (!before) return fail("PLAN_BEFORE_ROW_REQUIRED");
  const priorPayload = before.payload == null ? {} : record(before.payload, "INVALID_PLAN_BEFORE_PAYLOAD");
  const normalizedAliases = aliasesField(intent.aliases, false);
  return { ...before, aliases: normalizedAliases, revision: binding.revision + 1,
    payload: { ...priorPayload, aliases: normalizedAliases } };
}

function verifyBatchPlan(bindings: OperationBinding[], rawPlan: Plan): Array<{ entity_type: string; entity_id: string; revision: number }> {
  const plan = record(rawPlan, "INVALID_STRUCTURAL_PLAN");
  exactKeys(plan, ["batch_hash", "changes", "holds", "requires_r6"], "UNKNOWN_STRUCTURAL_PLAN_FIELD");
  if (plan.requires_r6 !== false) fail("R6_LINK_OUTSIDE_BASIC_IDENTITY_ADAPTER");
  if (!Array.isArray(plan.holds) || plan.holds.length !== 0) fail("STRUCTURAL_PLAN_HAS_HOLDS");
  if (!Array.isArray(plan.changes) || plan.changes.length !== bindings.length) fail("PLAN_INTENT_CHANGE_COUNT_MISMATCH");

  const bindingByKey = new Map(bindings.map(binding => [`${binding.operation}\0${binding.entity}\0${binding.id}`, binding]));
  const seen = new Set<string>();
  const revisions: Array<{ entity_type: string; entity_id: string; revision: number }> = [];
  for (const rawChange of plan.changes) {
    const change = record(rawChange, "INVALID_PLAN_CHANGE");
    exactKeys(change, ["entity_type", "entity_id", "field", "before", "after", "before_revision", "after_revision"], "UNKNOWN_PLAN_CHANGE_FIELD");
    if (typeof change.entity_type !== "string" || typeof change.entity_id !== "string" || typeof change.field !== "string") fail("INVALID_PLAN_CHANGE_TARGET");
    const key = `${change.field}\0${change.entity_type}\0${change.entity_id}`;
    const binding = bindingByKey.get(key);
    if (!binding || seen.has(key)) fail("PLAN_INTENT_CHANGE_TARGET_MISMATCH");
    seen.add(key);
    if (change.before_revision !== binding.revision || change.after_revision !== binding.revision + 1) fail("PLAN_REVISION_MISMATCH");

    const isCreate = binding.operation === "CREATE_BRAND" || binding.operation === "CREATE_MODEL_BASIC";
    let before: JsonRecord | null = null;
    if (isCreate) {
      if (change.before !== null || binding.revision !== 0) fail("PLAN_CREATE_PRECONDITION_MISMATCH");
    } else {
      before = record(change.before, "PLAN_BEFORE_ROW_REQUIRED");
      if (before.canonical_id !== binding.id || before.revision !== binding.revision || before.deleted_at != null)
        fail("PLAN_BEFORE_ROW_MISMATCH");
    }
    const after = record(change.after, "INVALID_PLAN_AFTER_ROW");
    if (structuralHash(after) !== structuralHash(plannedAfter(binding, before))) fail("PLAN_AFTER_ROW_MISMATCH");
    revisions.push({ entity_type: binding.entity, entity_id: binding.id, revision: binding.revision });
  }
  if (seen.size !== bindings.length) fail("PLAN_INTENT_CHANGE_COUNT_MISMATCH");
  return revisions;
}

/** Serialize an existing writer plan as a future RPC proposal. This binds the
 * envelope to the exact Batch, verifies a one-to-one plan/change mapping and
 * checks Writer after-state semantics. It is not DB authorization or freshness;
 * the future RPC must revalidate against locked live rows. */
export function buildStructuralRpcDraftRequest(batch: Batch, plan: Plan): StructuralRpcDraftRequest {
  const rawBatch = record(batch, "INVALID_BATCH");
  const rawPlan = record(plan, "INVALID_STRUCTURAL_PLAN");
  if (rawPlan.batch_hash !== structuralHash(rawBatch)) fail("PLAN_BATCH_HASH_MISMATCH");
  const validated = validateBatchForRpc(batch);
  const expectedRevisions = verifyBatchPlan(validated.bindings, plan);
  const sourceHash = structuralHash({ source_ref: batch.source_ref, raw_evidence: batch.raw_evidence ?? null,
    intents: validated.intents.map(({ expected_revision: _revision, ...intent }) => intent) });
  const envelope = {
    rpc: "vm_apply_structural_changes" as const,
    contract_version: "basic-identity-draft-v1" as const,
    batch_hash: rawPlan.batch_hash as string,
    batch_id: batch.batch_id,
    expected_revisions: expectedRevisions,
    intents: validated.intents,
    ...(batch.raw_evidence === undefined ? {} : { raw_evidence: batch.raw_evidence }),
    provenance: { source_ref: batch.source_ref, observed_at: batch.observed_at, reason: batch.reason, source_hash: sourceHash },
  };
  return { ...envelope, payload_hash: structuralHash(envelope) };
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
