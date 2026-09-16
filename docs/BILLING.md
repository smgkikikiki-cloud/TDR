# TDR billing architecture

## Product boundary

The consumer half of TDR stays public and anonymous: vehicle catalogue, current specifications, prices, production/factory context and public industry content do not require an account.

Accounts exist only for paid/member products such as TDR Report registration analytics.

## Identity model

Do not use a card number as account identity.

- `tdr_customers.id` = stable canonical Customer ID
- Supabase `auth.users.id` = authentication identity
- `tdr_customer_phone_identities.phone_e164` = OTP-verified login/phone identity
- `tdr_payment_customers` = provider-specific billing identity
- Stripe PaymentMethod = payment credential (never stored as PAN/CVC in TDR)
- `tdr_entitlements` = product access truth used by analytics endpoints

Supabase phone OTP creates/authenticates the user. A database trigger creates a
stable Customer UUID and links only `auth.users.phone` values that have a real
`phone_confirmed_at`; user metadata and the phone collected by Checkout never
become identity evidence.

## Browser/server boundary

The browser may use the public Supabase anon client for authentication only. It must never read billing tables or registration facts directly.

Authenticated browser calls:

- `GET /api/billing/status`
- `POST /api/billing/checkout`
- `POST /api/billing/portal`
- `GET /api/report/registration?...`

All four take the Supabase access token. Server code verifies the user and performs private reads with the server Supabase credential.

## Stripe flow

1. Member verifies a phone OTP through Supabase Auth.
2. TDR resolves the stable Customer ID and creates a provider customer binding.
3. Server creates a Stripe Checkout Session in subscription mode using `STRIPE_PRICE_REGISTRATION_MONTHLY`.
4. Stripe hosts card entry. TDR never receives PAN/CVC.
5. Stripe webhook is signature-verified and atomically claimed in `tdr_billing_webhook_events`; failed/stale work can be retried.
6. `checkout.session.completed` binds Stripe Customer/subscription IDs to the TDR user.
7. `invoice.paid` opens/renews `registration_full` entitlement.
8. `invoice.payment_failed` expires access by default; optional grace is controlled with `TDR_BILLING_GRACE_DAYS`.
9. `customer.subscription.deleted` expires entitlement.
10. Customer Portal handles card changes, invoice history and cancellation.

Payment-provider webhook delivery, not the browser success redirect, is the authority for access.

## Storage

`tdr_customers` + `tdr_customer_phone_identities`
- stable internal Customer UUID
- Supabase Auth user binding
- OTP-verified E.164 phone history

`tdr_payment_customers`
- provider + provider customer ID
- stable TDR Customer ID

`tdr_subscriptions`
- provider subscription ID
- plan/product
- provider state
- period start/end
- cancel-at-period-end

`tdr_payment_methods`
- provider PaymentMethod ID
- brand, last4, expiry only
- never PAN/CVC

`tdr_billing_webhook_events`
- provider event ID/type/object ID
- processing status/error
- raw payload intentionally not retained

`tdr_entitlements`
- remains the access-control source of truth
- analytics code does not need to know which payment provider granted the entitlement
- `product` is free text and already supports multiple tiers: `registration_full` (legacy, treated as Pro-equivalent), `tier_individual`, `tier_pro`. A Free account has no entitlement row at all.

## Tiered access model (Free / Individual / Pro / Corporate)

See `lib/access-policy.ts` for the single authoritative tier/quota/history
policy, `lib/access-policy-server.ts` for its DB-backed wiring, and
`lib/plans.ts` for the billing plan catalog. Legacy
`registration_monthly`/`registration_full` subscribers resolve to Pro via
`resolveTierFromEntitlements()` and are never rewritten. Corporate is a
sales-assisted path (see `/pricing`), not a fourth self-service tier.

