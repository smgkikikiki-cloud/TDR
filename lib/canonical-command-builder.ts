/**
 * Reusable, server-side compiler from a structured admin edit intent to a
 * canonical Vehicle Master batch payload (schema_version 1, source.kind
 * ADMIN, commands[]) — the exact same contract app/admin/input-actions.ts's
 * Advanced JSON textarea produces, and that vehreg/input_pipeline.py's
 * CanonicalInputPipeline validates against.
 *
 * This module intentionally has zero "@/" alias imports and touches no
 * network/filesystem/Next.js API, so scripts/check-vehicle-editor.ts can
 * import and execute it directly (same convention the rest of the repo's
 * scripts/check-*.ts tests rely on for testing outside a bundler).
 *
 * It never writes anywhere itself — callers hand the returned payload to
 * lib/canonical-input-queue.ts's enqueueCanonicalInputBatch, which is the
 * one place with Supabase/admin-auth access.
 */

export type CanonicalCommand = Record<string, unknown>;

export type CanonicalBatchPayload = {
  schema_version: 1;
  batch_id: string;
  year: number;
  submitted_at: string;
  source: { kind: string; ref?: string };
  reason: string;
  commands: CanonicalCommand[];
};

export type DiffRow = {
  field: string;
  label: string;
  current: unknown;
  proposed: unknown;
  changed: boolean;
};

export type EvidenceKind = "ADMIN" | "OEM" | "MEDIA";

export type Evidence = {
  /** What kind of source backs this edit -- shown in the diff/review UI and
   * used to decide whether a source_ref URL is required. This is provenance
   * metadata, not the batch's submission channel. */
  sourceKind: EvidenceKind;
  sourceRef?: string;
  reviewedAt: string; // YYYY-MM-DD, the day the editor actually looked
};

function normalizeForCompare(value: unknown): string {
  if (value === undefined || value === null || value === "") return "";
  return JSON.stringify(value);
}

/**
 * lib/canonical-input-queue.ts's enqueueCanonicalInputBatch (the review-queue
 * helper retail-lifecycle-actions.ts and trim-retail-lifecycle-actions.ts
 * already use, and the one every batch this module builds goes through)
 * requires source.kind === "ADMIN": a human editor submitted this batch,
 * whatever kind of evidence backs it. The evidence's own provenance (OEM
 * page, media, or an admin note with no URL) is recorded as source.ref plus
 * a prefix on the reason text, matching the ECO review path's
 * "HUMAN-reviewed ECO MarketTrim: ..." convention in eco-trim-actions.ts.
 */
export function evidenceReasonPrefix(evidence: Evidence): string {
  return evidence.sourceKind === "ADMIN" ? "" : `[${evidence.sourceKind} evidence] `;
}

/**
 * Only fields present as own keys of `patch` are considered "touched" by the
 * admin — this is what keeps untouched sibling fields out of the diff and,
 * downstream, out of the emitted command (UPSERT_MODEL_BUNDLE merges patches
 * with dict.update(), so a field this function omits is never overwritten).
 */
export function diffPatch(
  current: Record<string, unknown>,
  patch: Record<string, unknown>,
  labels: Record<string, string>,
): DiffRow[] {
  return Object.keys(patch).map((field) => {
    const proposed = patch[field];
    const currentValue = current[field] ?? null;
    return {
      field,
      label: labels[field] || field,
      current: currentValue,
      proposed,
      changed: normalizeForCompare(currentValue) !== normalizeForCompare(proposed),
    };
  });
}

export function evidenceSource(evidence: Evidence): { kind: string; ref?: string } {
  return { kind: "ADMIN", ref: evidence.sourceRef || undefined };
}

export type ModelGenerationEditArgs = {
  batchId: string;
  year: number;
  submittedAt: string;
  reason: string;
  evidence: Evidence;
  canonicalModelId: string;
  brand: { id: string; nameEn: string; nameTh?: string };
  /** Generation code is never user-editable here: it is part of generation_id
   * (see vehreg/canonical_write.py's _upsert_model_bundle), so re-submitting
   * anything but the current code would silently fork a new generation
   * identity instead of editing the existing one. */
  generationCode: string;
  modelPatch: { name_en?: string; name_th?: string; body_type?: string };
  generationPatch: { segment?: string; seats?: number; launched?: string; ended?: string };
};

export function buildModelGenerationBatch(args: ModelGenerationEditArgs): {
  payload: CanonicalBatchPayload;
  diff: DiffRow[];
} {
  const commandPayload: Record<string, unknown> = {
    brand: { id: args.brand.id, name_en: args.brand.nameEn, ...(args.brand.nameTh ? { name_th: args.brand.nameTh } : {}) },
    model: args.modelPatch,
    generation: { code: args.generationCode, ...args.generationPatch },
  };
  return {
    payload: {
      schema_version: 1,
      batch_id: args.batchId,
      year: args.year,
      submitted_at: args.submittedAt,
      source: evidenceSource(args.evidence),
      reason: evidenceReasonPrefix(args.evidence) + args.reason,
      commands: [{ operation: "UPSERT_MODEL_BUNDLE", canonical_id: args.canonicalModelId, payload: commandPayload }],
    },
    diff: [],
  };
}

