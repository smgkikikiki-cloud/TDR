-- Two things the exception work list needs the database to do that a
-- capped-at-1000 read in the browser cannot.
--
-- 1. A registration label's every open month has to be grouped for the
--    owner to make one decision that closes all of them -- but grouping
--    "the first 1000 rows the browser happened to load" and reporting
--    that as complete silently drops any label whose open rows do not
--    all fit inside that slice. GROUP BY belongs in the database, over
--    every open row, not in application code over a truncated page.
--
-- 2. /admin/exceptions has to be able to say how many rows are open and
--    page through them without missing or duplicating one as new rows
--    arrive between page loads -- which a plain OFFSET cannot promise.
--    A stable (created_at, id) keyset does.

-- --- 1. Registration gaps, grouped server-side, never truncated -------

create or replace view public.import_run_registration_gaps
with (security_invoker = true)
as
select
  (source_identity->>'registration_type') as registration_type,
  (source_identity->>'brand') as brand_name_raw,
  (source_identity->>'model') as model_name_raw,
  -- Grain is a property of the brand (Brand.trim_detail), so it is the
  -- same value on every row of one group; max() is just how SQL picks
  -- one of them.
  max(source_identity->>'grain') as grain,
  array_agg(id order by created_at desc) as exception_ids,
  count(*)::bigint as months,
  coalesce(sum(nullif(source_identity->>'units', '')::numeric), 0)::bigint as total_units,
  max(source_identity->>'period') as latest_period,
  (array_agg(reason order by created_at desc))[1] as reason
from public.import_run_exceptions
where status = 'OPEN'
  and kind = 'REGISTRATION_IDENTITY'
  and source_identity->>'brand' is not null
  and source_identity->>'model' is not null
group by 1, 2, 3;

revoke all on table public.import_run_registration_gaps from anon, authenticated;
grant select on table public.import_run_registration_gaps to service_role;

comment on view public.import_run_registration_gaps is
  'Every OPEN registration-identity exception, grouped by (registration_type, brand, model) over the WHOLE table -- never a truncated page of it. Resolving one group is one decision that closes every month it lists; exception_ids carries every row that decision must resolve.';

-- --- 2. A stable count and keyset for the general work list -----------
--
-- Nothing new to create for this: (created_at, id) is already a unique,
-- indexable ordering (import_run_exceptions_open_idx from migration_v41
-- covers created_at; id is the primary key), which is what a keyset page
-- needs. This section exists so the two pagination requirements are
-- documented together; the query shape itself lives in
-- lib/import-exceptions.ts.
