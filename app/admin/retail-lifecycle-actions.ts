"use server";

import { randomUUID } from "node:crypto";
import { redirect } from "next/navigation";
import { isAdmin } from "@/lib/admin-auth";
import { enqueueCanonicalInputBatch } from "@/lib/canonical-input-queue";
import { adminDb } from "@/lib/supabase";

const REVIEW_STATUSES = new Set(["CURRENT", "HISTORICAL"]);

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function required(formData: FormData, name: string, label = name): string {
  const value = field(formData, name);
  if (!value) throw new Error(`กรุณาใส่ ${label}`);
  return value;
}

function checkedDate(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(`${value}T00:00:00Z`))) {
    throw new Error("วันที่ตรวจต้องเป็น YYYY-MM-DD");
  }
  return value;
}

function evidenceUrl(value: string): string {
  let url: URL;
  try { url = new URL(value); } catch { throw new Error("Evidence ต้องเป็น URL ที่ถูกต้อง"); }
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error("Evidence ต้องเป็น HTTP(S) URL");
  return url.toString();
}

export async function enqueueModelRetailLifecycleReview(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const modelId = required(formData, "model_id", "canonical model");
  const status = required(formData, "retail_status", "retail status").toUpperCase();
  if (!REVIEW_STATUSES.has(status)) throw new Error("retail status ต้องเป็น CURRENT หรือ HISTORICAL");
  const sourceRef = evidenceUrl(required(formData, "source_ref", "official evidence URL"));
  const reviewedAt = checkedDate(required(formData, "reviewed_at", "วันที่ตรวจ"));
  const reason = required(formData, "reason", "review note");
  const submissionId = field(formData, "submission_id") || randomUUID();
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(submissionId)) throw new Error("submission_id ไม่ถูกต้อง");
  const submittedAt = required(formData, "submitted_at", "submission timestamp");
  if (Number.isNaN(Date.parse(submittedAt)) || !/(?:Z|[+-]\d{2}:\d{2})$/.test(submittedAt)) {
    throw new Error("submission timestamp ต้องเป็น ISO-8601 พร้อม timezone");
  }

  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const { data: model, error: modelError } = await db.from("current_vehicle_models")
    .select("canonical_id,release_id,brand_id,generation_id,name_en,name_th,payload")
    .eq("canonical_id", modelId).maybeSingle();
  if (modelError) throw modelError;
  if (!model?.release_id || !model.brand_id || !model.generation_id) {
    throw new Error("ไม่พบ model นี้ใน active canonical release");
  }
  const [{ data: brand, error: brandError }, { data: generation, error: generationError }, { data: release, error: releaseError }] = await Promise.all([
    db.from("current_vehicle_brands").select("canonical_id,name_en,name_th").eq("canonical_id", model.brand_id).maybeSingle(),
    db.from("current_vehicle_generations").select("canonical_id,code,segment").eq("canonical_id", model.generation_id).maybeSingle(),
    db.from("canonical_vehicle_releases").select("payload,as_of").eq("release_id", model.release_id).maybeSingle(),
  ]);
  if (brandError) throw brandError;
  if (generationError) throw generationError;
  if (releaseError) throw releaseError;
  if (!brand || !generation?.code) throw new Error("หา canonical brand/generation ของ model นี้ไม่ครบ");
  const releasePayload = release?.payload && typeof release.payload === "object"
    ? release.payload as Record<string, unknown> : {};
  const year = Number(releasePayload.year || String(release?.as_of || "").slice(0, 4));
  if (!Number.isInteger(year) || year < 2000 || year > 2100) throw new Error("หา catalog year ไม่ได้");

  await enqueueCanonicalInputBatch({
    schema_version: 1,
    batch_id: `admin-retail-lifecycle-${submissionId}`,
    year,
    submitted_at: submittedAt,
    source: { kind: "ADMIN", ref: sourceRef },
    reason,
    commands: [{
      operation: "UPSERT_MODEL_BUNDLE",
      canonical_id: modelId,
      payload: {
        brand: {
          id: model.brand_id,
          name_en: brand.name_en || model.brand_id,
          ...(brand.name_th ? { name_th: brand.name_th } : {}),
        },
        model: {
          retail_status: status,
          retail_source: sourceRef,
          retail_checked_at: reviewedAt,
        },
        generation: {
          code: generation.code,
          ...(generation.segment ? { segment: generation.segment } : {}),
        },
      },
    }],
  });

  redirect(`/admin/retail-lifecycle?queued=1&model=${encodeURIComponent(modelId)}`);
}
