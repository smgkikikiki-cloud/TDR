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
-- period_from/period_to fields are plain strings. The check constraint validates shape
-- only (four digits, dash, two digits) -- it cannot and does not try to distinguish a
-- Buddhist year from a Gregorian-looking one by range.
--
-- Import model: "replace whole set" (tdr-package-import/SKILL.md §2 step 3) -- every
-- accepted package replaces every row of every one of the six fact/dims tables,
-- because Ice may revise historical figures in any period on any delivery. This must
-- happen atomically: a `<table>_staging` twin of each live table exists so the
-- importer can load and reconcile a complete new delivery with zero visible effect,
-- then call `ice_commit_staged_import()` -- one function, one transaction -- which
-- replaces every live table from its staging twin and records the import log row
-- together, or raises and leaves every live table exactly as it was. The importer
-- (tools/ice_package_import.py) never issues its own per-table DELETE/INSERT against
-- a *live* table; only against staging, which is never read by anything live.
--
-- ice_package_imports is the append-only log of each accepted replace (never itself
-- replaced), recording exactly what the skill requires: period, package version,
-- master_version, status, confirmed_by, and the package-level md5 index, so "which
-- import produced the data currently live" is always answerable without inferring it
-- from the fact tables.
--
-- No row here is Vehicle Master data and none of this is read by any current_* view.
-- These tables have no application-facing contract yet; M4 defines how the market
-- engine reads them, behind the serving contract (SERVING_CONTRACT.md).
--
-- UNVERIFIED ASSUMPTION, isolated here rather than left implicit: the exact outer
-- full_package.json schema (the field names status/confirmed_by/panels/files/period/
-- version/master_version/changelog_since) has never been observed in a real Full
-- Package -- every real delivery inspected for M2 so far was missing that file
-- entirely. It is inferred from tdr-package-import/SKILL.md's prose and the owner's
-- own field list. This migration's schema does NOT depend on that assumption: every
-- table/column here is ground-truthed against the real per-panel manifest.json/
-- panel.json files and CSV headers already inspected. If the real full_package.json
-- turns out to use different field names, only vehreg/ice_package.py's
-- verify_full_package_status/verify_panel_set/verify_package_md5_index/
-- verify_changelog_continuity and their test fixtures need to change -- not this file.

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
--
-- PK includes fuel_group, unlike reg_trend: the panel's own grain is model x
-- powertrain (SKILL.md §1's "รุ่น x ระบบขับเคลื่อน"), and fuel_group is part of
-- that grain, not merely a display label the way model_name is for reg_trend's
-- model_group_id. No Ice contract has been seen guaranteeing a model group maps to
-- exactly one fuel_group within a period/province/reg_type/brand (a model group can
-- plausibly cover more than one powertrain, e.g. a nameplate sold as both HEV and
-- ICE) -- the narrower (period, province, reg_type, brand, model_group_id) key
-- would silently collapse such rows onto each other. Audited every other table in
-- this file against its own documented column list for the same risk: reg_trend
-- (model_group_id's own name is a 1:1 label, not an extra dimension),
-- rim_province/tyre_province (tyre_size already encodes rim_inch; rim_bucket/
-- tyre_size are themselves the full extra dimension beyond province/brand/type),
-- and every ice_dims_* lookup (one row per natural identity, no period) all already
-- match their documented grain exactly -- this was the one real gap.
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
  primary key (period, province, reg_type, brand, model_group_id, fuel_group)
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
-- Staging twins -- one per live table above, identical shape and PK. The
-- importer loads a complete new delivery here (never read by anything live),
-- then ice_commit_staged_import() moves every table over atomically.
-- --------------------------------------------------------------------------

create table if not exists public.ice_dims_brand_staging (like public.ice_dims_brand);
create table if not exists public.ice_dims_province_staging (like public.ice_dims_province);
create table if not exists public.ice_dims_reg_type_staging (like public.ice_dims_reg_type);
create table if not exists public.ice_dims_fuel_staging (like public.ice_dims_fuel);
create table if not exists public.ice_dims_tyre_staging (like public.ice_dims_tyre);
create table if not exists public.ice_dims_model_group_staging (like public.ice_dims_model_group);
create table if not exists public.ice_reg_province_staging (like public.ice_reg_province);
create table if not exists public.ice_reg_trend_staging (like public.ice_reg_trend);
create table if not exists public.ice_reg_powertrain_staging (like public.ice_reg_powertrain);
create table if not exists public.ice_rim_province_staging (like public.ice_rim_province);
create table if not exists public.ice_tyre_province_staging (like public.ice_tyre_province);
create table if not exists public.ice_tyre_coverage_staging (like public.ice_tyre_coverage);

-- Postgres has no "ADD PRIMARY KEY IF NOT EXISTS"; add one only when the
-- table doesn't already have one, so replaying this migration (proven by
-- test_v62_replays_and_is_idempotent) never tries to add a second primary
-- key to a staging table that already has one from a prior run.
do $$
declare
  staging_pk record;
begin
  for staging_pk in
    select * from (values
      ('ice_dims_brand_staging', 'brand'),
      ('ice_dims_province_staging', 'province'),
      ('ice_dims_reg_type_staging', 'reg_type'),
      ('ice_dims_fuel_staging', 'fuel_dlt'),
      ('ice_dims_tyre_staging', 'tyre_size'),
      ('ice_dims_model_group_staging', 'model_group_id'),
      ('ice_reg_province_staging', 'period, province, reg_type, brand, fuel_group'),
      ('ice_reg_trend_staging', 'period, province, reg_type, brand, model_group_id'),
      ('ice_reg_powertrain_staging', 'period, province, reg_type, brand, model_group_id, fuel_group'),
      ('ice_rim_province_staging', 'period, province, reg_type, brand, rim_bucket'),
      ('ice_tyre_province_staging', 'period, province, reg_type, brand, tyre_size'),
      ('ice_tyre_coverage_staging', 'period, province, reg_type, brand')
    ) as t(table_name, pk_columns)
  loop
    if not exists (
      select 1 from pg_constraint
      where conrelid = ('public.' || staging_pk.table_name)::regclass
        and contype = 'p'
    ) then
      execute format('alter table public.%I add primary key (%s)', staging_pk.table_name, staging_pk.pk_columns);
    end if;
  end loop;
end
$$;

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
    'ice_rim_province', 'ice_tyre_province', 'ice_tyre_coverage',
    'ice_dims_brand_staging', 'ice_dims_province_staging', 'ice_dims_reg_type_staging',
    'ice_dims_fuel_staging', 'ice_dims_tyre_staging', 'ice_dims_model_group_staging',
    'ice_reg_province_staging', 'ice_reg_trend_staging', 'ice_reg_powertrain_staging',
    'ice_rim_province_staging', 'ice_tyre_province_staging', 'ice_tyre_coverage_staging'
  ] loop
    execute format('alter table public.%I enable row level security', relation_name);
    execute format('revoke all on public.%I from public, anon, authenticated', relation_name);
    execute format('grant select, insert, update, delete on public.%I to service_role', relation_name);
  end loop;
