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

export type CanonicalWorkerDispatch = {
  started: boolean;
  reason?: "missing_token" | "missing_repository" | "github_rejected" | "network_error";
  status?: number;
};

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
    // A retry of the same save is also a useful chance to wake a worker that
    // the first request failed to dispatch. Idempotency belongs to the batch,
    // not to the wake-up attempt.
    const dispatch = await dispatchWorker();
    return { queued: false, duplicate: true, batchKey, dispatch };
  }
  if (error) throw error;
  const dispatch = await dispatchWorker();
  return { queued: true, duplicate: false, batchKey, dispatch };
}

/** Start the write now instead of leaving it for the scheduled sweeper.
 *
 * Queue insertion is durable. A dispatch failure therefore does NOT fail the
 * save, but it must be observable: callers can tell the editor that the batch
 * is waiting for the fallback sweep instead of pretending a worker started.
 */
async function dispatchWorker(): Promise<CanonicalWorkerDispatch> {
  const token = process.env.GITHUB_DISPATCH_TOKEN?.trim() || process.env.GITHUB_TOKEN?.trim();
  const explicitRepo = process.env.GITHUB_REPOSITORY?.trim();
  const vercelOwner = process.env.VERCEL_GIT_REPO_OWNER?.trim();
  const vercelSlug = process.env.VERCEL_GIT_REPO_SLUG?.trim();
  const repo = explicitRepo || (vercelOwner && vercelSlug ? `${vercelOwner}/${vercelSlug}` : "");

  if (!token) {
    console.warn("canonical input queued but immediate dispatch is unavailable: GITHUB_DISPATCH_TOKEN is not configured");
    return { started: false, reason: "missing_token" };
  }
  if (!repo) {
    console.warn("canonical input queued but immediate dispatch is unavailable: repository identity is not configured");
    return { started: false, reason: "missing_repository" };
  }

  try {
    const response = await fetch(`https://api.github.com/repos/${repo}/dispatches`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${token}`,
        accept: "application/vnd.github+json",
        "content-type": "application/json",
        "x-github-api-version": "2022-11-28",
      },
      body: JSON.stringify({ event_type: "canonical-input" }),
      cache: "no-store",
    });
    if (!response.ok) {
      const detail = (await response.text()).slice(0, 500);
      console.error(`canonical input dispatch rejected by GitHub (${response.status}); fallback sweep will pick it up: ${detail}`);
      return { started: false, reason: "github_rejected", status: response.status };
    }
    return { started: true };
  } catch (error) {
    console.error("canonical input dispatch failed; fallback sweep will pick it up", error);
    return { started: false, reason: "network_error" };
  }
}
