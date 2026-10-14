-- Rollback for v70: restores the v69 function (group-level check) and drops the added column.
-- Run supabase/migration_v69_ice_monthly_queue.sql's function block again, or simply re-run that whole file after this one.
begin;
drop function if exists public.ice_monthly_refresh_queue(integer);
alter table public.ice_review_queue drop column if exists uncovered_scopes;
commit;
-- Then re-run supabase/migration_v69_ice_monthly_queue.sql (it is idempotent) to put the v69 function back.
