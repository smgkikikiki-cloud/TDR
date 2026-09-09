-- Phase E: canonical Vehicle Master -> Supabase serving projection.
--
-- Vehicle Master stays authoritative. These columns mark rows that are merely
-- serving projections and let the publisher reconcile them by stable canonical
-- IDs without guessing from display names/slugs.

alter table public.models add column if not exists canonical_id text;
alter table public.models add column if not exists canonical_generation_id text;
alter table public.models add column if not exists serving_source text;
alter table public.models add column if not exists canonical_projection_hash text;
alter table public.models add column if not exists canonical_projected_at timestamptz;

alter table public.model_powertrains add column if not exists canonical_id text;
alter table public.model_powertrains add column if not exists serving_source text;
alter table public.model_powertrains add column if not exists canonical_projection_hash text;
alter table public.model_powertrains add column if not exists canonical_projected_at timestamptz;
alter table public.model_powertrains add column if not exists import_type text;
alter table public.model_powertrains add column if not exists origin_country text;

alter table public.trims add column if not exists canonical_id text;
alter table public.trims add column if not exists canonical_variant_id text;
alter table public.trims add column if not exists serving_source text;
alter table public.trims add column if not exists canonical_projection_hash text;
alter table public.trims add column if not exists canonical_projected_at timestamptz;
alter table public.trims add column if not exists list_price_source text;
alter table public.trims add column if not exists list_price_source_ref text;
alter table public.trims add column if not exists list_price_effective_from date;
alter table public.trims add column if not exists list_price_observed_at date;

create unique index if not exists models_canonical_id_uq
  on public.models(canonical_id) where canonical_id is not null;
create unique index if not exists model_powertrains_canonical_id_uq
  on public.model_powertrains(canonical_id) where canonical_id is not null;
create unique index if not exists trims_canonical_id_uq
  on public.trims(canonical_id) where canonical_id is not null;
create index if not exists trims_canonical_variant_idx
  on public.trims(canonical_variant_id) where canonical_variant_id is not null;

comment on column public.models.canonical_id is
  'Stable Vehicle Master Model ID. Supabase row remains a serving projection, not authority.';
comment on column public.models.canonical_generation_id is
  'Canonical Generation selected for this one-row current model serving surface.';
comment on column public.trims.price_baht is
  'Serving cache only. Phase E publisher may populate this only from PriceLedger current LIST_PRICE.';
comment on column public.model_powertrains.canonical_id is
  'Stable canonical Variant ID. model_powertrains is the serving projection of analytical Variant grain.';
comment on column public.trims.canonical_id is
  'Stable canonical MarketTrim ID. MarketTrim remains outside registration resolution.';

