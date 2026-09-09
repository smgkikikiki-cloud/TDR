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
  customerId: string;
  email: string | null;
  phone: string;
};

export interface CardPaymentGateway {
  readonly provider: "stripe";
  request(
    path: string,
    params?: Record<string, string | number | boolean | null | undefined>,
    method?: string,
    idempotencyKey?: string,
  ): Promise<StripeObject>;
}

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

class StripeCardPaymentGateway implements CardPaymentGateway {
  readonly provider = "stripe" as const;

  async request(path: string, params?: Record<string, string | number | boolean | null | undefined>, method = "POST", idempotencyKey?: string) {
    const response = await fetch(`https://api.stripe.com${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${stripeSecret()}`,
        ...(params ? { "Content-Type": "application/x-www-form-urlencoded" } : {}),
        ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
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
}

function cardGateway(): CardPaymentGateway {
  const provider = (process.env.TDR_PAYMENT_PROVIDER || "stripe").toLowerCase();
  if (provider !== "stripe") throw new BillingError(503, `unsupported card payment provider ${provider}`);
  return new StripeCardPaymentGateway();
}

export async function requireMember(accessToken: string): Promise<MemberContext> {
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");

  const { data, error } = await db.auth.getUser(accessToken);
  if (error || !data.user) throw new BillingError(401, "invalid or expired member session");

  const phone = data.user.phone || null;
  if (!phone || !data.user.phone_confirmed_at) {
    throw new BillingError(403, "verify a phone number with OTP before creating a billing customer");
  }
  let { data: customer, error: customerError } = await db.from("tdr_customers")
    .select("id").eq("auth_user_id", data.user.id).maybeSingle();
  if (customerError) throw new BillingError(503, "could not load customer identity");
  if (!customer) {
    const created = await db.from("tdr_customers").insert({ auth_user_id: data.user.id })
      .select("id").single();
    if (created.error) throw new BillingError(503, "could not create customer identity");
    customer = created.data;
  }
  const { error: phoneError } = await db.from("tdr_customer_phone_identities").upsert({
    customer_id: customer.id,
    phone_e164: phone,
    verified_at: data.user.phone_confirmed_at,
    is_primary: true,
    revoked_at: null,
    updated_at: new Date().toISOString(),
  }, { onConflict: "phone_e164" });
  if (phoneError) throw new BillingError(409, "verified phone is already linked to another customer");

  return { userId: data.user.id, customerId: customer.id, email: data.user.email ?? null, phone };
}

async function providerCustomer(customerId: string) {
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");
  const { data, error } = await db
    .from("tdr_payment_customers")
    .select("provider_customer_id")
    .eq("provider", "stripe")
    .eq("customer_id", customerId)
    .maybeSingle();
  if (error) throw new BillingError(503, "could not load billing profile");
  return data;
}

async function ensureStripeCustomer(member: MemberContext) {
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");
  const profile = await providerCustomer(member.customerId);
  if (profile?.provider_customer_id) return profile.provider_customer_id as string;

  const customer = await cardGateway().request("/v1/customers", {
    email: member.email,
    phone: member.phone,
    "metadata[tdr_user_id]": member.userId,
    "metadata[tdr_customer_id]": member.customerId,
  }, "POST", `tdr-stripe-customer-${member.customerId}`);

  const { error } = await db.from("tdr_payment_customers").upsert({
    provider: "stripe",
    customer_id: member.customerId,
    provider_customer_id: customer.id,
    billing_email: member.email,
    billing_phone_e164: member.phone,
    updated_at: new Date().toISOString(),
  }, { onConflict: "provider,provider_customer_id" });
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
  const session = await cardGateway().request("/v1/checkout/sessions", {
    mode: "subscription",
    customer: customerId,
    client_reference_id: member.customerId,
    "line_items[0][price]": registrationPriceId(),
    "line_items[0][quantity]": 1,
    success_url: args.successUrl,
    cancel_url: args.cancelUrl,
    allow_promotion_codes: true,
    "phone_number_collection[enabled]": true,
    "metadata[tdr_user_id]": member.userId,
    "metadata[tdr_customer_id]": member.customerId,
    "metadata[plan_code]": REGISTRATION_PLAN,
    "subscription_data[metadata][tdr_user_id]": member.userId,
    "subscription_data[metadata][tdr_customer_id]": member.customerId,
    "subscription_data[metadata][plan_code]": REGISTRATION_PLAN,
  });
  if (!session.url) throw new BillingError(502, "Stripe Checkout did not return a redirect URL");
  return { id: session.id as string, url: session.url as string };
}

export async function createBillingPortal(args: { accessToken: string; returnUrl: string }) {
  const member = await requireMember(args.accessToken);
  const profile = await providerCustomer(member.customerId);
  if (!profile?.provider_customer_id) throw new BillingError(409, "this account has no billing profile yet");

  const session = await cardGateway().request("/v1/billing_portal/sessions", {
    customer: profile.provider_customer_id,
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
    db.from("tdr_payment_customers").select("provider_customer_id").eq("provider", "stripe").eq("customer_id", member.customerId).maybeSingle(),
    db.from("tdr_subscriptions").select("plan_code,status,current_period_end,cancel_at_period_end,provider").eq("customer_id", member.customerId).order("updated_at", { ascending: false }).limit(1).maybeSingle(),
    db.from("tdr_entitlements").select("product,status,valid_until").eq("user_id", member.userId).eq("product", REGISTRATION_PRODUCT).maybeSingle(),
  ]);
  if (profileError || subscriptionError || entitlementError) {
    throw new BillingError(503, "could not load billing status");
  }

  return {
    user: { id: member.userId, customerId: member.customerId, email: member.email, phone: member.phone },
    customerBound: Boolean(profile?.provider_customer_id),
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

function metadataCustomerId(object: StripeObject) {
  return object.metadata?.tdr_customer_id
    || object.subscription_details?.metadata?.tdr_customer_id
    || object.parent?.subscription_details?.metadata?.tdr_customer_id
    || object.client_reference_id
    || null;
}

function metadataPlan(object: StripeObject) {
  return object.metadata?.plan_code
    || object.subscription_details?.metadata?.plan_code
    || object.parent?.subscription_details?.metadata?.plan_code
    || REGISTRATION_PLAN;
}

async function customerContext(object: StripeObject) {
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");
  const direct = metadataCustomerId(object);
  if (direct) {
    const { data } = await db.from("tdr_customers").select("id,auth_user_id").eq("id", String(direct)).maybeSingle();
    if (data) return { customerId: String(data.id), userId: String(data.auth_user_id) };
  }
  const providerCustomerId = typeof object.customer === "string"
    ? object.customer
    : typeof object.customer_details?.customer === "string" ? object.customer_details.customer : null;
  if (!providerCustomerId) return null;
  const { data } = await db.from("tdr_payment_customers")
    .select("customer_id").eq("provider", "stripe")
    .eq("provider_customer_id", providerCustomerId).maybeSingle();
  if (!data?.customer_id) return null;
  const { data: customer } = await db.from("tdr_customers")
    .select("id,auth_user_id").eq("id", data.customer_id).maybeSingle();
  return customer ? { customerId: String(customer.id), userId: String(customer.auth_user_id) } : null;
}

async function upsertSubscriptionFromObject(object: StripeObject, context: { customerId: string; userId: string } | null) {
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");
  const subscriptionId = typeof object.id === "string" && object.object === "subscription"
    ? object.id
    : stripeSubscriptionId(object);
  if (!subscriptionId) return null;

  let effective = context;
  if (!effective) {
    const { data } = await db.from("tdr_subscriptions").select("customer_id,user_id")
      .eq("provider", "stripe").eq("provider_subscription_id", subscriptionId).maybeSingle();
    effective = data?.customer_id && data?.user_id
      ? { customerId: String(data.customer_id), userId: String(data.user_id) } : null;
  }
  if (!effective) return null;

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
    customer_id: effective.customerId,
    user_id: effective.userId,
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
  return { ...effective, subscriptionId };
}

async function entitlementContextFromEvent(object: StripeObject) {
  const direct = await customerContext(object);
  if (direct) return direct;
  const subscriptionId = stripeSubscriptionId(object);
  if (!subscriptionId) return null;
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");
  const { data } = await db.from("tdr_subscriptions").select("customer_id,user_id")
    .eq("provider", "stripe").eq("provider_subscription_id", subscriptionId).maybeSingle();
  return data?.customer_id && data?.user_id
    ? { customerId: String(data.customer_id), userId: String(data.user_id) } : null;
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

async function currentSubscriptionEnd(customerId: string) {
  const db = adminDb();
  if (!db) throw new BillingError(503, "member database is not configured");
  const { data } = await db.from("tdr_subscriptions").select("current_period_end").eq("customer_id", customerId).order("updated_at", { ascending: false }).limit(1).maybeSingle();
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
  const { data: claimed, error: claimError } = await db.rpc("tdr_claim_billing_webhook", {
    p_provider: "stripe",
    p_event_id: event.id,
    p_event_type: event.type,
    p_object_id: object.id || null,
  });
  if (claimError) throw new BillingError(503, "could not claim billing webhook");
  if (!claimed) return { duplicate: true };

  try {
    if (event.type === "checkout.session.completed") {
      const context = await customerContext(object);
      if (context && typeof object.customer === "string") {
        const { error } = await db.from("tdr_payment_customers").upsert({
          provider: "stripe",
          provider_customer_id: object.customer,
          customer_id: context.customerId,
          billing_email: object.customer_details?.email || null,
          billing_phone_e164: object.customer_details?.phone || null,
          updated_at: new Date().toISOString(),
        }, { onConflict: "provider,provider_customer_id" });
        if (error) throw new BillingError(503, "could not bind payment customer");
        await upsertSubscriptionFromObject(object, context);
      }
    }

    if (event.type.startsWith("customer.subscription.")) {
      const result = await upsertSubscriptionFromObject(object, await customerContext(object));
      if (event.type === "customer.subscription.deleted" && result?.userId) {
        await setEntitlement(result.userId, "EXPIRED", new Date().toISOString());
      }
    }

    if (event.type === "invoice.paid") {
      const context = await entitlementContextFromEvent(object);
      if (context) {
        const periodEnd = isoFromUnix(object.lines?.data?.[0]?.period?.end) || await currentSubscriptionEnd(context.customerId);
        await setEntitlement(context.userId, "ACTIVE", periodEnd);
      }
    }

    if (event.type === "invoice.payment_failed") {
      const context = await entitlementContextFromEvent(object);
      if (context) {
        const until = graceUntil();
        await setEntitlement(context.userId, until ? "GRACE" : "EXPIRED", until || new Date().toISOString());
      }
    }

    if (event.type === "payment_method.attached") {
      const context = await customerContext(object);
      if (context && object.id) {
          const { error } = await db.from("tdr_payment_methods").upsert({
            provider: "stripe",
            provider_payment_method_id: object.id,
            customer_id: context.customerId,
            user_id: context.userId,
            brand: object.card?.brand || null,
            last4: object.card?.last4 || null,
            exp_month: object.card?.exp_month || null,
            exp_year: object.card?.exp_year || null,
            updated_at: new Date().toISOString(),
          }, { onConflict: "provider,provider_payment_method_id" });
          if (error) throw new BillingError(503, "could not save payment method metadata");
      }
    }

    await db.from("tdr_billing_webhook_events").update({
      status: "PROCESSED",
      processed_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      error: null,
    }).eq("provider", "stripe").eq("event_id", event.id);
    return { duplicate: false };
  } catch (error) {
    await db.from("tdr_billing_webhook_events").update({
      status: "ERROR",
      processed_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      error: error instanceof Error ? error.message.slice(0, 1000) : "unknown billing error",
    }).eq("provider", "stripe").eq("event_id", event.id);
    throw error;
  }
}
