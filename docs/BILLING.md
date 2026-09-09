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