create or replace function public.apply_vehicle_serving_projection(p_projection jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_canonical_model text := nullif(p_projection->>'canonical_model_id','');
  v_generation text := nullif(p_projection->>'canonical_generation_id','');
  v_hash text := nullif(p_projection->>'projection_hash','');
  v_model jsonb := p_projection->'model';
  v_model_id uuid;
  v_now timestamptz := now();
  v_variants integer := 0;
  v_trims integer := 0;
begin
  if v_canonical_model is null or v_generation is null or v_hash is null or v_model is null then
    raise exception 'projection requires canonical_model_id, canonical_generation_id, projection_hash and model';
  end if;
  if coalesce((p_projection->>'schema_version')::integer, 0) <> 1 then
    raise exception 'unsupported projection schema_version';
  end if;
  if jsonb_typeof(coalesce(p_projection->'variants','[]'::jsonb)) <> 'array'
     or jsonb_typeof(coalesce(p_projection->'trims','[]'::jsonb)) <> 'array' then
    raise exception 'projection variants/trims must be arrays';
  end if;
  if nullif(v_model->>'canonical_id','') is distinct from v_canonical_model
     or nullif(v_model->>'canonical_generation_id','') is distinct from v_generation then
    raise exception 'model payload canonical IDs disagree with projection envelope';
  end if;

  -- A verified UUID -> canonical mapping is the only authority for choosing the
  -- legacy TDR row. Names and slugs never participate in this lookup.
  select source_id into v_model_id
  from public.canonical_object_map
  where source_table = 'models'
    and canonical_entity_type = 'model'
    and canonical_id = v_canonical_model
    and status = 'verified';

  if v_model_id is null then
    raise exception 'no verified TDR model crosswalk for %', v_canonical_model;
  end if;
  if not exists (select 1 from public.models where id = v_model_id) then
    raise exception 'verified TDR model row % no longer exists', v_model_id;
  end if;

  -- Exact replay: no serving row churn and no updated_at churn.
  if exists (
    select 1 from public.models
    where id = v_model_id
      and serving_source = 'vehicle_master'
      and canonical_id = v_canonical_model
      and canonical_projection_hash = v_hash
  ) then
    return jsonb_build_object(
      'status','unchanged',
      'model_id',v_model_id,
      'canonical_model_id',v_canonical_model,
      'projection_hash',v_hash
    );
  end if;

  -- Adopt only children that already have an explicit verified crosswalk.
  update public.model_powertrains p
  set canonical_id = m.canonical_id
  from public.canonical_object_map m
  where p.model_id = v_model_id
    and p.canonical_id is null
    and m.source_table = 'model_powertrains'
    and m.source_id = p.id
    and m.canonical_entity_type = 'variant'
    and m.status = 'verified';

  update public.trims t
  set canonical_id = m.canonical_id
  from public.canonical_object_map m
  where t.model_id = v_model_id
    and t.canonical_id is null
    and m.source_table = 'trims'
    and m.source_id = t.id
    and m.canonical_entity_type = 'market_trim'
    and m.status = 'verified';

  -- A legacy child with no canonical identity must be reviewed, never silently
  -- deleted/relabelled merely because its display name happens to match.
  if exists (
    select 1 from public.model_powertrains
    where model_id = v_model_id and canonical_id is null
  ) then
    raise exception 'unmapped legacy model_powertrains block projection for %', v_canonical_model;
  end if;
  if exists (
    select 1 from public.trims
    where model_id = v_model_id and canonical_id is null
  ) then
    raise exception 'unmapped legacy trims block projection for %', v_canonical_model;
  end if;

  update public.models
  set canonical_id = v_canonical_model,
      canonical_generation_id = v_generation,
      serving_source = 'vehicle_master',
      canonical_projection_hash = v_hash,
      canonical_projected_at = v_now,
      name_en = coalesce(nullif(v_model->>'name_en',''), name_en),
      name_th = coalesce(nullif(v_model->>'name_th',''), name_th),
      generation = nullif(v_model->>'generation',''),
      body_type = nullif(v_model->>'body_type',''),
      segment = nullif(v_model->>'segment',''),
      powertrain = nullif(v_model->>'powertrain',''),
      powertrains = case
        when jsonb_typeof(v_model->'powertrains') = 'array'
          then array(select jsonb_array_elements_text(v_model->'powertrains'))
        else '{}'::text[]
      end,
      production_type = nullif(v_model->>'production_type',''),
      production_country = nullif(v_model->>'production_country',''),
      launch_date = nullif(v_model->>'launch_date','')::date,
      launch_quarter = nullif(v_model->>'launch_quarter',''),
      launch_month = nullif(v_model->>'launch_month','')::smallint,
      launch_year = nullif(v_model->>'launch_year','')::smallint,
      seats = nullif(v_model->>'seats','')::integer,
      length_mm = nullif(v_model->>'length_mm','')::integer,
      width_mm = nullif(v_model->>'width_mm','')::integer,
      wheelbase_mm = nullif(v_model->>'wheelbase_mm','')::integer,
      retail_price_min = nullif(v_model->>'retail_price_min','')::integer,
      retail_price_max = nullif(v_model->>'retail_price_max','')::integer,
      retail_price_updated_month = nullif(v_model->>'retail_price_updated_month','')::smallint,
      retail_price_updated_year = nullif(v_model->>'retail_price_updated_year','')::smallint,
      status = coalesce(nullif(v_model->>'status',''), status)
  where id = v_model_id;

  -- The same legacy model row represents the chosen current generation in the
  -- serving layer, so record an explicit generation crosswalk too.
  insert into public.canonical_object_map(
    source_table,source_id,canonical_entity_type,canonical_id,status,
    match_basis,verified_by,verified_at
  ) values (
    'models',v_model_id,'generation',v_generation,'verified',
    jsonb_build_object('basis','phase-e canonical serving projection','model',v_canonical_model),
    'phase-e-publisher',v_now
  )
  on conflict (source_table,source_id,canonical_entity_type) do update
    set canonical_id = excluded.canonical_id,
        status = 'verified',
        match_basis = excluded.match_basis,
        verified_by = excluded.verified_by,
        verified_at = excluded.verified_at,
        updated_at = v_now;

  insert into public.model_powertrains(
    model_id,label,powertrain_type,engine_code,displacement_cc,
    battery_capacity_kwh,transmission,drivetrain,import_type,origin_country,
    canonical_id,serving_source,canonical_projection_hash,canonical_projected_at
  )
  select
    v_model_id,x.label,x.powertrain_type,x.engine_code,x.displacement_cc,
    x.battery_capacity_kwh,x.transmission,x.drivetrain,x.import_type,x.origin_country,
    x.canonical_id,'vehicle_master',v_hash,v_now
  from jsonb_to_recordset(coalesce(p_projection->'variants','[]'::jsonb)) as x(
    canonical_id text,
    label text,
    powertrain_type text,
    engine_code text,
    displacement_cc integer,
    battery_capacity_kwh numeric,
    transmission text,
    drivetrain text,
    import_type text,
    origin_country text
  )
  on conflict (canonical_id) where canonical_id is not null do update
    set model_id = excluded.model_id,
        label = excluded.label,
        powertrain_type = excluded.powertrain_type,
        engine_code = excluded.engine_code,
        displacement_cc = excluded.displacement_cc,
        battery_capacity_kwh = excluded.battery_capacity_kwh,
        transmission = excluded.transmission,
        drivetrain = excluded.drivetrain,
        import_type = excluded.import_type,
        origin_country = excluded.origin_country,
        serving_source = 'vehicle_master',
        canonical_projection_hash = v_hash,
        canonical_projected_at = v_now;

  delete from public.model_powertrains p
  where p.model_id = v_model_id
    and p.serving_source = 'vehicle_master'
    and not exists (
      select 1
      from jsonb_array_elements(coalesce(p_projection->'variants','[]'::jsonb)) e
      where e->>'canonical_id' = p.canonical_id
    );

  insert into public.trims(
    model_id,name,price_baht,status,seats_override,sort_order,
    tire_size_front,tire_size_rear,wheel_size_front,wheel_size_rear,
    canonical_id,canonical_variant_id,serving_source,
    canonical_projection_hash,canonical_projected_at,
    list_price_source,list_price_source_ref,list_price_effective_from,list_price_observed_at
  )
  select
    v_model_id,x.name,x.price_baht,coalesce(x.status,'current'),x.seats_override,x.sort_order,
    x.tire_size_front,x.tire_size_rear,x.wheel_size_front,x.wheel_size_rear,
    x.canonical_id,x.canonical_variant_id,'vehicle_master',
    v_hash,v_now,x.list_price_source,x.list_price_source_ref,
    x.list_price_effective_from,x.list_price_observed_at
  from jsonb_to_recordset(coalesce(p_projection->'trims','[]'::jsonb)) as x(
    canonical_id text,
    canonical_variant_id text,
    name text,
    price_baht integer,
    status text,
    seats_override integer,
    sort_order integer,
    tire_size_front text,
    tire_size_rear text,
    wheel_size_front text,
    wheel_size_rear text,
    list_price_source text,
    list_price_source_ref text,
    list_price_effective_from date,
    list_price_observed_at date
  )
  on conflict (canonical_id) where canonical_id is not null do update
    set model_id = excluded.model_id,
        name = excluded.name,
        price_baht = excluded.price_baht,
        status = excluded.status,
        seats_override = excluded.seats_override,
        sort_order = excluded.sort_order,
        tire_size_front = excluded.tire_size_front,
        tire_size_rear = excluded.tire_size_rear,
        wheel_size_front = excluded.wheel_size_front,
        wheel_size_rear = excluded.wheel_size_rear,
        canonical_variant_id = excluded.canonical_variant_id,
        serving_source = 'vehicle_master',
        canonical_projection_hash = v_hash,
        canonical_projected_at = v_now,
        list_price_source = excluded.list_price_source,
        list_price_source_ref = excluded.list_price_source_ref,
        list_price_effective_from = excluded.list_price_effective_from,
        list_price_observed_at = excluded.list_price_observed_at;

  -- Remove links only for projected trims, then rebuild them from exact
  -- canonical MarketTrim -> Variant identity. No name matching is used.
  delete from public.trim_powertrains tp
  using public.trims t
  where tp.trim_id = t.id
    and t.model_id = v_model_id
    and t.serving_source = 'vehicle_master';

  delete from public.trims t
  where t.model_id = v_model_id
    and t.serving_source = 'vehicle_master'
    and not exists (
      select 1
      from jsonb_array_elements(coalesce(p_projection->'trims','[]'::jsonb)) e
      where e->>'canonical_id' = t.canonical_id
    );

  insert into public.trim_powertrains(trim_id,powertrain_id)
  select t.id,p.id
  from public.trims t
  join public.model_powertrains p
    on p.model_id = t.model_id
   and p.canonical_id = t.canonical_variant_id
  where t.model_id = v_model_id
    and t.serving_source = 'vehicle_master'
    and p.serving_source = 'vehicle_master'
    and t.canonical_variant_id is not null
  on conflict do nothing;

  -- Newly projected child UUIDs receive deterministic verified crosswalks. A
  -- future admin cutover can therefore address them by canonical identity.
  insert into public.canonical_object_map(
    source_table,source_id,canonical_entity_type,canonical_id,status,
    match_basis,verified_by,verified_at
  )
  select
    'model_powertrains',p.id,'variant',p.canonical_id,'verified',
    jsonb_build_object('basis','phase-e canonical serving projection','model',v_canonical_model),
    'phase-e-publisher',v_now
  from public.model_powertrains p
  where p.model_id = v_model_id and p.serving_source = 'vehicle_master'
  on conflict (source_table,source_id,canonical_entity_type) do update
    set canonical_id = excluded.canonical_id,
        status = 'verified',
        match_basis = excluded.match_basis,
        verified_by = excluded.verified_by,
        verified_at = excluded.verified_at,
        updated_at = v_now;

  insert into public.canonical_object_map(
    source_table,source_id,canonical_entity_type,canonical_id,status,
    match_basis,verified_by,verified_at
  )
  select
    'trims',t.id,'market_trim',t.canonical_id,'verified',
    jsonb_build_object('basis','phase-e canonical serving projection','model',v_canonical_model),
    'phase-e-publisher',v_now
  from public.trims t
  where t.model_id = v_model_id and t.serving_source = 'vehicle_master'
  on conflict (source_table,source_id,canonical_entity_type) do update
    set canonical_id = excluded.canonical_id,
        status = 'verified',
        match_basis = excluded.match_basis,
        verified_by = excluded.verified_by,
        verified_at = excluded.verified_at,
        updated_at = v_now;

  select count(*) into v_variants
  from public.model_powertrains
  where model_id = v_model_id and serving_source = 'vehicle_master';
  select count(*) into v_trims
  from public.trims
  where model_id = v_model_id and serving_source = 'vehicle_master';

  return jsonb_build_object(
    'status','applied',
    'model_id',v_model_id,
    'canonical_model_id',v_canonical_model,
    'canonical_generation_id',v_generation,
    'projection_hash',v_hash,
    'variants',v_variants,
    'trims',v_trims
  );
end;
$$;

revoke all on function public.apply_vehicle_serving_projection(jsonb) from public, anon, authenticated;
grant execute on function public.apply_vehicle_serving_projection(jsonb) to service_role;

comment on function public.apply_vehicle_serving_projection(jsonb) is
  'Transactional Phase-E apply. Requires an existing verified model crosswalk; never fuzzy-matches serving rows.';
