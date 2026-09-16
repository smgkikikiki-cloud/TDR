-- Freemium/tiered access-policy foundation: account-profile extension,
-- server-side usage metering (atomic, concurrency-safe), sales-module
-- selection storage, and product telemetry.
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
-- lib/billing.ts::requireMember() already reads/writes a table by this
-- name (user_id, phone_e164) but no prior migration ever created it --
-- migration_v21_billing.sql only migrates *out of* it conditionally, via
-- `if to_regclass('public.tdr_customer_profiles') is not null`. This
-- migration creates it for real, with the additional fields the free
-- account/profile requirement needs: postcode, company/individual flag,
-- and auditable marketing-consent (boolean + timestamp + text version).
-- ---------------------------------------------------------------------
create table if not exists public.tdr_customer_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  customer_id uuid references public.tdr_customers(id) on delete cascade,
  email text,
  phone_e164 text check (phone_e164 is null or phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),
  postcode text check (postcode is null or postcode ~ '^[0-9]{4,10}$'),
  is_individual boolean not null default true,
  company_name text,
  marketing_consent boolean not null default false,
  marketing_consent_at timestamptz,
  marketing_consent_version text,
  profile_completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint tdr_customer_profiles_company_required_unless_individual
    check (is_individual or (company_name is not null and length(trim(company_name)) > 0)),
  constraint tdr_customer_profiles_consent_is_auditable
    check (not marketing_consent or (marketing_consent_at is not null and marketing_consent_version is not null))
);

-- Backfill customer_id for any profile row created before this column
-- existed (defensive; the table itself is new, so this is a no-op today).
update public.tdr_customer_profiles p set customer_id = c.id
from public.tdr_customers c
where p.customer_id is null and c.auth_user_id = p.user_id;

create index if not exists tdr_customer_profiles_customer_idx
  on public.tdr_customer_profiles(customer_id);

alter table public.tdr_customer_profiles enable row level security;
revoke all on table public.tdr_customer_profiles from public, anon, authenticated;
grant select, insert, update, delete on table public.tdr_customer_profiles to service_role;

comment on table public.tdr_customer_profiles is
  'Additive account/profile detail (postcode, company vs individual, auditable marketing consent). Server-role only -- read/written exclusively through /api/account/profile and lib/billing.ts::requireMember(), never directly by anon/authenticated.';

-- ---------------------------------------------------------------------
-- 2. Usage metering: tdr_usage_counters + tdr_usage_actions + the
--    atomic consume RPC.
--
-- "One logical user action" (e.g. one Sales Tools Run/Apply, one Compare
-- submission) can fan out into several internal HTTP calls. The action-id
-- dedup table lets every call in that fan-out share one quota decision:
-- the first call for a given (user, metric, action_id) makes the atomic
-- decision and every later call with the same action_id reads it back
-- instead of consuming quota again.
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
  created_at timestamptz not null default now(),
  primary key (user_id, metric, action_id)
);

alter table public.tdr_usage_counters enable row level security;
alter table public.tdr_usage_actions enable row level security;
revoke all on table public.tdr_usage_counters from public, anon, authenticated;
revoke all on table public.tdr_usage_actions from public, anon, authenticated;
grant select, insert, update, delete on table public.tdr_usage_counters to service_role;
grant select, insert, update, delete on table public.tdr_usage_actions to service_role;

-- Atomic quota consumption. A single statement performs the
-- check-and-increment so concurrent requests from the same user cannot
-- both observe "under limit" and both be admitted past it.
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
  v_existing_action record;
  v_count integer;
  v_allowed boolean;
begin
  if p_action_id is not null then
    select a.allowed into v_existing_action
    from public.tdr_usage_actions a
    where a.user_id = p_user_id and a.metric = p_metric and a.action_id = p_action_id;

    if found then
      select c.count into v_count from public.tdr_usage_counters c
      where c.user_id = p_user_id and c.metric = p_metric and c.period_key = p_period_key;
      return query select v_existing_action.allowed, coalesce(v_count, 0), p_limit;
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

  if p_action_id is not null then
    insert into public.tdr_usage_actions(user_id, metric, action_id, period_key, allowed)
    values (p_user_id, p_metric, p_action_id, p_period_key, v_allowed)
    on conflict (user_id, metric, action_id) do nothing;
  end if;

  return query select v_allowed, v_count, p_limit;
end;
$$;

revoke all on function public.tdr_consume_usage(uuid, text, text, integer, text) from public, anon, authenticated;
grant execute on function public.tdr_consume_usage(uuid, text, text, integer, text) to service_role;

comment on function public.tdr_consume_usage is
  'Atomic check-and-increment quota consumption. p_action_id lets multiple internal calls belonging to one logical user action (e.g. one Sales Tools Run) share a single quota decision.';

-- ---------------------------------------------------------------------
-- 3. Sales module selection (Free tier: choose 4 of 6, locked per cycle).
--
-- cycle_key is an opaque, app-computed string (see
-- lib/access-policy.ts::currentSalesModuleCycleKey). The schema does not
-- encode "calendar month" anywhere, so product can change the cycle
-- policy later (e.g. rolling 30 days) without a schema rewrite -- only
-- the app-side cycle-key function changes.
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
