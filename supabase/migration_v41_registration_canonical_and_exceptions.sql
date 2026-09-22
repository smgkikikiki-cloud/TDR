-- Four things this pass needs the database to be able to say.
--
-- 1. Unresolved work has its own rows, not a capped JSON blob. A run with
--    900 unplaceable rows was silently keeping 500 of them.
-- 2. A run can name the commit and release its own write ended up in, so
--    finishing one run cannot finish another run's work by accident.
-- 3. Registration can carry a canonical identity directly. Until now the
--    only way to attribute a DLT label was the legacy models.id bridge, so
--    a car created today could not receive one until a release rebuilt the
--    crosswalk. Legacy columns stay exactly as they are.
-- 4. A monthly file can replace its period atomically. An official monthly
--    export is a complete snapshot: a row the corrected file drops has to
--    disappear, and per-row upsert leaves it behind forever.
--
-- Additive only. Nothing is dropped, and every legacy path keeps working.

-- --- 1. Durable, resolvable exceptions -------------------------------

create table if not exists public.import_run_exceptions (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references public.import_runs(id) on delete cascade,
  source_kind text not null,
  -- REGISTRATION_IDENTITY, VEHICLE_IDENTITY, CONFLICT, MALFORMED_ROW, ...
  kind text not null,
  -- Everything needed to resolve it later and to match the same thing
  -- again next month: the raw labels, the period, the units, the source id.
  source_identity jsonb not null default '{}'::jsonb,
  reason text not null,
  status text not null default 'OPEN' check (status in ('OPEN','RESOLVED')),
  resolution_target text,
  resolved_by text,
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

-- The open work list, and the lookup that closes a row when its identity is
-- resolved from somewhere else.
create index if not exists import_run_exceptions_open_idx
  on public.import_run_exceptions (created_at desc) where status = 'OPEN';
create index if not exists import_run_exceptions_run_idx
  on public.import_run_exceptions (run_id);
create index if not exists import_run_exceptions_identity_idx
  on public.import_run_exceptions using gin (source_identity);

alter table public.import_run_exceptions enable row level security;
revoke all on table public.import_run_exceptions from anon, authenticated;

comment on table public.import_run_exceptions is
  'One unresolved row from an import run, kept until somebody resolves it. Not a review queue: everything placeable was already written. Replaces the capped import_runs.exception_rows blob, which silently dropped rows past its limit.';

-- --- 2. A run knows what it produced ---------------------------------

alter table public.import_runs add column if not exists commit_sha text;
alter table public.import_runs add column if not exists release_id text;

comment on column public.import_runs.commit_sha is
  'The commit this run''s canonical write landed in. Set before publishing, so finalising one run can never mark another run''s work complete.';
comment on column public.import_runs.release_id is
  'The published release that carries this run''s write. COMPLETED means this exists and is serving.';

-- --- 3. Registration can name a canonical vehicle directly -----------
--
-- Nullable and additive. model_id (legacy models.id) stays authoritative
-- for everything already mapped; canonical_model_id is what a car created
-- today can be given immediately, with no legacy row to mint first.

alter table public.registrations
  add column if not exists canonical_model_id text,
  add column if not exists canonical_trim_id text,
  add column if not exists import_run_id uuid references public.import_runs(id) on delete set null,
  add column if not exists source_reference text;

create index if not exists registrations_canonical_model_period_idx
  on public.registrations (canonical_model_id, period)
  where canonical_model_id is not null;

comment on column public.registrations.canonical_model_id is
  'Canonical vehicle model this row is attributed to. Preferred over the legacy model_id bridge; both are kept so existing data and queries keep working.';
comment on column public.registrations.canonical_trim_id is
  'Set only where the source itself published trim detail and a deterministic mapping exists. Never inferred from a model-level row.';
comment on column public.registrations.source_reference is
  'Where this row came from -- the uploaded file or feed -- so a number can always be traced back to what published it.';

alter table public.registration_brand_aliases
  add column if not exists canonical_brand_id text;
alter table public.registration_model_aliases
  add column if not exists canonical_model_id text,
  add column if not exists canonical_trim_id text;

-- Backfill from the crosswalk that already exists: every canonical model
-- carrying a tdr_model_id tells us what its legacy id means.
update public.registration_model_aliases a
   set canonical_model_id = m.canonical_id
  from public.current_vehicle_models m
 where a.canonical_model_id is null
   and m.tdr_model_id is not null
   and m.tdr_model_id = a.model_id;

update public.registrations r
   set canonical_model_id = m.canonical_id
  from public.current_vehicle_models m
 where r.canonical_model_id is null
   and m.tdr_model_id is not null
   and m.tdr_model_id = r.model_id;

-- --- 4. A monthly snapshot replaces its period, atomically -----------

create or replace function public.tdr_replace_registration_period(
  p_period text,
  p_registration_type text,
  p_rows jsonb,
  p_import_run_id uuid default null,
  p_source_reference text default null
) returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  inserted integer;
  target_period date;
begin
  if p_period is null or p_period = '' then
    raise exception 'period is required to replace a registration snapshot';
  end if;
  -- The importers speak in months ('2026-06'); the column is a date. Accept
  -- either spelling and normalise to the first of the month, so a caller
  -- cannot half-replace a period by naming a different day of it.
  if p_period ~ '^\d{4}-\d{2}$' then
    target_period := to_date(p_period || '-01', 'YYYY-MM-DD');
  elsif p_period ~ '^\d{4}-\d{2}-\d{2}$' then
    target_period := date_trunc('month', to_date(p_period, 'YYYY-MM-DD'))::date;
  else
    raise exception 'period % is not a month (YYYY-MM)', p_period;
  end if;
  if jsonb_typeof(p_rows) <> 'array' or jsonb_array_length(p_rows) = 0 then
    raise exception 'refusing to replace period % with an empty snapshot', p_period;
  end if;

  -- Replacing one slice of a month means the file covers that slice. A row
  -- naming a different registration type would land outside what was just
  -- cleared, leaving the old row for it in place beside the new one.
  if p_registration_type is not null and exists (
       select 1 from jsonb_array_elements(p_rows) as row_data
        where coalesce(row_data->>'registration_type', p_registration_type)
              <> p_registration_type)
  then
    raise exception 'a % snapshot cannot carry rows of another registration type',
      p_registration_type;
  end if;

  -- One statement pair inside one transaction: a failure rolls the delete
  -- back with it, so a month can never be left emptied by a half-run import.
  delete from public.registrations
   where period = target_period
     and (p_registration_type is null or registration_type = p_registration_type);

  insert into public.registrations (
    period, registration_type, brand_name_raw, model_name_raw, registrations,
    model_id, canonical_model_id, canonical_trim_id, mapping_method,
    import_run_id, source_reference
  )
  select
    target_period,
    coalesce(row_data->>'registration_type', p_registration_type, '*'),
    row_data->>'brand_name_raw',
    row_data->>'model_name_raw',
    (row_data->>'registrations')::integer,
    nullif(row_data->>'model_id', '')::uuid,
    nullif(row_data->>'canonical_model_id', ''),
    nullif(row_data->>'canonical_trim_id', ''),
    coalesce(row_data->>'mapping_method', 'unmapped'),
    p_import_run_id,
    p_source_reference
  from jsonb_array_elements(p_rows) as row_data;

  get diagnostics inserted = row_count;
  return inserted;
end;
$$;

revoke all on function public.tdr_replace_registration_period(text, text, jsonb, uuid, text) from anon, authenticated;

comment on function public.tdr_replace_registration_period is
  'Replace one period of registration facts with a complete monthly snapshot, in one transaction. An official export is the whole month: a row the corrected file no longer lists must disappear, which per-row upsert cannot do. Unmatched rows are inserted too, with a null canonical mapping, so month totals stay complete while their identity is still being resolved.';

-- --- 5. The price feed is an import run too ---------------------------
--
-- Harvested prices resolve the same way an uploaded file does, and what the
-- resolver cannot place is the same kind of work: a source identity nobody
-- can attach to a trim. It belongs in the same exception list the owner
-- already reads, which means the run it hangs off has to be nameable.

alter table public.import_runs drop constraint if exists import_runs_source_kind_check;
alter table public.import_runs add constraint import_runs_source_kind_check
  check (source_kind in ('ECO','OEM','MEDIA','DLT','PRICE'));

comment on column public.import_runs.source_kind is
  'Where the rows came from. PRICE is the automated price feed, which has no uploaded file: its storage_path names the harvest batch instead.';

-- --- 6. A label can be bound to a car created today ------------------
--
-- registration_model_aliases.model_id was NOT NULL, so the only way to
-- teach the crosswalk a DLT label was to point it at a legacy models row.
-- A car created in the admin today has no legacy row until a release
-- rebuilds the crosswalk, which made "resolve this exception" impossible
-- for exactly the cars most likely to appear in an exception. The column
-- stays, and stays authoritative where it is set; it is simply no longer
-- the only way to name the target.

alter table public.registration_model_aliases alter column model_id drop not null;

alter table public.registration_model_aliases
  drop constraint if exists registration_model_aliases_identity_check;
alter table public.registration_model_aliases
  add constraint registration_model_aliases_identity_check
  check (model_id is not null or canonical_model_id is not null);

-- Grain is the source's, not the resolver's. A mapping is trim-grained
-- only where the file itself published trim detail; a model-level row
-- never acquires a trim by being resolved.
alter table public.registration_model_aliases
  add column if not exists grain text not null default 'MODEL';
alter table public.registration_model_aliases
  drop constraint if exists registration_model_aliases_grain_check;
alter table public.registration_model_aliases
  add constraint registration_model_aliases_grain_check
  check (grain in ('MODEL','TRIM')
         and (grain = 'TRIM') = (canonical_trim_id is not null));

comment on column public.registration_model_aliases.grain is
  'MODEL when the source names only a model, TRIM when the source itself publishes the grade. Never inferred: a model-level label cannot become trim-grained by being resolved.';
