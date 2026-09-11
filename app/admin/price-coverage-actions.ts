"use server";

import { randomUUID } from "node:crypto";
import { redirect } from "next/navigation";
import { enqueueVehicleInput } from "@/app/admin/input-actions";
import { isAdmin } from "@/lib/admin-auth";
import { adminDb } from "@/lib/supabase";

const REASONS = new Set([
  "AWAITING_FINAL_LIST_PRICE",
  "OFFICIAL_EVIDENCE_CONFLICT",
  "NO_RELIABLE_EVIDENCE",
]);

function field(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value.trim() : "";
}

function required(formData: FormData, name: string, label: string): string {
  const value = field(formData, name);
  if (!value) throw new Error(`กรุณาใส่ ${label}`);
  return value;
}

function validateSubmission(submissionId: string, submittedAt: string) {
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(submissionId)) throw new Error("submission_id ไม่ถูกต้อง");
  const stamp = new Date(submittedAt);
  if (Number.isNaN(stamp.getTime()) || !/(?:Z|[+-]\d{2}:\d{2})$/.test(submittedAt)) {
    throw new Error("submission timestamp ต้องเป็น ISO-8601 พร้อม timezone");
  }
}

async function releaseYear(db: any, releaseId: string): Promise<number> {
  const { data, error } = await db.from("canonical_vehicle_releases")
    .select("payload,as_of").eq("release_id", releaseId).maybeSingle();
  if (error) throw error;
  const payload = data?.payload && typeof data.payload === "object"
    ? data.payload as Record<string, unknown> : {};
  const year = Number(payload.year || String(data?.as_of || "").slice(0, 4));
  if (!Number.isInteger(year) || year < 2000 || year > 2100) {
    throw new Error("หา catalog year ของ active canonical release ไม่ได้");
  }
  return year;
}

export async function enqueuePriceCoverageDisposition(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const trimId = required(formData, "trim_id", "MarketTrim");
  const action = required(formData, "disposition", "review disposition").toLowerCase();
  if (!new Set(["defer", "reopen"]).has(action)) {
    throw new Error("price coverage disposition รองรับ defer/reopen เท่านั้น");
  }
  const submissionId = field(formData, "submission_id") || randomUUID();
  const submittedAt = required(formData, "submitted_at", "submission timestamp");
  validateSubmission(submissionId, submittedAt);

  const reasonCode = field(formData, "reason_code").toUpperCase();
  const sourceRef = field(formData, "source_ref");
  const notes = required(formData, "notes", "review note");
  if (action === "defer") {
    if (!REASONS.has(reasonCode)) throw new Error("reason_code ไม่รองรับ");
    if (!/^https?:\/\//i.test(sourceRef)) throw new Error("defer ต้องมี evidence URL");
  }

  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const { data: trim, error } = await db.from("current_market_trims")
    .select("canonical_id,release_id,model_id,current_list_price")
    .eq("canonical_id", trimId).maybeSingle();
  if (error) throw error;
  if (!trim?.release_id || !trim.model_id) throw new Error("ไม่พบ MarketTrim นี้ใน active canonical release");
  if (action === "defer" && Number(trim.current_list_price?.amount_thb || 0) > 0) {
    throw new Error("MarketTrim นี้มี current LIST_PRICE แล้ว ไม่ควรถูก defer");
  }
  const year = await releaseYear(db, trim.release_id);

  const advanced = new FormData();
  advanced.set("submitted_at", submittedAt);
  advanced.set("payload", JSON.stringify({
    schema_version: 1,
    batch_id: `admin-price-coverage-${submissionId}`,
    year,
    submitted_at: submittedAt,
    source: { kind: "ADMIN", ...(sourceRef ? { ref: sourceRef } : {}) },
    reason: `HUMAN price coverage ${action}: ${notes}`,
    commands: [{
      operation: "UPSERT_PRICE_COVERAGE_REVIEW",
      payload: {
        trim_id: trimId,
        action,
        ...(action === "defer" ? { reason_code: reasonCode, source_ref: sourceRef } : {}),
        notes,
      },
    }],
  }));
  return enqueueVehicleInput(advanced);
}
