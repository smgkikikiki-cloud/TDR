import { NextRequest, NextResponse } from "next/server";
import { adminDb } from "@/lib/supabase";
import { recordEvent } from "@/lib/telemetry";
import { MARKETING_CONSENT_TEXT, MARKETING_CONSENT_VERSION } from "@/lib/consent";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

async function requireUser(accessToken: string) {
  const db = adminDb();
  if (!db) throw new Error("account database is not configured");
  const { data, error } = await db.auth.getUser(accessToken);
  if (error || !data.user) return null;
  return { db, userId: data.user.id, email: data.user.email ?? null };
}

export async function GET(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });
  const auth = await requireUser(accessToken);
  if (!auth) return NextResponse.json({ error: "invalid or expired member session" }, { status: 401 });

  const { data, error } = await auth.db.from("tdr_customer_profiles")
    .select("postcode,is_individual,company_name,marketing_consent,marketing_consent_at,profile_completed_at")
    .eq("user_id", auth.userId).maybeSingle();
  if (error) return NextResponse.json({ error: "could not load profile" }, { status: 503 });

  return NextResponse.json({
    profile: data ?? null,
    marketing_consent_text: MARKETING_CONSENT_TEXT,
  }, { headers: { "Cache-Control": "private, no-store" } });
}

export async function POST(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });
  const auth = await requireUser(accessToken);
  if (!auth) return NextResponse.json({ error: "invalid or expired member session" }, { status: 401 });

  let body: Record<string, unknown> = {};
  try { body = await request.json(); } catch {}

  const postcode = typeof body.postcode === "string" ? body.postcode.trim() : "";
  if (!/^[0-9]{4,10}$/.test(postcode)) {
    return NextResponse.json({ error: "postcode must be 4-10 digits" }, { status: 400 });
  }
  const isIndividual = body.is_individual !== false; // default: individual / not affiliated
  const companyName = typeof body.company_name === "string" ? body.company_name.trim() : "";
  if (!isIndividual && !companyName) {
    return NextResponse.json({ error: "company name is required unless this is an individual / not-affiliated account" }, { status: 400 });
  }
  // Optional, unchecked-by-default marketing consent. Account creation and
  // profile completion must both work with this left false.
  const marketingConsent = body.marketing_consent === true;

  const { data: existing } = await auth.db.from("tdr_customer_profiles")
    .select("user_id").eq("user_id", auth.userId).maybeSingle();
  const isFirstProfile = !existing;

  const now = new Date().toISOString();
  const update: Record<string, unknown> = {
    user_id: auth.userId,
    email: auth.email,
    postcode,
    is_individual: isIndividual,
    company_name: isIndividual ? null : companyName,
    profile_completed_at: now,
    updated_at: now,
  };
  if (marketingConsent) {
    update.marketing_consent = true;
    update.marketing_consent_at = now;
    update.marketing_consent_version = MARKETING_CONSENT_VERSION;
  } else {
    update.marketing_consent = false;
  }

  const { error } = await auth.db.from("tdr_customer_profiles").upsert(update, { onConflict: "user_id" });
  if (error) return NextResponse.json({ error: "could not save profile" }, { status: 503 });

  if (isFirstProfile) await recordEvent({ eventName: "account_created", userId: auth.userId });
  await recordEvent({ eventName: "profile_completed", userId: auth.userId, props: { marketing_consent: marketingConsent, is_individual: isIndividual } });

  return NextResponse.json({ ok: true }, { headers: { "Cache-Control": "private, no-store" } });
}
