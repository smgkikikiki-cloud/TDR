"use server";

/**
 * Owner decisions for Ice model groups the monthly routine could not place (table ice_review_queue, v69).
 * Each action writes ONE decision for scope ALL into ice_model_crosswalk_scoped (provenance: the signed-in editor + date),
 * then closes the queue row. Nothing is guessed: a link needs an existing model id, a new car needs an explicit id and name.
 * Pickup groups that need a per-registration-type split (รย.1 / รย.2 ...) are not handled here; they stay a manual SQL job.
 */

import { createHash } from "node:crypto";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { currentEditor, isAdmin } from "@/lib/admin-auth";
import { field } from "@/lib/admin-form";
import { adminDb } from "@/lib/supabase";

const CANONICAL_ID = /^[a-z0-9_]+\.[a-z0-9_]+$/;

async function context(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const db = adminDb();
  if (!db) throw new Error("ฐานข้อมูลแอดมินยังไม่ได้ตั้งค่า");
  const groupId = field(formData, "model_group_id");
  if (!groupId) throw new Error("ไม่มีรหัสกลุ่มรุ่น");
  const { data: row, error } = await db.from("ice_review_queue").select("*").eq("model_group_id", groupId).eq("status", "OPEN").maybeSingle();
  if (error) throw new Error(`อ่านคิวไม่ได้: ${error.message}`);
  if (!row) throw new Error("รายการนี้ถูกตัดสินไปแล้วหรือไม่อยู่ในคิว");
  const editor = await currentEditor();
  const who = editor?.name || "tdr-admin";
  const today = new Date().toISOString().slice(0, 10);
  return { db, row, who, today };
}

async function decide(ctx: Awaited<ReturnType<typeof context>>, status: "APPROVED" | "EXCLUDED", target: string | null, kind: string, reason: string) {
  const { db, row, who, today } = ctx;
  const decisionRef = `admin-queue:${who}:${today}:${kind}`;
  const { error } = await db.from("ice_model_crosswalk_scoped").insert({
    model_group_id: row.model_group_id,
    reg_type_scope: "ALL",
    status,
    canonical_model_id: status === "APPROVED" ? target : null,
    master_version: row.first_seen_master_version || "unknown",
    decision_ref: decisionRef,
    source_sha256: createHash("sha256").update(`${decisionRef}|${row.model_group_id}|${target || ""}`).digest("hex"),
    reason,
  });
  if (error) throw new Error(`บันทึกคำตัดสินไม่สำเร็จ: ${error.message}`);
  const { error: closeError } = await db.from("ice_review_queue").update({ status: "DONE", closed_at: new Date().toISOString() }).eq("model_group_id", row.model_group_id);
  if (closeError) throw new Error(`ปิดรายการไม่สำเร็จ (คำตัดสินถูกบันทึกแล้ว): ${closeError.message}`);
  revalidatePath("/admin/ice-queue");
  redirect(`/admin/ice-queue?done=${encodeURIComponent(row.model_group_id)}`);
}

/** Link the group to a model that already exists. */
export async function iceQueueLink(formData: FormData) {
  const ctx = await context(formData);
  const target = field(formData, "canonical_model_id").toLowerCase();
  if (!CANONICAL_ID.test(target)) throw new Error("รหัสรถต้องอยู่ในรูป แบรนด์.รุ่น เช่น toyota.camry");
  const { data: model, error } = await ctx.db.from("vehicle_models").select("canonical_id").eq("canonical_id", target).is("deleted_at", null).maybeSingle();
  if (error) throw new Error(`ตรวจรถไม่ได้: ${error.message}`);
  if (!model) throw new Error(`ไม่พบรถ ${target} ในฐานข้อมูล`);
  await decide(ctx, "APPROVED", target, "link", `owner linked in admin queue to ${target}`);
}

/** The group is not a car TDR counts (trailer, unidentifiable, etc.). */
export async function iceQueueExclude(formData: FormData) {
  const ctx = await context(formData);
  const why = field(formData, "reason") || "excluded by owner in admin queue";
  await decide(ctx, "EXCLUDED", null, "exclude", why);
}

/** Create a brand-new model through the governed writer (v68), then link the group to it. */
export async function iceQueueCreate(formData: FormData) {
  const ctx = await context(formData);
  const canonicalId = field(formData, "canonical_id").toLowerCase();
  const nameEn = field(formData, "name_en");
  const brandName = field(formData, "brand_name_en");
  const status = field(formData, "status") || "UNVERIFIED";
  if (!CANONICAL_ID.test(canonicalId)) throw new Error("รหัสรถใหม่ต้องอยู่ในรูป แบรนด์.รุ่น เช่น byd.seal");
  if (!nameEn) throw new Error("กรุณาใส่ชื่อรุ่น");
  if (!["UNVERIFIED", "HISTORICAL"].includes(status)) throw new Error("สถานะต้องเป็น รอยืนยัน หรือ เลิกขายแล้ว");
  const batch = `admin-queue-${ctx.today}-${canonicalId.replace(/[^a-z0-9]/g, "")}`;
  const { data, error } = await ctx.db.rpc("vm_create_identities", {
    p_batch_id: batch,
    p_items: [{ canonical_id: canonicalId, brand_name_en: brandName || undefined, name_en: nameEn, status, note: `Ice group ${ctx.row.model_group_id}` }],
    p_actor: ctx.who,
  });
  if (error) throw new Error(`สร้างรถไม่สำเร็จ: ${error.message}`);
  const created = (data as any)?.created?.length || 0;
  const skipped = (data as any)?.skipped?.[0];
  if (!created && skipped?.why !== "EXISTS") throw new Error(`ไม่ได้สร้างรถ: ${skipped?.why || "ไม่ทราบสาเหตุ"} — ถ้ารถนี้มีอยู่แล้วให้ใช้ปุ่ม "ผูกกับรถที่มีอยู่"`);
  await decide(ctx, "APPROVED", canonicalId, "create", `owner created ${canonicalId} in admin queue (batch ${batch})`);
}
