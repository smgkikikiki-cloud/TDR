-- Freemium/tiered access-policy foundation: account-profile extension,
-- server-side usage metering (atomic, concurrency-safe), sales-module
-- selection storage, and product telemetry.
--
-- Numbered v34 (not v32/v33): main already carries
-- migration_v32_registration_v2_immutable_trigger_search_path_hardening.sql,
-- and v33 is reserved by PR #94 (migration_v33_vehicle_media.sql, already
-- applied to production). This migration does not touch either.
--
-- Purely additive. Does not touch any registration_* table/view (that area
-- is frozen mid-cutover, see docs/vehicle-platform/PHASE3_CUTOVER.md) and
-- does not alter tdr_entitlements' schema -- its existing free-text
-- `product` column already generalizes to multiple tiers (no CHECK
-- constraint restricts its values), so new tiers are added by writing new
-- product values ('tier_individual', 'tier_pro') rather than by migrating
-- the table. Legacy `registration_full` rows are left untouched and are
-- treated as Pro-equivalent by application code (lib/access-policy.ts),
-- not by a data rewrite.

-- ---------------------------------------------------------------------
-- 1. tdr_customer_profiles
--
-- PRODUCTION ALREADY HAS THIS TABLE. Its live shape is:
--   user_id uuid not null primary key
--   phone_e164 text
--   stripe_customer_id text
--   created_at timestamptz not null
--   updated_at timestamptz not null
-- with 1 existing row (a real paying customer): non-null phone, no phone
-- duplicates. `create table if not exists` is therefore a no-op against
-- production -- it must NOT be relied on to add the new columns below.
-- This block is written to be correct in BOTH cases: the CREATE TABLE
-- mirrors the live legacy shape exactly (so a fresh environment ends up
-- schema-identical to production before the ALTERs run), and every new
-- column/constraint after it uses ADD COLUMN IF NOT EXISTS / a
-- duplicate_object-tolerant DO block, so it applies cleanly whether the
-- table pre-existed or was just created above.
-- ---------------------------------------------------------------------
create table if not exists public.tdr_customer_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  phone_e164 text,
  stripe_customer_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.tdr_customer_profiles add column if not exists customer_id uuid;
alter table public.tdr_customer_profiles add column if not exists email text;
alter table public.tdr_customer_profiles add column if not exists postcode text;
alter table public.tdr_customer_profiles add column if not exists is_individual boolean not null default true;
alter table public.tdr_customer_profiles add column if not exists company_name text;
alter table public.tdr_customer_profiles add column if not exists marketing_consent boolean not null default false;
alter table public.tdr_customer_profiles add column if not exists marketing_consent_at timestamptz;
alter table public.tdr_customer_profiles add column if not exists marketing_consent_version text;
alter table public.tdr_customer_profiles add column if not exists profile_completed_at timestamptz;
-- The single authoritative activation gate (see lib/access-policy-server.ts
-- ::requireActivatedAccess). Set once all activation criteria are first
-- met (email confirmed + a TDR-confirmed phone verification + postcode +
-- company-or-individual), or by the legacy-compatibility backfill below
-- for the pre-existing paid row. A stored flag rather than a recomputed
-- check so activation, once granted, survives e.g. a later phone
-- re-verification.
alter table public.tdr_customer_profiles add column if not exists activation_completed_at timestamptz;
-- Records HOW activation was granted, so a legacy grandfather is never
-- mistaken for a real OTP-verified account. 'VERIFIED' = every criterion
-- (including a real TDR-confirmed phone verification, see
-- tdr_phone_verification_attempts below) was independently computed true.
-- 'LEGACY_PAID' = granted once, by this migration, to the pre-existing
-- paying customer who predates the verification flow -- never computed,
-- never re-derived.
alter table public.tdr_customer_profiles add column if not exists activation_source text;

do $$ begin
  alter table public.tdr_customer_profiles add constraint tdr_customer_profiles_customer_id_fkey
    foreign key (customer_id) references public.tdr_customers(id) on delete cascade;
exception when duplicate_object then null; end $$;

do $$ begin
  alter table public.tdr_customer_profiles add constraint tdr_customer_profiles_postcode_format
    check (postcode is null or postcode ~ '^[0-9]{4,10}$');
exception when duplicate_object then null; end $$;

do $$ begin
  alter table public.tdr_customer_profiles add constraint tdr_customer_profiles_activation_source_known
    check (activation_source is null or activation_source in ('VERIFIED', 'LEGACY_PAID'));