/**
 * Optional fields are three-state, not two: a key absent from this object
 * means "untouched, keep whatever the canonical writer already has" (dict
 * .update() semantics in vehreg/canonical_write.py never sees the key at
 * all); a key present with a real value means "set it"; a key present with
 * `null` (numeric fields) or the field's own canonical empty string (text
 * fields; `"UNKNOWN"` for the drivetrain enum) means "explicitly clear it" --
 * still an ordinary dict.update() overwrite, just to the field's cleared
 * representation instead of a new value. `name` and `powertrain` are
 * required MarketTrim identity (vehreg/entities.py's MarketTrim.validate())
 * and so are never optional/clearable here.
 */
export type MarketTrimFields = {
  name: string;
  powertrain: string;
  drivetrain?: string;
  engine_code?: string;
  engine_cc?: number | null;
  battery_kwh?: number | null;
  transmission?: string;
  seats?: number | null;
  length_mm?: number | null;
  width_mm?: number | null;
  height_mm?: number | null;
  wheelbase_mm?: number | null;
  tire_front?: string;
  tire_rear?: string;
  wheel_front?: string;
  wheel_rear?: string;
  notes?: string;
};

export type MarketTrimEditArgs = {
  batchId: string;
  year: number;
  submittedAt: string;
  reason: string;
  evidence: Evidence;
  canonicalModelId: string;
  brand: { id: string; nameEn: string; nameTh?: string };
  generationCode: string;
  /** Present when editing an existing MarketTrim; absent when creating one. */
  existingTrimId?: string;
  trim: MarketTrimFields;
  sourceRefs?: Record<string, string[]>;
};

export function buildMarketTrimBatch(args: MarketTrimEditArgs): {
  payload: CanonicalBatchPayload;
} {
  const trimPayload: Record<string, unknown> = {
    ...(args.existingTrimId ? { canonical_id: args.existingTrimId } : {}),
    ...args.trim,
    ...(args.sourceRefs ? { source_refs: args.sourceRefs } : {}),
  };
  return {
    payload: {
      schema_version: 1,
      batch_id: args.batchId,
      year: args.year,
      submitted_at: args.submittedAt,
      source: evidenceSource(args.evidence),
      reason: evidenceReasonPrefix(args.evidence) + args.reason,
      commands: [{
        operation: "UPSERT_MODEL_BUNDLE",
        canonical_id: args.canonicalModelId,
        payload: {
          brand: { id: args.brand.id, name_en: args.brand.nameEn, ...(args.brand.nameTh ? { name_th: args.brand.nameTh } : {}) },
          model: {},
          generation: { code: args.generationCode },
          variants: [],
          trims: [trimPayload],
        },
      }],
    },
  };
}

export type SpecFactValueState = "KNOWN" | "UNKNOWN" | "NOT_AVAILABLE" | "NOT_APPLICABLE";
export type SpecFactVerification = "VERIFIED" | "PROVISIONAL";

/**
 * One field's worth of a spec-draft edit session. A whole vehicle-spec draft
 * (drivetrain, power, torque, battery, dimensions, ...) is just an array of
 * these compiled into ONE batch by buildSpecDraftBatch -- one field per
 * APPEND_SPEC command, never a "replace all specs" operation.
 */
export type SpecDraftEntry = {
  fieldKey: string;
  labelForDiff: string;
  valueState: SpecFactValueState;
  /** Must be null unless valueState is KNOWN (vehreg SpecFieldDefinition.validate_value). */
  value: string | number | boolean | string[] | null;
  unit: string;
  qualifiers?: Record<string, string>;
  observedAt?: string;
  verificationStatus?: SpecFactVerification;
  /** Per-field evidence override. Falls back to the draft's default evidence
   * so the common case -- one source backs every field in the session --
   * never requires retyping the same URL/date per field. */
  evidence?: Evidence;
};

export type SpecDraftBatchArgs = {
  batchId: string;
  year: number;
  submittedAt: string;
  reason: string;
  /** Draft-level default: used for the batch's own source.ref, and for any
   * entry that does not carry its own evidence override. */
  evidence: Evidence;
  trimId: string;
  entries: SpecDraftEntry[];
};

function specFactPayload(trimId: string, entry: SpecDraftEntry, fallbackEvidence: Evidence): Record<string, unknown> {
  const evidence = entry.evidence || fallbackEvidence;
  return {
    field_key: entry.fieldKey,
    value_state: entry.valueState,
    value: entry.valueState === "KNOWN" ? entry.value : null,
    unit: entry.valueState === "KNOWN" ? entry.unit : "",
    ...(entry.qualifiers && Object.keys(entry.qualifiers).length ? { qualifiers: entry.qualifiers } : {}),
    observed_at: entry.observedAt || evidence.reviewedAt,
    verification_status: entry.verificationStatus || "VERIFIED",
    source: evidence.sourceKind.toLowerCase(),
    ...(evidence.sourceRef ? { source_ref: evidence.sourceRef } : {}),
  };
}

