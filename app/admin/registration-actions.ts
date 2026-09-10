"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { currentEditor } from "@/lib/admin-auth";
import { adminDb } from "@/lib/supabase";

function required(form: FormData, key: string) {
  const value = String(form.get(key) || "").trim();
  if (!value) throw new Error(`${key} is required`);
  return value;
}
function periodValue(raw: string) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(raw)) throw new Error("period must be YYYY-MM");
  return raw;
}
function sourceUrl(period: string, kind: string) {
  const base = "https://raw.githubusercontent.com/smgkikikiki-cloud/TDR/main/automotive/vehicle_master/data";
  if (kind === "api") return `${base}/raw/dlt_${period}.csv`;
  if (kind === "long") return `${base}/raw_pivot/long_${period}.csv`;
  if (kind === "pivot") return `${base}/raw_pivot/pivot_${period}.csv`;
  throw new Error("unsupported registration snapshot kind");
}
function normalize(value: string) { return value.toLocaleLowerCase().replace(/[^a-z0-9]+/g, ""); }

async function requireAdminDb() {
  const editor = await currentEditor();
  if (!editor) throw new Error("admin session required");
  const db = adminDb();
  if (!db) throw new Error("admin database is not configured");
  return { db, editor };
}

export async function ingestRegistrationSnapshot(form: FormData) {
  const { db } = await requireAdminDb();
  const period = periodValue(required(form, "period"));
  const kind = required(form, "snapshot_kind");
  const url = sourceUrl(period, kind);
  const { data, error } = await db.rpc("ingest_registration_snapshot", {
    p_snapshot_url: url,
    p_expected_period: `${period}-01`,
    p_source_title: `DLT registration snapshot ${period}`,
  });
  if (error) throw new Error(`registration ingest failed: ${error.message}`);
  revalidatePath("/admin/registrations");
  revalidatePath("/member");
  revalidatePath("/member/market");
  const result = (data || {}) as Record<string, unknown>;
  const query = new URLSearchParams({ ingested: "1", period });
  if (result.units != null) query.set("units", String(result.units));
  if (result.mapped_unit_pct != null) query.set("coverage", String(result.mapped_unit_pct));
  redirect(`/admin/registrations?${query.toString()}`);
}

export async function teachRegistrationAlias(form: FormData) {
  const { db, editor } = await requireAdminDb();
  const rawBrand = required(form, "raw_brand");
  const rawModel = required(form, "raw_model");
  const registrationType = required(form, "registration_type");
  const targetModelId = required(form, "target_model_id");
  const matchMode = String(form.get("match_mode") || "prefix") === "exact" ? "exact" : "prefix";
  const brandNorm = normalize(rawBrand);
  const aliasNorm = normalize(rawModel).replace(new RegExp(`^${brandNorm}`), "") || normalize(rawModel);
  if (!brandNorm || !aliasNorm) throw new Error("registration alias normalizes to an empty token");

  const { data: target, error: targetError } = await db.from("models")
    .select("id,brand_id,name_en").eq("id", targetModelId).maybeSingle();
  if (targetError || !target?.id || !target.brand_id) throw new Error("target model does not resolve to legacy registration identity");
  const notes = `reviewed in TDR Admin by ${editor.name}`;
  const { error: brandError } = await db.from("registration_brand_aliases").upsert({
    raw_brand_norm: brandNorm, brand_id: target.brand_id, notes, reviewed_at: new Date().toISOString(),
  }, { onConflict: "raw_brand_norm" });
  if (brandError) throw new Error(`brand alias write failed: ${brandError.message}`);
  const { error: modelError } = await db.from("registration_model_aliases").upsert({
    brand_id: target.brand_id, registration_type: registrationType, alias_norm: aliasNorm,
    model_id: target.id, match_mode: matchMode, notes, reviewed_at: new Date().toISOString(),
  }, { onConflict: "brand_id,registration_type,alias_norm" });
  if (modelError) throw new Error(`model alias write failed: ${modelError.message}`);

  let remap = db.from("registrations").update({ model_id: target.id, mapping_method: "admin-reviewed-alias" })
    .eq("brand_name_raw", rawBrand).eq("model_name_raw", rawModel);
  if (registrationType !== "*") remap = remap.eq("registration_type", registrationType);
  const { error: remapError } = await remap;
  if (remapError) throw new Error(`existing registration remap failed: ${remapError.message}`);

  revalidatePath("/admin/registrations");
  revalidatePath("/admin/market");
  revalidatePath("/member");
  revalidatePath("/member/market");
  redirect(`/admin/registrations?mapped=1&raw=${encodeURIComponent(`${rawBrand} ${rawModel}`)}`);
}