end
$$;

-- --------------------------------------------------------------------------
-- Atomic commit: staging -> live + import log, one function, one transaction.
-- Every table must already be staged (non-empty) or the whole call raises
-- before touching any live table -- Postgres rolls the entire function call
-- back on any exception, so a failure here leaves every live table exactly
-- as it was. Not security definer: only service_role is ever granted
-- execute, and service_role already bypasses RLS on every table involved.
-- --------------------------------------------------------------------------

create or replace function public.ice_commit_staged_import(
  p_period text,
  p_package_version integer,
  p_master_version text,
  p_status text,
  p_confirmed_by jsonb,
  p_md5_index jsonb,
  p_panels jsonb,
  p_imported_by text
)
returns jsonb
language plpgsql
set search_path = public, pg_temp
as $$
declare
  tbl text;
  staged_count bigint;
  live_count bigint;
  counts jsonb := '{}'::jsonb;
begin
  foreach tbl in array array[
    'ice_reg_province', 'ice_reg_trend', 'ice_reg_powertrain',
    'ice_rim_province', 'ice_tyre_province', 'ice_tyre_coverage',
    'ice_dims_brand', 'ice_dims_province', 'ice_dims_reg_type',
    'ice_dims_fuel', 'ice_dims_tyre', 'ice_dims_model_group'
  ] loop
    execute format('select count(*) from public.%I', tbl || '_staging') into staged_count;
    if staged_count = 0 then
      raise exception using errcode = '55000',
        message = format('refused ice_commit_staged_import: %s is empty', tbl || '_staging'),
        hint = 'stage every panel''s rows before committing -- an empty staging table '
               'means the import never finished staging, and nothing has been replaced';
    end if;
  end loop;

  foreach tbl in array array[
    'ice_reg_province', 'ice_reg_trend', 'ice_reg_powertrain',
    'ice_rim_province', 'ice_tyre_province', 'ice_tyre_coverage',
    'ice_dims_brand', 'ice_dims_province', 'ice_dims_reg_type',
    'ice_dims_fuel', 'ice_dims_tyre', 'ice_dims_model_group'
  ] loop
    execute format('delete from public.%I', tbl);
    execute format('insert into public.%I select * from public.%I', tbl, tbl || '_staging');
    execute format('delete from public.%I', tbl || '_staging');
    execute format('select count(*) from public.%I', tbl) into live_count;
    counts := counts || jsonb_build_object(tbl, live_count);
  end loop;

  insert into public.ice_package_imports
    (period, package_version, master_version, status, confirmed_by, md5_index, panels, imported_by)
  values
    (p_period, p_package_version, p_master_version, p_status, p_confirmed_by, p_md5_index,
     p_panels, p_imported_by);

  return jsonb_build_object('tables', counts, 'period', p_period, 'master_version', p_master_version);
end;
$$;

revoke all on function public.ice_commit_staged_import(
  text, integer, text, text, jsonb, jsonb, jsonb, text
) from public, anon, authenticated;
grant execute on function public.ice_commit_staged_import(
  text, integer, text, text, jsonb, jsonb, jsonb, text
) to service_role;

-- Independent post-commit readback: a fresh count of every live table, called
-- by the importer after ice_commit_staged_import returns, so a discrepancy
-- between what was staged and what is actually live is caught by re-reading
-- the committed state rather than only trusting the commit call's own
-- self-reported counts.
create or replace function public.ice_live_table_counts()
returns jsonb
language plpgsql
set search_path = public, pg_temp
as $$
declare
  tbl text;
  cnt bigint;
  result jsonb := '{}'::jsonb;
begin
  foreach tbl in array array[
    'ice_reg_province', 'ice_reg_trend', 'ice_reg_powertrain',
    'ice_rim_province', 'ice_tyre_province', 'ice_tyre_coverage',
    'ice_dims_brand', 'ice_dims_province', 'ice_dims_reg_type',
    'ice_dims_fuel', 'ice_dims_tyre', 'ice_dims_model_group'
  ] loop
    execute format('select count(*) from public.%I', tbl) into cnt;
    result := result || jsonb_build_object(tbl, cnt);
  end loop;
  return result;
end;
$$;

revoke all on function public.ice_live_table_counts() from public, anon, authenticated;
grant execute on function public.ice_live_table_counts() to service_role;
