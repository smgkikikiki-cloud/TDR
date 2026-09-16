/**
 * Server-side storage for the Canonical Vehicle Editor's review-before-queue
 * step, backing supabase/migration_v35_admin_edit_sessions.sql's
 * admin_edit_sessions table (not applied to production by this branch).
 *
 * Replaces the earlier signed-token design (lib/edit-proposal-token.ts,
 * removed): that token carried the full canonical command payload, diff,
 * evidence and reason inside the review URL. A leaked/logged/bookmarked URL
 * was a leaked proposal. This module instead hands the caller only an
 * opaque, high-entropy id; the actual content never leaves the server except
 * rendered into the review page's HTML for its owning admin.
 *
 * Every read/write here is scoped by `actor` (the authenticated admin's
 * name from lib/admin-auth.ts's currentEditor()) so one admin can never load
 * or confirm another admin's pending proposal, and by `expires_at`/`status`
 * so an expired or already-consumed proposal fails closed rather than
 * replaying. Confirmation is a single atomic conditional UPDATE
 * (status = 'PENDING_REVIEW' -> 'CONSUMED'), so two concurrent confirms of
 * the same proposal can never both succeed.
 */
import { randomBytes } from "node:crypto";
import { adminDb } from "@/lib/supabase";

const SESSION_TTL_MS = 1000 * 60 * 20; // ~20 minutes, per the task's own guidance.

export type EditSessionKind = "MODEL_GENERATION" | "MARKET_TRIM" | "SPEC_DRAFT";

export type EvidenceRecord = { sourceKind: string; sourceRef?: string; reviewedAt: string };

export type SpecDraftEntryRecord = {
  fieldKey: string;
  labelForDiff: string;
  valueState: string;
  value: unknown;
  unit: string;
  qualifiers?: Record<string, string>;
  observedAt?: string;
  verificationStatus?: string;
  evidence?: EvidenceRecord;
};

export type EditSessionRow = {
  id: string;
  kind: EditSessionKind;
  status: "DRAFT" | "PENDING_REVIEW" | "CONSUMED";
  modelId: string;
  trimId: string | null;
  actor: string;
  pageReleaseId: string;
  draftEntries: SpecDraftEntryRecord[];
  defaultEvidence: EvidenceRecord | null;
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
    draftEntries: Array.isArray(row.draft_entries) ? row.draft_entries : [],
    defaultEvidence: row.default_evidence || null,
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
  kind: "MODEL_GENERATION" | "MARKET_TRIM";
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

export async function createDraft(args: {
  modelId: string; trimId: string; actor: string; pageReleaseId: string; defaultEvidence?: EvidenceRecord;
}): Promise<string> {
  const id = newSessionId();
  const { error } = await db().from("admin_edit_sessions").insert({
    id, kind: "SPEC_DRAFT", status: "DRAFT", model_id: args.modelId, trim_id: args.trimId,
    actor: args.actor, page_release_id: args.pageReleaseId, draft_entries: [],
    default_evidence: args.defaultEvidence || null,
    expires_at: new Date(Date.now() + SESSION_TTL_MS).toISOString(),
  });
  if (error) throw error;
  return id;
}

/** Loads a live (not expired), owned session in the given status. Returns
 * null for every failure mode alike (wrong owner, expired, wrong status, or
 * genuinely missing) -- the caller should show one generic "not found or
 * expired" message rather than a signal an attacker could use to probe for
 * other admins' proposal ids. */
async function loadOwned(id: string, actor: string, status: "DRAFT" | "PENDING_REVIEW"): Promise<EditSessionRow | null> {
  if (!id || !actor) return null;
  const { data, error } = await db().from("admin_edit_sessions")
    .select("*").eq("id", id).eq("actor", actor).eq("status", status)
    .gt("expires_at", new Date().toISOString()).maybeSingle();
  if (error) throw error;
  return data ? fromRow(data) : null;
}

export async function loadDraft(id: string, actor: string): Promise<EditSessionRow | null> {
  return loadOwned(id, actor, "DRAFT");
}

/** All of this admin's still-open (not expired) spec drafts for a model, so
 * the workspace page can surface a draft in progress even if the admin
 * navigates back to it without the `?draft=` redirect param (closed tab,
 * bookmarked link, etc). */
export async function listOpenDraftsForModel(modelId: string, actor: string): Promise<EditSessionRow[]> {
  if (!actor) return [];
  const { data, error } = await db().from("admin_edit_sessions")
    .select("*").eq("model_id", modelId).eq("actor", actor).eq("status", "DRAFT")
    .gt("expires_at", new Date().toISOString()).order("created_at", { ascending: true });
  if (error) throw error;
  return (data || []).map(fromRow);
}

export async function loadProposal(id: string, actor: string): Promise<EditSessionRow | null> {
  return loadOwned(id, actor, "PENDING_REVIEW");
}

export async function upsertDraftEntry(
  id: string, actor: string, entry: SpecDraftEntryRecord, defaultEvidence: EvidenceRecord,
): Promise<EditSessionRow> {
  const draft = await loadDraft(id, actor);
  if (!draft) throw new Error("draft session หมดอายุหรือไม่พบ — กรุณาเริ่ม spec draft ใหม่");
  const entries = draft.draftEntries.filter((row) => row.fieldKey !== entry.fieldKey);
  entries.push(entry);
  const { data, error } = await db().from("admin_edit_sessions")
    .update({
      draft_entries: entries, default_evidence: defaultEvidence, updated_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + SESSION_TTL_MS).toISOString(),
    })
    .eq("id", id).eq("actor", actor).eq("status", "DRAFT")
    .select("*").maybeSingle();
  if (error) throw error;
  if (!data) throw new Error("draft session หมดอายุหรือไม่พบ — กรุณาเริ่ม spec draft ใหม่");
  return fromRow(data);
}

