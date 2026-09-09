import { createHmac, timingSafeEqual } from "node:crypto";
import { adminDb } from "@/lib/supabase";

export const REGISTRATION_PLAN = "registration_monthly";
export const REGISTRATION_PRODUCT = "registration_full";

export class BillingError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type StripeObject = Record<string, any>;

type MemberContext = {
  userId: string;
  email: string | null;
  phone: string | null;
};

function stripeSecret() {
  const secret = process.env.STRIPE_SECRET_KEY;
  if (!secret) throw new BillingError(503, "Stripe billing is not configured");
  return secret;
}

function registrationPriceId() {
  const price = process.env.STRIPE_PRICE_REGISTRATION_MONTHLY;
  if (!price) throw new BillingError(503, "registration subscription price is not configured");
  return price;
}

function asForm(params: Record<string, string | number | boolean | null | undefined>) {
  const form = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    form.set(key, String(value));
  }
  return form;
}

async function stripeRequest(path: string, params?: Record<string, string | number | boolean | null | undefined>, method = "POST") {
  const response = await fetch(`https://api.stripe.com${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${stripeSecret()}`,
      ...(params ? { "Content-Type": "application/x-www-form-urlencoded" } : {}),
    },
    body: params ? asForm(params).toString() : undefined,
    cache: "no-store",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = body?.error?.message || `Stripe request failed (${response.status})`;
    throw new BillingError(response.status >= 500 ? 502 : 400, message);
  }
  return body as StripeObject;
}

export async function requireMember(accessToken: string): Promise<MemberContext> {
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");

  const { data, error } = await db.auth.getUser(accessToken);
  if (error || !data.user) throw new BillingError(401, "invalid or expired member session");

  const phone = typeof data.user.user_metadata?.phone_e164 === "string"
    ? data.user.user_metadata.phone_e164
    : null;

  return { userId: data.user.id, email: data.user.email ?? null, phone };
}

async function customerProfile(userId: string) {
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");
  const { data, error } = await db
    .from("tdr_customer_profiles")
    .select("user_id,phone_e164,stripe_customer_id")
    .eq("user_id", userId)
    .maybeSingle();
  if (error) throw new BillingError(503, "could not load billing profile");
  return data;
}

async function ensureStripeCustomer(member: MemberContext) {
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");
  const profile = await customerProfile(member.userId);
  if (profile?.stripe_customer_id) return profile.stripe_customer_id as string;

  const customer = await stripeRequest("/v1/customers", {
    email: member.email,
    phone: profile?.phone_e164 || member.phone,
    "metadata[tdr_user_id]": member.userId,
  });

  const { error } = await db.from("tdr_customer_profiles").upsert({
    user_id: member.userId,
    phone_e164: profile?.phone_e164 || member.phone,
    stripe_customer_id: customer.id,
    updated_at: new Date().toISOString(),
  }, { onConflict: "user_id" });
  if (error) throw new BillingError(503, "could not save Stripe customer binding");
  return String(customer.id);
}

export async function createRegistrationCheckout(args: {
  accessToken: string;
  successUrl: string;
  cancelUrl: string;
}) {
  const member = await requireMember(args.accessToken);
  const customerId = await ensureStripeCustomer(member);
  const session = await stripeRequest("/v1/checkout/sessions", {
    mode: "subscription",
    customer: customerId,
    client_reference_id: member.userId,
    "line_items[0][price]": registrationPriceId(),
    "line_items[0][quantity]": 1,
    success_url: args.successUrl,
    cancel_url: args.cancelUrl,
    allow_promotion_codes: true,
    "phone_number_collection[enabled]": true,
    "metadata[tdr_user_id]": member.userId,
    "metadata[plan_code]": REGISTRATION_PLAN,
    "subscription_data[metadata][tdr_user_id]": member.userId,
    "subscription_data[metadata][plan_code]": REGISTRATION_PLAN,
  });
  if (!session.url) throw new BillingError(502, "Stripe Checkout did not return a redirect URL");
  return { id: session.id as string, url: session.url as string };
}

export async function createBillingPortal(args: { accessToken: string; returnUrl: string }) {
  const member = await requireMember(args.accessToken);
  const profile = await customerProfile(member.userId);
  if (!profile?.stripe_customer_id) throw new BillingError(409, "this account has no billing profile yet");

  const session = await stripeRequest("/v1/billing_portal/sessions", {
    customer: profile.stripe_customer_id,
    return_url: args.returnUrl,
    configuration: process.env.STRIPE_PORTAL_CONFIGURATION_ID || undefined,
  });
  if (!session.url) throw new BillingError(502, "Stripe portal did not return a redirect URL");
  return { url: session.url as string };
}

