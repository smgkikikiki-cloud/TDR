-- Provider-neutral customer, verified-phone and card-billing foundation.
-- Supabase Auth verifies the phone. Payment providers vault all card secrets.

create extension if not exists pgcrypto;

create table if not exists public.tdr_customers (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid not null unique references auth.users(id) on delete cascade,
  status text not null default 'ACTIVE'
    check (status in ('ACTIVE','SUSPENDED','CLOSED')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

insert into public.tdr_customers(auth_user_id)
select id from auth.users on conflict (auth_user_id) do nothing;

create table if not exists public.tdr_customer_phone_identities (
  customer_id uuid not null references public.tdr_customers(id) on delete cascade,
  phone_e164 text not null unique
    check (phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),
  verified_at timestamptz not null,
  is_primary boolean not null default true,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (customer_id, phone_e164),
  check ((is_primary and revoked_at is null) or not is_primary)
);

create unique index if not exists tdr_customer_one_primary_phone_uq
  on public.tdr_customer_phone_identities(customer_id) where is_primary;

insert into public.tdr_customer_phone_identities(customer_id, phone_e164, verified_at)
select c.id, u.phone, u.phone_confirmed_at
from auth.users u join public.tdr_customers c on c.auth_user_id = u.id
where u.phone is not null and u.phone_confirmed_at is not null
on conflict (phone_e164) do update
set verified_at = greatest(public.tdr_customer_phone_identities.verified_at, excluded.verified_at),
    updated_at = now()
where public.tdr_customer_phone_identities.customer_id = excluded.customer_id;

create table if not exists public.tdr_payment_customers (
  provider text not null check (provider in ('stripe','omise','2c2p','manual')),
  provider_customer_id text not null,
  customer_id uuid not null references public.tdr_customers(id) on delete cascade,
  billing_email text,
  billing_phone_e164 text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (provider, provider_customer_id),
  unique (provider, customer_id),
  check (billing_phone_e164 is null or billing_phone_e164 ~ '^\+[1-9][0-9]{7,14}$')
);

-- Compatibility table may exist from the unmerged billing prototype. Migrate
-- its provider binding but never treat its metadata phone as verified identity.
do $$ begin
  if to_regclass('public.tdr_customer_profiles') is not null then
    insert into public.tdr_payment_customers(provider, provider_customer_id, customer_id)
    select 'stripe', p.stripe_customer_id, c.id
    from public.tdr_customer_profiles p
    join public.tdr_customers c on c.auth_user_id = p.user_id
    where p.stripe_customer_id is not null
    on conflict (provider, provider_customer_id) do nothing;
  end if;
end $$;

create table if not exists public.tdr_subscriptions (
  id uuid primary key default gen_random_uuid(),
  customer_id uuid references public.tdr_customers(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null default 'stripe'
    check (provider in ('stripe','manual','omise','2c2p')),
  provider_subscription_id text,
  plan_code text not null,
  product text not null default 'registration_full',
  status text not null default 'INCOMPLETE'
    check (status in ('INCOMPLETE','TRIALING','ACTIVE','PAST_DUE','UNPAID','CANCELED','PAUSED','EXPIRED')),
  current_period_start timestamptz,
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table public.tdr_subscriptions add column if not exists customer_id uuid;
update public.tdr_subscriptions s set customer_id = c.id
from public.tdr_customers c where s.customer_id is null and c.auth_user_id = s.user_id;
do $$ begin
  alter table public.tdr_subscriptions add constraint tdr_subscriptions_customer_id_fkey
    foreign key (customer_id) references public.tdr_customers(id) on delete cascade;
exception when duplicate_object then null; end $$;
alter table public.tdr_subscriptions alter column customer_id set not null;
create unique index if not exists tdr_subscriptions_provider_id_uq
  on public.tdr_subscriptions(provider, provider_subscription_id)
  where provider_subscription_id is not null;
create index if not exists tdr_subscriptions_customer_idx
  on public.tdr_subscriptions(customer_id, updated_at desc);

create table if not exists public.tdr_payment_methods (
  provider text not null default 'stripe',
  provider_payment_method_id text not null,
  customer_id uuid references public.tdr_customers(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  brand text,
  last4 text check (last4 is null or last4 ~ '^[0-9]{4}$'),
  exp_month smallint check (exp_month is null or exp_month between 1 and 12),
  exp_year smallint,
  is_default boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (provider, provider_payment_method_id)
);
alter table public.tdr_payment_methods add column if not exists customer_id uuid;
update public.tdr_payment_methods p set customer_id = c.id
from public.tdr_customers c where p.customer_id is null and c.auth_user_id = p.user_id;
do $$ begin
  alter table public.tdr_payment_methods add constraint tdr_payment_methods_customer_id_fkey
    foreign key (customer_id) references public.tdr_customers(id) on delete cascade;
exception when duplicate_object then null; end $$;
alter table public.tdr_payment_methods alter column customer_id set not null;
create index if not exists tdr_payment_methods_customer_idx
  on public.tdr_payment_methods(customer_id, is_default desc, updated_at desc);

create table if not exists public.tdr_billing_webhook_events (
  provider text not null,
  event_id text not null,
  event_type text not null,
  object_id text,
  status text not null default 'RECEIVED',
  attempts integer not null default 0,
  error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  processing_started_at timestamptz,
  processed_at timestamptz,
  primary key (provider, event_id)
);
alter table public.tdr_billing_webhook_events add column if not exists attempts integer not null default 0;
alter table public.tdr_billing_webhook_events add column if not exists updated_at timestamptz not null default now();
alter table public.tdr_billing_webhook_events add column if not exists processing_started_at timestamptz;
alter table public.tdr_billing_webhook_events drop constraint if exists tdr_billing_webhook_events_status_check;
alter table public.tdr_billing_webhook_events add constraint tdr_billing_webhook_events_status_check
  check (status in ('RECEIVED','PROCESSING','PROCESSED','ERROR'));

alter table public.tdr_customers enable row level security;
alter table public.tdr_customer_phone_identities enable row level security;
alter table public.tdr_payment_customers enable row level security;
alter table public.tdr_subscriptions enable row level security;
alter table public.tdr_payment_methods enable row level security;
alter table public.tdr_billing_webhook_events enable row level security;

revoke all on table public.tdr_customers from public, anon, authenticated;
revoke all on table public.tdr_customer_phone_identities from public, anon, authenticated;
revoke all on table public.tdr_payment_customers from public, anon, authenticated;
revoke all on table public.tdr_subscriptions from public, anon, authenticated;
revoke all on table public.tdr_payment_methods from public, anon, authenticated;
revoke all on table public.tdr_billing_webhook_events from public, anon, authenticated;
grant select, insert, update, delete on table public.tdr_customers to service_role;
grant select, insert, update, delete on table public.tdr_customer_phone_identities to service_role;
grant select, insert, update, delete on table public.tdr_payment_customers to service_role;
grant select, insert, update, delete on table public.tdr_subscriptions to service_role;
grant select, insert, update, delete on table public.tdr_payment_methods to service_role;
grant select, insert, update, delete on table public.tdr_billing_webhook_events to service_role;

drop trigger if exists tdr_on_auth_user_created_customer_profile on auth.users;
drop function if exists public.tdr_create_customer_profile();

create or replace function public.tdr_sync_customer_from_auth()
returns trigger language plpgsql security definer set search_path = public, pg_temp as $$
declare customer_uuid uuid;
begin
  insert into public.tdr_customers(auth_user_id, updated_at)
  values (new.id, now())
  on conflict (auth_user_id) do update set updated_at = now()
  returning id into customer_uuid;

  if new.phone is not null and new.phone_confirmed_at is not null
     and new.phone ~ '^\+[1-9][0-9]{7,14}$' then
    update public.tdr_customer_phone_identities
    set is_primary = false, revoked_at = coalesce(revoked_at, now()), updated_at = now()
    where customer_id = customer_uuid and is_primary and phone_e164 <> new.phone;

    insert into public.tdr_customer_phone_identities(
      customer_id, phone_e164, verified_at, is_primary, revoked_at, updated_at
    ) values (customer_uuid, new.phone, new.phone_confirmed_at, true, null, now())
    on conflict (phone_e164) do update
      set verified_at = greatest(public.tdr_customer_phone_identities.verified_at, excluded.verified_at),
          is_primary = true, revoked_at = null, updated_at = now()
      where public.tdr_customer_phone_identities.customer_id = excluded.customer_id;
  end if;
  return new;
end $$;
revoke all on function public.tdr_sync_customer_from_auth() from public, anon, authenticated;

drop trigger if exists tdr_on_auth_user_customer_sync on auth.users;
create trigger tdr_on_auth_user_customer_sync
after insert or update of phone, phone_confirmed_at on auth.users
for each row execute function public.tdr_sync_customer_from_auth();

create or replace function public.tdr_claim_billing_webhook(
  p_provider text, p_event_id text, p_event_type text, p_object_id text default null
) returns boolean language plpgsql security invoker set search_path = public, pg_temp as $$
declare claimed boolean := false;
begin
  insert into public.tdr_billing_webhook_events(
    provider,event_id,event_type,object_id,status,attempts,processing_started_at,updated_at
  ) values (p_provider,p_event_id,p_event_type,p_object_id,'PROCESSING',1,now(),now())
  on conflict (provider,event_id) do update
    set status='PROCESSING', attempts=public.tdr_billing_webhook_events.attempts+1,
        processing_started_at=now(), updated_at=now(), error=null
    where public.tdr_billing_webhook_events.status in ('RECEIVED','ERROR')
       or (public.tdr_billing_webhook_events.status='PROCESSING'
           and public.tdr_billing_webhook_events.processing_started_at < now()-interval '5 minutes')
  returning true into claimed;
  return coalesce(claimed,false);
end $$;
revoke all on function public.tdr_claim_billing_webhook(text,text,text,text) from public, anon, authenticated;
grant execute on function public.tdr_claim_billing_webhook(text,text,text,text) to service_role;

comment on table public.tdr_customers is
  'Stable internal customer UUID. It is not a phone number, auth user ID or payment-provider ID.';
comment on table public.tdr_customer_phone_identities is
  'Only phone identities confirmed by Supabase Auth OTP. User metadata never grants identity.';
comment on table public.tdr_payment_customers is
  'Provider adapter bindings. Card PAN/CVC stay in the payment provider vault.';
comment on table public.tdr_billing_webhook_events is
  'Retryable, idempotent payment webhook ledger; raw card/payment payloads are not retained.';
