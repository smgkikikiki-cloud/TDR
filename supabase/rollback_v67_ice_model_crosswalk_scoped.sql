-- Rollback for v67. Drops only the new scoped table and its trigger function; v63 ice_model_crosswalk is untouched.
begin;
drop table if exists public.ice_model_crosswalk_scoped;
drop function if exists public.ice_scoped_crosswalk_keep_provenance();
commit;
