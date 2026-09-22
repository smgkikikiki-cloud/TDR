/**
 * Pure builder for the ONE canonical write a brand-new car needs: a fresh
 * Brand (or an existing one, referenced by its own id), a fresh Model, its
 * first Generation, and its first MarketTrim — all in one UPSERT_MODEL_BUNDLE
 * command, so they land together or not at all (CanonicalInputPipeline.apply
 * stages a whole batch before any file is written).
 *
 * No canonical id is ever typed by a caller and none is derived here. The
 * model's canonical_id is left out of the command on purpose:
 * vehreg/canonical_write.py's _upsert_model_bundle derives
 * `{slug(brand.id or brand.name_en)}.{slug(model.name_en)}` itself, and
 * vehreg/normalize.py's own docstring says why that rule is not ported to
 * TypeScript (it folds Thai marks and strips corporate words -- "Auto"
 * alone collapses to "unnamed" -- so a second implementation here would
 * silently disagree with the real one on exactly the brand names likely to
 * appear, e.g. "Great Wall Motors"). The caller who needs the id back reads
 * it from the live serving projection once the write has published (see
 * lib/canonical-editor.ts's findCreatedModel/findCreatedTrim), the same way
 * an existing brand's id is looked up rather than guessed.
 *
 * This mirrors lib/canonical-command-builder.ts's buildTrimEditBatch, which
 * already solves the identical problem for a brand-new TRIM under an
 * existing model (referencing it by {generation_id, name, powertrain} and
 * letting the writer resolve trim_identity() itself) -- this module is the
 * missing other half: a brand-new MODEL (and optionally brand).
 */

export type CanonicalCommand = Record<string, unknown>;

export type CanonicalBatchPayload = {
  schema_version: 1;
  batch_id: string;
  year: number;
  submitted_at: string;
  source: { kind: "ADMIN"; ref?: string };
  reason: string;
  commands: CanonicalCommand[];
};

export type BrandChoice =
  | { mode: "existing"; id: string }
  | { mode: "new"; nameEn: string; nameTh?: string };

export type NewVehicleArgs = {
  batchId: string;
  year: number;
  submittedAt: string;
  reason: string;
  actor: string;
  brand: BrandChoice;
  model: { nameEn: string; nameTh?: string };
  generationCode: string;
  /** Absent for a MODEL-grain DLT/ECO find: the source names a car, never a
   *  grade or a powertrain, and MarketTrim.powertrain cannot be UNKNOWN
   *  (vehreg/entities.py) -- so a trim built from nothing that source
   *  stated would be a fabricated fact, exactly what this round forbids.
   *  Present only where the caller actually has a name and a powertrain
   *  (a TRIM-grain source, or an admin who chose to add the first grade
   *  immediately from Vehicles). */
  trim?: { name: string; powertrain: string };
};

function brandPatch(brand: BrandChoice): Record<string, unknown> {
  if (brand.mode === "existing") return { id: brand.id };
  const patch: Record<string, unknown> = { name_en: brand.nameEn };
  if (brand.nameTh) patch.name_th = brand.nameTh;
  return patch;
}

/**
 * A whole new car: new (or existing) brand, new model, its first generation,
 * and -- only when the caller actually has one -- a starter trim. The model
 * is written `incomplete: true` -- the sanctioned, pre-existing escape hatch
 * (vehreg/entities.py's Model.incomplete, vehreg/catalog.py's
 * Catalog.validate) for a nameplate whose registrations are real but whose
 * full specification (body_type, variants, and now possibly its trims too)
 * is not researched yet. That is exactly this case: DLT/ECO found a car, and
 * nothing here invents a body type, a spec line, or a grade/powertrain
 * nobody stated. Zero variants is deliberate for the same reason --
 * Catalog.validate skips the "no variants" check for an incomplete model,
 * and a model with zero trims is not checked for that at all (only trims
 * that exist are ever validated).
 */
export function buildNewVehicleBatch(args: NewVehicleArgs): { payload: CanonicalBatchPayload } {
  const modelPatch: Record<string, unknown> = { name_en: args.model.nameEn, incomplete: true };
  if (args.model.nameTh) modelPatch.name_th = args.model.nameTh;

  const command: CanonicalCommand = {
    operation: "UPSERT_MODEL_BUNDLE",
    // canonical_id deliberately omitted -- see module docstring.
    payload: {
      brand: brandPatch(args.brand),
      model: modelPatch,
      generation: { code: args.generationCode },
      variants: [],
      trims: args.trim ? [{ name: args.trim.name, powertrain: args.trim.powertrain.toUpperCase() }] : [],
    },
  };

  return {
    payload: {
      schema_version: 1,
      batch_id: args.batchId,
      year: args.year,
      submitted_at: args.submittedAt,
      source: { kind: "ADMIN" },
      reason: args.reason || "Created via TDR Admin Vehicles → + สร้างรถใหม่",
      commands: [command],
    },
  };
}

