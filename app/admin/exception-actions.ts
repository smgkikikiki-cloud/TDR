"use server";

/**
 * Resolving the few rows an import could not place.
 *
 * A DLT label the crosswalk has never seen is the only reason a monthly
 * registration file stops being automatic. Assigning it here writes the
 * alias, so the same label next month matches itself and is never asked
 * about again -- that persistence is the whole point, not a side effect.
 *
 * DLT reports at model grain, so a label binds to a canonical model. It
 * never binds to a trim: the source does not say which trim, and guessing
 * one would put registration volume behind a car it was never counted for.
 */

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { currentEditor, isAdmin } from "@/lib/admin-auth";
import { field } from "@/lib/admin-form";
import { adminDb } from "@/lib/supabase";

function normalize(value: string) {
  return String(value || "").normalize("NFKC").toLocaleLowerCase("en-US")
    .replace(/[^\p{L}\p{N}]+/gu, "").trim();
}

/** The legacy registration identity a canonical model joins through.
 *
 *  Registration joins on models.id (migration_v31), and which legacy row a
 *  canonical model owns is decided by the release build's crosswalk --
 *  integration_data/crosswalk_overrides.json plus the source markers
 *  tdr_bridge/release.py::_model_crosswalk reads. That is the bridge, and
 *  there is exactly one of it.
 *
 *  So this reads the link and never forges one. Inserting a models row here
 *  would create an identity the crosswalk has never heard of: the next
 *  release resolves tdr_model_id from its own inventory snapshot, would not
 *  find this row, and the alias written against it would point at a car
 *  canonical does not recognise. A model with no link yet is a real blocker,
 *  reported as one. */
async function legacyModelId(db: any, canonicalModelId: string): Promise<string> {
  const { data: model, error } = await db.from("current_vehicle_models")
    .select("canonical_id,tdr_model_id,name_en")
    .eq("canonical_id", canonicalModelId).maybeSingle();
  if (error) throw error;
  if (!model) throw new Error("ไม่พบรถคันนี้ใน active canonical release");
  if (!model.tdr_model_id) {
    throw new Error(
      `"${model.name_en || canonicalModelId}" ยังไม่ได้เชื่อมกับ registration identity `
      + "(crosswalk ยังไม่มี tdr_model_id ให้รุ่นนี้) — ผูกยอดจดทะเบียนกับรุ่นนี้ยังไม่ได้ "
      + "จนกว่า crosswalk จะเชื่อมให้ เลือกรุ่นอื่นที่เชื่อมแล้วไปก่อน",
    );
  }
  return String(model.tdr_model_id);
}

/** Bind one unmatched DLT label to a canonical model, for good. */
export async function assignRegistrationIdentity(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await currentEditor();
  const rawBrand = field(formData, "raw_brand");
  const rawModel = field(formData, "raw_model");
  const registrationType = field(formData, "registration_type") || "*";
  const canonicalModelId = field(formData, "canonical_model_id");
  if (!rawBrand || !rawModel) throw new Error("ไม่พบป้ายชื่อจากต้นทาง");
  if (!canonicalModelId) throw new Error("เลือกรถปลายทางก่อน");

  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const modelId = await legacyModelId(db, canonicalModelId);
  const { data: target, error: targetError } = await db.from("models")
    .select("id,brand_id").eq("id", modelId).maybeSingle();
  if (targetError || !target?.brand_id) throw new Error("รถปลายทางไม่มี registration identity");

  const brandNorm = normalize(rawBrand);
  const modelNorm = normalize(rawModel);
  const aliasNorm = (brandNorm && modelNorm.startsWith(brandNorm)
    ? modelNorm.slice(brandNorm.length) : modelNorm) || modelNorm;
  if (!brandNorm || !aliasNorm) throw new Error("ป้ายชื่อนี้ normalize แล้วว่างเปล่า");

  const notes = `assigned in TDR Admin by ${editor?.name || "tdr-admin"}`;
  const reviewedAt = new Date().toISOString();
  const { error: brandError } = await db.from("registration_brand_aliases").upsert(
    { raw_brand_norm: brandNorm, brand_id: target.brand_id, notes, reviewed_at: reviewedAt },
    { onConflict: "raw_brand_norm" });
  if (brandError) throw new Error(`brand alias write failed: ${brandError.message}`);
  const { error: aliasError } = await db.from("registration_model_aliases").upsert(
    {
      brand_id: target.brand_id, registration_type: registrationType,
      alias_norm: aliasNorm, model_id: target.id, match_mode: "exact",
      notes, reviewed_at: reviewedAt,
    },
    { onConflict: "brand_id,registration_type,alias_norm" });
  if (aliasError) throw new Error(`model alias write failed: ${aliasError.message}`);

  // Months already loaded carry the mapping too, so assigning once fixes the
  // history as well as every file that arrives after it.
  let remap = db.from("registrations")
    .update({ model_id: target.id, mapping_method: "admin-assigned-alias" })
    .eq("brand_name_raw", rawBrand).eq("model_name_raw", rawModel);
  if (registrationType !== "*") remap = remap.eq("registration_type", registrationType);
  const { error: remapError } = await remap;
  if (remapError) throw new Error(`existing registration remap failed: ${remapError.message}`);

  revalidatePath("/admin/exceptions");
  redirect("/admin/exceptions?assigned=1");
}
