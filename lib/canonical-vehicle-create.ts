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
  trim: { name: string; powertrain: string };
};

function brandPatch(brand: BrandChoice): Record<string, unknown> {
  if (brand.mode === "existing") return { id: brand.id };
  const patch: Record<string, unknown> = { name_en: brand.nameEn };
  if (brand.nameTh) patch.name_th = brand.nameTh;
  return patch;
}

/**
 * A whole new car: new (or existing) brand, new model, its first generation,
 * one starter trim. The model is written `incomplete: true` -- the sanctioned,
 * pre-existing escape hatch (vehreg/entities.py's Model.incomplete,
 * vehreg/catalog.py's Catalog.validate) for a nameplate whose registrations
 * are real but whose full specification (body_type, variants) is not
 * researched yet. That is exactly this case: DLT/ECO found a car, and
 * nothing here invents a body type or a spec line nobody stated. Zero
 * variants is deliberate for the same reason -- Catalog.validate skips the
 * "no variants" check for an incomplete model.
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
      trims: [{ name: args.trim.name, powertrain: args.trim.powertrain.toUpperCase() }],
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
