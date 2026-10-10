-- Market Track R5 production fix: the DELETEs inside ice_commit_staged_import carry a WHERE clause.
--
-- migration_v62's commit function emptied the live and staging tables with an unconditional
-- `delete from public.%I`. Production rejects that statement ("DELETE requires a WHERE clause",
-- SQLSTATE 21000, the safe-update guard on API roles). The real R5 import of
-- TDR_FULL_2569-09_v3_M7.0.zip staged every panel and then failed at the first
-- replace-whole-set DELETE; the commit is one transaction, so no live row changed and no
-- ice_package_imports row was written. The repository's CI Postgres does not load that guard,
-- which is why the v62 tests passed.
--
-- This replaces the function with the identical body except `where true` on both DELETEs
-- (same semantics: every row). Purely additive on v62-v64; v62 is frozen and not edited.
-- Grants are restated so the function stays callable by service_role only.

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
    execute format('delete from public.%I where true', tbl);
    execute format('insert into public.%I select * from public.%I', tbl, tbl || '_staging');
    execute format('delete from public.%I where true', tbl || '_staging');
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
