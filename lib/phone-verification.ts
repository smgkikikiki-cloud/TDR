// TDR-owned phone verification reservation/binding layer
// (tdr_phone_verification_attempts, migration_v34).
//
// Why this exists: Supabase resolves phone-change OTP verification
// (auth.updateUser({phone}) + auth.verifyOtp({type:"phone_change"}))
// through auth.users.phone_change, which is NOT a unique column. Two
// different pending auth users could in principle carry the same
// phone_change value, so a phone-change OTP is not, by itself, sufficient
// proof that THIS TDR account is the one that completed verification.
// TDR reserves the (user, phone) pair before the SMS is ever sent, then
// independently re-reads the CALLER'S OWN current Supabase Auth state
// (never a client claim) after the client says verifyOtp succeeded, and
// only grants TDR-side confirmation when that caller's own auth user id,
// confirmed phone, and confirmation flag all match the reservation. See
// lib/access-policy-server.ts::hasTdrConfirmedPhoneVerification for how
// this gates activation.
//
// tdr_customer_phone_identities (migration_v21) remains the canonical
// verified-phone ledger, synced automatically by the existing
// tdr_sync_customer_from_auth trigger -- this module never writes to it
// directly, it only reads it to check for cross-account phone reuse and
// to confirm the trigger has caught up.
import { adminDb } from "@/lib/supabase";

export class PhoneVerificationError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const E164_RE = /^\+[1-9][0-9]{7,14}$/;
const RESERVATION_TTL_MS = 10 * 60 * 1000;

function requireDb() {
  const db = adminDb();
  if (!db) throw new PhoneVerificationError(503, "phone verification database is not configured");
  return db;
}

async function requireUser(db: NonNullable<ReturnType<typeof adminDb>>, accessToken: string) {
  const { data, error } = await db.auth.getUser(accessToken);
  if (error || !data.user) throw new PhoneVerificationError(401, "invalid or expired member session");
  return data.user;
}

async function customerIdFor(db: NonNullable<ReturnType<typeof adminDb>>, userId: string): Promise<string> {
  const { data: existing, error } = await db.from("tdr_customers").select("id").eq("auth_user_id", userId).maybeSingle();
  if (error) throw new PhoneVerificationError(503, "could not resolve customer identity");
  if (existing) return existing.id as string;
  const created = await db.from("tdr_customers").insert({ auth_user_id: userId }).select("id").single();
  if (created.error) throw new PhoneVerificationError(503, "could not create customer identity");
  return created.data.id as string;
}

export interface PhoneReservation {
  expiresAt: string;
}

