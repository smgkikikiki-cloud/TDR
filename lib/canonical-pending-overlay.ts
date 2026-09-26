import type { TrimEditorField } from "./trim-editor-fields.ts";
import {
  displayValue,
  type EditableField,
  type NormalizedTrim,
  type SpecFactValueState,
} from "./trim-editor-state.ts";

/**
 * The canonical writer is deliberately asynchronous: an Admin save first lands
 * durably in canonical_input_batches and GitHub/release publication follows in
 * the background. The editor, however, must behave like an editor -- once the
 * queue insert succeeds, a refresh must show what the admin just saved rather
 * than waiting for the next canonical release.
 *
 * This module is the read-through layer for that gap. It overlays non-failed
 * queued/staged batches on top of the active release in memory. Nothing here
 * mutates canonical projection tables or weakens the canonical writer; once a
 * batch is represented by the active release, the overlay naturally disappears.
 */

export type PendingCanonicalBatch = {
  status?: string | null;
  created_at?: string | null;
  payload?: unknown;
};

export type PendingOverlayModel = {
  name_en?: string | null;
  name_th?: string | null;
  body_type?: string | null;
};

export type PendingOverlayGeneration = {
  code?: string | null;
  segment?: string | null;
  launched?: string | null;
  ended?: string | null;
  seats?: number | null;
  payload?: Record<string, unknown> | null;
};

export type PendingOverlayTrim = {
  canonicalId: string;
  name: string;
  powertrain: string;
  sourceRefs: Record<string, string[]>;
  editor: NormalizedTrim;
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object" && !Array.isArray(row))
    : [];
}

function sourceRefs(value: unknown): Record<string, string[]> {
  const refs: Record<string, string[]> = {};
  for (const [kind, urls] of Object.entries(record(value))) {
    if (Array.isArray(urls)) refs[kind] = urls.map(String);
  }
  return refs;
}

function valueState(value: unknown): SpecFactValueState {
  const state = String(value || "").toUpperCase();
  if (state === "KNOWN" || state === "NOT_AVAILABLE" || state === "NOT_APPLICABLE") return state;
  return "UNKNOWN";
}

function editableFromTrim(raw: unknown): EditableField {
  if (raw === null || raw === undefined || raw === "" || raw === "UNKNOWN") {
    return { value: "", valueState: "UNKNOWN", qualifiers: {}, origin: "none" };
  }
  return { value: displayValue(raw), valueState: "KNOWN", qualifiers: {}, origin: "trim" };
}

function editableFromSpec(payload: Record<string, unknown>): EditableField {
  const state = valueState(payload.value_state);
  const qualifiers: Record<string, string> = {};
  for (const [key, raw] of Object.entries(record(payload.qualifiers))) {
    if (raw === null || raw === undefined || raw === "") continue;
    qualifiers[key] = String(raw);
  }
  return {
    value: state === "KNOWN" ? displayValue(payload.value) : "",
    valueState: state,
    qualifiers,
    origin: "spec",
  };
}