exception when duplicate_object then null; end $$;

-- Both new columns default to values that trivially satisfy these checks
-- for the pre-existing row (is_individual defaults true; marketing_consent
-- defaults false), so adding them is safe against live data.
do $$ begin
  alter table public.tdr_customer_profiles add constraint tdr_customer_profiles_company_required_unless_individual
    check (is_individual or (company_name is not null and length(trim(company_name)) > 0));
exception when duplicate_object then null; end $$;

do $$ begin
  alter table public.tdr_customer_profiles add constraint tdr_customer_profiles_consent_is_auditable
    check (not marketing_consent or (marketing_consent_at is not null and marketing_consent_version is not null));
exception when duplicate_object then null; end $$;

-- Bind every existing profile row (including the pre-existing legacy one)
-- to its stable tdr_customers identity. tdr_customers rows already exist
-- for every auth.users row today via the trigger in migration_v21, so
-- this is a pure lookup, never a create.
update public.tdr_customer_profiles p set customer_id = c.id
from public.tdr_customers c
where p.customer_id is null and c.auth_user_id = p.user_id;

create index if not exists tdr_customer_profiles_customer_idx
  on public.tdr_customer_profiles(customer_id);

alter table public.tdr_customer_profiles enable row level security;
revoke all on table public.tdr_customer_profiles from public, anon, authenticated;
grant select, insert, update, delete on table public.tdr_customer_profiles to service_role;

comment on table public.tdr_customer_profiles is
  'Account/profile detail (postcode, company vs individual, auditable marketing consent, activation state). Legacy production table, extended additively in migration_v34 -- stripe_customer_id/phone_e164/created_at/updated_at predate this migration and are preserved as-is. Server-role only.';

