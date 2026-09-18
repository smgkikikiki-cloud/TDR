/**
 * Server-side storage for the Canonical Vehicle Editor's review-before-queue
 * step, backing the admin_edit_sessions table created by
 * supabase/migration_v35_admin_edit_sessions.sql (applied in production) and
 * carried to this module's shape -- kind 'TRIM', no DRAFT status -- by
 * supabase/migration_v36_admin_edit_sessions_trim_kind.sql.
 *
 * The review URL carries only an opaque, high-entropy id; the proposal's
 * canonical payload, diff, evidence and reason never leave the server except
 * rendered into the review page for its owning admin.
 *
 * Every read/write here is scoped by `actor` (the authenticated admin's name
 * from lib/admin-auth.ts's currentEditor()) so one admin can never load or
 * confirm another admin's pending proposal, and by `expires_at`/`status` so
 * an expired or already-consumed proposal fails closed rather than replaying.
 * Consumption is a single atomic conditional UPDATE, so two concurrent
 * confirms of the same proposal can never both succeed.
 */
import { randomBytes } from "node:crypto";
import { adminDb } from "@/lib/supabase";

const SESSION_TTL_MS = 1000 * 60 * 60; // 1 hour: long enough to read a whole trim's diff without racing a timer.

export type EditSessionKind = "MODEL_GENERATION" | "TRIM";

export type EvidenceRecord = { sourceKind: string; sourceRef?: string; reviewedAt: string };

export type EditSessionRow = {
  id: string;
  kind: EditSessionKind;
  status: "PENDING_REVIEW" | "CONSUMED";
  modelId: string;
  trimId: string | null;
  actor: string;
  pageReleaseId: string;
  batchPayload: Record<string, unknown> | null;
  diff: unknown[] | null;
  reason: string | null;
  evidence: EvidenceRecord | null;
  expiresAt: string;
};

function newSessionId(): string {
  return randomBytes(24).toString("base64url");
}

function fromRow(row: any): EditSessionRow {
  return {
    id: row.id, kind: row.kind, status: row.status, modelId: row.model_id, trimId: row.trim_id,
    actor: row.actor, pageReleaseId: row.page_release_id,
    batchPayload: row.batch_payload || null, diff: row.diff || null,
    reason: row.reason || null, evidence: row.evidence || null, expiresAt: row.expires_at,
  };
}

function db() {
  const client = adminDb();
  if (!client) throw new Error("ยังไม่ได้ตั้งค่า Supabase server credential");
  return client;
}

export async function createProposal(args: {
  kind: EditSessionKind;
  modelId: string;
  trimId?: string;
  actor: string;
  pageReleaseId: string;
  batchPayload: Record<string, unknown>;
  diff: unknown[];
  reason: string;
  evidence: EvidenceRecord;
}): Promise<string> {
  const id = newSessionId();
  const { error } = await db().from("admin_edit_sessions").insert({
    id, kind: args.kind, status: "PENDING_REVIEW", model_id: args.modelId, trim_id: args.trimId || null,
    actor: args.actor, page_release_id: args.pageReleaseId,
    batch_payload: args.batchPayload, diff: args.diff, reason: args.reason, evidence: args.evidence,
    expires_at: new Date(Date.now() + SESSION_TTL_MS).toISOString(),
  });
  if (error) throw error;
  return id;
}

/** Loads a live (not expired), owned, still-pending proposal. Returns null for
 * every failure mode alike (wrong owner, expired, already consumed, missing) --
 * the caller shows one generic message rather than a signal an attacker could
 * use to probe for other admins' proposal ids. */
export async function loadProposal(id: string, actor: string): Promise<EditSessionRow | null> {
  if (!id || !actor) return null;
  const { data, error } = await db().from("admin_edit_sessions")
    .select("*").eq("id", id).eq("actor", actor).eq("status", "PENDING_REVIEW")
    .gt("expires_at", new Date().toISOString()).maybeSingle();
  if (error) throw error;
  return data ? fromRow(data) : null;
}

/** Consumes a proposal exactly once: an atomic conditional UPDATE, not a
 * read-then-write, so a duplicate confirm (double click, retried request)
 * can never queue the same proposal twice. Returns null for any failure
 * (wrong owner, expired, already consumed, missing). */
export async function consumeProposal(id: string, actor: string): Promise<EditSessionRow | null> {
  const { data, error } = await db().from("admin_edit_sessions")
    .update({ status: "CONSUMED", consumed_at: new Date().toISOString(), updated_at: new Date().toISOString() })
    .eq("id", id).eq("actor", actor).eq("status", "PENDING_REVIEW")
    .gt("expires_at", new Date().toISOString())
    .select("*").maybeSingle();
  if (error) throw error;
  return data ? fromRow(data) : null;
}