Server-side usage metering (`tdr_usage_counters`/`tdr_usage_actions`,
migration_v34) is atomic (via `pg_advisory_xact_lock`, race-free under
concurrent identical calls) and Asia/Bangkok-boundary aware. Quota is
consumed exactly once per logical user action by exactly one top-level
route (e.g. `getRegistrationDashboard()` for the Sales Tools dashboard
Run, `consumeMarketReportQuota()` for one Market Comparison request);
lower-level fetchers it calls internally never consume quota themselves.
There is no client-supplied action id anywhere in this design -- the
dedup/idempotency key passed to `tdr_consume_usage` is always a
server-computed, time-bucketed fingerprint of the request's own semantic
parameters (`lib/access-policy-server.ts::requestFingerprint`), so a
client cannot reuse one identifier to avoid paying for a materially
different request.

### Account activation

A Free account is not usable for Compare/Sales Tools/Research/PDF until
it is *activated*: confirmed email (Supabase Auth), a verified phone
identity (a real `tdr_customer_phone_identities` row -- Supabase Auth
phone OTP via `updateUser({phone})` + `verifyOtp({..., type:
"phone_change"})`, never a typed `user_metadata` string), a postcode, and
either a company name or explicit individual/not-affiliated status.
`tdr_customer_profiles.activation_completed_at` is the single stored gate;
`lib/access-policy-server.ts::requireActivatedAccess()` is the only check
every tool route uses, so an incomplete account is blocked server-side
regardless of which client calls the API. The pre-existing production
`tdr_customer_profiles` row (a real paying legacy customer) is
grandfathered as activated by migration_v34, since the pre-tiered signup
flow never wired real phone verification into the UI.

### Preventing double subscriptions

`createCheckout()` refuses to create a second Stripe Checkout Session
while the customer already has a `tdr_subscriptions` row in `ACTIVE`,
`TRIALING`, `PAST_DUE`, `UNPAID` or `PAUSED` status (`BLOCKING_SUBSCRIPTION_STATUSES`
in `lib/billing.ts`) -- it returns 409 and the billing UI hides the
"subscribe" buttons entirely in that state, pointing to the Billing
Portal instead. **Stripe plan switching (upgrade/downgrade) is
intentionally not implemented yet** -- a customer who wants to change
plans must cancel in the Portal and start a fresh Checkout once the old
subscription is gone. Until real plan-switching is built, do not add a
"change plan" flow that upserts a new `tier_*` entitlement without also
expiring the old one: `setEntitlement()` keys on `(user_id, product)`, so
an old `tier_pro` row is never touched by a webhook for a new
`tier_individual` subscription (different product key) and would stay
`ACTIVE` forever, letting `resolveTierFromEntitlements()` keep resolving
to Pro after an intentional downgrade to Individual. Any future
plan-switch implementation must explicitly expire the entitlement row for
the plan being switched away from in the same transaction/webhook that
activates the new one.

## PromptPay later

PromptPay should be implemented as a prepaid access pass, not forced into recurring billing. It can grant/extend the same `registration_full` entitlement after a confirmed provider webhook or reviewed manual payment.

This keeps Stripe replaceable. A future Omise/2C2P adapter writes the same
payment-customer/subscription/entitlement contract; analytics and free consumer
pages do not change.

## Production configuration still required

The code intentionally fails closed until these exist:

- `TDR_APP_URL`
- `TDR_PAYMENT_PROVIDER=stripe`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_REGISTRATION_MONTHLY`

New tiered plan catalog (all optional -- each plan checkouts fail closed
with 503 until its price ID is set):

- `STRIPE_PRICE_INDIVIDUAL_MONTHLY` (฿399/month)
- `STRIPE_PRICE_PRO_MONTHLY` (฿990/month)
- `STRIPE_PRICE_INDIVIDUAL_ANNUAL`, `STRIPE_PRICE_PRO_ANNUAL` -- annual prices are not decided yet; do not invent one. Set these only once product picks a price materially better than 12x monthly.

Supabase Auth must also have Phone sign-in and an SMS provider enabled. Apply
CAPTCHA and OTP rate limits before opening public signup.

Stripe webhook endpoint: `/api/billing/webhook`.

Recommended Stripe events for the first release:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`
- `payment_method.attached`
