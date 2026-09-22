-- Import run results have to outlive the worker.
--
-- The worker processes an uploaded file in a temp directory that is gone the
-- moment it exits, so anything the owner has to come back and resolve is
-- stored on the run row itself. /admin/exceptions reads it from here.
--
-- WRITTEN_PENDING_PUBLISH exists so a canonical run cannot claim to be
-- finished before its files are committed and pushed: the worker parks the
-- run there, and only the post-push finalize step moves it to COMPLETED. A
-- failed push therefore leaves the run visibly unfinished instead of lying.

alter table public.import_runs
  add column if not exists exception_rows jsonb not null default '[]'::jsonb;

alter table public.import_runs drop constraint if exists import_runs_status_check;
alter table public.import_runs add constraint import_runs_status_check
  check (status in ('UPLOADED','PROCESSING','WRITTEN_PENDING_PUBLISH','COMPLETED','FAILED'));

drop index if exists import_runs_pending_idx;
create index if not exists import_runs_pending_idx
  on public.import_runs (created_at)
  where status in ('UPLOADED','PROCESSING','WRITTEN_PENDING_PUBLISH');

comment on column public.import_runs.exception_rows is
  'Rows the importer could not place, kept with the run so /admin/exceptions can show them after the worker''s temp directory is gone. Capped by the worker.';
