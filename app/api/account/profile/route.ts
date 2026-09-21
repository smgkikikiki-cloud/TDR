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

  // Enrichment, edited a field at a time. Only what the request actually
  // sends is written: a member updating their postcode is not also saying
  // they withdrew marketing consent and are no longer a company, and a
  // body that omits a key must leave that key exactly as it was. Presence
  // is what counts, so an explicit false or empty string still writes --
  // clearing a field is an edit, omitting it is not.
  const sent = (key: string) => Object.prototype.hasOwnProperty.call(body, key);

  if (sent("postcode")) {
    const postcode = typeof body.postcode === "string" ? body.postcode.trim() : "";
    if (postcode && !/^[0-9]{4,10}$/.test(postcode)) {
      return NextResponse.json({ error: "postcode must be 4-10 digits" }, { status: 400 });
    }
  }

  try {
    const ctx = await resolveAccessContext(accessToken);

    const { data: existing } = await ctx.db.from("tdr_customer_profiles")
      .select("user_id,is_individual").eq("user_id", ctx.userId).maybeSingle();
    const isFirstProfile = !existing;

    const { data: customer } = await ctx.db.from("tdr_customers")
      .select("id").eq("auth_user_id", ctx.userId).maybeSingle();

    const now = new Date().toISOString();
    const update: Record<string, unknown> = {
      user_id: ctx.userId,
      customer_id: customer?.id ?? null,
      email: ctx.email,
      updated_at: now,
    };
    if (sent("postcode")) {
      update.postcode = typeof body.postcode === "string" ? body.postcode.trim() : null;
    }
    if (sent("is_individual")) update.is_individual = body.is_individual !== false;
    // Company name belongs to a company account, so declaring yourself an
    // individual clears it -- that is the edit, not a side effect of an
    // unrelated one. Whether this is a company account is read from the
    // request when it says, and from the stored row when it does not.
    const isIndividual = sent("is_individual")
      ? body.is_individual !== false
      : existing?.is_individual !== false;
    if (sent("company_name") || sent("is_individual")) {
      const companyName = typeof body.company_name === "string" ? body.company_name.trim() : "";
      update.company_name = isIndividual ? null : (companyName || null);
    }
    if (sent("marketing_consent")) {
      const marketingConsent = body.marketing_consent === true;
      update.marketing_consent = marketingConsent;
      if (marketingConsent) {
        update.marketing_consent_at = now;
        update.marketing_consent_version = MARKETING_CONSENT_VERSION;
      }
    }
    // Only a request that carried something counts as having filled the
    // profile in; an empty body must not stamp it as done.
    const touchedFields = Object.keys(update).length > 4;
    if (touchedFields) update.profile_completed_at = now;

    const { error } = await ctx.db.from("tdr_customer_profiles").upsert(update, { onConflict: "user_id" });
    if (error) return NextResponse.json({ error: "could not save profile" }, { status: 503 });

    if (isFirstProfile) await recordEvent({ eventName: "account_created", userId: ctx.userId, customerId: customer?.id ?? null });
    if (touchedFields) {
      await recordEvent({
        eventName: "profile_completed", userId: ctx.userId, customerId: customer?.id ?? null,
        props: { fields: Object.keys(body), is_individual: isIndividual },
      });
    }

    const activation = await evaluateAndPersistActivation(ctx);
    return NextResponse.json({ ok: true, activation }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    if (error instanceof AccessPolicyError) return NextResponse.json({ error: error.message }, { status: error.status });
    console.error("profile save error", error);
    return NextResponse.json({ error: "could not save profile" }, { status: 500 });
  }
}
