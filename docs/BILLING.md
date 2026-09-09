# TDR billing architecture

## Product boundary

The consumer half of TDR stays public and anonymous: vehicle catalogue, current specifications, prices, production/factory context and public industry content do not require an account.

Accounts exist only for paid/member products such as TDR Report registration analytics.

## Identity model

Do not use a card number as account identity.

- Supabase `auth.users.id` = canonical member identity
- email/password = current login method
- `tdr_customer_profiles.phone_e164` = phone/contact identity
- `stripe_customer_id` = billing identity at Stripe
- Stripe PaymentMethod = payment credential (never stored as PAN/CVC in TDR)
- `tdr_entitlements` = product access truth used by analytics endpoints

At sign-up the phone is normalized to E.164 and stored in Supabase user metadata. A database trigger mirrors it into the service-role-only customer profile. Stripe Checkout also collects phone and may refresh the profile from the verified Checkout customer details.

## Browser/server boundary

The browser may use the public Supabase anon client for authentication only. It must never read billing tables or registration facts directly.

Authenticated browser calls:

- `GET /api/billing/status`
- `POST /api/billing/checkout`
- `POST /api/billing/portal`
- `GET /api/report/registration?...`

All four take the Supabase access token. Server code verifies the user and performs private reads with the server Supabase credential.

## Stripe flow

1. Member creates/signs into a Supabase account.
2. `POST /api/billing/checkout` resolves or creates a Stripe Customer tied to `tdr_user_id`.
3. Server creates a Stripe Checkout Session in subscription mode using `STRIPE_PRICE_REGISTRATION_MONTHLY`.
4. Stripe hosts card entry. TDR never receives PAN/CVC.
5. Stripe webhook is signature-verified and idempotently recorded in `tdr_billing_webhook_events`.
6. `checkout.session.completed` binds Stripe Customer/subscription IDs to the TDR user.
7. `invoice.paid` opens/renews `registration_full` entitlement.
8. `invoice.payment_failed` expires access by default; optional grace is controlled with `TDR_BILLING_GRACE_DAYS`.
9. `customer.subscription.deleted` expires entitlement.
10. Customer Portal handles card changes, invoice history and cancellation.

Payment-provider webhook delivery, not the browser success redirect, is the authority for access.

## Storage

`tdr_customer_profiles`
- `user_id`
- phone in E.164
- Stripe Customer ID

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

## PromptPay later

PromptPay should be implemented as a prepaid access pass, not forced into recurring billing. It can grant/extend the same `registration_full` entitlement after a confirmed provider webhook or reviewed manual payment.

This keeps Stripe replaceable. A future Omise/2C2P integration only needs to map its payment lifecycle into `tdr_subscriptions` + `tdr_entitlements`; registration analytics and consumer pages do not change.

## Production configuration still required

The code intentionally fails closed until these exist:

- `TDR_APP_URL`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_REGISTRATION_MONTHLY`

Stripe webhook endpoint: `/api/billing/webhook`.

Recommended Stripe events for the first release:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`
- `payment_method.attached`
