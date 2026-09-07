import crypto from "node:crypto";
import { cookies } from "next/headers";

const COOKIE = "tdr_admin_session";
const MAX_AGE_MS = 1000 * 60 * 60 * 24 * 30;
const NAME_RE = /^[A-Za-z0-9฀-๿ _.@-]{1,40}$/;

export type AdminEditor = { name: string };

/** No fallback secret. A build with ADMIN_SESSION_SECRET unset cannot mint or
 *  accept a session at all — a shipped default would let anyone who reads the
 *  repository forge an admin cookie. */
function sessionSecret(): string | null {
  const s = process.env.ADMIN_SESSION_SECRET;
  return s && s.length >= 16 ? s : null;
}

export function hasSessionSecret() {
  return sessionSecret() !== null;
}

function signature(payload: string, key: string) {
  return crypto.createHmac("sha256", key).update(payload).digest("hex");
}

/** Compare two secrets without leaking their length or a prefix match. */
function sameSecret(a: string, b: string) {
  const ha = crypto.createHash("sha256").update(a).digest();
  const hb = crypto.createHash("sha256").update(b).digest();
  return crypto.timingSafeEqual(ha, hb);
}

/** TDR_ADMIN_USERS="somchai:pass1,nan:pass2" — one password per editor, so the
 *  session can say who is editing. Falls back to the single TDR_ADMIN_PASSWORD. */
function namedEditors(): Map<string, string> | null {
  const raw = process.env.TDR_ADMIN_USERS;
  if (!raw) return null;
  const out = new Map<string, string>();
  for (const pair of raw.split(",")) {
    const i = pair.indexOf(":");
    if (i <= 0) continue;
    const name = pair.slice(0, i).trim();
    const password = pair.slice(i + 1);
    if (name && password) out.set(name, password);
  }
  return out.size ? out : null;
}

/** Returns the editor name to record, or null when the credentials do not match. */
export function authenticate(name: string | null, password: string | null): string | null {
  if (!password) return null;
  const given = (name || "").trim();
  const users = namedEditors();

  if (users) {
    const expected = users.get(given);
    // Still hash on the miss so a wrong name and a wrong password cost the same.
    if (!expected) { sameSecret(password, " no-such-editor"); return null; }
    return sameSecret(password, expected) ? given : null;
  }

  const single = process.env.TDR_ADMIN_PASSWORD;
  if (!single) return null;
  if (!sameSecret(password, single)) return null;
  // One shared password: the name is a label the editor types, not an identity
  // the server verified. Enough to show who is in, not an audit trail.
  return NAME_RE.test(given) ? given : "editor";
}

export function makeAdminToken(name: string) {
  const key = sessionSecret();
  if (!key) throw new Error("ADMIN_SESSION_SECRET is not set");
  const payload = `admin:${encodeURIComponent(name)}:${Date.now()}`;
  return `${Buffer.from(payload).toString("base64url")}.${signature(payload, key)}`;
}

export function readAdminToken(token?: string): AdminEditor | null {
  const key = sessionSecret();
  if (!key || !token) return null;
  const [encoded, sig] = token.split(".");
  if (!encoded || !sig) return null;
  try {
    const payload = Buffer.from(encoded, "base64url").toString("utf8");
    const expected = signature(payload, key);
    if (sig.length !== expected.length) return null;
    if (!crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) return null;
    const parts = payload.split(":");
    if (parts.length !== 3 || parts[0] !== "admin") return null;
    const age = Date.now() - Number(parts[2]);
    if (!(age >= 0 && age < MAX_AGE_MS)) return null;
    const name = decodeURIComponent(parts[1]);
    return { name: NAME_RE.test(name) ? name : "editor" };
  } catch {
    return null;
  }
}

export function verifyAdminToken(token?: string) {
  return readAdminToken(token) !== null;
}

export async function currentEditor(): Promise<AdminEditor | null> {
  const store = await cookies();
  return readAdminToken(store.get(COOKIE)?.value);
}

export async function isAdmin() {
  return (await currentEditor()) !== null;
}

export async function setAdminCookie(name: string) {
  const store = await cookies();
  store.set(COOKIE, makeAdminToken(name), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: MAX_AGE_MS / 1000,
  });
}

export async function clearAdminCookie() {
  const store = await cookies();
  store.delete(COOKIE);
}