// Step 1: reserve (user, phone) BEFORE the browser ever calls
// supabase.auth.updateUser({phone}). Fails closed if the phone is already
// a verified identity on a different TDR account, or already has an
// active (pending or confirmed) reservation belonging to someone else --
// enforced both here and at the database level (a partial unique index on
// tdr_phone_verification_attempts(phone_e164) where status in
// ('PENDING','CONFIRMED')), so this is race-safe even under concurrent
// requests, not just a check-then-act client-side race.
export async function reservePhoneVerification(accessToken: string, rawPhone: string): Promise<PhoneReservation> {
  const db = requireDb();
  const user = await requireUser(db, accessToken);

  const phone = rawPhone.trim();
  if (!E164_RE.test(phone)) throw new PhoneVerificationError(400, "phone must be a valid E.164 number");

  const customerId = await customerIdFor(db, user.id);

  const { data: existingIdentity, error: identityError } = await db
    .from("tdr_customer_phone_identities")
    .select("customer_id")
    .eq("phone_e164", phone)
    .eq("is_primary", true)
    .is("revoked_at", null)
    .maybeSingle();
  if (identityError) throw new PhoneVerificationError(503, "could not check phone availability");
  if (existingIdentity && existingIdentity.customer_id !== customerId) {
    throw new PhoneVerificationError(409, "this phone number is already verified on another TDR account");
  }

  // Best-effort lazy cleanup: expire this user's own stale attempts and
  // any globally abandoned PENDING rows, so a long-abandoned reservation
  // never permanently blocks the phone for anyone. See
  // tdr_expire_stale_phone_verification_attempts() in migration_v34 --
  // errors here are non-fatal, the insert below still fails closed via
  // the partial unique index if cleanup didn't run.
  try {
    await db.rpc("tdr_expire_stale_phone_verification_attempts");
  } catch {
    // best-effort; the insert below still fails closed via the partial
    // unique index if this cleanup pass didn't run.
  }

  const { error: cancelError } = await db
    .from("tdr_phone_verification_attempts")
    .update({ status: "CANCELLED", updated_at: new Date().toISOString() })
    .eq("user_id", user.id)
    .eq("status", "PENDING");
  if (cancelError) throw new PhoneVerificationError(503, "could not reset previous phone verification attempt");

  const expiresAt = new Date(Date.now() + RESERVATION_TTL_MS).toISOString();
  const { error: insertError } = await db.from("tdr_phone_verification_attempts").insert({
    user_id: user.id,
    customer_id: customerId,
    phone_e164: phone,
    status: "PENDING",
    expires_at: expiresAt,
  });
  if (insertError) {
    if ((insertError as { code?: string }).code === "23505") {
      throw new PhoneVerificationError(409, "this phone number is currently being verified on another TDR account");
    }
    throw new PhoneVerificationError(503, "could not start phone verification");
  }

  return { expiresAt };
}

export interface PhoneConfirmation {
  phone: string;
  confirmedAt: string;
}

// Step 2: called AFTER the browser's own supabase.auth.verifyOtp(...)
// call reports success. Never trusts that client-reported success by
// itself -- independently re-reads the CALLER'S OWN current Supabase Auth
// user via their own access token and proves all four of: (1) same user
// as the reservation owner (true by construction, since the reservation
// is looked up BY this user id), (2) the currently confirmed Auth phone
// exactly equals the reserved phone, (3) that phone is actually
// Supabase-confirmed, (4) the reservation has not expired. Only then is
// the reservation marked CONFIRMED.
export async function confirmPhoneVerification(accessToken: string): Promise<PhoneConfirmation> {
  const db = requireDb();
  const user = await requireUser(db, accessToken);

  const { data: reservation, error: reservationError } = await db
    .from("tdr_phone_verification_attempts")
    .select("id,phone_e164,expires_at")
    .eq("user_id", user.id)
    .eq("status", "PENDING")
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (reservationError) throw new PhoneVerificationError(503, "could not load phone verification status");
  if (!reservation) throw new PhoneVerificationError(404, "no pending phone verification found -- start again from /member/profile");

  if (new Date(reservation.expires_at).getTime() <= Date.now()) {
    await db.from("tdr_phone_verification_attempts")
      .update({ status: "EXPIRED", updated_at: new Date().toISOString() })
      .eq("id", reservation.id);
    throw new PhoneVerificationError(410, "phone verification expired -- request a new code");
  }

  const currentPhone = user.phone || null;
  const currentPhoneConfirmed = Boolean(user.phone_confirmed_at);
  if (!currentPhoneConfirmed || currentPhone !== reservation.phone_e164) {
    throw new PhoneVerificationError(
      409,
      "the confirmed phone on this account does not match the number reserved -- verify the OTP was sent to and confirmed for the reserved number",
    );
  }

  const confirmedAt = new Date().toISOString();
  const { error: confirmError } = await db.from("tdr_phone_verification_attempts")
    .update({ status: "CONFIRMED", confirmed_at: confirmedAt, updated_at: confirmedAt })
    .eq("id", reservation.id);
  if (confirmError) throw new PhoneVerificationError(503, "could not confirm phone verification");

  return { phone: reservation.phone_e164, confirmedAt };
}
