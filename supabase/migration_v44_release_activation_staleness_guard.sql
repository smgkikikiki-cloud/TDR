-- Four writers publish a canonical vehicle release: source-import.yml,
-- canonical-input.yml, pricefeed.yml, and vehicle-release.yml (triggered
-- independently by any push touching vehreg/**, on its own concurrency
-- group). publish_vehicle_release() activates whatever release_id it is
-- given, unconditionally -- there is no check that the release being
-- activated is newer than the one already serving. Two jobs racing (an
-- older commit's publish call reaching Postgres after a newer commit's
-- already activated) rolls the active pointer backward, silently, with
-- nothing recorded to say it happened.
--
-- git commit ancestry cannot be evaluated inside Postgres, so this uses
-- the caller-supplied revision_ordinal (typically `git rev-list --count
-- <revision>` from a full clone) as a monotonic proxy: main here only
-- ever fast-forwards (every writer rebases before it pushes), so a later
-- commit always has a >= ordinal than an earlier one. A release built
-- without one (older releases, or a caller that could not determine it)
-- carries no ordinal and is never blocked by this guard -- it is a
-- safety net on top of the real defense, which is the shared
-- concurrency group all four workflows now use, not a hard requirement.

alter table public.canonical_vehicle_releases
  add column if not exists revision_ordinal bigint;

comment on column public.canonical_vehicle_releases.revision_ordinal is
  'A monotonic proxy for how far along git history this release was built from (git rev-list --count), so publish_vehicle_release can refuse to activate a release older than what is already serving. Null for releases published without one -- the guard simply does not apply to them.';

create or replace function public.publish_vehicle_release(release jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  rid text := release->>'release_id';
  expected jsonb := release->'counts';
  actual jsonb;
  incoming_ordinal bigint := nullif(release->>'revision_ordinal', '')::bigint;
  active_ordinal bigint;
  active_release_id text;
begin
  if rid is null or rid !~ '^vehicle-[0-9]{4}-[a-f0-9]{16}$' then
    raise exception 'invalid release_id';
  end if;
  if coalesce((release->>'schema_version')::integer, 0) <> 1 then
    raise exception 'unsupported schema_version';
  end if;
  if release->>'source_hash' is null or release->>'canonical_revision' is null then
    raise exception 'source_hash and canonical_revision are required';
  end if;

  -- The staleness guard. Both sides have to know their ordinal for it to
  -- apply at all; the currently-ACTIVE release for this scope is looked
  -- up by its own stored ordinal, not recomputed.
  select r.release_id, r.revision_ordinal into active_release_id, active_ordinal
    from public.canonical_vehicle_state s
    join public.canonical_vehicle_releases r on r.release_id = s.active_release_id
   where s.scope = 'vehicle_catalog';

  if incoming_ordinal is not null and active_ordinal is not null
     and incoming_ordinal < active_ordinal and rid <> active_release_id then
    raise exception
      'stale revision: % (ordinal %) is older than the active release % (ordinal %); refusing to activate',
      rid, incoming_ordinal, active_release_id, active_ordinal;
  end if;

  actual := jsonb_build_object(
    'brands', jsonb_array_length(coalesce(release->'brands','[]'::jsonb)),
    'models', jsonb_array_length(coalesce(release->'models','[]'::jsonb)),
    'generations', jsonb_array_length(coalesce(release->'generations','[]'::jsonb)),
    'market_trims', jsonb_array_length(coalesce(release->'market_trims','[]'::jsonb)),
    'price_ledger', jsonb_array_length(coalesce(release->'price_ledger','[]'::jsonb)),
    'spec_facts', jsonb_array_length(coalesce(release->'spec_facts','[]'::jsonb))
  );
  if actual <> expected then
    raise exception 'release counts do not match payload: expected %, actual %', expected, actual;
  end if;

  insert into public.canonical_vehicle_releases
    (release_id, schema_version, canonical_revision, source_hash, as_of, counts, payload,
     status, revision_ordinal)
  values
    (rid, 1, release->>'canonical_revision', release->>'source_hash',
     (release->>'as_of')::date, expected, release, 'STAGING', incoming_ordinal)
  on conflict (release_id) do update set
    canonical_revision = excluded.canonical_revision,
    source_hash = excluded.source_hash,
    as_of = excluded.as_of,
    counts = excluded.counts,
    payload = excluded.payload,
    status = 'STAGING',
    revision_ordinal = excluded.revision_ordinal;

  delete from public.canonical_brand_projection where release_id = rid;
  insert into public.canonical_brand_projection
    (release_id, canonical_id, tdr_brand_id, slug, name_en, name_th, origin_country, payload)
  select rid, x->>'canonical_id', nullif(x->>'tdr_brand_id','')::uuid,
    x->>'slug', x->>'name_en', x->>'name_th', x->>'origin_country', x->'payload'
  from jsonb_array_elements(release->'brands') x;

  delete from public.canonical_model_projection where release_id = rid;
  insert into public.canonical_model_projection
    (release_id, canonical_id, tdr_model_id, brand_id, slug, name_en, name_th,
     generation_id, status, segment, body_type, retail_price_min, retail_price_max, payload)
  select rid, x->>'canonical_id', nullif(x->>'tdr_model_id','')::uuid,
    x->>'brand_id', x->>'slug', x->>'name_en', x->>'name_th',
    x->>'generation_id', x->>'status', x->>'segment', x->>'body_type',
    nullif(x->>'retail_price_min','')::numeric,
    nullif(x->>'retail_price_max','')::numeric, x->'payload'
  from jsonb_array_elements(release->'models') x;

  delete from public.canonical_generation_projection where release_id = rid;
  insert into public.canonical_generation_projection
    (release_id, canonical_id, model_id, code, segment, launched, ended, payload)
  select rid, x->>'canonical_id', x->>'model_id', x->>'code', x->>'segment',
    nullif(x->>'launched','')::date, nullif(x->>'ended','')::date, x->'payload'
  from jsonb_array_elements(release->'generations') x;

  delete from public.canonical_market_trim_projection where release_id = rid;
  insert into public.canonical_market_trim_projection
    (release_id, canonical_id, model_id, generation_id, variant_id, name,
     powertrain, status, payload, current_list_price, campaign_quote, price_history, source_refs)
  select rid, x->>'canonical_id', x->>'model_id', x->>'generation_id',
    nullif(x->>'variant_id',''), x->>'name', x->>'powertrain',
    coalesce(x->>'status', 'current'), x->'payload',
    x->'current_list_price', coalesce(x->'campaign_quote','{}'::jsonb),
    coalesce(x->'price_history','[]'::jsonb), coalesce(x->'source_refs','{}'::jsonb)
  from jsonb_array_elements(release->'market_trims') x;

  delete from public.canonical_price_projection where release_id = rid;
  insert into public.canonical_price_projection
    (release_id, record_id, trim_id, amount_thb, price_type, effective_from,
     effective_to, observed_at, campaign_id, option_id, source, source_ref, payload)
  select rid, x->>'record_id', x->>'trim_id', (x->>'amount_thb')::bigint,
    x->>'price_type', nullif(x->>'effective_from','')::date,
    nullif(x->>'effective_to','')::date, nullif(x->>'observed_at','')::date,
    x->>'campaign_id', x->>'option_id', x->>'source', x->>'source_ref', x
  from jsonb_array_elements(release->'price_ledger') x;

  delete from public.canonical_spec_projection where release_id = rid;
  insert into public.canonical_spec_projection
    (release_id, fact_id, trim_id, field_key, verification_status, payload)
  select rid, x->>'fact_id', x->>'trim_id', x->>'field_key',
    x->>'verification_status', x
  from jsonb_array_elements(release->'spec_facts') x;

  update public.canonical_vehicle_releases
    set status = 'SUPERSEDED'
    where status = 'ACTIVE' and release_id <> rid;
  update public.canonical_vehicle_releases
    set status = 'ACTIVE', activated_at = now()
    where release_id = rid;
  insert into public.canonical_vehicle_state(scope, active_release_id, activated_at)
    values ('vehicle_catalog', rid, now())
    on conflict (scope) do update set
      active_release_id = excluded.active_release_id,
      activated_at = excluded.activated_at;

  return jsonb_build_object('release_id', rid, 'status', 'ACTIVE', 'counts', actual);
end;
$$;

revoke all on function public.publish_vehicle_release(jsonb) from public, anon, authenticated;
grant execute on function public.publish_vehicle_release(jsonb) to service_role;

comment on function public.publish_vehicle_release is
  'Stages and activates one canonical vehicle release. Refuses to activate a release whose revision_ordinal is older than the currently active release''s, when both are known -- see migration_v44. A release with no ordinal is never blocked by this guard.';
