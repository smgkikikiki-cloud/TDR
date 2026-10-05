-- Market Track M2 (docs/vehicle-db/VEHICLE_DB_V3.md §14.1): storage for the Ice Full
-- Package panels. Purely additive -- no existing table, view, or RPC is touched.
--
-- Each panel is its own table (CLAUDE.md rule 1: "never mix panels in one request or
-- export" -- a query against one of these tables can never accidentally combine rows
-- from a different panel). A "dims" lookup set (brand/province/reg_type/fuel/tyre/
-- model_group) backs the other five fact panels but is itself not a time series.
--
-- `period` is a Buddhist-calendar "YYYY-MM" string (e.g. '2569-08'), never a SQL date:
-- the Buddhist year does not correspond to a real Gregorian date, and the skill's own
-- period_from/period_to fields are plain strings.
--
-- Import model: "replace whole set" (tdr-package-import/SKILL.md §2 step 3) -- every
-- accepted package replaces every row of every one of these tables, because Ice may
-- revise historical figures in any period on any delivery. ice_package_imports is the
-- append-only log of each accepted replace (never itself replaced), recording exactly
-- what the skill requires: period, package version, master_version, status,
-- confirmed_by, and the package-level md5 index, so "which import produced the data
-- currently live" is always answerable without inferring it from the fact tables.
--
-- No row here is Vehicle Master data and none of this is read by any current_* view.
-- These tables have no application-facing contract yet; M4 defines how the market
-- engine reads them, behind the serving contract (SERVING_CONTRACT.md).

create table if not exists public.ice_package_imports (
  id bigint generated always as identity primary key,
  period text not null check (period ~ '^[0-9]{4}-[0-9]{2}$'),
  package_version integer not null check (package_version > 0),
  master_version text not null,
  status text not null,
  confirmed_by jsonb not null default '[]'::jsonb,
  md5_index jsonb not null default '{}'::jsonb,
  panels jsonb not null default '[]'::jsonb,
  imported_by text not null,
  imported_at timestamptz not null default now()
);

create index if not exists ice_package_imports_period_idx
  on public.ice_package_imports(period, imported_at desc);

-- --------------------------------------------------------------------------
-- Dims (lookup, not time series)
-- --------------------------------------------------------------------------

create table if not exists public.ice_dims_brand (
  brand text primary key
);

create table if not exists public.ice_dims_province (
  province text primary key
);

create table if not exists public.ice_dims_reg_type (
  reg_type text primary key
);

create table if not exists public.ice_dims_fuel (
  fuel_dlt text primary key,
  fuel_group text not null
);

create table if not exists public.ice_dims_tyre (
  tyre_size text primary key,
  rim_inch numeric
);

-- segment/body are nullable: the skill's contract (§1) names them, but the first real
-- delivery inspected for M2 did not carry them (dims/model_group.csv header was only
-- model_group_id,model_name,brand,reg_total_all). Never infer them from absence.
create table if not exists public.ice_dims_model_group (
  model_group_id text primary key,
  model_name text not null,
  brand text not null,
  reg_total_all bigint,
  segment text,
  body text
);

-- --------------------------------------------------------------------------
-- Fact panels
-- --------------------------------------------------------------------------

create table if not exists public.ice_reg_province (
  period text not null check (period ~ '^[0-9]{4}-[0-9]{2}$'),
  province text not null,
  reg_type text not null,
  brand text not null,
  fuel_group text not null,
  reg_count bigint not null check (reg_count >= 0),
  primary key (period, province, reg_type, brand, fuel_group)
);

create table if not exists public.ice_reg_trend (
  period text not null check (period ~ '^[0-9]{4}-[0-9]{2}$'),
  province text not null,
  reg_type text not null,
  brand text not null,
  model_group_id text not null,
  model_name text not null,
  reg_count bigint not null check (reg_count >= 0),
  primary key (period, province, reg_type, brand, model_group_id)
);

create index if not exists ice_reg_trend_model_idx on public.ice_reg_trend(model_group_id);

-- certainty: exact | family | range (tdr-package-import/SKILL.md §4).
create table if not exists public.ice_reg_powertrain (
  period text not null check (period ~ '^[0-9]{4}-[0-9]{2}$'),
  province text not null,
  reg_type text not null,
  brand text not null,
  model_group_id text not null,
  model_name text not null,
  fuel_group text not null,
  reg_est numeric,
  reg_min numeric,
  reg_max numeric,
  certainty text not null check (certainty in ('exact', 'family', 'range')),
  primary key (period, province, reg_type, brand, model_group_id)
);

create index if not exists ice_reg_powertrain_model_idx on public.ice_reg_powertrain(model_group_id);

create table if not exists public.ice_rim_province (
  period text not null check (period ~ '^[0-9]{4}-[0-9]{2}$'),
  province text not null,
  reg_type text not null,
  brand text not null,
  rim_bucket text not null,
  reg_est numeric,
  primary key (period, province, reg_type, brand, rim_bucket)
);

create table if not exists public.ice_tyre_province (
  period text not null check (period ~ '^[0-9]{4}-[0-9]{2}$'),
  province text not null,
  reg_type text not null,
  brand text not null,
  tyre_size text not null,
  rim_inch numeric,
  reg_est numeric,
  primary key (period, province, reg_type, brand, tyre_size)
);

-- Shared by rim_province and tyre_province (tdr-package-import/SKILL.md §1); both
-- panels ship the identical data/coverage.csv, so it is stored once.
create table if not exists public.ice_tyre_coverage (
  period text not null check (period ~ '^[0-9]{4}-[0-9]{2}$'),
  province text not null,
  reg_type text not null,
  brand text not null,
  reg_total numeric,
  reg_tyre_known numeric,
  primary key (period, province, reg_type, brand)
);

-- --------------------------------------------------------------------------
-- Access: server-side only, same pattern as the Vehicle Master tables
-- (migration_v57). RLS is on and no policy exists, so browser roles get
-- nothing; service_role bypasses RLS for the importer and the future M4
-- market engine.
-- --------------------------------------------------------------------------

do $$
declare
  relation_name text;
begin
  foreach relation_name in array array[
    'ice_package_imports',
    'ice_dims_brand', 'ice_dims_province', 'ice_dims_reg_type', 'ice_dims_fuel',
    'ice_dims_tyre', 'ice_dims_model_group',
    'ice_reg_province', 'ice_reg_trend', 'ice_reg_powertrain',
    'ice_rim_province', 'ice_tyre_province', 'ice_tyre_coverage'
  ] loop
    execute format('alter table public.%I enable row level security', relation_name);
    execute format('revoke all on public.%I from public, anon, authenticated', relation_name);
    execute format('grant select, insert, update, delete on public.%I to service_role', relation_name);
  end loop;
end
$$;
