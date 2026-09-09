-- Canonical Vehicle Master serving releases and market-data entitlement gate.
-- A release is immutable after activation. All projection rows are versioned by
-- release_id, so activation and rollback only move one pointer.

create table if not exists public.canonical_vehicle_releases (
  release_id text primary key,
  schema_version integer not null,
  canonical_revision text not null,
  source_hash text not null,
  as_of date not null,
  counts jsonb not null,
  payload jsonb not null,
  status text not null check (status in ('STAGING','ACTIVE','SUPERSEDED')),
  created_at timestamptz not null default now(),
  activated_at timestamptz
);

create table if not exists public.canonical_vehicle_state (
  scope text primary key,
  active_release_id text not null references public.canonical_vehicle_releases(release_id),
  activated_at timestamptz not null default now()
);

create table if not exists public.canonical_brand_projection (
  release_id text not null references public.canonical_vehicle_releases(release_id) on delete cascade,
  canonical_id text not null,
  tdr_brand_id uuid references public.brands(id) on delete set null,
  slug text not null,
  name_en text not null,
  name_th text,
  origin_country text,
  payload jsonb not null,
  primary key (release_id, canonical_id),
  unique (release_id, slug)
);

create table if not exists public.canonical_model_projection (
  release_id text not null references public.canonical_vehicle_releases(release_id) on delete cascade,
  canonical_id text not null,
  tdr_model_id uuid references public.models(id) on delete set null,
  brand_id text not null,
  slug text not null,
  name_en text not null,
  name_th text,
  generation_id text,
  status text not null,
  segment text,
  body_type text,
  retail_price_min numeric,
  retail_price_max numeric,
  payload jsonb not null,
  primary key (release_id, canonical_id),
  unique (release_id, slug)
);

create index if not exists canonical_model_projection_brand_idx
  on public.canonical_model_projection(release_id, brand_id);

create table if not exists public.canonical_generation_projection (
  release_id text not null references public.canonical_vehicle_releases(release_id) on delete cascade,
  canonical_id text not null,
  model_id text not null,
  code text,
  segment text,
  launched date,
  ended date,
  payload jsonb not null,
  primary key (release_id, canonical_id),
  foreign key (release_id, model_id)
    references public.canonical_model_projection(release_id, canonical_id) on delete cascade
);

create table if not exists public.canonical_market_trim_projection (
  release_id text not null references public.canonical_vehicle_releases(release_id) on delete cascade,
  canonical_id text not null,
  model_id text not null,
  generation_id text not null,
  variant_id text,
  name text not null,
  powertrain text not null,
  status text not null default 'current',
  payload jsonb not null,
  current_list_price jsonb,
  campaign_quote jsonb not null default '{}'::jsonb,
  price_history jsonb not null default '[]'::jsonb,
  source_refs jsonb not null default '{}'::jsonb,
  primary key (release_id, canonical_id),
  foreign key (release_id, model_id)
    references public.canonical_model_projection(release_id, canonical_id) on delete cascade,
  foreign key (release_id, generation_id)
    references public.canonical_generation_projection(release_id, canonical_id) on delete cascade
);

create index if not exists canonical_market_trim_model_idx
  on public.canonical_market_trim_projection(release_id, model_id);

create table if not exists public.canonical_price_projection (
  release_id text not null references public.canonical_vehicle_releases(release_id) on delete cascade,
  record_id text not null,
  trim_id text not null,
  amount_thb bigint not null,
  price_type text not null,
  effective_from date,
  effective_to date,
  observed_at date,
  campaign_id text,
  option_id text,
  source text,
  source_ref text,
  payload jsonb not null,
  primary key (release_id, record_id),
  foreign key (release_id, trim_id)
    references public.canonical_market_trim_projection(release_id, canonical_id) on delete cascade
);

create index if not exists canonical_price_trim_idx
  on public.canonical_price_projection(release_id, trim_id, price_type);

create table if not exists public.canonical_spec_projection (
  release_id text not null references public.canonical_vehicle_releases(release_id) on delete cascade,
  fact_id text not null,
  trim_id text not null,
  field_key text,
  verification_status text,
  payload jsonb not null,
  primary key (release_id, fact_id),
  foreign key (release_id, trim_id)
    references public.canonical_market_trim_projection(release_id, canonical_id) on delete cascade
);

