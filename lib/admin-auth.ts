import crypto from "node:crypto";
import { cookies } from "next/headers";

const COOKIE = "tdr_admin_session";

function signature(payload: string) {
  const secret = process.env.ADMIN_SESSION_SECRET || "dev-only-change-me";
  return crypto.createHmac("sha256", secret).update(payload).digest("hex");
}

export function makeAdminToken() {
  const payload = `admin:${Date.now()}`;
  return `${Buffer.from(payload).toString("base64url")}.${signature(payload)}`;
}

export function verifyAdminToken(token?: string) {
  if (!token) return false;
  const [encoded, sig] = token.split(".");
  if (!encoded || !sig) return false;
  try {
    const payload = Buffer.from(encoded, "base64url").toString("utf8");
    const expected = signature(payload);
    if (sig.length !== expected.length || !crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) return false;
    const [, timestamp] = payload.split(":");
    const age = Date.now() - Number(timestamp);
    return payload.startsWith("admin:") && age >= 0 && age < 1000 * 60 * 60 * 24 * 30;
  } catch {
    return false;
  }
}

export async function isAdmin() {
  const store = await cookies();
  return verifyAdminToken(store.get(COOKIE)?.value);
}

export async function setAdminCookie() {
  const store = await cookies();
  store.set(COOKIE, makeAdminToken(), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
}

export async function clearAdminCookie() {
  const store = await cookies();
  store.delete(COOKIE);
}
