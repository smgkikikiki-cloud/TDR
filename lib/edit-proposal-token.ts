/**
 * Signed, opaque, short-lived carrier for the "review before queue" step of
 * the Canonical Vehicle Editor: a prepare-* server action computes the full
 * canonical command payload and a human-readable diff, signs both into this
 * token, and redirects to a review page that can only act on a token it can
 * still verify. Nothing is written to Supabase until the review page's
 * confirm action re-verifies the token AND re-checks the release fingerprint
 * against live state (see lib/canonical-command-builder.ts's isStaleRelease).
 *
 * Reuses the HMAC-over-base64url pattern lib/admin-auth.ts already uses for
 * the admin session cookie, keyed by the same ADMIN_SESSION_SECRET so no new
 * secret needs provisioning. No "@/" alias imports — see
 * lib/canonical-command-builder.ts's header for why that matters for tests.
 */
import crypto from "node:crypto";
import type { CanonicalBatchPayload, DiffRow, Evidence } from "./canonical-command-builder";

export type EditProposalKind = "MODEL_GENERATION" | "MARKET_TRIM" | "SPEC_FACT";

export type EditProposal = {
  kind: EditProposalKind;
  modelId: string;
  /** release_id the editor page was rendered against — the stale-edit fingerprint. */
  pageReleaseId: string;
  batchPayload: CanonicalBatchPayload;
  diff: DiffRow[];
  reason: string;
  evidence: Evidence;
  actor: string;
  createdAt: number;
};

const MAX_AGE_MS = 1000 * 60 * 20; // 20 minutes: long enough to read a diff, short enough to bound staleness exposure.

function secret(): string | null {
  const value = process.env.ADMIN_SESSION_SECRET;
  return value && value.length >= 16 ? value : null;
}

function sign(payload: string, key: string): string {
  return crypto.createHmac("sha256", key).update(payload).digest("hex");
}

export function hasProposalSigningSecret(): boolean {
  return secret() !== null;
}

export function signEditProposal(proposal: Omit<EditProposal, "createdAt">): string {
  const key = secret();
  if (!key) throw new Error("ADMIN_SESSION_SECRET is not set");
  const full: EditProposal = { ...proposal, createdAt: Date.now() };
  const encoded = Buffer.from(JSON.stringify(full)).toString("base64url");
  return `${encoded}.${sign(encoded, key)}`;
}

export function verifyEditProposal(token: string | null | undefined): EditProposal | null {
  const key = secret();
  if (!key || !token) return null;
  const dot = token.indexOf(".");
  if (dot <= 0) return null;
  const encoded = token.slice(0, dot);
  const providedSig = token.slice(dot + 1);
  const expectedSig = sign(encoded, key);
  if (providedSig.length !== expectedSig.length) return null;
  if (!crypto.timingSafeEqual(Buffer.from(providedSig), Buffer.from(expectedSig))) return null;
  try {
    const proposal = JSON.parse(Buffer.from(encoded, "base64url").toString("utf8")) as EditProposal;
    const age = Date.now() - Number(proposal.createdAt);
    if (!(age >= 0 && age < MAX_AGE_MS)) return null;
    if (!proposal.kind || !proposal.modelId || !proposal.batchPayload) return null;
    return proposal;
  } catch {
    return null;
  }
}
