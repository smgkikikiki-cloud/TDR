-- Keep canonical vehicle release storage bounded after successful publishes.
--
-- The projection tables are versioned by release_id and cascade from
-- canonical_vehicle_releases. Without retention, every successful publish
-- permanently keeps another full copy of the catalogue; by 2026-09-26 this
-- had accumulated 151 releases and ~1.0M canonical_spec_projection rows,
-- exhausting a 2 GB database disk.
--
-- This function is intentionally separate from activate_vehicle_release():
-- activation remains the small atomic pointer flip. The publisher calls this
-- immediately after activation (and again on an idempotent ACTIVE retry), so
-- retention failure is visible/retryable without risking the serving release.

create or replace function public.prune_vehicle_releases(
  p_keep_superseded integer default 1,
  p_staging_ttl interval default interval '6 hours'
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
set statement_timeout = '30s'
as $$
declare
  active_release_id text;
  active_rows integer;
  deleted_staging integer := 0;
  deleted_superseded integer := 0;
  kept_superseded integer := 0;
begin
  if p_keep_superseded < 1 or p_keep_superseded > 10 then
    raise exception 'p_keep_superseded must be between 1 and 10';
  end if;
  if p_staging_ttl < interval '1 hour' then
    raise exception 'p_staging_ttl must be at least 1 hour';
  end if;

  -- Serialize with activate_vehicle_release() so pruning can never race the
  -- ACTIVE/SUPERSEDED pointer flip. This is the exact advisory-lock key used
  -- by migration_v48.
  perform pg_advisory_xact_lock(
    hashtext('canonical_vehicle_release_activation:vehicle_catalog')::bigint
  );

  select s.active_release_id
    into active_release_id
    from public.canonical_vehicle_state s
   where s.scope = 'vehicle_catalog'
   for update;

  if active_release_id is null then
    raise exception 'vehicle_catalog has no active release; refusing to prune';
  end if;

  select count(*) into active_rows
    from public.canonical_vehicle_releases
   where status = 'ACTIVE';

  if active_rows <> 1 then
    raise exception 'expected exactly one ACTIVE release, found %; refusing to prune', active_rows;
  end if;

  if not exists (
    select 1
      from public.canonical_vehicle_releases r
     where r.release_id = active_release_id
       and r.status = 'ACTIVE'
  ) then
    raise exception 'canonical_vehicle_state points to %, which is not ACTIVE; refusing to prune',
      active_release_id;
  end if;

  -- Never delete a recently-created STAGING release: a manual/out-of-band
  -- publisher could be staging outside the GitHub concurrency group. Failed
  -- staging attempts become eligible after the grace period and are removed
  -- by a later successful publish.
  with deleted as (
    delete from public.canonical_vehicle_releases r
     where r.status = 'STAGING'
       and r.release_id <> active_release_id
       and r.created_at < now() - p_staging_ttl
    returning 1
  )
  select count(*) into deleted_staging from deleted;

  -- Keep only the newest N finalized rollback releases. Projection rows,
  -- chunk-ledger rows and other release-scoped children disappear through
  -- the existing ON DELETE CASCADE foreign keys.
  with ranked as (
    select r.release_id,
           row_number() over (
             order by r.activated_at desc nulls last,
                      r.created_at desc,
                      r.revision_ordinal desc nulls last,
                      r.release_id desc
           ) as rn
      from public.canonical_vehicle_releases r
     where r.status = 'SUPERSEDED'
  ), deleted as (
    delete from public.canonical_vehicle_releases r
     using ranked x
     where r.release_id = x.release_id
       and x.rn > p_keep_superseded
    returning 1
  )
  select count(*) into deleted_superseded from deleted;

  select count(*) into kept_superseded
    from public.canonical_vehicle_releases
   where status = 'SUPERSEDED';

  return jsonb_build_object(
    'active_release_id', active_release_id,
    'kept_superseded', kept_superseded,
    'deleted_superseded', deleted_superseded,
    'deleted_staging', deleted_staging,
    'staging_ttl_seconds', extract(epoch from p_staging_ttl)::bigint
  );
end;
$$;

revoke all on function public.prune_vehicle_releases(integer, interval)
  from public, anon, authenticated;
grant execute on function public.prune_vehicle_releases(integer, interval)
  to service_role;

comment on function public.prune_vehicle_releases(integer, interval) is
  'Bounds canonical release storage after publish: preserves the ACTIVE release, keeps the newest N SUPERSEDED rollback releases, and deletes only STAGING releases older than a grace period. Release-scoped projections are removed by ON DELETE CASCADE.';
