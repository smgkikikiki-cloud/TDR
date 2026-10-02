-- Vehicle DB v3, Phase 0 step 5: close the old file/release write path.
--
-- From this point the Vehicle Master tables are the authority.  The old
-- canonical_input_batches -> vehreg/data -> release projection pipeline is
-- retained only as readable history/compatibility data.  No application role
-- may enqueue into it, mutate its release/projection tables, or call the old
-- publish/activate/rollback RPCs.
--
-- canonical_write_revisions is deliberately NOT frozen here: v3 Phase 1 reuses
-- that table as the new DB-master change log.

begin;

-- Production cutover gate.  Never strand an in-flight legacy write, and never
-- close the release path while the serving pointer has drifted away from the
-- master seed.  Empty migration-replay databases are allowed through.
do $$
declare
  seeded_release text;
  active_release text;
  active_jobs integer;
  staging_releases integer;
  seed_failures integer;
  parity_failures integer;
  rule_failures integer;
begin
  select seed_release_id into seeded_release
    from public.vehicle_master_state
   where scope = 'vehicle_catalog';

  select active_release_id into active_release
    from public.canonical_vehicle_state
   where scope = 'vehicle_catalog';

  if seeded_release is not null then
    if active_release is distinct from seeded_release then
      raise exception using errcode = '55000',
        message = format(
          'refused Phase 0 step 5: Vehicle Master seed release %s does not match active legacy release %s',
          seeded_release, coalesce(active_release, '<null>')),
        hint = 'restore serving parity before closing the legacy write path';
    end if;

    select count(*) into seed_failures
      from public.vehicle_master_seed_check() where not ok;
    select count(*) into parity_failures
      from public.vehicle_serving_parity_check() where not ok;
    select count(*) into rule_failures
      from public.vehicle_engine_rules_check();

    if seed_failures <> 0 or parity_failures <> 0 or rule_failures <> 0 then
      raise exception using errcode = '55000',
        message = format(
          'refused Phase 0 step 5: pre-cutover checks failed (seed=%s parity=%s engine_rules=%s)',
          seed_failures, parity_failures, rule_failures),
        hint = 'fix the Vehicle Master before closing the legacy write path';
    end if;
  end if;

  select count(*) into active_jobs
    from public.canonical_input_batches
   where status in ('QUEUED', 'PROCESSING', 'STAGED');
  if active_jobs <> 0 then
    raise exception using errcode = '55000',
      message = format(
        'refused Phase 0 step 5: %s canonical_input_batches job(s) are still QUEUED/PROCESSING/STAGED',
        active_jobs),
      hint = 'finish or explicitly reject the in-flight legacy jobs before cutover';
  end if;

  select count(*) into staging_releases
    from public.canonical_vehicle_releases
   where status = 'STAGING';
  if staging_releases <> 0 then
    raise exception using errcode = '55000',
      message = format(
        'refused Phase 0 step 5: %s canonical vehicle release(s) are still STAGING',
        staging_releases),
      hint = 'finish or remove the abandoned staging release before cutover';
  end if;
end
$$;

-- Application-level read-only boundary.  service_role keeps SELECT so old
-- admin/history readers continue to work, but it loses every data-mutation
-- privilege on the queue, release/projection store, and obsolete Phase-C
-- command/outbox bridge.  Browser roles were already read-only or denied.
do $$
declare
  relation_name text;
begin
  foreach relation_name in array array[
    'canonical_input_batches',
    'canonical_object_map',
    'canonical_write_commands',
    'canonical_publish_outbox',
    'canonical_vehicle_releases',
    'canonical_vehicle_state',
    'canonical_release_chunks',
    'canonical_brand_projection',
    'canonical_model_projection',
    'canonical_generation_projection',
    'canonical_market_trim_projection',
    'canonical_price_projection',
    'canonical_spec_projection'
  ] loop
    execute format(
      'revoke insert, update, delete, truncate on table public.%I from service_role',
      relation_name
    );
    execute format(
      'revoke insert, update, delete, truncate on table public.%I from anon, authenticated',
      relation_name
    );
    execute format('grant select on table public.%I to service_role', relation_name);
  end loop;
