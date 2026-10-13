/** Vehicle DB v3 Phase 1 structural slice. Pure planner + transaction contract.
 * No HTTP/Supabase adapter, browser route, legacy queue, or price RPC is provided.
 * A server supplies authenticated permissions and a serializable store. The only
 * shipped store is the test double. See STRUCTURAL_IDENTITY_WRITER.md for DB gates. */
import { createHash } from "node:crypto";
import { canonicalJson } from "./specs.ts";
import { facetValues, checkBodySegment } from "./taxonomy.ts";
import type { ActorKind } from "./price-writer.ts";
import { normalizeIceRegType } from "../ice-scoped-crosswalk.ts";

export type Row = Record<string, any>;
export type Entity = "vehicle_brands" | "vehicle_models" | "ice_model_crosswalk_scoped";
export type Evidence = { granularity: "MODEL" | "MODEL_REGISTRATION_CLASS" | "TRIM" | "UNCERTAIN"; model_name: string; references: string[] };
export type Intent = {
  operation: "CREATE_BRAND" | "CREATE_MODEL_BASIC" | "UPDATE_MODEL_ALIAS" | "LINK_ICE_MODEL_GROUP_BY_REG_TYPE";
  canonical_id?: string; brand_id?: string; name_en?: string; aliases?: string[];
  expected_revision: number;
  identity_evidence?: Evidence;
  model_group_id?: string; reg_type_scope?: string; master_version?: string;
  decision_ref?: string; source_hash?: string;
};
export type BatchMetadata = { batch_id: string; reason: string; source_ref: string; observed_at: string };
export type Batch = BatchMetadata & { intents: Intent[]; raw_evidence?: Row };
export type Scope = { model_group_id: string; reg_type_scope: string; master_version: string;
  frozen_status?: "APPROVED" | "EXCLUDED"; frozen_target_id?: string | null; decision_ref?: string; source_hash?: string };
export type Snapshot = {
  vehicle_brands: Row[]; vehicle_models: Row[]; ice_model_crosswalk_scoped: Row[];
  ice_scopes: Scope[];
  /** Trusted, already-approved TDR classification evidence, for this exact ID.
   * Not populated from batch/raw Ice evidence or a sibling model. */
  approved_alias_equivalences?: { model_id: string; alias: string; reference: string }[];
  tdr_classifications?: { canonical_id: string; segment: string | null; body_type: string | null; cab_type?: string | null; evidence_ref: string }[];
};
export type Change = { entity_type: Entity; entity_id: string; field: string; before: Row | null; after: Row; before_revision: number; after_revision: number };
export type Hold = { index: number; code: string; detail: string };
export type Plan = { batch_hash: string; changes: Change[]; holds: Hold[]; requires_r6: boolean };
export type Principal = { actor_id: string; actor_kind: ActorKind; can_propose: boolean; can_apply_structure: boolean; r6_allowed: boolean };
/** Obtained from verified server session/job credentials, never from request JSON. */
export type Authorizer = (credential: string) => Promise<Principal>;
export type Revision = Change & { id: string; revision_id: string; topic: "catalog"; actor: string; actor_kind: ActorKind;
  batch_id: string; before_hash: string; after_hash: string; source: string; reason: string; reverts_id: string | null };
export type Result = { status: "APPLIED" | "PROPOSED" | "HELD" | "REVERTED" | "SUPPRESSED"; batch_id: string; revision_ids: string[]; proposal_id?: string; plan: Plan; replay: boolean };
export type Proposal = { id: string; kind: "STRUCTURE"; status: "OPEN" | "APPROVED" | "REJECTED"; dedupe_key: string;
  source_hash: string; batch: Batch; plan: Plan; seen_count: number; actor: string };
