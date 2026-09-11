"use server";

import { randomUUID } from "node:crypto";
import { redirect } from "next/navigation";
import { isAdmin } from "@/lib/admin-auth";
import { enqueueCanonicalInputBatch } from "@/lib/canonical-input-queue";
import { adminDb } from "@/lib/supabase";

const ACTIONS = new Set(["current", "historical", "reopen"]);

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function required(formData: FormData, name: string, label = name): string {
  const value = field(formData, name);
  if (!value) throw new Error(`กรุณาใส่ ${label}`);
  return value;
}

function evidenceUrl(value: string): string {
  let url: URL;
  try { url = new URL(value); } catch { throw new Error("Evidence ต้องเป็น URL ที่ถูกต้อง"); }
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("Evidence ต้องเป็น HTTP(S) URL");
  return url.toString();
}

export async function enqueueTrimRetailLifecycleReview(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const trimId = required(formData, "trim_id", "MarketTrim");
  const action = required(formData, "action", "lifecycle action").toLowerCase();
  if (!ACTIONS.has(action)) throw new Error("lifecycle action ต้องเป็น current, historical หรือ reopen");
  const modelId = required(formData, "model_id", "canonical model");
  const sourceRef = action === "reopen" ? "" : evidenceUrl(required(formData, "source_ref", "official evidence URL"));
  const notes = action === "reopen" ? field(formData, "notes") : required(formData, "notes", "review note");
  const submissionId = field(formData, "submission_id") || randomUUID();
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(submissionId)) throw new Error("submission_id ไม่ถูกต้อง");
  const submittedAt = required(formData, "submitted_at", "submission timestamp");
  if (Number.isNaN(Date.parse(submittedAt)) || !/(?:Z|[+-]\d{2}:\d{2})$/.test(submittedAt)) {
    throw new Error("submission timestamp ต้องเป็น ISO-8601 พร้อม timezone");
  }

  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const { data: trim, error: trimError } = await db.from("current_market_trims")
    .select("canonical_id,model_id,release_id")
    .eq("canonical_id", trimId).maybeSingle();
  if (trimError) throw trimError;
  if (!trim?.release_id || trim.model_id !== modelId) throw new Error("ไม่พบ MarketTrim นี้ใต้ canonical model ที่เลือก");

  const [{ data: model, error: modelError }, { data: release, error: releaseError }] = await Promise.all([
    db.from("current_vehicle_models").select("canonical_id,payload").eq("canonical_id", modelId).maybeSingle(),
    db.from("canonical_vehicle_releases").select("payload,as_of").eq("release_id", trim.release_id).maybeSingle(),
  ]);
  if (modelError) throw modelError;
  if (releaseError) throw releaseError;
  const canonicalModelStatus = String((model?.payload as any)?.retail_status || "UNVERIFIED").toUpperCase();
  if (canonicalModelStatus !== "CURRENT") {
    throw new Error("ต้อง review parent model เป็น CURRENT ก่อน review trim lifecycle");
  }
  const releasePayload = release?.payload && typeof release.payload === "object"
    ? release.payload as Record<string, unknown> : {};
  const year = Number(releasePayload.year || String(release?.as_of || "").slice(0, 4));
  if (!Number.isInteger(year) || year < 2000 || year > 2100) throw new Error("หา catalog year ไม่ได้");

  await enqueueCanonicalInputBatch({
    schema_version: 1,
    batch_id: `admin-trim-lifecycle-${submissionId}`,
    year,
    submitted_at: submittedAt,
    source: { kind: "ADMIN", ...(sourceRef ? { ref: sourceRef } : {}) },
    reason: notes,
    commands: [{
      operation: "UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW",
      payload: {
        trim_id: trimId,
        action,
        ...(sourceRef ? { source_ref: sourceRef } : {}),
        notes,
      },
    }],
  });

  redirect(`/admin/retail-lifecycle?trimQueued=1&model=${encodeURIComponent(modelId)}`);
}
