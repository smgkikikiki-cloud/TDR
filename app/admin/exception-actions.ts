"use server";

/**
 * Resolving the few rows an import could not place.
 *
 * A label the crosswalk has never seen is the only reason a monthly
 * registration file stops being automatic. Assigning it here writes the
 * mapping, so the same label next month matches itself and is never asked
 * about again -- that persistence is the whole point, not a side effect.
 *
 * Grain belongs to the source. Where a file publishes only a model name,
 * the binding is to a model and nothing here invents a trim for it; where
 * the file itself prints the grade -- which several marques do -- the trim
 * it names is kept. The exception row records which of the two it was when
 * it was read, and that recorded grain, not the form, decides what may be
 * bound.
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

type Target = {
  canonicalModelId: string;
  /** The legacy registration identity, where a release has crosswalked one. */
  legacyModelId: string | null;
  legacyBrandId: string;
};

/** What a canonical model can be bound to, without forging anything.
 *
 *  Registration has always joined on models.id, and which legacy row a
 *  canonical model owns is decided by the release build's crosswalk --
 *  integration_data/crosswalk_overrides.json plus the markers
 *  tdr_bridge/release.py::_model_crosswalk reads. That is the bridge, and
 *  there is exactly one of it, so this reads the link and never mints one:
 *  a models row inserted here would be an identity the next release has
 *  never heard of.
 *
 *  A car created today simply has no legacy row yet, and that used to make
 *  it unbindable -- exactly the cars most likely to turn up in an
 *  exception. Since v41 the mapping can name the canonical model directly,
 *  so the legacy id is recorded when it exists and left null when it does
 *  not. The brand still resolves through the legacy brand row, which is
 *  what the alias tables are keyed by. */
async function resolveTarget(db: any, canonicalModelId: string): Promise<Target> {
  const { data: model, error } = await db.from("current_vehicle_models")
    .select("canonical_id,tdr_model_id,brand_id,name_en")
    .eq("canonical_id", canonicalModelId).maybeSingle();
  if (error) throw error;
  if (!model) throw new Error("ไม่พบรถคันนี้ใน active canonical release");

  const { data: brand, error: brandError } = await db.from("current_vehicle_brands")
    .select("canonical_id,tdr_brand_id,name_en")
    .eq("canonical_id", model.brand_id).maybeSingle();
  if (brandError) throw brandError;
  if (!brand?.tdr_brand_id) {
    throw new Error(
      `ยี่ห้อ "${brand?.name_en || model.brand_id}" ยังไม่มี registration identity `
      + "— ผูกป้ายชื่อกับยี่ห้อนี้ยังไม่ได้จนกว่า crosswalk จะเชื่อมให้",
    );
  }
  return {
    canonicalModelId: String(model.canonical_id),
    legacyModelId: model.tdr_model_id ? String(model.tdr_model_id) : null,
    legacyBrandId: String(brand.tdr_brand_id),
  };
}

function exceptionIds(formData: FormData): string[] {
  return field(formData, "exception_ids").split(",").map((id) => id.trim()).filter(Boolean);
}

/** The grain the source published, read back from the stored exception.
 *
 *  Not from the form: the form is what a browser sent, and a trim binding
 *  made against a model-level row would put a month of registration volume
 *  behind a car it was never counted for. */
async function recordedGrain(db: any, ids: string[]): Promise<"MODEL" | "TRIM"> {
  if (!ids.length) return "MODEL";
  const { data, error } = await db.from("import_run_exceptions")
    .select("source_identity").in("id", ids);
  if (error) throw error;
  const grains = new Set((data || []).map(
    (row: any) => String(row?.source_identity?.grain || "MODEL")));
  return grains.size === 1 && grains.has("TRIM") ? "TRIM" : "MODEL";
}

