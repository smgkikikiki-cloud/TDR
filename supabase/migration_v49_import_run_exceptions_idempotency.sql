-- Replay-safe idempotency for import_run_exceptions, at the persistence
-- layer rather than by filename convention.
--
-- The production Price Feed bug this fixes: tools/pricefeed_write.py's
-- exception-only path derived its import_runs.storage_path from the
-- calendar date alone (`pricefeed/pricefeed-YYYY-MM-DD-none`), so a
-- second exception-only harvest on the same day collided with the first
-- on import_runs' existing `storage_path` unique constraint -- Postgres
-- error 23505 / HTTP 409, and the workflow tick failed even though
-- nothing was actually wrong with either harvest.
--
-- Fixing the storage_path collision alone is not enough: import_run_exceptions
-- itself has no natural-key uniqueness at all (a plain gen_random_uuid()
-- primary key), so even once import_runs stops colliding, replaying the
-- same harvest batch would insert a fresh, duplicate exception row every
-- time -- and could resurrect one a human had already resolved back to
-- OPEN by touching it again.
--
-- This table is shared by every import path (ECO/OEM/MEDIA/DLT/PRICE,
-- migration_v41), not owned by Price Feed, so the fix must not force
-- every existing writer to start computing a content hash. exception_hash
-- defaults to a fresh random value -- as unique as the row's own id would
-- be -- so a writer that never sets it keeps exactly today's behavior:
-- every insert is a new, distinct exception row. A writer that DOES want
-- replay-safe idempotency (tools/pricefeed_write.py) sets exception_hash
-- to a content hash of (kind, reason, source_identity) itself; the unique
-- index on (run_id, exception_hash) then makes a PostgREST upsert with
-- Prefer: resolution=ignore-duplicates a true no-op on replay -- the
-- second insert attempt matches the first row's key and is silently
-- skipped, never touching a status a human may have already changed.

alter table public.import_run_exceptions
  add column if not exists exception_hash text
  not null default gen_random_uuid()::text;

comment on column public.import_run_exceptions.exception_hash is
  'A writer that wants replay-safe idempotency sets this to a content hash of (kind, reason, source_identity), so re-inserting the same logical exception on a replay collides with (run_id, exception_hash) and is skipped rather than duplicated. Left at its random default, a writer gets exactly today''s behavior: every insert is unique.';

create unique index if not exists import_run_exceptions_run_hash_key
  on public.import_run_exceptions (run_id, exception_hash);
