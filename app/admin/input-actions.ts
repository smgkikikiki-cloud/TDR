"use server";

import { createHash } from "node:crypto";
import { redirect } from "next/navigation";
import { currentEditor, isAdmin } from "@/lib/admin-auth";
import { adminDb } from "@/lib/supabase";

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const row = value as Record<string, unknown>;
    return `{${Object.keys(row).sort().map((key) => `${JSON.stringify(key)}:${canonical(row[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export async function enqueueVehicleInput(formData: FormData) {
  if (!(await isAdmin())) redirect("/admin/login");
  const raw = formData.get("payload");
  if (typeof raw !== "string" || !raw.trim()) throw new Error("กรุณาใส่ input batch JSON");

  let payload: Record<string, unknown>;
  try { payload = JSON.parse(raw); } catch { throw new Error("input batch ต้องเป็น JSON ที่ถูกต้อง"); }
  if (payload.schema_version !== 1) throw new Error("รองรับเฉพาะ schema_version 1");
  const batchKey = typeof payload.batch_id === "string" ? payload.batch_id.trim() : "";
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(batchKey)) throw new Error("batch_id ไม่ถูกต้อง");
  const commands = Array.isArray(payload.commands) ? payload.commands : [];
  if (!commands.length || commands.length > 500) throw new Error("commands ต้องมี 1–500 รายการ");
  const source = payload.source && typeof payload.source === "object"
    ? payload.source as Record<string, unknown> : {};
  const sourceKind = String(source.kind || "ADMIN").toUpperCase();
  if (["DLT", "REGISTRATION"].includes(sourceKind)) {
    throw new Error("ข้อมูลจดทะเบียนใช้ registration ingest แยกจาก Vehicle Master");
  }
  const allowed = new Set(["ADMIN", "ECO", "OEM", "MEDIA", "PRICE_HARVEST", "MIGRATION", "API"]);
  if (!allowed.has(sourceKind)) throw new Error("source.kind ไม่รองรับ");

  const editor = await currentEditor();
  const actor = editor?.name || "tdr-admin";
  const submittedAt = new Date().toISOString();
  payload = {
    ...payload,
    source: { ...source, kind: sourceKind },
    actor,
    submitted_at: submittedAt,
    commands: commands.map((command) => command && typeof command === "object"
      ? { ...(command as Record<string, unknown>), actor, submitted_at: submittedAt }
      : command),
  };
  const payloadSha256 = createHash("sha256").update(canonical(payload)).digest("hex");
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  const row = {
    batch_key: batchKey,
    source_kind: sourceKind,
    source_ref: typeof source.ref === "string" ? source.ref : null,
    payload,
    payload_sha256: payloadSha256,
    item_count: commands.length,
    actor,
    status: "QUEUED",
  };
  const { error } = await db.from("canonical_input_batches").insert(row);
  if (error?.code === "23505") {
    const { data: existing } = await db.from("canonical_input_batches")
      .select("payload_sha256").eq("batch_key", batchKey).maybeSingle();
    if (existing?.payload_sha256 !== payloadSha256) {
      throw new Error("batch_id นี้เคยใช้กับข้อมูลคนละชุดแล้ว");
    }
    redirect("/admin/vehicle-input?queued=duplicate");
  }
  if (error) throw error;
  redirect("/admin/vehicle-input?queued=1");
}