/** Bind one unmatched registration label to a canonical car, for good. */
export async function assignRegistrationIdentity(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await currentEditor();
  const rawBrand = field(formData, "raw_brand");
  const rawModel = field(formData, "raw_model");
  const registrationType = field(formData, "registration_type") || "*";
  // One select, one value, so a picker that offers a car and its grades
  // cannot send half an answer: "model" or "model::trim".
  const [targetModel, targetTrim] = field(formData, "target").split("::");
  const canonicalModelId = targetModel || field(formData, "canonical_model_id");
  const requestedTrimId = targetTrim || field(formData, "canonical_trim_id");
  if (!rawBrand || !rawModel) throw new Error("ไม่พบป้ายชื่อจากต้นทาง");
  if (!canonicalModelId) throw new Error("เลือกรถปลายทางก่อน");

  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const ids = exceptionIds(formData);
  const target = await resolveTarget(db, canonicalModelId);

  let canonicalTrimId: string | null = null;
  if (requestedTrimId) {
    if (await recordedGrain(db, ids) !== "TRIM") {
      throw new Error(
        "ต้นทางรายงานแค่ระดับรุ่น จึงผูกได้แค่ระดับรุ่น — เลือกรุ่นย่อยไม่ได้สำหรับแถวนี้",
      );
    }
    const { data: trim, error: trimError } = await db.from("current_market_trims")
      .select("canonical_id,model_id").eq("canonical_id", requestedTrimId).maybeSingle();
    if (trimError) throw trimError;
    if (!trim) throw new Error("ไม่พบรุ่นย่อยนี้ใน active canonical release");
    if (String(trim.model_id) !== canonicalModelId) {
      throw new Error("รุ่นย่อยที่เลือกไม่ได้อยู่ในรถคันนี้");
    }
    canonicalTrimId = String(trim.canonical_id);
  }

  const brandNorm = normalize(rawBrand);
  const modelNorm = normalize(rawModel);
  const aliasNorm = (brandNorm && modelNorm.startsWith(brandNorm)
    ? modelNorm.slice(brandNorm.length) : modelNorm) || modelNorm;
  if (!brandNorm || !aliasNorm) throw new Error("ป้ายชื่อนี้ normalize แล้วว่างเปล่า");

  const notes = `assigned in TDR Admin by ${editor?.name || "tdr-admin"}`;
  const reviewedAt = new Date().toISOString();
  const { error: brandError } = await db.from("registration_brand_aliases").upsert(
    { raw_brand_norm: brandNorm, brand_id: target.legacyBrandId, notes, reviewed_at: reviewedAt },
    { onConflict: "raw_brand_norm" });
  if (brandError) throw new Error(`brand alias write failed: ${brandError.message}`);
  const { error: aliasError } = await db.from("registration_model_aliases").upsert(
    {
      brand_id: target.legacyBrandId, registration_type: registrationType,
      alias_norm: aliasNorm, model_id: target.legacyModelId,
      canonical_model_id: target.canonicalModelId,
      canonical_trim_id: canonicalTrimId,
      grain: canonicalTrimId ? "TRIM" : "MODEL",
      match_mode: "exact", notes, reviewed_at: reviewedAt,
    },
    { onConflict: "brand_id,registration_type,alias_norm" });
  if (aliasError) throw new Error(`model alias write failed: ${aliasError.message}`);

  // Months already loaded carry the mapping too, so assigning once fixes the
  // history as well as every file that arrives after it.
  const patch: Record<string, unknown> = {
    canonical_model_id: target.canonicalModelId,
    canonical_trim_id: canonicalTrimId,
    mapping_method: "admin-assigned-alias",
  };
  if (target.legacyModelId) patch.model_id = target.legacyModelId;
  let remap = db.from("registrations").update(patch)
    .eq("brand_name_raw", rawBrand).eq("model_name_raw", rawModel);
  if (registrationType !== "*") remap = remap.eq("registration_type", registrationType);
  const { error: remapError } = await remap;
  if (remapError) throw new Error(`existing registration remap failed: ${remapError.message}`);

  await closeExceptions(db, ids, {
    target: canonicalTrimId || target.canonicalModelId,
    by: editor?.name || "tdr-admin",
  });

  revalidatePath("/admin/exceptions");
  redirect("/admin/exceptions?assigned=1");
}

async function closeExceptions(db: any, ids: string[],
                               { target, by }: { target: string; by: string }) {
  if (!ids.length) return;
  const { error } = await db.from("import_run_exceptions")
    .update({
      status: "RESOLVED", resolution_target: target,
      resolved_by: by, resolved_at: new Date().toISOString(),
    })
    .in("id", ids).eq("status", "OPEN");
  if (error) throw new Error(`exception close failed: ${error.message}`);
}

/** Close a row that needed no data change -- a duplicate, or a line that
 *  was never a vehicle. The row stays, with who closed it and why. */
export async function resolveException(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const editor = await currentEditor();
  const ids = exceptionIds(formData);
  const note = field(formData, "note");
  if (!ids.length) throw new Error("ไม่พบรายการที่จะปิด");
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  await closeExceptions(db, ids, {
    target: note || "closed without a mapping",
    by: editor?.name || "tdr-admin",
  });
  revalidatePath("/admin/exceptions");
  redirect("/admin/exceptions?resolved=1");
}
