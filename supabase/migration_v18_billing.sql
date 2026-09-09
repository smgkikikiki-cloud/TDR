-- Billing/customer boundary for TDR Report.
--
-- Consumer catalogue pages remain anonymous/free. These tables exist only for
-- member billing and are never readable from anon/authenticated browser roles.
-- Card PAN/CVC are never stored here; Stripe remains the payment credential vault.

create table if not exists public.tdr_customer_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  phone_e164 text,
  stripe_customer_id text unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint tdr_customer_profiles_phone_check
    check (phone_e164 is null or phone_e164 ~ '^\+[1-9][0-9]{7,14}$')
);

create table if not exists public.tdr_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null default 'stripe'
    check (provider in ('stripe', 'manual', 'omise')),
  provider_subscription_id text,
  plan_code text not null,
  product text not null default 'registration_full',
  status text not null default 'INCOMPLETE'
    check (status in ('INCOMPLETE', 'TRIALING', 'ACTIVE', 'PAST_DUE', 'UNPAID', 'CANCELED', 'PAUSED', 'EXPIRED')),
  current_period_start timestamptz,
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists tdr_subscriptions_provider_id_uq
  on public.tdr_subscriptions(provider, provider_subscription_id)
  where provider_subscription_id is not null;
create index if not exists tdr_subscriptions_user_idx
  on public.tdr_subscriptions(user_id, updated_at desc);

create table if not exists public.tdr_payment_methods (
  provider text not null default 'stripe',
  provider_payment_method_id text not null,
  user_id uuid not null references auth.users(id) on delete cascade,
  brand text,
  last4 text,
  exp_month smallint,
  exp_year smallint,
  is_default boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (provider, provider_payment_method_id),
  constraint tdr_payment_methods_last4_check check (last4 is null or last4 ~ '^[0-9]{4}$'),
  constraint tdr_payment_methods_month_check check (exp_month is null or exp_month between 1 and 12)
);

create index if not exists tdr_payment_methods_user_idx
  on public.tdr_payment_methods(user_id, is_default desc, updated_at desc);

create table if not exists public.tdr_billing_webhook_events (
  provider text not null,
  event_id text not null,
  event_type text not null,
  object_id text,
  status text not null default 'RECEIVED'
    check (status in ('RECEIVED', 'PROCESSED', 'ERROR')),
  error text,
  created_at timestamptz not null default now(),
  processed_at timestamptz,
  primary key (provider, event_id)
);

-- All billing state is server-side only. Being signed in is not proof of payment.
alter table public.tdr_customer_profiles enable row level security;
alter table public.tdr_subscriptions enable row level security;
alter table public.tdr_payment_methods enable row level security;
alter table public.tdr_billing_webhook_events enable row level security;

revoke all on table public.tdr_customer_profiles from anon, authenticated;
revoke all on table public.tdr_subscriptions from anon, authenticated;
revoke all on table public.tdr_payment_methods from anon, authenticated;
revoke all on table public.tdr_billing_webhook_events from anon, authenticated;

grant select, insert, update, delete on table public.tdr_customer_profiles to service_role;
grant select, insert, update, delete on table public.tdr_subscriptions to service_role;
grant select, insert, update, delete on table public.tdr_payment_methods to service_role;
grant select, insert, update, delete on table public.tdr_billing_webhook_events to service_role;

-- Email/password remains the login mechanism for now. Phone is collected as
-- customer contact/identity metadata and copied into the server-only profile.
create or replace function public.tdr_create_customer_profile()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  insert into public.tdr_customer_profiles(user_id, phone_e164)
  values (
    new.id,
    nullif(new.raw_user_meta_data ->> 'phone_e164', '')
  )
  on conflict (user_id) do update
    set phone_e164 = coalesce(excluded.phone_e164, public.tdr_customer_profiles.phone_e164),
        updated_at = now();
  return new;
end;
$$;

revoke all on function public.tdr_create_customer_profile() from public, anon, authenticated;

drop trigger if exists tdr_on_auth_user_created_customer_profile on auth.users;
create trigger tdr_on_auth_user_created_customer_profile
after insert on auth.users
for each row execute function public.tdr_create_customer_profile();

-- Backfill existing member accounts without exposing billing tables to clients.
insert into public.tdr_customer_profiles(user_id, phone_e164)
select id, nullif(raw_user_meta_data ->> 'phone_e164', '')
from auth.users
on conflict (user_id) do nothing;

comment on table public.tdr_customer_profiles is
  'TDR member billing identity. Phone + provider customer ID only; no raw card credentials.';
comment on table public.tdr_payment_methods is
  'Display-safe payment method metadata only (brand/last4/expiry). PAN/CVC must never be stored.';
comment on table public.tdr_billing_webhook_events is
  'Idempotency/audit ledger for payment-provider webhooks. Raw webhook payload is intentionally not retained.';