export interface Transaction {
  snapshot(): Snapshot;
  write(entity: Entity, id: string, row: Row): void;
  appendRevision(revision: Revision): void;
  revisions(batchId: string): Revision[];
  isReverted(revisionId: string): boolean;
  appendObservation(observation: Row): void;
  propose(proposal: Proposal): Proposal;
  proposal(id: string): Proposal | undefined;
  approveProposal(id: string, actor: string): void;
  receipt(key: string): { hash: string; result: Result } | undefined;
  saveReceipt(key: string, hash: string, result: Result): void;
}
export interface TransactionalIdentityStore {
  /** Must serialize concurrent transactions, lock/read current rows, enforce
   * uniqueness/FKs, and roll back master+observations+inbox+audit+receipt together. */
  transaction<T>(work: (tx: Transaction) => T): Promise<T>;
}
export class StructuralWriteError extends Error {}
export const structuralHash = (value: unknown): string => createHash("sha256").update(canonicalJson(value)).digest("hex");
const clone = <T>(value: T): T => structuredClone(value);
const segmentId = /^[a-z0-9]+(?:_[a-z0-9]+)*$/;
const token = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const active = (row: Row): boolean => !row.deleted_at;
/** One canonical physical key for the (Ice model group, registration class).
 * Callers retain the canonical class from this result rather than normalizing it
 * separately, so planner, store, audit and revert use the same representation. */
