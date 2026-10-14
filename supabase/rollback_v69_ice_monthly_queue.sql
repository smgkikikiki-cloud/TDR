-- Rollback for v69. Rows already copied into ice_model_crosswalk_scoped by carry-over are NOT removed (their decision_ref starts with 'carry-over-rename:').
begin;
drop function if exists public.ice_monthly_refresh_queue(integer);
drop function if exists public.ice_coverage_by_period();
drop table if exists public.ice_review_queue;
commit;