export async function getBillingStatus(accessToken: string) {
  const member = await requireMember(accessToken);
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");

  const [{ data: profile, error: profileError }, { data: subscription, error: subscriptionError }, { data: entitlement, error: entitlementError }] = await Promise.all([
    db.from("tdr_customer_profiles").select("phone_e164,stripe_customer_id").eq("user_id", member.userId).maybeSingle(),
    db.from("tdr_subscriptions").select("plan_code,status,current_period_end,cancel_at_period_end,provider").eq("user_id", member.userId).order("updated_at", { ascending: false }).limit(1).maybeSingle(),
    db.from("tdr_entitlements").select("product,status,valid_until").eq("user_id", member.userId).eq("product", REGISTRATION_PRODUCT).maybeSingle(),
  ]);
  if (profileError || subscriptionError || entitlementError) {
    throw new BillingError(503, "could not load billing status");
  }

  return {
    user: { id: member.userId, email: member.email, phone: profile?.phone_e164 || member.phone },
    customerBound: Boolean(profile?.stripe_customer_id),
    subscription: subscription ?? null,
    entitlement: entitlement ?? null,
    checkoutConfigured: Boolean(process.env.STRIPE_SECRET_KEY && process.env.STRIPE_PRICE_REGISTRATION_MONTHLY),
    portalConfigured: Boolean(process.env.STRIPE_SECRET_KEY),
  };
}

function safeCompareHex(left: string, right: string) {
  try {
    const a = Buffer.from(left, "hex");
    const b = Buffer.from(right, "hex");
    return a.length === b.length && timingSafeEqual(a, b);
  } catch {
    return false;
  }
}

export function verifyStripeWebhook(rawBody: string, signatureHeader: string | null) {
  const secret = process.env.STRIPE_WEBHOOK_SECRET;
  if (!secret) throw new BillingError(503, "Stripe webhook secret is not configured");
  if (!signatureHeader) throw new BillingError(400, "missing Stripe-Signature header");

  const parts = signatureHeader.split(",").map((part) => part.trim());
  const timestamp = parts.find((part) => part.startsWith("t="))?.slice(2);
  const signatures = parts.filter((part) => part.startsWith("v1=")).map((part) => part.slice(3));
  if (!timestamp || !signatures.length) throw new BillingError(400, "invalid Stripe-Signature header");

  const age = Math.abs(Date.now() / 1000 - Number(timestamp));
  if (!Number.isFinite(age) || age > 300) throw new BillingError(400, "stale Stripe webhook signature");

  const expected = createHmac("sha256", secret).update(`${timestamp}.${rawBody}`, "utf8").digest("hex");
  if (!signatures.some((signature) => safeCompareHex(signature, expected))) {
    throw new BillingError(400, "invalid Stripe webhook signature");
  }
}

function isoFromUnix(value: unknown) {
  const seconds = Number(value);
  return Number.isFinite(seconds) && seconds > 0 ? new Date(seconds * 1000).toISOString() : null;
}

function stripeSubscriptionId(object: StripeObject) {
  if (typeof object.subscription === "string") return object.subscription;
  if (typeof object.parent?.subscription_details?.subscription === "string") return object.parent.subscription_details.subscription;
  return null;
}

function metadataUserId(object: StripeObject) {
  return object.metadata?.tdr_user_id
    || object.subscription_details?.metadata?.tdr_user_id
    || object.parent?.subscription_details?.metadata?.tdr_user_id
    || object.client_reference_id
    || null;
}

function metadataPlan(object: StripeObject) {
  return object.metadata?.plan_code
    || object.subscription_details?.metadata?.plan_code
    || object.parent?.subscription_details?.metadata?.plan_code
    || REGISTRATION_PLAN;
}

async function upsertSubscriptionFromObject(object: StripeObject, userId: string | null) {
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");
  const subscriptionId = typeof object.id === "string" && object.object === "subscription"
    ? object.id
    : stripeSubscriptionId(object);
  if (!subscriptionId) return null;

  let effectiveUserId = userId;
  if (!effectiveUserId) {
    const { data } = await db.from("tdr_subscriptions").select("user_id").eq("provider", "stripe").eq("provider_subscription_id", subscriptionId).maybeSingle();
    effectiveUserId = data?.user_id ?? null;
  }
  if (!effectiveUserId) return null;

  const statusMap: Record<string, string> = {
    incomplete: "INCOMPLETE",
    incomplete_expired: "EXPIRED",
    trialing: "TRIALING",
    active: "ACTIVE",
    past_due: "PAST_DUE",
    unpaid: "UNPAID",
    canceled: "CANCELED",
    paused: "PAUSED",
  };

  const { error } = await db.from("tdr_subscriptions").upsert({
    user_id: effectiveUserId,
    provider: "stripe",
    provider_subscription_id: subscriptionId,
    plan_code: metadataPlan(object),
    product: REGISTRATION_PRODUCT,
    status: statusMap[String(object.status || "").toLowerCase()] || "INCOMPLETE",
    current_period_start: isoFromUnix(object.current_period_start),
    current_period_end: isoFromUnix(object.current_period_end),
    cancel_at_period_end: Boolean(object.cancel_at_period_end),
    updated_at: new Date().toISOString(),
  }, { onConflict: "provider,provider_subscription_id" });
  if (error) throw new BillingError(503, "could not save subscription state");
  return { userId: effectiveUserId, subscriptionId };
}

