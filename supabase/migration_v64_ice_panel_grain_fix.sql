-- Market Track R5 compatibility fix (docs/vehicle-db/VEHICLE_DB_V3.md §14.1,
-- docs/market-track/ROADMAP.md): migration_v62 shipped three primary keys one
-- column narrower than the Ice Full Package contract actually declares.
-- Ground-truthed against the owner-declared final package
-- TDR_FULL_2569-09_v3_M7.0.zip (master_version 7.0) -- its shipped
-- validate_package.py, tdr-package-import/SKILL.md and dims/method.md/
-- reg_powertrain/method.md all independently declare the same keys below.
-- Purely additive on top of migration_v62 -- v62 is frozen and not edited.
--
-- 1. ice_reg_powertrain / ice_reg_powertrain_staging
--    migration_v62 key: (period, province, reg_type, brand, model_group_id, fuel_group)
--    real contract key: (period, province, reg_type, brand, model_group_id, fuel_group, certainty)
--    Proven against the real M7.0 data (146,483 rows): 254 keys under the old,
--    narrower key hold more than one row (508 rows total) -- every one of them
--    is exactly a 2-row group differing only by certainty (234 exact+range,
--    20 exact+family); 0 rows collide under the full 7-column key. Under the
--    migration_v62 schema a real --apply of this package would not merely
--    mis-aggregate: `stage_table`'s plain INSERT (no upsert/ON CONFLICT) would
--    hit a unique-violation on the second row of every colliding key and
--    the whole import would fail outright.
--
-- 2. ice_tyre_province / ice_tyre_province_staging
--    migration_v62 key: (period, province, reg_type, brand, tyre_size)
--    real contract key: (period, province, reg_type, brand, tyre_size, rim_inch)
--
-- 3. ice_dims_tyre / ice_dims_tyre_staging
--    migration_v62 key: (tyre_size)
--    real contract key: (tyre_size, rim_inch)
--
--    For 2 and 3: empirically, in the real M7.0 data, tyre_size already
--    functionally determines rim_inch (it is embedded as the size string's
--    own trailing "R<nn>" segment, e.g. "205/55R16" -> rim_inch=16), so the
--    narrower migration_v62 key produces zero duplicate rows today (checked:
--    520,685 tyre_province rows, 175 dims/tyre rows, 0 collisions either
--    way). This migration still adopts Ice's declared compound key exactly,
--    rather than relying on an invariant that is true of today's delivery
--    but that Ice's own contract does not promise to hold in a future one
--    (the shipped validator itself checks uniqueness at the compound key,
--    not at tyre_size alone).
--
-- rim_inch is not null in either real file today (0 blank cells in 520,685 +
-- 175 rows) and both live tables are currently empty in production (no real
-- Ice package has ever been imported -- docs/WORK_STATE.md), so marking it
-- NOT NULL here is safe; Postgres itself would refuse this migration loudly
-- (not silently) if any existing row ever violated it.
--
-- No other table, RPC, index, grant or RLS policy changes: ice_commit_staged_import
-- and ice_live_table_counts copy/count whole rows (`select *` / `count(*)`),
-- never a column list, so they need no change; no table here is referenced by
-- a foreign key; ice_reg_powertrain_model_idx and every other existing index
-- is unaffected by a primary-key column addition.

alter table public.ice_tyre_province alter column rim_inch set not null;
alter table public.ice_tyre_province_staging alter column rim_inch set not null;
alter table public.ice_dims_tyre alter column rim_inch set not null;
alter table public.ice_dims_tyre_staging alter column rim_inch set not null;

-- Idempotent PK replacement: only drop + re-add a table's primary key when
-- its current column list does not already match the target, so replaying
-- this migration (test_v64_replays_and_is_idempotent) is a no-op the second
-- time, the same convention migration_v62's own staging-PK loop uses.
do $$
declare
  spec record;
  existing_pk_cols text;
  existing_pk_name text;
begin
  for spec in
    select * from (values
      ('ice_reg_powertrain', 'period, province, reg_type, brand, model_group_id, fuel_group, certainty'),
      ('ice_reg_powertrain_staging', 'period, province, reg_type, brand, model_group_id, fuel_group, certainty'),
      ('ice_tyre_province', 'period, province, reg_type, brand, tyre_size, rim_inch'),
      ('ice_tyre_province_staging', 'period, province, reg_type, brand, tyre_size, rim_inch'),
      ('ice_dims_tyre', 'tyre_size, rim_inch'),
      ('ice_dims_tyre_staging', 'tyre_size, rim_inch')
    ) as t(table_name, pk_columns)
  loop
    select c.conname into existing_pk_name
    from pg_constraint c
    where c.conrelid = ('public.' || spec.table_name)::regclass and c.contype = 'p';

    select string_agg(a.attname, ', ' order by k.ord) into existing_pk_cols
    from pg_constraint c
    cross join lateral unnest(c.conkey) with ordinality as k(attnum, ord)
    join pg_attribute a on a.attrelid = c.conrelid and a.attnum = k.attnum
    where c.conrelid = ('public.' || spec.table_name)::regclass and c.contype = 'p';

    if existing_pk_cols is distinct from spec.pk_columns then
      if existing_pk_name is not null then
        execute format('alter table public.%I drop constraint %I', spec.table_name, existing_pk_name);
      end if;
      execute format('alter table public.%I add primary key (%s)', spec.table_name, spec.pk_columns);
    end if;
  end loop;
end
$$;