create table if not exists public.tdr_entitlements (
  user_id uuid not null references auth.users(id) on delete cascade,
  product text not null,
  status text not null check (status in ('ACTIVE','TRIALING','GRACE','EXPIRED','REVOKED')),
  valid_until timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, product)
);

create table if not exists public.public_model_market_teaser (
  canonical_model_id text not null,
  period date not null,
  metric text not null,
  display_value text not null,
  context text,
  updated_at timestamptz not null default now(),
  primary key (canonical_model_id, period, metric)
);

alter table public.canonical_vehicle_releases enable row level security;
alter table public.canonical_vehicle_state enable row level security;
alter table public.canonical_brand_projection enable row level security;
alter table public.canonical_model_projection enable row level security;
alter table public.canonical_generation_projection enable row level security;
alter table public.canonical_market_trim_projection enable row level security;
alter table public.canonical_price_projection enable row level security;
alter table public.canonical_spec_projection enable row level security;
alter table public.tdr_entitlements enable row level security;
alter table public.public_model_market_teaser enable row level security;

drop policy if exists "public read canonical state" on public.canonical_vehicle_state;
create policy "public read canonical state" on public.canonical_vehicle_state
  for select to anon, authenticated using (true);
drop policy if exists "public read canonical brands" on public.canonical_brand_projection;
create policy "public read canonical brands" on public.canonical_brand_projection
  for select to anon, authenticated using (true);
drop policy if exists "public read canonical models" on public.canonical_model_projection;
create policy "public read canonical models" on public.canonical_model_projection
  for select to anon, authenticated using (true);
drop policy if exists "public read canonical generations" on public.canonical_generation_projection;
create policy "public read canonical generations" on public.canonical_generation_projection
  for select to anon, authenticated using (true);
drop policy if exists "public read canonical market trims" on public.canonical_market_trim_projection;
create policy "public read canonical market trims" on public.canonical_market_trim_projection
  for select to anon, authenticated using (true);
drop policy if exists "public read canonical prices" on public.canonical_price_projection;
create policy "public read canonical prices" on public.canonical_price_projection
  for select to anon, authenticated using (true);
drop policy if exists "public read canonical specs" on public.canonical_spec_projection;
create policy "public read canonical specs" on public.canonical_spec_projection
  for select to anon, authenticated using (true);
drop policy if exists "user reads own entitlements" on public.tdr_entitlements;
create policy "user reads own entitlements" on public.tdr_entitlements
  for select to authenticated using ((select auth.uid()) = user_id);
drop policy if exists "public read market teasers" on public.public_model_market_teaser;
create policy "public read market teasers" on public.public_model_market_teaser
  for select to anon, authenticated using (true);

grant select on public.canonical_vehicle_state,
  public.canonical_brand_projection, public.canonical_model_projection,
  public.canonical_generation_projection, public.canonical_market_trim_projection,
  public.canonical_price_projection, public.canonical_spec_projection,
  public.public_model_market_teaser to anon, authenticated;
grant select on public.tdr_entitlements to authenticated;

create or replace function public.has_market_access(requested_product text default 'MARKET_ANALYTICS')
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.tdr_entitlements e
    where e.user_id = (select auth.uid())
      and e.product = upper(requested_product)
      and e.status in ('ACTIVE','TRIALING','GRACE')
      and (e.valid_until is null or e.valid_until > now())
  );
$$;

revoke all on function public.has_market_access(text) from public, anon;
grant execute on function public.has_market_access(text) to authenticated, service_role;

drop policy if exists "public read registrations" on public.registrations;
drop policy if exists "paid read registrations" on public.registrations;
create policy "paid read registrations" on public.registrations
  for select to authenticated using ((select public.has_market_access('MARKET_ANALYTICS')));
revoke select on public.registrations from public, anon;
grant select on public.registrations to authenticated, service_role;

