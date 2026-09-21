"use server";

/**
 * Creating a canonical vehicle that does not exist yet -- from Vehicles'
 * own "+ สร้างรถใหม่", or from an Exceptions row whose raw label matches no
 * car in the catalogue at all (not just no alias). Goes through the exact
 * same canonical queue every other admin write uses
 * (lib/canonical-input-queue.ts's enqueueCanonicalInputBatch): there is no
 * second write path here, only a new command shape
 * (lib/canonical-vehicle-create.ts's buildNewVehicleBatch) for a case the
 * existing editor never had to build -- a model that is not in the release
 * yet at all.
 *
 * Redirecting back to Exceptions afterwards cannot hand back the new car's
 * canonical_id: the write is queued, not applied, and the id itself is
 * derived server-side by the Python writer (see buildNewVehicleBatch's
 * docstring for why this file does not re-derive it). What it hands back
 * instead is everything /admin/exceptions needs to *ask* for that id once
 * the write has actually published -- the batch_key, and the exact
 * brand/model/trim identity the batch submitted -- via
 * lib/canonical-editor.ts's findCreatedBrand/findCreatedModel/findCreatedTrim.
 */
import { redirect } from "next/navigation";
import { currentEditor, isAdmin } from "@/lib/admin-auth";
import { field, requiredField, safeSubmissionId, submissionTimestamp } from "@/lib/admin-form";
import { buildNewVehicleBatch, type BrandChoice } from "@/lib/canonical-vehicle-create";
import { enqueueCanonicalInputBatch } from "@/lib/canonical-input-queue";
import { MARKET_TRIM_POWERTRAINS } from "@/lib/vehicle-taxonomy";

const DEFAULT_YEAR = 2026;

function readBrandChoice(formData: FormData): BrandChoice {
  const mode = field(formData, "brand_mode");
  if (mode === "existing") {
    const id = requiredField(formData, "brand_id", "ยี่ห้อที่มีอยู่");
    return { mode: "existing", id };
  }
  const nameEn = requiredField(formData, "brand_name_en", "ชื่อยี่ห้อ (EN)");
  const nameTh = field(formData, "brand_name_th") || undefined;
  return { mode: "new", nameEn, nameTh };
}

/** Context carried from /admin/exceptions, all optional -- present only
 *  when this save started life as "+ สร้างรถใหม่" on an exception row. */
function returnContext(formData: FormData) {
  const returnTo = field(formData, "return");
  if (returnTo !== "exceptions") return null;
  return {
    exceptionIds: field(formData, "exception_ids"),
    rawBrand: field(formData, "raw_brand"),
    rawModel: field(formData, "raw_model"),
    registrationType: field(formData, "registration_type"),
    grain: field(formData, "grain"),
  };
}

export async function createCanonicalVehicle(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await currentEditor();

  const brand = readBrandChoice(formData);
  const modelNameEn = requiredField(formData, "model_name_en", "ชื่อรุ่น (EN)");
  const modelNameTh = field(formData, "model_name_th") || undefined;
  const generationCode = requiredField(formData, "generation_code", "รหัส generation");
  const trimName = requiredField(formData, "trim_name", "ชื่อรุ่นย่อย");
  const powertrain = requiredField(formData, "trim_powertrain", "powertrain").toUpperCase();
  if (!MARKET_TRIM_POWERTRAINS.includes(powertrain as any)) {
    throw new Error("powertrain ไม่อยู่ใน canonical taxonomy");
  }

  const submissionId = safeSubmissionId(formData);
  const submittedAt = submissionTimestamp(formData);
  const { payload } = buildNewVehicleBatch({
    batchId: `admin-create-vehicle-${submissionId}`,
    year: DEFAULT_YEAR,
    submittedAt,
    reason: field(formData, "reason"),
    actor: editor?.name || "tdr-admin",
    brand,
    model: { nameEn: modelNameEn, nameTh: modelNameTh },
    generationCode,
    trim: { name: trimName, powertrain },
  });
  const { batchKey } = await enqueueCanonicalInputBatch(payload as Record<string, unknown>);

  const ctx = returnContext(formData);
  if (ctx) {
    const params = new URLSearchParams({
      created: batchKey,
      exception_ids: ctx.exceptionIds,
      raw_brand: ctx.rawBrand,
      raw_model: ctx.rawModel,
      registration_type: ctx.registrationType,
      grain: ctx.grain,
      brand_mode: brand.mode,
      brand_id: brand.mode === "existing" ? brand.id : "",
      brand_name_en: brand.mode === "new" ? brand.nameEn : "",
      model_name_en: modelNameEn,
      trim_name: trimName,
      powertrain,
    });
    redirect(`/admin/exceptions?${params.toString()}`);
  }
  redirect(`/admin/vehicles?created=${encodeURIComponent(batchKey)}`);
}