/**
 * Compiles a whole spec-editing session into ONE canonical batch: one
 * APPEND_SPEC command per changed field, nothing for fields the admin never
 * touched (they simply never became a SpecDraftEntry). This is the single
 * place "one draft -> one review -> one queued batch" is enforced for specs.
 */
export function buildSpecDraftBatch(args: SpecDraftBatchArgs): { payload: CanonicalBatchPayload } {
  if (!args.entries.length) throw new Error("a spec draft needs at least one field before it can be queued");
  const commands = args.entries.map((entry) => ({
    operation: "APPEND_SPEC",
    canonical_id: args.trimId,
    payload: specFactPayload(args.trimId, entry, args.evidence),
  }));
  return {
    payload: {
      schema_version: 1,
      batch_id: args.batchId,
      year: args.year,
      submitted_at: args.submittedAt,
      source: evidenceSource(args.evidence),
      reason: evidenceReasonPrefix(args.evidence) + args.reason,
      commands,
    },
  };
}

/** Diff for a spec draft: current vs proposed {value_state, value} per field,
 * reusing diffPatch's JSON-equality comparison (works fine on composite
 * values, not just scalars). */
export function diffSpecDraft(
  currentByField: Record<string, { value_state: string; value: unknown }>,
  entries: SpecDraftEntry[],
): DiffRow[] {
  const current: Record<string, unknown> = {};
  const patch: Record<string, unknown> = {};
  const labels: Record<string, string> = {};
  for (const entry of entries) {
    const existing = currentByField[entry.fieldKey];
    current[entry.fieldKey] = existing ? { value_state: existing.value_state, value: existing.value } : { value_state: "UNKNOWN", value: null };
    patch[entry.fieldKey] = { value_state: entry.valueState, value: entry.valueState === "KNOWN" ? entry.value : null };
    labels[entry.fieldKey] = entry.labelForDiff;
  }
  return diffPatch(current, patch, labels);
}

export type SourceRefEdit = { kind: string; url: string };

/**
 * Compiles structured "remove these, add these" source-ref edits into the
 * same {kind: [url, ...]} shape MarketTrim.source_refs already uses (see
 * vehreg/entities.py's MarketTrim.source_refs) -- the routine editing UI
 * never needs to know or reproduce that shape as raw JSON.
 */
export function applySourceRefEdits(
  existing: Record<string, string[]>,
  edits: { remove: SourceRefEdit[]; add: SourceRefEdit[] },
): Record<string, string[]> {
  const result: Record<string, string[]> = {};
  for (const [kind, urls] of Object.entries(existing || {})) {
    const kept = urls.filter((url) => !edits.remove.some((r) => r.kind === kind && r.url === url));
    if (kept.length) result[kind] = [...kept];
  }
  for (const { kind, url } of edits.add) {
    if (!kind || !url) continue;
    const bucket = result[kind] || (result[kind] = []);
    if (!bucket.includes(url)) bucket.push(url);
  }
  return result;
}

export function normalizedTrimName(value: string): string {
  return String(value || "")
    .normalize("NFKC")
    .toLocaleLowerCase("en-US")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}

export type MarketTrimIdentity = { canonicalId: string; generationId: string; name: string; powertrain: string };

/** Same identity rule the ECO review path already enforces
 * (app/admin/eco-trim-actions.ts): same generation + same powertrain + same
 * normalized name is the same retail trim. Never auto-merge — this only
 * flags the collision so a human decides. */
export function findDuplicateMarketTrim(
  existing: MarketTrimIdentity[],
  candidate: { generationId: string; name: string; powertrain: string; excludeCanonicalId?: string },
): MarketTrimIdentity | null {
  const wantedName = normalizedTrimName(candidate.name);
  const wantedPowertrain = String(candidate.powertrain || "").toUpperCase();
  return existing.find((row) =>
    row.canonicalId !== candidate.excludeCanonicalId
    && row.generationId === candidate.generationId
    && String(row.powertrain || "").toUpperCase() === wantedPowertrain
    && normalizedTrimName(row.name) === wantedName) || null;
}

/** Stale-edit protection: the editor page carries the release_id it was
 * rendered against; at prepare/confirm time this is compared with the
 * release_id the target row currently carries. A mismatch means another
 * canonical release activated while the page was open, so the edit must
 * fail closed rather than silently apply against state the admin never saw. */
export function isStaleRelease(pageReleaseId: string, liveReleaseId: string): boolean {
  return Boolean(pageReleaseId) && Boolean(liveReleaseId) && pageReleaseId !== liveReleaseId;
}