end
$$;

-- Keep the old RPC names alive only to fail loudly.  This matters because the
-- old publishers are SECURITY DEFINER: revoking table DML from service_role by
-- itself would not stop a granted RPC from mutating tables as its owner.
create or replace function public.publish_vehicle_release(release jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  raise exception using errcode = '55000',
    message = 'legacy vehicle release write path is closed (Phase 0 step 5)',
    hint = 'Vehicle Master is authoritative; write the DB master through the v3 write layer';
end;
$$;

create or replace function public.begin_vehicle_release(manifest jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  raise exception using errcode = '55000',
    message = 'legacy staged vehicle release write path is closed (Phase 0 step 5)',
    hint = 'Vehicle Master is authoritative; release staging is now read-only history';
end;
$$;

create or replace function public.stage_vehicle_release_chunk(
  p_release_id text,
  p_section text,
  p_chunk_index integer,
  p_chunk_hash text,
  p_rows jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  raise exception using errcode = '55000',
    message = 'legacy staged vehicle release write path is closed (Phase 0 step 5)',
    hint = 'Vehicle Master is authoritative; release staging is now read-only history';
end;
$$;

create or replace function public.activate_vehicle_release(p_release_id text)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  raise exception using errcode = '55000',
    message = 'legacy vehicle release activation is closed (Phase 0 step 5)',
    hint = 'current_* serving is backed by the Vehicle Master; the legacy active-release pointer is frozen';
end;
$$;

create or replace function public.rollback_vehicle_release(target_release_id text)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  raise exception using errcode = '55000',
    message = 'legacy vehicle release rollback is closed (Phase 0 step 5)',
    hint = 'Vehicle Master changes are no longer rolled back by moving the legacy release pointer';
end;
$$;

create or replace function public.prune_vehicle_releases(
  p_keep_superseded integer default 1,
  p_staging_ttl interval default interval '6 hours'
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  raise exception using errcode = '55000',
    message = 'legacy vehicle release retention writer is closed (Phase 0 step 5)',
    hint = 'legacy release/projection rows are read-only history after DB-master cutover';
end;
$$;

-- Browser callers never had these write RPCs.  service_role keeps EXECUTE so
-- any stale worker gets the diagnostic above instead of a misleading permission
-- error; the RPC itself can no longer write anything.
revoke all on function public.publish_vehicle_release(jsonb) from public, anon, authenticated;
revoke all on function public.begin_vehicle_release(jsonb) from public, anon, authenticated;
revoke all on function public.stage_vehicle_release_chunk(text, text, integer, text, jsonb) from public, anon, authenticated;
revoke all on function public.activate_vehicle_release(text) from public, anon, authenticated;
revoke all on function public.rollback_vehicle_release(text) from public, anon, authenticated;
revoke all on function public.prune_vehicle_releases(integer, interval) from public, anon, authenticated;

grant execute on function public.publish_vehicle_release(jsonb) to service_role;
grant execute on function public.begin_vehicle_release(jsonb) to service_role;
grant execute on function public.stage_vehicle_release_chunk(text, text, integer, text, jsonb) to service_role;
grant execute on function public.activate_vehicle_release(text) to service_role;
grant execute on function public.rollback_vehicle_release(text) to service_role;
grant execute on function public.prune_vehicle_releases(integer, interval) to service_role;

comment on table public.canonical_input_batches is
  'READ-ONLY legacy Vehicle Master intake history after Vehicle DB v3 Phase 0 step 5. New writes go to the DB-master pipeline.';
comment on table public.canonical_vehicle_releases is
  'READ-ONLY legacy file-backed release history after Vehicle DB v3 Phase 0 step 5. Vehicle Master is authoritative.';
comment on table public.canonical_vehicle_state is
  'Frozen legacy release pointer retained for compatibility/history. current_* views are backed by Vehicle Master.';

commit;
