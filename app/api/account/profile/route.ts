import { NextRequest, NextResponse } from "next/server";
import { resolveAccessContext, evaluateAndPersistActivation, AccessPolicyError } from "@/lib/access-policy-server";
import { recordEvent } from "@/lib/telemetry";
import { MARKETING_CONSENT_TEXT, MARKETING_CONSENT_VERSION } from "@/lib/consent";
import { planProfileUpdate } from "@/lib/profile-update";

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

  try {
    const ctx = await resolveAccessContext(accessToken);

    const { data: existing } = await ctx.db.from("tdr_customer_profiles")
      .select("user_id,is_individual,postcode,company_name,profile_completed_at")
      .eq("user_id", ctx.userId).maybeSingle();
    const isFirstProfile = !existing;

    const now = new Date().toISOString();
    // What this save changes is decided in one place, from the request and
    // the row it is being applied to -- see lib/profile-update.ts. Only
    // what the request actually sends is written, and "complete" means the
    // profile is complete, not that somebody edited something.
    const plan = planProfileUpdate(body, existing, now, MARKETING_CONSENT_VERSION);
    if (plan.error) return NextResponse.json({ error: plan.error }, { status: 400 });

    const { data: customer } = await ctx.db.from("tdr_customers")
      .select("id").eq("auth_user_id", ctx.userId).maybeSingle();

    const update: Record<string, unknown> = {
      user_id: ctx.userId,
      customer_id: customer?.id ?? null,
      email: ctx.email,
      updated_at: now,
      ...plan.changes,
    };

    const { error } = await ctx.db.from("tdr_customer_profiles").upsert(update, { onConflict: "user_id" });
    if (error) return NextResponse.json({ error: "could not save profile" }, { status: 503 });

    if (isFirstProfile) await recordEvent({ eventName: "account_created", userId: ctx.userId, customerId: customer?.id ?? null });
    // Once, when the profile becomes complete. Firing on every edit made
    // the funnel count the same member as completing their profile again
    // every time they changed a field.
    if (plan.justCompleted) {
      await recordEvent({
        eventName: "profile_completed", userId: ctx.userId, customerId: customer?.id ?? null,
        props: { fields: Object.keys(body), is_individual: plan.isIndividual },
      });
    }

    const activation = await evaluateAndPersistActivation(ctx);
    return NextResponse.json({
      ok: true, activation, saved: plan.touched, profile_complete: plan.profileComplete,
    }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof AccessPolicyError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("profile save error", error);
    return NextResponse.json({ error: "could not save profile" }, { status: 500 });
  }
}
