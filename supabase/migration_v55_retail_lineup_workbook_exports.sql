-- Admin-requested workbook generation for Retail Lineup Bootstrap.
--
-- This is not canonical write state. It is a server-only queue whose worker
-- snapshots the CURRENT canonical tree into the three-sheet Chunk-3 workbook
-- and stores that generated XLSX in the existing private source-imports bucket.
-- Chunk 7 remains responsible for compiling an uploaded edited workbook into
-- retail_lineup_plans and for the final apply/publish worker.

create table if not exists public.retail_lineup_workbook_exports (
  id uuid primary key default gen_random_uuid(),
  status text not null default 'QUEUED'
    check (status in ('QUEUED','PROCESSING','READY','FAILED')),
  actor text not null check (btrim(actor) <> ''),
  model_ids text[] not null,
  catalog_year integer not null check (catalog_year between 2000 and 2100),
  base_release_id text not null check (btrim(base_release_id) <> ''),
  storage_path text unique,
  baseline_hash text
    check (baseline_hash is null or baseline_hash ~ '^[0-9a-f]{64}$'),
  summary jsonb not null default '{}'::jsonb
    check (jsonb_typeof(summary) = 'object'),
  error text,
  created_at timestamptz not null default now(),
  processing_started_at timestamptz,
  completed_at timestamptz,

  constraint retail_lineup_workbook_exports_models_nonempty
    check (cardinality(model_ids) > 0),
  constraint retail_lineup_workbook_exports_models_clean
    check (array_position(model_ids, '') is null),
  constraint retail_lineup_workbook_exports_ready_has_file
    check (status <> 'READY' or (
      storage_path is not null and btrim(storage_path) <> ''
      and baseline_hash is not null
      and completed_at is not null
    )),
  constraint retail_lineup_workbook_exports_processing_has_started
    check (status <> 'PROCESSING' or processing_started_at is not null),
  constraint retail_lineup_workbook_exports_failed_has_error
    check (status <> 'FAILED' or (error is not null and btrim(error) <> ''))
);

create index if not exists retail_lineup_workbook_exports_status_created_idx
  on public.retail_lineup_workbook_exports(status, created_at asc);

-- Request identity is immutable. A retry is a new export request so the XLSX
-- keeps an auditable relationship to the release/baseline it was generated
-- from rather than silently becoming a different workbook under one row id.
create or replace function public.tdr_guard_retail_lineup_workbook_export_update()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if new.actor is distinct from old.actor
     or new.model_ids is distinct from old.model_ids
     or new.catalog_year is distinct from old.catalog_year
     or new.base_release_id is distinct from old.base_release_id
     or new.created_at is distinct from old.created_at then
    raise exception 'RETAIL_LINEUP_WORKBOOK_EXPORT_IMMUTABLE';
  end if;

  if new.status is distinct from old.status then
    if old.status = 'QUEUED' and new.status <> 'PROCESSING' then
      raise exception 'invalid workbook export transition % -> %', old.status, new.status;
    elsif old.status = 'PROCESSING' and new.status not in ('READY','FAILED') then
      raise exception 'invalid workbook export transition % -> %', old.status, new.status;
    elsif old.status in ('READY','FAILED') then
      raise exception 'terminal workbook export % cannot transition to %', old.status, new.status;
    end if;
  end if;

  if old.status <> 'PROCESSING' and (
      new.storage_path is distinct from old.storage_path
      or new.baseline_hash is distinct from old.baseline_hash
      or new.summary is distinct from old.summary
      or new.error is distinct from old.error
      or new.completed_at is distinct from old.completed_at) then
    raise exception 'workbook export result fields may only be written while PROCESSING';
  end if;

  return new;
end;
$$;

revoke all on function public.tdr_guard_retail_lineup_workbook_export_update()
  from public, anon, authenticated;

drop trigger if exists retail_lineup_workbook_exports_guard_update
  on public.retail_lineup_workbook_exports;
create trigger retail_lineup_workbook_exports_guard_update
before update on public.retail_lineup_workbook_exports
for each row execute function public.tdr_guard_retail_lineup_workbook_export_update();

alter table public.retail_lineup_workbook_exports enable row level security;
revoke all on table public.retail_lineup_workbook_exports from public, anon, authenticated;
grant select, insert, update on table public.retail_lineup_workbook_exports to service_role;

comment on table public.retail_lineup_workbook_exports is
  'Server-only queue for generating Retail Lineup Bootstrap XLSX snapshots. It never writes canonical vehicle data.';
