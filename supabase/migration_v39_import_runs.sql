-- Import runs: one row per source file the owner uploads.
--
-- The owner sees upload -> processing -> completed on this table alone. The
-- worker claims a row, runs the deterministic importer against the stored
-- file, and writes back what it did. Nothing here is a review queue: a row
-- is a job record, and rows the importer could not place deterministically
-- land in its exceptions report rather than waiting for an approval.

create table if not exists public.import_runs (
  id uuid primary key default gen_random_uuid(),
  storage_path text not null unique,
  original_name text not null,
  source_kind text not null check (source_kind in ('ECO','OEM','MEDIA','DLT')),
  status text not null default 'UPLOADED'
    check (status in ('UPLOADED','PROCESSING','COMPLETED','FAILED')),
  actor text not null default 'tdr-admin',
  rows_read integer,
  patched integer,
  created integer,
  exceptions integer,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);

create index if not exists import_runs_pending_idx
  on public.import_runs (created_at)
  where status in ('UPLOADED','PROCESSING');

alter table public.import_runs enable row level security;
revoke all on table public.import_runs from anon, authenticated;

comment on table public.import_runs is
  'One uploaded source file and what the deterministic importer did with it. Internal/service-role only. Not a review queue: matched rows are written without approval, and unresolved identities go to the run''s exceptions report.';