create or replace function public.publish_vehicle_release(release jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  rid text := release->>'release_id';
  expected jsonb := release->'counts';
  actual jsonb;
begin
  if rid is null or rid !~ '^vehicle-[0-9]{4}-[a-f0-9]{16}$' then
    raise exception 'invalid release_id';
  end if;
  if coalesce((release->>'schema_version')::integer, 0) <> 1 then
    raise exception 'unsupported schema_version';
  end if;
  if release->>'source_hash' is null or release->>'canonical_revision' is null then
    raise exception 'source_hash and canonical_revision are required';
  end if;

  actual := jsonb_build_object(
    'brands', jsonb_array_length(coalesce(release->'brands','[]'::jsonb)),
    'models', jsonb_array_length(coalesce(release->'models','[]'::jsonb)),
    'generations', jsonb_array_length(coalesce(release->'generations','[]'::jsonb)),
    'market_trims', jsonb_array_length(coalesce(release->'market_trims','[]'::jsonb)),
    'price_ledger', jsonb_array_length(coalesce(release->'price_ledger','[]'::jsonb)),
    'spec_facts', jsonb_array_length(coalesce(release->'spec_facts','[]'::jsonb))
  );
  if actual <> expected then
    raise exception 'release counts do not match payload: expected %, actual %', expected, actual;
  end if;

  insert into public.canonical_vehicle_releases
    (release_id, schema_version, canonical_revision, source_hash, as_of, counts, payload, status)
  values
    (rid, 1, release->>'canonical_revision', release->>'source_hash',
     (release->>'as_of')::date, expected, release, 'STAGING')
  on conflict (release_id) do update set
    canonical_revision = excluded.canonical_revision,
    source_hash = excluded.source_hash,
    as_of = excluded.as_of,
    counts = excluded.counts,
    payload = excluded.payload,
    status = 'STAGING';

  delete from public.canonical_brand_projection where release_id = rid;
  insert into public.canonical_brand_projection
    (release_id, canonical_id, tdr_brand_id, slug, name_en, name_th, origin_country, payload)
  select rid, x->>'canonical_id', nullif(x->>'tdr_brand_id','')::uuid,
    x->>'slug', x->>'name_en', x->>'name_th', x->>'origin_country', x->'payload'
  from jsonb_array_elements(release->'brands') x;

  delete from public.canonical_model_projection where release_id = rid;
  insert into public.canonical_model_projection
    (release_id, canonical_id, tdr_model_id, brand_id, slug, name_en, name_th,
     generation_id, status, segment, body_type, retail_price_min, retail_price_max, payload)
  select rid, x->>'canonical_id', nullif(x->>'tdr_model_id','')::uuid,
    x->>'brand_id', x->>'slug', x->>'name_en', x->>'name_th',
    x->>'generation_id', x->>'status', x->>'segment', x->>'body_type',
    nullif(x->>'retail_price_min','')::numeric,
    nullif(x->>'retail_price_max','')::numeric, x->'payload'
  from jsonb_array_elements(release->'models') x;

  delete from public.canonical_generation_projection where release_id = rid;
  insert into public.canonical_generation_projection
    (release_id, canonical_id, model_id, code, segment, launched, ended, payload)
  select rid, x->>'canonical_id', x->>'model_id', x->>'code', x->>'segment',
    nullif(x->>'launched','')::date, nullif(x->>'ended','')::date, x->'payload'
  from jsonb_array_elements(release->'generations') x;

  delete from public.canonical_market_trim_projection where release_id = rid;
  insert into public.canonical_market_trim_projection
    (release_id, canonical_id, model_id, generation_id, variant_id, name,
     powertrain, status, payload, current_list_price, campaign_quote, price_history, source_refs)
  select rid, x->>'canonical_id', x->>'model_id', x->>'generation_id',
    nullif(x->>'variant_id',''), x->>'name', x->>'powertrain',
    coalesce(x->>'status', 'current'), x->'payload',
    x->'current_list_price', coalesce(x->'campaign_quote','{}'::jsonb),
    coalesce(x->'price_history','[]'::jsonb), coalesce(x->'source_refs','{}'::jsonb)
  from jsonb_array_elements(release->'market_trims') x;

  delete from public.canonical_price_projection where release_id = rid;
  insert into public.canonical_price_projection
    (release_id, record_id, trim_id, amount_thb, price_type, effective_from,
     effective_to, observed_at, campaign_id, option_id, source, source_ref, payload)
  select rid, x->>'record_id', x->>'trim_id', (x->>'amount_thb')::bigint,
    x->>'price_type', nullif(x->>'effective_from','')::date,
    nullif(x->>'effective_to','')::date, nullif(x->>'observed_at','')::date,
    x->>'campaign_id', x->>'option_id', x->>'source', x->>'source_ref', x
  from jsonb_array_elements(release->'price_ledger') x;

  delete from public.canonical_spec_projection where release_id = rid;
  insert into public.canonical_spec_projection
    (release_id, fact_id, trim_id, field_key, verification_status, payload)
  select rid, x->>'fact_id', x->>'trim_id', x->>'field_key',
    x->>'verification_status', x
  from jsonb_array_elements(release->'spec_facts') x;

  update public.canonical_vehicle_releases
    set status = 'SUPERSEDED'
    where status = 'ACTIVE' and release_id <> rid;
  update public.canonical_vehicle_releases
    set status = 'ACTIVE', activated_at = now()
    where release_id = rid;
  insert into public.canonical_vehicle_state(scope, active_release_id, activated_at)
    values ('vehicle_catalog', rid, now())
    on conflict (scope) do update set
      active_release_id = excluded.active_release_id,
      activated_at = excluded.activated_at;

  return jsonb_build_object('release_id', rid, 'status', 'ACTIVE', 'counts', actual);
end;
$$;

revoke all on function public.publish_vehicle_release(jsonb) from public, anon, authenticated;
grant execute on function public.publish_vehicle_release(jsonb) to service_role;

create or replace function public.rollback_vehicle_release(target_release_id text)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if not exists (select 1 from public.canonical_vehicle_releases where release_id = target_release_id) then
    raise exception 'unknown release %', target_release_id;
  end if;
  update public.canonical_vehicle_releases set status = 'SUPERSEDED' where status = 'ACTIVE';
  update public.canonical_vehicle_releases
    set status = 'ACTIVE', activated_at = now() where release_id = target_release_id;
  insert into public.canonical_vehicle_state(scope, active_release_id, activated_at)
    values ('vehicle_catalog', target_release_id, now())
    on conflict (scope) do update set
      active_release_id = excluded.active_release_id,
      activated_at = excluded.activated_at;
  return jsonb_build_object('release_id', target_release_id, 'status', 'ACTIVE');
end;
$$;

revoke all on function public.rollback_vehicle_release(text) from public, anon, authenticated;
grant execute on function public.rollback_vehicle_release(text) to service_role;

create or replace view public.current_vehicle_brands
with (security_invoker = true) as
select p.* from public.canonical_brand_projection p
join public.canonical_vehicle_state s
  on s.scope = 'vehicle_catalog' and s.active_release_id = p.release_id;

create or replace view public.current_vehicle_models
with (security_invoker = true) as
select p.* from public.canonical_model_projection p
join public.canonical_vehicle_state s
  on s.scope = 'vehicle_catalog' and s.active_release_id = p.release_id;

create or replace view public.current_vehicle_generations
with (security_invoker = true) as
select p.* from public.canonical_generation_projection p
join public.canonical_vehicle_state s
  on s.scope = 'vehicle_catalog' and s.active_release_id = p.release_id;

create or replace view public.current_market_trims
with (security_invoker = true) as
select p.* from public.canonical_market_trim_projection p
join public.canonical_vehicle_state s
  on s.scope = 'vehicle_catalog' and s.active_release_id = p.release_id;

create or replace view public.current_price_ledger
with (security_invoker = true) as
select p.* from public.canonical_price_projection p
join public.canonical_vehicle_state s
  on s.scope = 'vehicle_catalog' and s.active_release_id = p.release_id;

create or replace view public.current_spec_facts
with (security_invoker = true) as
select p.* from public.canonical_spec_projection p
join public.canonical_vehicle_state s
  on s.scope = 'vehicle_catalog' and s.active_release_id = p.release_id;

grant select on public.current_vehicle_brands, public.current_vehicle_models,
  public.current_vehicle_generations, public.current_market_trims,
  public.current_price_ledger, public.current_spec_facts to anon, authenticated;

grant all on public.canonical_vehicle_releases, public.canonical_vehicle_state,
  public.canonical_brand_projection, public.canonical_model_projection,
  public.canonical_generation_projection, public.canonical_market_trim_projection,
  public.canonical_price_projection, public.canonical_spec_projection,
  public.tdr_entitlements to service_role;