async function entitlementUserFromEvent(object: StripeObject) {
  const direct = metadataUserId(object);
  if (direct) return String(direct);
  const subscriptionId = stripeSubscriptionId(object);
  if (!subscriptionId) return null;
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");
  const { data } = await db.from("tdr_subscriptions").select("user_id").eq("provider", "stripe").eq("provider_subscription_id", subscriptionId).maybeSingle();
  return data?.user_id ?? null;
}

async function setEntitlement(userId: string, status: "ACTIVE" | "GRACE" | "EXPIRED", validUntil: string | null) {
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");
  const { error } = await db.from("tdr_entitlements").upsert({
    user_id: userId,
    product: REGISTRATION_PRODUCT,
    status,
    valid_until: validUntil,
    updated_at: new Date().toISOString(),
  }, { onConflict: "user_id,product" });
  if (error) throw new BillingError(503, "could not update member entitlement");
}

async function currentSubscriptionEnd(userId: string) {
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");
  const { data } = await db.from("tdr_subscriptions").select("current_period_end").eq("user_id", userId).order("updated_at", { ascending: false }).limit(1).maybeSingle();
  return data?.current_period_end ?? null;
}

function graceUntil() {
  const days = Number(process.env.TDR_BILLING_GRACE_DAYS || "0");
  if (!Number.isFinite(days) || days <= 0) return null;
  return new Date(Date.now() + Math.min(days, 30) * 86_400_000).toISOString();
}

export async function processStripeWebhook(event: StripeObject) {
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");
  if (!event?.id || !event?.type || !event?.data?.object) throw new BillingError(400, "invalid Stripe event payload");

  const object = event.data.object as StripeObject;
  const { error: insertError } = await db.from("tdr_billing_webhook_events").insert({
    provider: "stripe",
    event_id: event.id,
    event_type: event.type,
    object_id: object.id || null,
    status: "RECEIVED",
  });
  if (insertError?.code === "23505") return { duplicate: true };
  if (insertError) throw new BillingError(503, "could not record billing webhook");

  try {
    if (event.type === "checkout.session.completed") {
      const userId = metadataUserId(object);
      if (userId) {
        await db.from("tdr_customer_profiles").upsert({
          user_id: userId,
          phone_e164: object.customer_details?.phone || undefined,
          stripe_customer_id: typeof object.customer === "string" ? object.customer : undefined,
          updated_at: new Date().toISOString(),
        }, { onConflict: "user_id" });
        await upsertSubscriptionFromObject(object, String(userId));
      }
    }

    if (event.type.startsWith("customer.subscription.")) {
      const result = await upsertSubscriptionFromObject(object, metadataUserId(object));
      if (event.type === "customer.subscription.deleted" && result?.userId) {
        await setEntitlement(result.userId, "EXPIRED", new Date().toISOString());
      }
    }

    if (event.type === "invoice.paid") {
      const userId = await entitlementUserFromEvent(object);
      if (userId) {
        const periodEnd = isoFromUnix(object.lines?.data?.[0]?.period?.end) || await currentSubscriptionEnd(userId);
        await setEntitlement(userId, "ACTIVE", periodEnd);
      }
    }

    if (event.type === "invoice.payment_failed") {
      const userId = await entitlementUserFromEvent(object);
      if (userId) {
        const until = graceUntil();
        await setEntitlement(userId, until ? "GRACE" : "EXPIRED", until || new Date().toISOString());
      }
    }

    if (event.type === "payment_method.attached") {
      const customerId = typeof object.customer === "string" ? object.customer : null;
      if (customerId && object.id) {
        const { data: profile } = await db.from("tdr_customer_profiles").select("user_id").eq("stripe_customer_id", customerId).maybeSingle();
        if (profile?.user_id) {
          await db.from("tdr_payment_methods").upsert({
            provider: "stripe",
            provider_payment_method_id: object.id,
            user_id: profile.user_id,
            brand: object.card?.brand || null,
            last4: object.card?.last4 || null,
            exp_month: object.card?.exp_month || null,
            exp_year: object.card?.exp_year || null,
            updated_at: new Date().toISOString(),
          }, { onConflict: "provider,provider_payment_method_id" });
        }
      }
    }

    await db.from("tdr_billing_webhook_events").update({
      status: "PROCESSED",
      processed_at: new Date().toISOString(),
      error: null,
    }).eq("provider", "stripe").eq("event_id", event.id);
    return { duplicate: false };
  } catch (error) {
    await db.from("tdr_billing_webhook_events").update({
      status: "ERROR",
      processed_at: new Date().toISOString(),
      error: error instanceof Error ? error.message.slice(0, 1000) : "unknown billing error",
    }).eq("provider", "stripe").eq("event_id", event.id);
    throw error;
  }
}
