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

import type { TrimEditorField } from "./trim-editor-fields.ts";

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
 * Reason is optional for the editor's users but never empty in the audit
 * trail: a blank one becomes a plain statement of what happened. Nothing
 * downstream rejects an empty reason, so this is about keeping the canonical
 * revision log readable, not about gating the save.
 */
export function composeReason(evidence: Evidence, reason: string): string {
  const text = reason.trim() || "Manual edit via Canonical Vehicle Editor";
  return evidenceReasonPrefix(evidence) + text;
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
      reason: composeReason(args.evidence, args.reason),
      commands: [{ operation: "UPSERT_MODEL_BUNDLE", canonical_id: args.canonicalModelId, payload: commandPayload }],
    },
    diff: [],
  };
}

export type SpecFactValueState = "KNOWN" | "UNKNOWN" | "NOT_AVAILABLE" | "NOT_APPLICABLE";
export type SpecFactVerification = "VERIFIED" | "PROVISIONAL";

/**
 * One UI field the admin actually touched, already validated and coerced.
 * Fields left alone never become a submission, so they never produce a
 * command and never appear in the diff.
 */
export type TrimFieldSubmission = {
  /** The UI field key from lib/trim-editor-fields.ts, not a backend key. */
  key: string;
  valueState: SpecFactValueState;
  /** Must be null unless valueState is KNOWN (SpecFieldDefinition.validate_value). */
  value: string | number | boolean | null;
  /** Only the qualifiers the field's registry definition declares. */
  qualifiers?: Record<string, string>;
};

export type TrimEditArgs = {
  batchId: string;
  year: number;
  submittedAt: string;
  /** Free text; may be empty. Nothing downstream requires it -- both
   * CanonicalInputBatch.from_dict and CanonicalWriteCommand.from_dict accept
   * an empty reason -- so the editor never blocks a save on it. */
  reason: string;
  /** One source context for the whole trim edit, chosen once. */
  evidence: Evidence;
  canonicalModelId: string;
  brand: { id: string; nameEn: string; nameTh?: string };
  generationCode: string;
  /** Needed to name a brand-new trim by reference (see below). */
  generationId: string;
  /** Present when editing an existing MarketTrim; absent when creating one. */
  existingTrimId?: string;
  /** The trim's identity as it will stand after this edit. */
  identity: { name: string; powertrain: string };
  /** Every touched field, in editor order. */
  submissions: TrimFieldSubmission[];
  /** The resolved field catalog the page rendered, so the builder fans out to
   * exactly the backends the UI promised and no others. */
  fields: TrimEditorField[];
  sourceRefs?: Record<string, string[]>;
};

/**
 * The cleared representation of a MarketTrim column. Clearing is an ordinary
 * dict.update() overwrite, so each column needs the empty value its own type
 * uses: null for numbers, "UNKNOWN" for the drivetrain enum, "" for text.
 */
function clearedTrimValue(field: TrimEditorField): string | number | null {
  if (field.input === "number") return null;
  if (field.targets.trimField === "drivetrain") return "UNKNOWN";
  return "";
}

function marketTrimPatch(args: TrimEditArgs): Record<string, unknown> {
  const byKey = new Map(args.fields.map((field) => [field.key, field]));
  // name and powertrain are required MarketTrim identity (MarketTrim.validate)
  // and are always sent, whether or not this edit touched them.
  const patch: Record<string, unknown> = {
    name: args.identity.name,
    powertrain: args.identity.powertrain,
  };
  for (const submission of args.submissions) {
    const field = byKey.get(submission.key);
    if (!field?.targets.trimField) continue;
    if (field.targets.trimField === "name" || field.targets.trimField === "powertrain") continue;
    patch[field.targets.trimField] = submission.valueState === "KNOWN"
      ? submission.value : clearedTrimValue(field);
  }
  return patch;
}

/**
 * Comparable-spec facts do not carry a unit for a non-KNOWN state, and must
 * carry exactly the canonical unit when KNOWN (SpecFieldDefinition
 * .validate_value), which is why the unit comes from the resolved field rather
 * than from whatever the form posted.
 *
 * fact_id is deliberately omitted. It is derived by the canonical writer as
 * admin:{trim_id}:{field_key} once the trim is resolved -- which is the only
 * place that can compose it when the trim is being created by the very same
 * batch, and which makes re-editing a field revise its fact instead of filing
 * a second, conflicting one.
 */
function specFactPayload(
  field: TrimEditorField,
  submission: TrimFieldSubmission,
  evidence: Evidence,
  trimRef: { trimId?: string; ref?: Record<string, string> },
): Record<string, unknown> {
  const known = submission.valueState === "KNOWN";
  const qualifiers: Record<string, string> = {};
  for (const qualifier of field.qualifiers) {
    const value = submission.qualifiers?.[qualifier.key];
    if (value) qualifiers[qualifier.key] = value;
  }
  return {
    ...(trimRef.trimId ? { trim_id: trimRef.trimId } : { trim_ref: trimRef.ref }),
    field_key: field.targets.specKey,
    value_state: submission.valueState,
    value: known ? submission.value : null,
    unit: known && field.unit ? field.unit : "",
    ...(Object.keys(qualifiers).length ? { qualifiers } : {}),
    observed_at: evidence.reviewedAt,
    verification_status: "VERIFIED",
    source: evidence.sourceKind.toLowerCase(),
    source_ref: evidence.sourceRef || evidence.sourceKind.toLowerCase(),
  };
}