export async function removeDraftEntry(id: string, actor: string, fieldKey: string): Promise<EditSessionRow> {
  const draft = await loadDraft(id, actor);
  if (!draft) throw new Error("draft session หมดอายุหรือไม่พบ — กรุณาเริ่ม spec draft ใหม่");
  const entries = draft.draftEntries.filter((row) => row.fieldKey !== fieldKey);
  const { data, error } = await db().from("admin_edit_sessions")
    .update({ draft_entries: entries, updated_at: new Date().toISOString() })
    .eq("id", id).eq("actor", actor).eq("status", "DRAFT")
    .select("*").maybeSingle();
  if (error) throw error;
  if (!data) throw new Error("draft session หมดอายุหรือไม่พบ — กรุณาเริ่ม spec draft ใหม่");
  return fromRow(data);
}

export async function discardDraft(id: string, actor: string): Promise<void> {
  const { error } = await db().from("admin_edit_sessions").delete().eq("id", id).eq("actor", actor).eq("status", "DRAFT");
  if (error) throw error;
}

/** Transitions a SPEC_DRAFT from mutable DRAFT to immutable PENDING_REVIEW.
 * Conditioned on (id, actor, status='DRAFT') in one UPDATE so a draft can
 * only ever be promoted once even under a double submit. */
export async function promoteDraftToProposal(
  id: string, actor: string,
  compiled: { batchPayload: Record<string, unknown>; diff: unknown[]; reason: string; evidence: EvidenceRecord },
): Promise<string> {
  const { data, error } = await db().from("admin_edit_sessions")
    .update({
      status: "PENDING_REVIEW", batch_payload: compiled.batchPayload, diff: compiled.diff,
      reason: compiled.reason, evidence: compiled.evidence, updated_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + SESSION_TTL_MS).toISOString(),
    })
    .eq("id", id).eq("actor", actor).eq("status", "DRAFT")
    .select("id").maybeSingle();
  if (error) throw error;
  if (!data) throw new Error("draft session หมดอายุหรือไม่พบ — กรุณาเริ่ม spec draft ใหม่");
  return data.id as string;
}

/** Consumes a proposal exactly once: an atomic conditional UPDATE, not a
 * read-then-write, so a duplicate confirm (double click, retried request)
 * can never queue the same proposal twice. Returns null for any failure
 * (wrong owner, expired, already consumed, missing) -- callers must fail
 * closed on null, never assume "already applied, fine to skip". */
export async function consumeProposal(id: string, actor: string): Promise<EditSessionRow | null> {
  const { data, error } = await db().from("admin_edit_sessions")
    .update({ status: "CONSUMED", consumed_at: new Date().toISOString(), updated_at: new Date().toISOString() })
    .eq("id", id).eq("actor", actor).eq("status", "PENDING_REVIEW")
    .gt("expires_at", new Date().toISOString())
    .select("*").maybeSingle();
  if (error) throw error;
  return data ? fromRow(data) : null;
}
