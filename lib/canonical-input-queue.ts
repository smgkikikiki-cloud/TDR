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
  await dispatchWorker();
  return { queued: true, duplicate: false, batchKey };
}

/** Start the write now instead of leaving it for the next scheduled sweep.
 *
 *  The queue is a job record, not an inbox somebody works through, so a save
 *  should not sit in it waiting for a clock. A dispatch that fails changes
 *  nothing except how soon the job runs -- the sweep still picks it up -- so
 *  it never fails the save. */
async function dispatchWorker() {
  const token = process.env.GITHUB_DISPATCH_TOKEN;
  const repo = process.env.GITHUB_REPOSITORY;
  if (!token || !repo) return;
  try {
    await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${token}`,
        accept: "application/vnd.github+json",
        "content-type": "application/json",
      },
      body: JSON.stringify({ event_type: "canonical-input" }),
    });
  } catch (error) {
    console.error("canonical input dispatch failed; the sweep will pick it up", error);
  }
}