export function canonicalScopedLinkKey(model_group_id: string, reg_type_scope: string): {
  key: string; model_group_id: string; reg_type_scope: string;
} {
  if (typeof model_group_id !== "string" || !model_group_id.trim()) reject("INVALID_SCOPED_LINK_GROUP");
  const scope = normalizeIceRegType(reg_type_scope);
  return { key: canonicalJson([model_group_id, scope]), model_group_id, reg_type_scope: scope };
}
function adminProtectedScopedLink(row: Row): boolean {
  return row.authority === "ADMIN" || row.actor_kind === "ADMIN" || row.admin_locked === true || row.locked === true;
}
export function normalizeModelIdentity(name: string, brand = ""): string {
  let text = name.normalize("NFKC").trim().toLocaleLowerCase("en");
  const prefix = brand.normalize("NFKC").trim().toLocaleLowerCase("en");
  if (prefix && (text.startsWith(prefix + " ") || text.startsWith(prefix + ":"))) text = text.slice(prefix.length);
  // Preserve every letter/number. Never use the trim/price/series normalizer.
  return text.replace(/[^\p{L}\p{N}]/gu, "");
}
export function flattenIdentityAliases(value: unknown): string[] {
  if (typeof value === "string") return value.split(/[|,;]/).map(s => s.trim()).filter(Boolean);
  if (Array.isArray(value)) return value.flatMap(flattenIdentityAliases);
  if (value && typeof value === "object") return Object.values(value).flatMap(flattenIdentityAliases);
  return [];
}
function reject(code: string): never { throw new StructuralWriteError(code); }
function unknownFields(value: Row, allowed: string[], code: string): void {
  if (Object.keys(value).some(key => !allowed.includes(key))) reject(code);
}
function validateMetadata(batch: BatchMetadata): void {
  if (!token.test(batch.batch_id) || !batch.reason?.trim() || !batch.source_ref?.trim()
      || !batch.observed_at || !/(Z|[+-]\d\d:\d\d)$/.test(batch.observed_at) || !Number.isFinite(Date.parse(batch.observed_at))) reject("INVALID_BATCH_METADATA");
}
function validateBatch(batch: Batch): void {
  if (!batch || typeof batch !== "object") reject("INVALID_BATCH");
  unknownFields(batch, ["batch_id", "reason", "source_ref", "observed_at", "intents", "raw_evidence"], "UNKNOWN_BATCH_FIELD");
  validateMetadata(batch);
  if (!Array.isArray(batch.intents) || !batch.intents.length || batch.intents.length > 500) reject("INVALID_BATCH");
}
function aliases(raw: unknown): string[] {
  if (raw === undefined) return [];
  if (!Array.isArray(raw) || raw.some(s => typeof s !== "string" || !s.trim())) reject("INVALID_ALIAS_SET");
  return [...new Set((raw as string[]).map(s => s.trim()))].sort();
}
function names(row: Row, brand: Row | undefined): Set<string> {
  return new Set([row.name_en, row.name_th, ...flattenIdentityAliases(row.aliases ?? row.payload?.aliases)]
    .filter(v => typeof v === "string" && v.trim()).map(v => normalizeModelIdentity(v, brand?.name_en || "")));
}
function assertUniqueTouched(snapshot: Snapshot, changes: Change[]): void {
  for (const change of changes) {
    if (change.entity_type === "ice_model_crosswalk_scoped" || !active(change.after)) continue;
    const row = change.after;
    const collection = snapshot[change.entity_type];
    const brand = snapshot.vehicle_brands.find(b => b.canonical_id === row.brand_id);
    const tokens = names(row, change.entity_type === "vehicle_models" ? brand : undefined);
    for (const other of collection) {
      if (other.canonical_id === row.canonical_id) continue;
      // Hidden identities still reserve names/aliases: do not recreate a historical model.
      if (other.slug === row.slug) reject("DUPLICATE_SLUG:" + row.slug);
      if (change.entity_type === "vehicle_models" && other.brand_id !== row.brand_id) continue;
      const otherNames = names(other, change.entity_type === "vehicle_models" ? brand : undefined);
      if ([...tokens].some(t => otherNames.has(t))) reject("IDENTITY_OR_ALIAS_COLLISION:" + other.canonical_id);
    }
  }
}
/** Deterministic planning. Mutates only cloned snapshots; no apply authority. */
export function planStructuralChanges(input: Snapshot, batch: Batch): Plan {
  validateBatch(batch);
  const scopedKeys = new Set<string>();
  for (const row of input.ice_model_crosswalk_scoped) {
    const key = canonicalScopedLinkKey(row.model_group_id, row.reg_type_scope).key;
    if (scopedKeys.has(key)) reject("DUPLICATE_SCOPED_LINK_KEY:" + key);
    scopedKeys.add(key);
  }
  const state = clone(input);
  const changes: Change[] = [], holds: Hold[] = [];
  const seen = new Set<string>();
  const ranks = { CREATE_BRAND: 0, CREATE_MODEL_BASIC: 1, UPDATE_MODEL_ALIAS: 2, LINK_ICE_MODEL_GROUP_BY_REG_TYPE: 3 };
  const ordered = batch.intents.map((intent, index) => ({ intent, index }))
    .sort((a, b) => (ranks[a.intent.operation] ?? 99) - (ranks[b.intent.operation] ?? 99) || a.index - b.index);
  for (const { intent: i, index } of ordered) {
    try {
      if (!i || typeof i !== "object" || !Number.isSafeInteger(i.expected_revision) || i.expected_revision < 0) reject("INVALID_INTENT");
      const fields: Record<Intent["operation"], string[]> = {
        CREATE_BRAND: ["operation", "canonical_id", "name_en", "aliases", "expected_revision"],
        CREATE_MODEL_BASIC: ["operation", "canonical_id", "brand_id", "name_en", "aliases", "expected_revision", "identity_evidence"],
        UPDATE_MODEL_ALIAS: ["operation", "canonical_id", "aliases", "expected_revision"],
        LINK_ICE_MODEL_GROUP_BY_REG_TYPE: ["operation", "canonical_id", "expected_revision", "model_group_id", "reg_type_scope", "master_version", "decision_ref", "source_hash"],
      };
      if (!fields[i.operation]) reject("UNKNOWN_OPERATION");
      unknownFields(i, fields[i.operation], "UNKNOWN_INTENT_FIELD");
      const entity: Entity = i.operation === "CREATE_BRAND" ? "vehicle_brands" :
        i.operation === "LINK_ICE_MODEL_GROUP_BY_REG_TYPE" ? "ice_model_crosswalk_scoped" : "vehicle_models";
      const scopedTarget = entity === "ice_model_crosswalk_scoped" ? canonicalScopedLinkKey(i.model_group_id || "", i.reg_type_scope || "") : null;
      const id = scopedTarget?.key ?? i.canonical_id ?? "";
      if (seen.has(entity + ":" + id)) reject("DUPLICATE_TARGET_IN_BATCH");
      seen.add(entity + ":" + id);
      const collection: Row[] = state[entity];
      const before = collection.find(row => entity === "ice_model_crosswalk_scoped" ?
        canonicalScopedLinkKey(row.model_group_id, row.reg_type_scope).key === id : row.canonical_id === id) ?? null;
      if ((before ? before.revision : 0) !== i.expected_revision) reject("STALE_REVISION_OR_DUPLICATE_ID");
      let after: Row;
      if (i.operation === "CREATE_BRAND" || i.operation === "CREATE_MODEL_BASIC") {
        if (before) reject("DUPLICATE_CANONICAL_ID");
        if (typeof i.name_en !== "string" || !i.name_en.trim()) reject("EMPTY_IDENTITY_NAME");
        if (i.operation === "CREATE_BRAND" && !segmentId.test(id)) reject("INVALID_BRAND_ID");
        if (i.operation === "CREATE_MODEL_BASIC") {
          const brand = state.vehicle_brands.find(b => b.canonical_id === i.brand_id && active(b));
          if (!brand) reject("MISSING_BRAND_FK");
          if (!id.startsWith(i.brand_id + ".") || !segmentId.test(id.slice(i.brand_id!.length + 1))) reject("INVALID_MODEL_ID");
          const evidence = i.identity_evidence;
          if (!evidence || !["MODEL", "MODEL_REGISTRATION_CLASS"].includes(evidence.granularity)
              || !Array.isArray(evidence.references) || !evidence.references.length
              || evidence.references.some(ref => typeof ref !== "string" || !ref.trim())
              || normalizeModelIdentity(evidence.model_name || "", brand.name_en) !== normalizeModelIdentity(i.name_en, brand.name_en)) reject("UNCERTAIN_MODEL_VS_TRIM_IDENTITY");
        }
        if (entity === "vehicle_models" && i.identity_evidence?.granularity === "MODEL_REGISTRATION_CLASS") {
          const brand = state.vehicle_brands.find(b => b.canonical_id === i.brand_id)!;
          const rootName = i.name_en.replace(/\s+(?:double\s*cab|single\s*cab|smart\s*cab|cab)$/i, "").trim();
          if (rootName !== i.name_en.trim()) {
            const rootKey = normalizeModelIdentity(rootName, brand.name_en);
            const parent = state.vehicle_models.find(m => m.brand_id === i.brand_id && names(m, brand).has(rootKey));
            if (parent) reject("REGISTRATION_CLASS_PARENT_ALIAS_CONFLICT:" + parent.canonical_id);
          }
        }
        after = { canonical_id: id, slug: id.replaceAll(".", "-"), name_en: i.name_en.trim(), aliases: aliases(i.aliases),
          revision: 1, deleted_at: null, payload: { id, name_en: i.name_en.trim(), aliases: aliases(i.aliases) } };
        if (entity === "vehicle_models") {
          const fact = state.tdr_classifications?.find(f => f.canonical_id === id);
          if (fact && !fact.evidence_ref?.trim()) reject("UNAPPROVED_TDR_CLASSIFICATION");
          const segment = fact?.segment ?? null, body = fact?.body_type ?? null;
          if (segment !== null && !facetValues("Segment").includes(segment)) reject("INVALID_TDR_SEGMENT");
          if (body !== null && !facetValues("BodyType").includes(body)) reject("INVALID_TDR_BODY_TYPE");
          if (body === "PICKUP" && (segment !== "F" || !fact?.cab_type)) reject("UNPROVEN_PICKUP_CLASSIFICATION");
          if (body && fact?.cab_type && checkBodySegment(body, fact.cab_type, segment ?? "UNKNOWN").length) reject("INVALID_TDR_BODY_SEGMENT");
          Object.assign(after, { brand_id: i.brand_id, identity_level: "BASIC", status: null, generation_id: null,
            segment, body_type: body, classification_evidence_ref: fact?.evidence_ref ?? null });
          Object.assign(after.payload, { brand_id: i.brand_id, identity_level: "BASIC", incomplete: true,
            body_type: body, segment, cab_type: fact?.cab_type ?? null, identity_evidence: clone(i.identity_evidence) });
        }
      } else if (i.operation === "UPDATE_MODEL_ALIAS") {
        if (!before || !active(before)) reject("UNKNOWN_OR_HIDDEN_MODEL");
        if (i.aliases === undefined) reject("ALIAS_SET_REQUIRED");
        after = { ...clone(before), aliases: aliases(i.aliases), revision: before.revision + 1,
          payload: { ...clone(before.payload || {}), aliases: aliases(i.aliases) } };
      } else {
        const scope = scopedTarget!.reg_type_scope;
        if (scope === "ALL") reject("CLASS_SCOPE_REQUIRED");
        const source = state.ice_scopes.find(s => canonicalScopedLinkKey(s.model_group_id, s.reg_type_scope).key === id && s.master_version === i.master_version);
        if (!source || !i.model_group_id || !i.decision_ref || !/^[a-f0-9]{64}$/.test(i.source_hash || "")) reject("UNKNOWN_OR_STALE_ICE_SOURCE_SCOPE");
        if (!state.vehicle_models.some(m => m.canonical_id === i.canonical_id && active(m))) reject("MISSING_MODEL_FK");
        if (before && (before.status === "APPROVED" || adminProtectedScopedLink(before))
            && before.canonical_model_id !== i.canonical_id) reject("APPROVED_TARGET_IMMUTABLE");
        if (source.source_hash && source.source_hash !== i.source_hash) reject("ICE_SOURCE_HASH_CONFLICT");
        if (source.decision_ref && source.decision_ref !== i.decision_ref) reject("FROZEN_OWNER_DECISION_REF_CONFLICT");
        if (source.frozen_status === "EXCLUDED" || (source.frozen_status === "APPROVED" && source.frozen_target_id !== i.canonical_id)) reject("FROZEN_OWNER_DECISION_CONFLICT");
        if (before && (before.master_version !== i.master_version || before.decision_ref !== i.decision_ref || before.source_hash !== i.source_hash)) reject("IMMUTABLE_SCOPE_PROVENANCE_CONFLICT");
        if (before && before.canonical_model_id === i.canonical_id
            && (before.status === "APPROVED" || adminProtectedScopedLink(before))) continue;
        after = { ...(before || {}), model_group_id: i.model_group_id, reg_type_scope: scope, master_version: i.master_version,
          canonical_model_id: i.canonical_id, pending_target_id: null, decision_ref: i.decision_ref, source_hash: i.source_hash,
          status: "APPROVED", revision: (before?.revision || 0) + 1 };
      }
      const change = { entity_type: entity, entity_id: id, field: i.operation, before: clone(before), after,
        before_revision: before?.revision || 0, after_revision: after.revision };
      changes.push(change);
      if (before) collection[collection.indexOf(before)] = after; else collection.push(after);
    } catch (error) { holds.push({ index, code: "VALIDATION_HOLD", detail: (error as Error).message }); }
  }
  try {
    assertUniqueTouched(state, changes);
    for (const change of changes.filter(c => c.entity_type === "vehicle_models")) {
      const model = change.after;
      const brand = state.vehicle_brands.find(b => b.canonical_id === model.brand_id);
      const canonical = normalizeModelIdentity(model.name_en, brand?.name_en || "");
      const prior = names(change.before || {}, brand);
      for (const alias of flattenIdentityAliases(model.aliases)) {
        const normalized = normalizeModelIdentity(alias, brand?.name_en || "");
        if (normalized === canonical || prior.has(normalized)) continue;
        const approved = state.approved_alias_equivalences?.some(e => e.model_id === model.canonical_id
          && normalizeModelIdentity(e.alias, brand?.name_en || "") === normalized && e.reference.trim());
        if (!approved) reject("UNPROVEN_ALIAS_EQUIVALENCE:" + alias);
      }
    }
  }
  catch (error) { holds.push({ index: -1, code: "COLLISION_HOLD", detail: (error as Error).message }); }
  return { batch_hash: structuralHash(batch), changes, holds,
    requires_r6: batch.intents.some(i => i.operation === "LINK_ICE_MODEL_GROUP_BY_REG_TYPE") };
}
function checkPrincipal(p: Principal, apply: boolean): void {
  if (!p.actor_id || !p.can_propose) reject("UNAUTHENTICATED_OR_FORBIDDEN");
  if (apply && (p.actor_kind !== "ADMIN" || !p.can_apply_structure)) reject("STRUCTURAL_APPLY_ADMIN_ONLY");
}
function logged(change: Change, batch: Batch, p: Principal, index: number, reverts: string | null = null): Revision {
  const id = structuralHash([batch.batch_id, index, change.entity_type, change.entity_id, reverts]);
  return { ...clone(change), id, revision_id: id, topic: "catalog", actor: p.actor_id, actor_kind: p.actor_kind,
    batch_id: batch.batch_id, source: batch.source_ref, reason: batch.reason, reverts_id: reverts,
    before_hash: structuralHash(change.before), after_hash: structuralHash(change.after) };
}
export class StructuralIdentityWriter {
  private store: TransactionalIdentityStore;
  private authorize: Authorizer;
  constructor(store: TransactionalIdentityStore, authorize: Authorizer) { this.store = store; this.authorize = authorize; }
  async submit(credential: string, batch: Batch, mode: "PROPOSE" | "APPLY"): Promise<Result> {
    if (mode !== "PROPOSE" && mode !== "APPLY") reject("INVALID_MODE");
    batch = clone(batch); // Freeze untrusted request before any asynchronous boundary.
    validateBatch(batch);
    const p = await this.authorize(credential); checkPrincipal(p, mode === "APPLY");
    validateBatch(batch);
    if (mode === "APPLY" && batch.intents.some(i => i.operation === "LINK_ICE_MODEL_GROUP_BY_REG_TYPE") && !p.r6_allowed) reject("R6_AUTHORIZATION_DENIED");
    return this.store.transaction(tx => this.execute(tx, p, batch, mode));
  }
  private execute(tx: Transaction, p: Principal, batch: Batch, mode: "PROPOSE" | "APPLY"): Result {
    const hash = structuralHash({ mode, actor: p.actor_id, batch });
    const saved = tx.receipt(batch.batch_id);
    if (saved) { if (saved.hash !== hash) reject("IDEMPOTENCY_KEY_REUSED"); return { ...clone(saved.result), replay: true }; }
    const plan = planStructuralChanges(tx.snapshot(), batch);
    const sourceHash = structuralHash({ source_ref: batch.source_ref, raw_evidence: batch.raw_evidence ?? null,
      intents: batch.intents.map(({ expected_revision: _revision, ...intent }) => intent) });
    if (mode === "APPLY" && plan.holds.length) reject("ATOMIC_VALIDATION_REJECTED:" + canonicalJson(plan.holds));
    const result: Result = { status: plan.holds.length ? "HELD" : mode === "APPLY" ? "APPLIED" : "PROPOSED",
      batch_id: batch.batch_id, revision_ids: [], plan, replay: false };
    if (mode === "APPLY" && !plan.holds.length && !plan.changes.length) {
      // Record only the idempotency receipt: no master row, observation or audit
      // revision is written for an exact same-target approved-link no-op.
      tx.saveReceipt(batch.batch_id, hash, clone(result));
      return result;
    }
    tx.appendObservation({ id: structuralHash([batch.batch_id, p.actor_id, "observation"]), run_id: batch.batch_id,
      source_kind: p.actor_kind === "ADMIN" ? "ADMIN_PANEL" : p.actor_kind === "EXCEL" ? "EXCEL" : p.actor_kind === "OFFICIAL" ? "SCRAPE" : "AGENT",
      field_key: "STRUCTURAL_IDENTITY", raw: clone(batch), source_url: batch.source_ref, content_hash: sourceHash,
      observed_at: batch.observed_at, actor: p.actor_id, actor_kind: p.actor_kind });
    if (mode === "PROPOSE") {
      const card = tx.propose({ id: structuralHash(["STRUCTURE", batch.batch_id]), kind: "STRUCTURE", status: "OPEN",
        dedupe_key: structuralHash(["STRUCTURE", batch.intents.map(i => [i.operation, i.canonical_id, i.model_group_id, i.reg_type_scope])]),
        source_hash: sourceHash, batch: clone(batch), plan: clone(plan), seen_count: 1, actor: p.actor_id });
      result.proposal_id = card.id;
      if (card.status !== "OPEN") result.status = "SUPPRESSED";
    } else {
      plan.changes.forEach((change, index) => { tx.write(change.entity_type, change.entity_id, clone(change.after));
        const entry = logged(change, batch, p, index); tx.appendRevision(entry); result.revision_ids.push(entry.id); });
    }
    tx.saveReceipt(batch.batch_id, hash, clone(result));
    return result;
  }
  async approve(credential: string, proposalId: string): Promise<Result> {
    const p = await this.authorize(credential); checkPrincipal(p, true);
    return this.store.transaction(tx => {
      const card = tx.proposal(proposalId);
      if (!card || !["OPEN", "APPROVED"].includes(card.status)) reject("PROPOSAL_NOT_OPEN");
      if (card.plan.requires_r6 && !p.r6_allowed) reject("R6_AUTHORIZATION_DENIED");
      // Recompute diff/current revisions; never execute the stored preview.
      const batch = { ...clone(card.batch), batch_id: "approve:" + proposalId.slice(0, 64) };
      const result = this.execute(tx, p, batch, "APPLY");
      if (card.status === "OPEN") tx.approveProposal(proposalId, p.actor_id);
      return result;
    });
  }
  async revert(credential: string, originalBatch: string, metadata: BatchMetadata): Promise<Result> {
    metadata = clone(metadata);
    const p = await this.authorize(credential); checkPrincipal(p, true);
    unknownFields(metadata, ["batch_id", "reason", "source_ref", "observed_at"], "UNKNOWN_REVERT_FIELD");
    validateMetadata(metadata);
    const batch: Batch = { ...clone(metadata), intents: [] };
    // Inverse targets come from immutable audit, never from request JSON.
    return this.store.transaction(tx => {
      const hash = structuralHash({ revert: originalBatch, actor: p.actor_id, batch });
      const saved = tx.receipt(batch.batch_id);
      if (saved) { if (saved.hash !== hash) reject("IDEMPOTENCY_KEY_REUSED"); return { ...clone(saved.result), replay: true }; }
      const entries = tx.revisions(originalBatch);
      if (!entries.length) reject("UNKNOWN_BATCH");
      if (entries.some(r => r.entity_type === "ice_model_crosswalk_scoped") && !p.r6_allowed) reject("R6_AUTHORIZATION_DENIED");
      if (entries.every(entry => tx.isReverted(entry.id))) {
        const result: Result = { status: "REVERTED", batch_id: batch.batch_id, revision_ids: [],
          plan: { batch_hash: hash, changes: [], holds: [], requires_r6: false }, replay: true };
        tx.saveReceipt(batch.batch_id, hash, clone(result)); return result;
      }
      if (entries.some(entry => tx.isReverted(entry.id))) reject("PARTIALLY_REVERTED_BATCH");
      const snapshot = tx.snapshot();
      const changes: Change[] = [];
      for (const entry of [...entries].reverse()) {
        const row = snapshot[entry.entity_type].find(r => entry.entity_type === "ice_model_crosswalk_scoped" ?
          canonicalScopedLinkKey(r.model_group_id, r.reg_type_scope).key === entry.entity_id : r.canonical_id === entry.entity_id);
        if (!row || row.revision !== entry.after_revision || structuralHash(row) !== entry.after_hash) reject("STALE_REVERT");
        if (entry.entity_type === "ice_model_crosswalk_scoped" && entry.before
            && (entry.before.status === "APPROVED" || adminProtectedScopedLink(entry.before))
            && entry.before.canonical_model_id !== entry.after.canonical_model_id) reject("APPROVED_TARGET_IMMUTABLE");
        const after = entry.before ? clone(entry.before) : entry.entity_type === "ice_model_crosswalk_scoped" ?
          { ...clone(row), status: "PENDING", canonical_model_id: null, pending_target_id: row.canonical_model_id } :
          { ...clone(row), deleted_at: batch.observed_at };
        after.revision = row.revision + 1;
        const change: Change = { entity_type: entry.entity_type, entity_id: entry.entity_id, field: "REVERT:" + entry.field,
          before: clone(row), after, before_revision: row.revision, after_revision: after.revision };
        snapshot[entry.entity_type][snapshot[entry.entity_type].indexOf(row)] = after;
        changes.push(change);
      }
      assertUniqueTouched(snapshot, changes);
      for (const change of changes) {
        if (change.entity_type === "vehicle_models" && active(change.after)
            && !snapshot.vehicle_brands.some(b => b.canonical_id === change.after.brand_id && active(b))) reject("REVERT_MISSING_ACTIVE_BRAND_FK");
        if (change.entity_type === "ice_model_crosswalk_scoped") {
          const link = change.after;
          const source = snapshot.ice_scopes.find(s => canonicalScopedLinkKey(s.model_group_id, s.reg_type_scope).key === change.entity_id);
          if (!source || source.frozen_status === "EXCLUDED" || (source.frozen_status === "APPROVED" && source.frozen_target_id !== link.canonical_model_id)) reject("FROZEN_OWNER_REVERT_CONFLICT");
          if (link.status === "APPROVED" && !snapshot.vehicle_models.some(m => m.canonical_id === link.canonical_model_id && active(m))) reject("REVERT_MISSING_ACTIVE_MODEL_FK");
        }
        if (!active(change.after) && change.entity_type === "vehicle_models" && snapshot.ice_model_crosswalk_scoped.some(l => l.canonical_model_id === change.entity_id && l.status === "APPROVED")) reject("REVERT_HAS_ACTIVE_ICE_DEPENDENT");
        if (!active(change.after) && change.entity_type === "vehicle_brands" && snapshot.vehicle_models.some(m => m.brand_id === change.entity_id && active(m))) reject("REVERT_HAS_ACTIVE_MODEL_DEPENDENT");
      }
      const result: Result = { status: "REVERTED", batch_id: batch.batch_id, revision_ids: [],
        plan: { batch_hash: hash, changes, holds: [], requires_r6: entries.some(e => e.entity_type === "ice_model_crosswalk_scoped") }, replay: false };
      tx.appendObservation({ id: structuralHash([batch.batch_id, p.actor_id, "revert-observation"]), run_id: batch.batch_id,
        source_kind: "ADMIN_PANEL", field_key: "STRUCTURAL_IDENTITY", raw: { ...clone(metadata), reverts_batch_id: originalBatch },
        source_url: batch.source_ref, observed_at: batch.observed_at, actor: p.actor_id, actor_kind: p.actor_kind });
      changes.forEach((change, index) => { tx.write(change.entity_type, change.entity_id, clone(change.after));
        const original = entries.find(e => e.entity_id === change.entity_id && e.entity_type === change.entity_type)!;
        const revision = logged(change, batch, p, index, original.id); tx.appendRevision(revision); result.revision_ids.push(revision.id); });
      tx.saveReceipt(batch.batch_id, hash, clone(result)); return result;
    });
  }
}