/**
 * Compiles ONE trim's whole edit into ONE canonical batch.
 *
 * The admin edits "this trim" once. The split into an UPSERT_MODEL_BUNDLE
 * command and N APPEND_SPEC commands is an internal detail of the canonical
 * command language, and a single UI field routinely produces both -- Seats
 * becomes MarketTrim `seats` *and* a `vehicle.seats` fact, from one box, so
 * the two representations cannot drift apart. The fan-out is entirely decided
 * by each field's `targets` in lib/trim-editor-fields.ts.
 *
 * A brand-new trim gets its specs in this same batch. It has no canonical_id
 * yet and its id is not computable outside Python (vehreg/normalize.py's
 * trim_identity folds Thai marks and strips corporate words), so rather than
 * reimplement that rule here -- two algorithms that would drift, silently
 * attaching facts to a trim that does not exist -- the spec commands name the
 * trim by reference and the writer resolves it with the same one rule. The
 * pipeline applies a batch's commands sequentially against one staged tree
 * (CanonicalInputPipeline.apply), so the trim and its facts land together or
 * not at all.
 */
export function buildTrimEditBatch(args: TrimEditArgs): { payload: CanonicalBatchPayload } {
  const byKey = new Map(args.fields.map((field) => [field.key, field]));
  const trimRow: Record<string, unknown> = {
    ...(args.existingTrimId ? { canonical_id: args.existingTrimId } : {}),
    ...marketTrimPatch(args),
    ...(args.sourceRefs ? { source_refs: args.sourceRefs } : {}),
  };

  const trimRef = args.existingTrimId
    ? { trimId: args.existingTrimId }
    : { ref: {
        generation_id: args.generationId,
        name: args.identity.name,
        powertrain: args.identity.powertrain,
      } };

  const specCommands = args.submissions
    .map((submission) => ({ submission, field: byKey.get(submission.key) }))
    .filter((row): row is { submission: TrimFieldSubmission; field: TrimEditorField } =>
      Boolean(row.field?.targets.specKey))
    .map(({ submission, field }) => ({
      operation: "APPEND_SPEC",
      ...(args.existingTrimId ? { canonical_id: args.existingTrimId } : {}),
      payload: specFactPayload(field, submission, args.evidence, trimRef),
    }));

  return {
    payload: {
      schema_version: 1,
      batch_id: args.batchId,
      year: args.year,
      submitted_at: args.submittedAt,
      source: evidenceSource(args.evidence),
      reason: composeReason(args.evidence, args.reason),
      commands: [
        {
          operation: "UPSERT_MODEL_BUNDLE",
          canonical_id: args.canonicalModelId,
          payload: {
            brand: {
              id: args.brand.id, name_en: args.brand.nameEn,
              ...(args.brand.nameTh ? { name_th: args.brand.nameTh } : {}),
            },
            model: {},
            generation: { code: args.generationCode },
            variants: [],
            trims: [trimRow],
          },
        },
        ...specCommands,
      ],
    },
  };
}

/**
 * ONE Current-vs-Proposed diff for the whole trim edit, in the order the
 * editor shows the fields. Deliberately not split into "MarketTrim changes"
 * and "comparable-spec changes": the admin changed Seats, once, and which
 * backends that lands in is not a thing they should have to reconcile in
 * review. A field whose value carries qualifiers shows them inline, so a range
 * reads "442 km (NEDC)" and losing the NEDC would be visible.
 */
export function diffTrimEdit(args: {
  current: Record<string, { value: string; valueState: string; qualifiers: Record<string, string> }>;
  submissions: TrimFieldSubmission[];
  fields: TrimEditorField[];
}): DiffRow[] {
  const byKey = new Map(args.fields.map((field) => [field.key, field]));
  return args.submissions.map((submission) => {
    const field = byKey.get(submission.key);
    const before = args.current[submission.key]
      || { value: "", valueState: "UNKNOWN", qualifiers: {} };
    const after = {
      value: submission.valueState === "KNOWN" ? String(submission.value ?? "") : "",
      valueState: submission.valueState,
      qualifiers: submission.qualifiers || {},
    };
    return {
      field: submission.key,
      label: field ? field.labelEn : submission.key,
      current: describeValue(before, field),
      proposed: describeValue(after, field),
      changed: normalizeForCompare([before.valueState, before.value, before.qualifiers])
        !== normalizeForCompare([after.valueState, after.value, after.qualifiers]),
    };
  });
}

/** "442 km (NEDC)" -- one readable cell, unit and qualifiers included. */
export function describeValue(
  state: { value: string; valueState: string; qualifiers: Record<string, string> },
  field?: TrimEditorField,
): string {
  if (state.valueState !== "KNOWN") {
    return state.valueState === "UNKNOWN" ? "—" : state.valueState.replace(/_/g, " ").toLowerCase();
  }
  const unit = field?.unit ? ` ${field.unit}` : "";
  const qualifiers = Object.entries(state.qualifiers)
    .filter(([, value]) => value)
    .map(([, value]) => value);
  return `${state.value}${unit}${qualifiers.length ? ` (${qualifiers.join(", ")})` : ""}`;
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