function time(value: unknown): number {
  const parsed = Date.parse(String(value || ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

/** A published batch only needs an overlay during the tiny window where its
 * batch status has advanced but the active-release projection has not. Any
 * non-terminal batch remains authoritative for the editor until publication. */
export function batchNeedsOptimisticOverlay(
  batch: PendingCanonicalBatch,
  activeReleaseCreatedAt?: string | null,
): boolean {
  const status = String(batch.status || "").toUpperCase();
  if (status === "FAILED" || status === "REJECTED" || status === "CANCELLED") return false;
  if (status !== "PUBLISHED") return true;
  const releaseTime = time(activeReleaseCreatedAt);
  const batchTime = time(batch.created_at);
  return Boolean(batchTime && releaseTime && batchTime > releaseTime);
}

/**
 * Overlay Admin input batches in submission order so the newest save wins.
 * Only commands that address this model or one of its existing trims are
 * considered; unrelated queue traffic is ignored even though the caller reads
 * a small shared batch window.
 */
export function applyPendingCanonicalBatches(args: {
  modelId: string;
  activeReleaseCreatedAt?: string | null;
  model: PendingOverlayModel;
  generation: PendingOverlayGeneration | null;
  trims: PendingOverlayTrim[];
  fields: TrimEditorField[];
  batches: PendingCanonicalBatch[];
}): void {
  const byTrimId = new Map(args.trims.map((trim) => [trim.canonicalId, trim]));
  const byTrimField = new Map<string, TrimEditorField>();
  const bySpecKey = new Map<string, TrimEditorField>();
  for (const field of args.fields) {
    if (field.targets.trimField) byTrimField.set(field.targets.trimField, field);
    if (field.targets.specKey) bySpecKey.set(field.targets.specKey, field);
  }

  const batches = [...args.batches]
    .filter((batch) => batchNeedsOptimisticOverlay(batch, args.activeReleaseCreatedAt))
    .sort((a, b) => time(a.created_at) - time(b.created_at));

  for (const batch of batches) {
    const payload = record(batch.payload);
    for (const command of records(payload.commands)) {
      const operation = String(command.operation || "").toUpperCase();
      const commandPayload = record(command.payload);

      if (operation === "UPSERT_MODEL_BUNDLE" && String(command.canonical_id || "") === args.modelId) {
        const modelPatch = record(commandPayload.model);
        if (Object.hasOwn(modelPatch, "name_en")) args.model.name_en = String(modelPatch.name_en || "");
        if (Object.hasOwn(modelPatch, "name_th")) args.model.name_th = String(modelPatch.name_th || "");
        if (Object.hasOwn(modelPatch, "body_type")) args.model.body_type = String(modelPatch.body_type || "") || null;

        const generationPatch = record(commandPayload.generation);
        if (args.generation && (!generationPatch.code || String(generationPatch.code) === String(args.generation.code || ""))) {
          if (Object.hasOwn(generationPatch, "segment")) args.generation.segment = String(generationPatch.segment || "") || null;
          if (Object.hasOwn(generationPatch, "launched")) args.generation.launched = String(generationPatch.launched || "") || null;
          if (Object.hasOwn(generationPatch, "ended")) args.generation.ended = String(generationPatch.ended || "") || null;
          if (Object.hasOwn(generationPatch, "seats")) {
            const seats = Number(generationPatch.seats);
            args.generation.seats = Number.isFinite(seats) ? seats : null;
          }
        }

        for (const trimPatch of records(commandPayload.trims)) {
          const trimId = String(trimPatch.canonical_id || "");
          const trim = byTrimId.get(trimId);
          // New trims have no canonical_id until the canonical writer derives
          // one. Existing-trim edits are the latency-sensitive path here; the
          // create flow already waits for read-back by (name,powertrain).
          if (!trim) continue;

          if (Object.hasOwn(trimPatch, "source_refs")) {
            trim.sourceRefs = sourceRefs(trimPatch.source_refs);
            trim.editor.sourceRefs = trim.sourceRefs;
          }

          for (const [column, field] of byTrimField) {
            if (!Object.hasOwn(trimPatch, column)) continue;
            const raw = trimPatch[column];
            trim.editor.marketTrimFields[column] = raw;
            trim.editor.editableSpecs[field.key] = editableFromTrim(raw);
            if (column === "name") {
              trim.name = String(raw || "");
              trim.editor.name = trim.name;
            } else if (column === "powertrain") {
              trim.powertrain = String(raw || "");
              trim.editor.powertrain = trim.powertrain;
            }
          }
        }
        continue;
      }

      if (operation === "APPEND_SPEC") {
        const trimId = String(commandPayload.trim_id || command.canonical_id || "");
        const trim = byTrimId.get(trimId);
        const field = bySpecKey.get(String(commandPayload.field_key || ""));
        if (!trim || !field) continue;
        trim.editor.editableSpecs[field.key] = editableFromSpec(commandPayload);
      }
    }
  }
}