/**
 * Whether this save is even allowed to carry a trim, decided from where it
 * came from -- never from what the form happened to contain. Extracted as
 * its own pure function (rather than left inline in
 * app/admin/vehicle-create-actions.ts's server action) so it can be
 * exercised directly by scripts/check-vehicle-create.ts: a "use server"
 * action cannot run outside a Next.js request in this sandbox, and this is
 * the exact decision that action makes, not a test-only stand-in for it.
 *
 *   grain "TRIM"    -- the source published the grade itself; a trim is
 *                      required.
 *   grain "MODEL"   -- the source named only a car; a trim is never
 *                      offered here at all (see buildNewVehicleBatch's
 *                      trim? docstring), regardless of createMode.
 *   no grain at all -- a direct create from Vehicles, not from an
 *                      Exceptions row: the admin's own explicit choice
 *                      (createMode) decides.
 */
export function trimIsRequired(grain: string | null, createMode: string | null): boolean {
  if (grain === "TRIM") return true;
  if (grain === "MODEL") return false;
  return createMode === "with_trim";
}

/**
 * Reads the trim the form actually submitted, or refuses clearly when one
 * was required and is missing/invalid -- never fabricates a powertrain
 * MarketTrim.validate() would reject as UNKNOWN (vehreg/entities.py).
 * Returns undefined, never a placeholder, when no trim is required.
 */
export function resolveTrimInput(args: {
  required: boolean;
  name: string;
  powertrain: string;
  allowedPowertrains: readonly string[];
}): { name: string; powertrain: string } | undefined {
  if (!args.required) return undefined;
  const name = args.name.trim();
  if (!name) throw new Error("กรุณาใส่ชื่อรุ่นย่อย");
  const powertrain = args.powertrain.trim().toUpperCase();
  if (!powertrain) throw new Error("กรุณาเลือก powertrain");
  if (!args.allowedPowertrains.includes(powertrain)) {
    throw new Error("powertrain ไม่อยู่ใน canonical taxonomy");
  }
  return { name, powertrain };
}

export type CreatedVehicleStatusKind = "pending" | "ready" | "failed" | "readback_error";

export type CreatedVehicleStatus = {
  kind: CreatedVehicleStatusKind;
  /** The batch's own status column, or null when it could not be read. */
  status: string | null;
  /** A model/model::trim id, set only when kind is "ready". */
  target: string | null;
  /** The batch's own error text, set only when kind is "failed". */
  error: string | null;
};

//: canonical_input_batches.status's own check constraint
//: (migration_v22_unified_vehicle_input.sql): these three never progress to
//: PUBLISHED on their own -- an operator has to act, so they read the same
//: as FAILED to a caller deciding whether to keep waiting.
const BLOCKED_BATCH_STATUSES = new Set(["FAILED", "NEEDS_REVIEW", "REJECTED"]);

/**
 * The one place that decides "pending" vs "ready" vs "failed" vs
 * "readback_error" for a "+ สร้างรถใหม่" round trip -- extracted so
 * scripts/check-vehicle-create.ts can assert the FAILED case is never
 * classified as pending, which is exactly the bug this fixes (Exceptions
 * used to look only at `target`, and a FAILED batch's target is always
 * null, so it fell into the same "กำลังสร้างรถใหม่..." branch as a batch that
 * is still genuinely in flight).
 *
 *   pending         -- QUEUED/PROCESSING/STAGED, or a status this cannot
 *                       read yet: still worth waiting on.
 *   ready           -- PUBLISHED and the live projection has the target.
 *   readback_error  -- PUBLISHED but the live projection does not have it
 *                       (should not happen; distinct from "still writing"
 *                       so the owner is not told to just wait longer).
 *   failed          -- FAILED/NEEDS_REVIEW/REJECTED: this will never
 *                       become ready on its own.
 */
export function classifyCreatedVehicleStatus(args: {
  status: string | null;
  error: string | null;
  target: string | null;
}): CreatedVehicleStatus {
  if (args.status && BLOCKED_BATCH_STATUSES.has(args.status)) {
    return { kind: "failed", status: args.status, target: null, error: args.error };
  }
  if (args.status === "PUBLISHED") {
    return args.target
      ? { kind: "ready", status: args.status, target: args.target, error: null }
      : { kind: "readback_error", status: args.status, target: null, error: null };
  }
  return { kind: "pending", status: args.status, target: null, error: null };
}
