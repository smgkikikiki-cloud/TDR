import crypto from "node:crypto";
import { headers } from "next/headers";
import { adminDb } from "@/lib/supabase";

const LOCKOUT_SECONDS = 15 * 60;

function rateLimitSecret() {
  const value = process.env.ADMIN_SESSION_SECRET;
  return value && value.length >= 16 ? value : null;
}

async function requestKeyHash() {
  const secret = rateLimitSecret();
  if (!secret) return null;

  const requestHeaders = await headers();
  const forwardedFor = requestHeaders.get("x-forwarded-for");
  const clientIp = (forwardedFor?.split(",")[0]?.trim() || requestHeaders.get("x-real-ip")?.trim() || "unknown").slice(0, 128);

  // Never persist a raw client IP. The same secret that protects admin sessions
  // also makes this lookup key opaque to anyone reading the database.
  return crypto.createHmac("sha256", secret).update(`admin-login:${clientIp}`).digest("hex");
}

export async function checkAdminLoginRateLimit(): Promise<{ allowed: boolean; retryAfterSeconds: number }> {
  const keyHash = await requestKeyHash();
  const db = adminDb();
  if (!keyHash || !db) return { allowed: false, retryAfterSeconds: LOCKOUT_SECONDS };

  const { data, error } = await db.rpc("tdr_admin_login_rate_check", { p_key_hash: keyHash });
  if (error) return { allowed: false, retryAfterSeconds: LOCKOUT_SECONDS };

  const row = Array.isArray(data) ? data[0] : data;
  return {
    allowed: Boolean(row?.allowed),
    retryAfterSeconds: Number(row?.retry_after_seconds || 0),
  };
}

export async function recordAdminLoginFailure() {
  const keyHash = await requestKeyHash();
  const db = adminDb();
  if (!keyHash || !db) return;
  await db.rpc("tdr_admin_login_rate_record_failure", { p_key_hash: keyHash });
}

export async function clearAdminLoginFailures() {
  const keyHash = await requestKeyHash();
  const db = adminDb();
  if (!keyHash || !db) return;
  await db.rpc("tdr_admin_login_rate_clear", { p_key_hash: keyHash });
}
