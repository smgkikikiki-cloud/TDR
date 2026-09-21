import { NextRequest, NextResponse } from "next/server";
import { resolveAccessContext, evaluateAndPersistActivation, AccessPolicyError } from "@/lib/access-policy-server";
import { recordEvent } from "@/lib/telemetry";
import { MARKETING_CONSENT_TEXT, MARKETING_CONSENT_VERSION } from "@/lib/consent";

export const dynamic = "force-dynamic";

function bearer(request: NextRequest) {
  const match = /^Bearer\s+(.+)$/i.exec(request.headers.get("authorization") || "");
  return match?.[1] || null;
}

export async function GET(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  try {
    const ctx = await resolveAccessContext(accessToken);
    const [{ data: profile, error: profileError }, activation] = await Promise.all([
      ctx.db.from("tdr_customer_profiles")
        .select("postcode,is_individual,company_name,marketing_consent,marketing_consent_at,profile_completed_at,activation_completed_at")
        .eq("user_id", ctx.userId).maybeSingle(),
      evaluateAndPersistActivation(ctx),
    ]);
    if (profileError) return NextResponse.json({ error: "could not load profile" }, { status: 503 });

    return NextResponse.json({
      profile: profile ?? null,
      activation,
      marketing_consent_text: MARKETING_CONSENT_TEXT,
    }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof AccessPolicyError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("profile status error", error);
    return NextResponse.json({ error: "could not load profile" }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  const accessToken = bearer(request);
  if (!accessToken) return NextResponse.json({ error: "member bearer token required" }, { status: 401 });

  let body: Record<string, unknown> = {};
  try { body = await request.json(); } catch {}

  // Enrichment, not a form to complete: a member may save a postcode and
  // leave the rest, or save nothing at all. Only a value that is actually
  // present has to be well formed, because storing a malformed postcode
  // helps nobody -- an absent one costs nothing.
  const postcode = typeof body.postcode === "string" ? body.postcode.trim() : "";
  if (postcode && !/^[0-9]{4,10}$/.test(postcode)) {
    return NextResponse.json({ error: "postcode must be 4-10 digits" }, { status: 400 });
  }
  const isIndividual = body.is_individual !== false; // default: individual / not affiliated
  const companyName = typeof body.company_name === "string" ? body.company_name.trim() : "";
  // Optional, unchecked-by-default marketing consent. Account creation and
  // profile completion must both work with this left false.
  const marketingConsent = body.marketing_consent === true;

  try {
    const ctx = await resolveAccessContext(accessToken);

    const { data: existing } = await ctx.db.from("tdr_customer_profiles")
      .select("user_id").eq("user_id", ctx.userId).maybeSingle();
    const isFirstProfile = !existing;

    const { data: customer } = await ctx.db.from("tdr_customers")
      .select("id").eq("auth_user_id", ctx.userId).maybeSingle();

    const now = new Date().toISOString();
    const update: Record<string, unknown> = {
      user_id: ctx.userId,
      customer_id: customer?.id ?? null,
      email: ctx.email,
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

    const { error } = await ctx.db.from("tdr_customer_profiles").upsert(update, { onConflict: "user_id" });
    if (error) return NextResponse.json({ error: "could not save profile" }, { status: 503 });

    if (isFirstProfile) await recordEvent({ eventName: "account_created", userId: ctx.userId, customerId: customer?.id ?? null });
    await recordEvent({ eventName: "profile_completed", userId: ctx.userId, customerId: customer?.id ?? null, props: { marketing_consent: marketingConsent, is_individual: isIndividual } });

    const activation = await evaluateAndPersistActivation(ctx);
    return NextResponse.json({ ok: true, activation }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof AccessPolicyError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("profile save error", error);
    return NextResponse.json({ error: "could not save profile" }, { status: 500 });
  }
}