-- ---------------------------------------------------------------------
-- 1b. Activation compatibility backfill for the pre-existing legacy row.
--
-- The pre-tiered signup flow never wired real phone-OTP verification into
-- the member UI (typed phone went into user_metadata only, never through
-- Supabase Auth's OTP flow), so under the new activation gate the existing
-- paying customer(s) would otherwise be locked out of their own paid
-- product on this migration alone. Grandfather exactly the rows that have
-- already completed a real Stripe checkout (stripe_customer_id is not
-- null -- proof of a trusted, revenue-bearing relationship) as activated
-- for TOOL USE (Compare/Sales Tools), tagged activation_source =
-- 'LEGACY_PAID' so this is never confused with a real verification.
--
-- IMPORTANT: this does NOT insert into tdr_customer_phone_identities.
-- That table (migration_v21) is defined as Supabase-Auth-OTP-verified
-- phone identity -- writing the legacy row's old typed/billing phone into
-- it as if Supabase had confirmed it would be a false provenance claim.
-- The legacy row keeps activation without ever appearing to have
-- completed real OTP verification; if this customer starts a brand-new
-- Stripe Checkout in the future, requireCheckoutEligibleMember()
-- (lib/billing.ts) still requires a REAL tdr_customer_phone_identities
-- row before Stripe is involved -- this backfill grants activation for
-- tool use only, not a trusted phone for billing. New Free signups get
-- none of this and must complete real verification (see
-- lib/access-policy-server.ts, lib/phone-verification.ts).
-- ---------------------------------------------------------------------
update public.tdr_customer_profiles p
set activation_completed_at = coalesce(p.activation_completed_at, now()),
    activation_source = coalesce(p.activation_source, 'LEGACY_PAID')
where p.stripe_customer_id is not null;

-- ---------------------------------------------------------------------
-- 2. Usage metering: tdr_usage_counters + tdr_usage_actions + the
--    atomic consume RPC.
--
-- Neither table nor this function has ever been applied to any
-- environment (this migration is renamed from the never-shipped v32), so
-- unlike tdr_customer_profiles above, these are defined fresh with no
-- legacy-schema concern.
--
-- Quota is meant to be consumed exactly once per externally meaningful
-- user action, by exactly one top-level server route per action (see
-- lib/registration-analytics.ts, app/api/tools/*). p_action_id is never a
-- client-supplied token: callers pass a server-computed request
-- fingerprint (lib/access-policy-server.ts::requestFingerprint, a
-- time-bucketed hash of the user id, metric and the request's own
-- semantic parameters), so retried/duplicate calls with genuinely
-- identical parameters coalesce, but a client cannot reuse one identifier
-- to escape paying for a materially different request.
-- ---------------------------------------------------------------------
create table if not exists public.tdr_usage_counters (
  user_id uuid not null references auth.users(id) on delete cascade,
  metric text not null check (metric in ('vehicle_compare','sales_query','research_full','pdf_export')),
  period_key text not null,
  count integer not null default 0,
  updated_at timestamptz not null default now(),
  primary key (user_id, metric, period_key)
);
create index if not exists tdr_usage_counters_lookup_idx
  on public.tdr_usage_counters(user_id, metric, period_key);

create table if not exists public.tdr_usage_actions (
  user_id uuid not null references auth.users(id) on delete cascade,
  metric text not null check (metric in ('vehicle_compare','sales_query','research_full','pdf_export')),
  action_id text not null,
  period_key text not null,
  allowed boolean not null,
  used integer not null,
  created_at timestamptz not null default now(),
  primary key (user_id, metric, action_id)
);

alter table public.tdr_usage_counters enable row level security;
alter table public.tdr_usage_actions enable row level security;
revoke all on table public.tdr_usage_counters from public, anon, authenticated;
revoke all on table public.tdr_usage_actions from public, anon, authenticated;
grant select, insert, update, delete on table public.tdr_usage_counters to service_role;
grant select, insert, update, delete on table public.tdr_usage_actions to service_role;

-- Atomic quota consumption.
--
-- Concurrency safety for the p_action_id dedup path: a naive
-- "select tdr_usage_actions, then increment, then insert" sequence lets
-- two concurrent callers sharing the same action_id both observe "not
-- claimed yet" and both increment before either finalizes its action row
-- -- a real double-count. This version closes that race with
-- pg_advisory_xact_lock: every caller sharing the same
-- (user, metric, action_id) serializes on that lock for the lifetime of
-- its transaction (one RPC call = one transaction, so the lock always
-- auto-releases at commit/rollback with no manual unlock needed), so the
-- second caller's SELECT always sees the first caller's already-committed
-- action row instead of racing it.
--
-- p_limit = null means unlimited (paid tiers): the counter is still
-- incremented for telemetry/reporting, but the request is always allowed.
create or replace function public.tdr_consume_usage(
  p_user_id uuid,
  p_metric text,
  p_period_key text,
  p_limit integer,
  p_action_id text default null
) returns table(allowed boolean, used integer, quota_limit integer)
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_existing record;
  v_count integer;
  v_allowed boolean;
begin
  if p_action_id is not null then
    perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || '|' || p_metric || '|' || p_action_id, 0));

    select a.allowed, a.used into v_existing
    from public.tdr_usage_actions a
    where a.user_id = p_user_id and a.metric = p_metric and a.action_id = p_action_id;
    if found then
      return query select v_existing.allowed, v_existing.used, p_limit;
      return;
    end if;
  end if;

  if p_limit is null then
    insert into public.tdr_usage_counters(user_id, metric, period_key, count, updated_at)
    values (p_user_id, p_metric, p_period_key, 1, now())
    on conflict (user_id, metric, period_key)
      do update set count = public.tdr_usage_counters.count + 1, updated_at = now()
    returning count into v_count;
    v_allowed := true;
  else
    insert into public.tdr_usage_counters(user_id, metric, period_key, count, updated_at)
    values (p_user_id, p_metric, p_period_key, 1, now())
    on conflict (user_id, metric, period_key)
      do update set count = public.tdr_usage_counters.count + 1, updated_at = now()
      where public.tdr_usage_counters.count < p_limit
    returning count into v_count;

    if v_count is null then
      v_allowed := false;
      select c.count into v_count from public.tdr_usage_counters c
      where c.user_id = p_user_id and c.metric = p_metric and c.period_key = p_period_key;
      v_count := coalesce(v_count, 0);
    else
      v_allowed := true;
    end if;
  end if;

  -- No ON CONFLICT here: the advisory lock above guarantees this session
  -- is the only writer for this action_id, and a pre-existing row for it
  -- would already have been returned early above.
  if p_action_id is not null then
    insert into public.tdr_usage_actions(user_id, metric, action_id, period_key, allowed, used)
    values (p_user_id, p_metric, p_action_id, p_period_key, v_allowed, v_count);
  end if;

  return query select v_allowed, v_count, p_limit;
end;
$$;

revoke all on function public.tdr_consume_usage(uuid, text, text, integer, text) from public, anon, authenticated;
grant execute on function public.tdr_consume_usage(uuid, text, text, integer, text) to service_role;

comment on function public.tdr_consume_usage is
  'Atomic check-and-increment quota consumption, race-free under concurrent identical calls via pg_advisory_xact_lock. p_action_id must be a server-computed request fingerprint (lib/access-policy-server.ts::requestFingerprint), never a raw client-supplied token.';

-- ---------------------------------------------------------------------
-- 3. Sales module selection (Free tier: choose 4 of 6, locked per cycle).
--
-- cycle_key is an opaque, app-computed string (see
-- lib/access-policy.ts::currentSalesModuleCycleKey). The schema does not
-- encode "calendar month" anywhere, so product can change the cycle
-- policy later (e.g. rolling 30 days) without a schema rewrite -- only
-- the app-side cycle-key function changes. provincial_registration is
-- deliberately not a selectable value here (see lib/access-policy.ts's
-- FEATURES registry) -- it is a reserved capability outside this catalog
-- entirely, not a 7th module a Free account could pick instead of one of
-- the six real ones.
-- ---------------------------------------------------------------------
create table if not exists public.tdr_sales_module_selection (
  user_id uuid not null references auth.users(id) on delete cascade,
  cycle_key text not null,
  modules text[] not null,
  locked_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, cycle_key),
  constraint tdr_sales_module_selection_count
    check (array_length(modules, 1) between 1 and 4),
  constraint tdr_sales_module_selection_known_modules
    check (modules <@ array[
      'brand_share','model_share','month_on_month',
      'segment_share','powertrain_share','chinese_bev_rank'
    ]::text[])
);

alter table public.tdr_sales_module_selection enable row level security;
revoke all on table public.tdr_sales_module_selection from public, anon, authenticated;
grant select, insert, update, delete on table public.tdr_sales_module_selection to service_role;

comment on table public.tdr_sales_module_selection is
  'Free-tier sales-module choice (4 of 6), locked for one selection cycle. cycle_key is app-computed (see lib/access-policy.ts) so the cycle policy can change without a schema rewrite.';

-- ---------------------------------------------------------------------
-- 4. Product telemetry (no prior analytics/event system exists in this
--    repo -- confirmed by repo-wide search before writing this migration).
-- ---------------------------------------------------------------------
create table if not exists public.tdr_product_events (
  id bigint generated always as identity primary key,
  user_id uuid references auth.users(id) on delete set null,
  customer_id uuid references public.tdr_customers(id) on delete set null,
  event_name text not null,
  event_props jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists tdr_product_events_name_time_idx
  on public.tdr_product_events(event_name, created_at desc);
create index if not exists tdr_product_events_user_idx
  on public.tdr_product_events(user_id, created_at desc);

alter table public.tdr_product_events enable row level security;
revoke all on table public.tdr_product_events from public, anon, authenticated;
grant select, insert on table public.tdr_product_events to service_role;

comment on table public.tdr_product_events is
  'Minimal auditable server-side product-event ledger (account_created, compare_run, sales_quota_hit, upgrade_viewed, etc. -- see lib/telemetry.ts for the full event set). Never stores payment-card data. Service-role only.';

-- ---------------------------------------------------------------------
-- 5. TDR-owned phone verification reservation/binding layer.
--
-- Supabase resolves phone-change OTP verification
-- (auth.updateUser({phone}) + auth.verifyOtp({type:"phone_change"}))
-- through auth.users.phone_change, which is NOT a unique column -- two
-- different pending auth users could in principle carry the same
-- phone_change value. A phone-change OTP succeeding is therefore not, by
-- itself, proof that a SPECIFIC TDR account is the one that completed
-- verification. This table lets TDR reserve (user, phone) BEFORE any SMS
-- is sent and only grant TDR-side confirmation after independently
-- re-checking the calling account's own current Supabase Auth state
-- matches what it reserved -- see lib/phone-verification.ts and
-- lib/access-policy-server.ts::hasTdrConfirmedPhoneVerification.
--
-- tdr_customer_phone_identities (migration_v21) remains the canonical
-- verified-phone ledger; this table is never written to it directly by
-- application code, only read to check for cross-account phone reuse.
-- ---------------------------------------------------------------------
create table if not exists public.tdr_phone_verification_attempts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  customer_id uuid not null references public.tdr_customers(id) on delete cascade,
  phone_e164 text not null check (phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),
  status text not null default 'PENDING' check (status in ('PENDING','CONFIRMED','EXPIRED','CANCELLED')),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '10 minutes'),
  confirmed_at timestamptz,
  updated_at timestamptz not null default now()
);

-- At most one ACTIVE (pending or confirmed) reservation may exist for a
-- given phone at a time, across every TDR customer -- this is the
-- database-level backstop (not just an application check-then-act) that
-- makes "prevent two active reservations from legitimately claiming the
-- same phone" race-safe under concurrent requests.
create unique index if not exists tdr_phone_verification_attempts_active_phone_uq
  on public.tdr_phone_verification_attempts(phone_e164)
  where status in ('PENDING', 'CONFIRMED');

create index if not exists tdr_phone_verification_attempts_user_idx
  on public.tdr_phone_verification_attempts(user_id, status, created_at desc);

alter table public.tdr_phone_verification_attempts enable row level security;
revoke all on table public.tdr_phone_verification_attempts from public, anon, authenticated;
grant select, insert, update, delete on table public.tdr_phone_verification_attempts to service_role;

comment on table public.tdr_phone_verification_attempts is
  'TDR-owned phone verification reservation/binding, closing a Supabase phone_change ambiguity gap (auth.users.phone_change is not unique). See lib/phone-verification.ts. Service-role only.';

-- Maintenance: expire abandoned PENDING reservations. This table is
-- fully TDR-owned, so unlike Supabase's own auth.users.phone_change
-- staleness (see the operational note below), a runtime cleanup path is
-- safe to implement here. Called lazily at the start of every new
-- reservation request (lib/phone-verification.ts::reservePhoneVerification)
-- so an abandoned attempt never permanently blocks a phone number; can
-- also be invoked on a schedule (e.g. a periodic job) if the deployment
-- has one, though that is not required for correctness.
create or replace function public.tdr_expire_stale_phone_verification_attempts()
returns integer
language sql
security invoker
set search_path = public, pg_temp
as $$
  with expired as (
    update public.tdr_phone_verification_attempts
    set status = 'EXPIRED', updated_at = now()
    where status = 'PENDING' and expires_at < now()
    returning 1
  )
  select count(*)::integer from expired;
$$;

revoke all on function public.tdr_expire_stale_phone_verification_attempts() from public, anon, authenticated;
grant execute on function public.tdr_expire_stale_phone_verification_attempts() to service_role;

comment on function public.tdr_expire_stale_phone_verification_attempts is
  'Marks abandoned PENDING tdr_phone_verification_attempts rows EXPIRED. Called lazily on every new reservation request; safe to also run on a schedule.';

-- ---------------------------------------------------------------------
-- Operational note: Supabase's own auth.users.phone_change staleness.
--
-- Separately from the TDR-owned table above, Supabase Auth itself can
-- carry a stale, unconfirmed `phone_change` value on `auth.users` when a
-- user starts (but never completes) a phone-change flow. There is no
-- documented, supported Admin API method (auth.admin.updateUserById or
-- otherwise) to directly clear a pending `phone_change` -- and
-- `auth.users` is Supabase-managed schema that this project does not
-- write to directly by convention (every other migration in this repo
-- only reads `auth.users`/creates triggers on it, never ALTERs its rows'
-- managed auth columns from application code). Implementing a "smallest
-- safe runtime cleanup" for that specific column is therefore not done
-- here -- there is nothing this repo's code can safely do to it.
--
-- In practice this is a non-issue for correctness: Supabase's documented
-- behavior is that a fresh `auth.updateUser({phone})` call overwrites any
-- prior pending `phone_change` for that same user, and TDR's own
-- reservation-cancel-and-retry flow (reservePhoneVerification cancels the
-- caller's previous PENDING reservation before creating a new one) always
-- triggers exactly that fresh call. A stale `phone_change` left behind by
-- a user who started verification and never returned is inert: it can
-- never itself grant TDR activation (this migration's
-- hasTdrConfirmedPhoneVerification check requires a matching CONFIRMED
-- TDR reservation, which never exists for an abandoned attempt), and it
-- does not block that phone number from anyone else's use of Supabase's
-- own OTP flow. Production currently has zero pending `phone_change`
-- rows (verified before writing this migration), so this is preventive
-- documentation, not incident recovery. If a stale `phone_change` is ever
-- suspected to require a fix, the supported path is the Supabase
-- Dashboard (Authentication > Users) or Supabase support, not a
-- migration or application code change against `auth.users`.
-- ---------------------------------------------------------------------
