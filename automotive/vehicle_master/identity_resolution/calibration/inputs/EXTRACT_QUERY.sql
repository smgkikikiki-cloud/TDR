-- READ-ONLY extraction of the first-run R6 rows and of the matcher's inputs, run on 2026-10-11 02:55 UTC
-- through the Supabase MCP `execute_sql` tool against project ltvwzkffmpudpjfjomrg. SELECT only; nothing was written.
-- The single result row (a JSON object) was split into the files of this directory by key; see MANIFEST.json.
--
-- Two further read-only checks were run (results are in MANIFEST.json "verification"):
--   1. counts of ice_model_crosswalk / ice_model_group_redirects / ice_known_model_groups / ice_brand_aliases (490 / 50 / 1200 / 4);
--   2. an md5 over every (model_group_id, period, units) cell of ice_reg_trend and over ice_dims_model_group, to compare with the archived package.
with months as (select generate_series(date '2021-01-01', date '2026-08-01', interval '1 month')::date m),
cells as (select canonical_model_id cid, period, sum(registrations)::bigint u from registrations where canonical_model_id is not null group by 1,2),
models_c as (select distinct cid from cells),
grid as (select md.cid, mo.m, c.u from models_c md cross join months mo left join cells c on c.cid = md.cid and c.period = mo.m),
series as (select cid, string_agg(coalesce(u::text,''), ',' order by m) s from grid group by cid),
per as (select period, count(*) rows_all, sum(registrations)::bigint units_all, count(*) filter (where canonical_model_id is not null) rows_canon,
               coalesce(sum(registrations) filter (where canonical_model_id is not null),0)::bigint units_canon from registrations group by period)
select json_build_object(
 'meta', json_build_object('extracted_at', to_char(now() at time zone 'utc','YYYY-MM-DD"T"HH24:MI:SS"Z"'), 'project', 'ltvwzkffmpudpjfjomrg',
   'access', 'read-only SELECT via the Supabase MCP execute_sql tool', 'registrations_rows', (select count(*) from registrations),
   'registrations_max_created_at', (select to_char(max(created_at) at time zone 'utc','YYYY-MM-DD"T"HH24:MI:SS.US') from registrations),
   'registrations_rows_created_after_run_start', (select count(*) from registrations where created_at >= timestamptz '2026-10-10 15:38:00+00'),
   'vehicle_models_max_updated_at', (select to_char(max(updated_at) at time zone 'utc','YYYY-MM-DD"T"HH24:MI:SS.US') from vehicle_models),
   'vehicle_models_updated_after_run_start', (select count(*) from vehicle_models where updated_at >= timestamptz '2026-10-10 15:38:00+00'),
   'vehicle_generations_updated_after_run_start', (select count(*) from vehicle_generations where updated_at >= timestamptz '2026-10-10 15:38:00+00')),
 'crosswalk', (select json_agg(json_build_object('id', id, 'model_group_id', model_group_id, 'canonical_model_id', canonical_model_id, 'match_method', match_method,
   'score', score::text, 'status', status, 'master_version', master_version, 'decision_fingerprint', decision_fingerprint, 'reason', reason,
   'created_at', to_char(created_at at time zone 'utc','YYYY-MM-DD"T"HH24:MI:SS.US'), 'updated_at', to_char(updated_at at time zone 'utc','YYYY-MM-DD"T"HH24:MI:SS.US')) order by id) from ice_model_crosswalk),
 'redirects', (select json_agg(json_build_object('old_model_group_id', old_model_group_id, 'new_model_group_id', new_model_group_id, 'change_type', change_type, 'reason', reason,
   'created_at', to_char(created_at at time zone 'utc','YYYY-MM-DD"T"HH24:MI:SS.US')) order by old_model_group_id collate "C", new_model_group_id collate "C") from ice_model_group_redirects),
 'brand_aliases', (select json_agg(json_build_object('brand', brand, 'alias_group', alias_group) order by brand collate "C") from ice_brand_aliases),
 'brands', (select json_agg(json_build_object('canonical_id', canonical_id, 'slug', slug, 'name_en', name_en, 'name_th', name_th, 'deleted', deleted_at is not null) order by canonical_id collate "C") from vehicle_brands),
 'models', (select json_agg(json_build_object('canonical_id', canonical_id, 'brand_id', brand_id, 'slug', slug, 'name_en', name_en, 'name_th', name_th, 'status', status, 'body_type', body_type,
   'segment', segment, 'generation_id', generation_id, 'deleted', deleted_at is not null, 'aliases', payload->'aliases', 'nameplate', payload->'nameplate', 'cab_type', payload->'cab_type',
   'registration_type', payload->'registration_type', 'launch_year', payload->'launch_year', 'launch_quarter', payload->'launch_quarter', 'retail_status', payload->'retail_status',
   'market_scope', payload->'market_scope', 'production_type', payload->'production_type', 'incomplete', payload->'incomplete') order by canonical_id collate "C") from vehicle_models),
 'generations', (select json_agg(json_build_object('canonical_id', canonical_id, 'model_id', model_id, 'code', code, 'launched', launched, 'ended', ended, 'deleted', deleted_at is not null) order by canonical_id collate "C") from vehicle_generations),
 'tdr_series', json_build_object('start', '2021-01', 'end', '2026-08', 'source', 'registrations where canonical_model_id is not null, summed by (canonical_model_id, period); blank = no row in that month',
   'rows', (select json_object_agg(cid, s order by cid collate "C") from series)),
 'tdr_period_totals', (select json_agg(json_build_object('period', to_char(period,'YYYY-MM'), 'rows_all', rows_all, 'units_all', units_all, 'rows_canon', rows_canon, 'units_canon', units_canon) order by period) from per),
 'ice_checks', json_build_object('ice_reg_trend_cells', (select count(*) from (select 1 from ice_reg_trend group by model_group_id, period) t), 'ice_dims_model_group', (select count(*) from ice_dims_model_group),
   'ice_package_imports', (select json_agg(json_build_object('period', period, 'package_version', package_version, 'master_version', master_version)) from ice_package_imports))
) as j;
