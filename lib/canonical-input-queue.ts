import { createHash } from "node:crypto";
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

export async function enqueueCanonicalInputBatch(payload: Record<string, unknown>) {
  if (!(await isAdmin())) throw new Error("admin authentication required");
  if (payload.schema_version !== 1) throw new Error("รองรับเฉพาะ schema_version 1");
  const batchKey = String(payload.batch_id || "").trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(batchKey)) throw new Error("batch_id ไม่ถูกต้อง");
  const commands = Array.isArray(payload.commands) ? payload.commands : [];
  if (!commands.length || commands.length > 500) throw new Error("commands ต้องมี 1–500 รายการ");
  const source = payload.source && typeof payload.source === "object"
    ? payload.source as Record<string, unknown> : {};
  const kind = String(source.kind || "ADMIN").toUpperCase();
  if (kind !== "ADMIN") throw new Error("review queue helper accepts ADMIN source only");

  const editor = await currentEditor();
  const actor = editor?.name || "tdr-admin";
  const submittedAt = typeof payload.submitted_at === "string" && payload.submitted_at.trim()
    ? payload.submitted_at.trim()
    : new Date().toISOString();
  const normalized = {
    ...payload,
    source: { ...source, kind },
    actor,
    submitted_at: submittedAt,
    commands: commands.map((command) => command && typeof command === "object"
      ? { ...(command as Record<string, unknown>), actor, submitted_at: submittedAt }
      : command),
  };
  const payloadSha256 = createHash("sha256").update(canonical(normalized)).digest("hex");
  const db = adminDb();
  if (!db) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");

  const row = {
    domain: "VEHICLE_MARKET",
    batch_key: batchKey,
    source_kind: kind,
    source_ref: typeof source.ref === "string" ? source.ref : null,
    payload: normalized,
    payload_sha256: payloadSha256,
    item_count: commands.length,
    actor,
    status: "QUEUED",
  };
  const { error } = await db.from("canonical_input_batches").insert(row);
  if (error?.code === "23505") {
    const { data: existing, error: readError } = await db.from("canonical_input_batches")
      .select("payload_sha256").eq("batch_key", batchKey).maybeSingle();
    if (readError) throw readError;
    if (existing?.payload_sha256 !== payloadSha256) {
      throw new Error("batch_id นี้เคยใช้กับข้อมูลคนละชุดแล้ว");
    }
    return { queued: false, duplicate: true, batchKey };
  }
  if (error) throw error;
  return { queued: true, duplicate: false, batchKey };
}
