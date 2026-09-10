-- Canonical registration market query contract.
--
-- The legacy dashboard views join registrations to public.models, which is a
-- mutable/legacy serving table. Public catalogue pages now read the immutable
-- active Vehicle Master release through current_vehicle_models instead. This
-- contract makes paid analytics use that same active release for dimensions.
--
-- Deliberately NOT included yet:
--   * price band: canonical PriceLedger coverage is not broad enough to define
--     the market honestly, and price must eventually be effective-date aware;
--   * province / trim grain: the current Supabase registration fact does not
--     carry those fields. They remain in the Vehicle Master warehouse/admin
--     workbench until a richer fact projection is published.

create or replace view public.registration_canonical_fact
with (security_invoker = true)
as
select
  r.period,
  r.registration_type,
  r.registrations,
  r.model_id as tdr_model_id,
  cm.canonical_id as canonical_model_id,
  cm.brand_id as canonical_brand_id,
  coalesce(cb.name_en, r.brand_name_raw) as brand_name,
  coalesce(cm.name_en, r.model_name_raw) as model_name,
  coalesce(nullif(cm.segment, ''), 'UNKNOWN') as segment,
  coalesce(nullif(cm.body_type, ''), 'UNKNOWN') as body_type,
  case
    when cm.canonical_id is null then 'UNKNOWN'
    when jsonb_array_length(coalesce(cm.payload->'powertrains', '[]'::jsonb)) = 0 then 'UNKNOWN'
    when jsonb_array_length(coalesce(cm.payload->'powertrains', '[]'::jsonb)) = 1
      then cm.payload->'powertrains'->>0
    else 'MIXED'
  end as powertrain,
  coalesce(nullif(cm.payload->>'market_position', ''), 'UNKNOWN') as market_position,
  coalesce(nullif(cm.payload->>'market_scope', ''), 'UNKNOWN') as market_scope,
  coalesce(nullif(cm.payload->>'production_type', ''), 'UNKNOWN') as import_type,
  coalesce(nullif(cm.payload->>'production_country', ''), 'UNKNOWN') as origin_country,
  coalesce(nullif(cb.payload->>'oem_group', ''), 'UNKNOWN') as oem_group,
  coalesce(nullif(cb.payload->>'brand_origin', ''), 'UNKNOWN') as brand_origin,
  r.brand_name_raw,
  r.model_name_raw,
  r.mapping_method,
  (cm.canonical_id is not null) as canonically_mapped
from public.registrations r
left join public.current_vehicle_models cm
  on cm.tdr_model_id = r.model_id
left join public.current_vehicle_brands cb
  on cb.canonical_id = cm.brand_id;

revoke all on table public.registration_canonical_fact from public, anon, authenticated;
grant select on table public.registration_canonical_fact to service_role;

comment on view public.registration_canonical_fact is
  'Paid registration fact projected against the active canonical Vehicle Master release. Registration rows stay separate; segment/body/powertrain/etc always come from current_vehicle_*.';

create or replace function public.registration_market_slice(
  p_period_from date,
  p_period_to date,
  p_dimension text,
  p_registration_types text[] default null,
  p_brand_ids text[] default null,
  p_model_ids text[] default null,
  p_segments text[] default null,
  p_body_types text[] default null,
  p_powertrains text[] default null,
  p_oem_groups text[] default null,
  p_market_positions text[] default null,
  p_import_types text[] default null,
  p_origin_countries text[] default null,
  p_brand_origins text[] default null,
  p_market_scopes text[] default null,
  p_include_unmapped boolean default false,
  p_limit integer default 100
)
returns table (
  entity_key text,
  entity_label text,
  registrations bigint,
  market_total bigint,
  market_share_pct numeric,
  market_rank bigint,
  window_raw_units bigint,
  window_mapped_units bigint,
  window_mapping_coverage_pct numeric
)
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_limit integer := least(greatest(coalesce(p_limit, 100), 1), 500);
begin
  if p_period_from is null or p_period_to is null or p_period_to < p_period_from then
    raise exception 'invalid registration market window';
  end if;

  if p_dimension not in (
    'brand', 'model', 'segment', 'body_type', 'powertrain',
    'oem_group', 'market_position', 'import_type', 'origin_country',
    'brand_origin', 'registration_type', 'market_scope'
  ) then
    raise exception 'unsupported registration market dimension: %', p_dimension;
  end if;

  return query
  with window_base as (
    select f.*
    from public.registration_canonical_fact f
    where f.period between p_period_from and p_period_to
      and (p_registration_types is null or f.registration_type = any(p_registration_types))
  ), coverage as (
    select
      coalesce(sum(w.registrations), 0)::bigint as raw_units,
      coalesce(sum(w.registrations) filter (where w.canonically_mapped), 0)::bigint as mapped_units
    from window_base w
  ), scoped as (
    select w.*
    from window_base w
    where (p_include_unmapped or w.canonically_mapped)
      -- The dimension being ranked stays open. A Brand ranking with Brand=B
      -- must still contain Brand A/C/etc so share and rank retain a meaningful
      -- denominator. This is the same rule as Vehicle Master's
      -- comparison_filters().
      and (p_dimension = 'registration_type' or p_registration_types is null or w.registration_type = any(p_registration_types))
      and (p_dimension = 'brand' or p_brand_ids is null or w.canonical_brand_id = any(p_brand_ids))
      and (p_dimension = 'model' or p_model_ids is null or w.canonical_model_id = any(p_model_ids))
      and (p_dimension = 'segment' or p_segments is null or w.segment = any(p_segments))
      and (p_dimension = 'body_type' or p_body_types is null or w.body_type = any(p_body_types))
      and (p_dimension = 'powertrain' or p_powertrains is null or w.powertrain = any(p_powertrains))
      and (p_dimension = 'oem_group' or p_oem_groups is null or w.oem_group = any(p_oem_groups))
      and (p_dimension = 'market_position' or p_market_positions is null or w.market_position = any(p_market_positions))
      and (p_dimension = 'import_type' or p_import_types is null or w.import_type = any(p_import_types))
      and (p_dimension = 'origin_country' or p_origin_countries is null or w.origin_country = any(p_origin_countries))
      and (p_dimension = 'brand_origin' or p_brand_origins is null or w.brand_origin = any(p_brand_origins))
      and (p_dimension = 'market_scope' or p_market_scopes is null or w.market_scope = any(p_market_scopes))
  ), labelled as (
    select
      case p_dimension
        when 'brand' then coalesce(s.canonical_brand_id, 'raw-brand:' || public.normalize_registration_token(s.brand_name_raw))
        when 'model' then coalesce(s.canonical_model_id, 'raw-model:' || public.normalize_registration_token(s.brand_name_raw) || ':' || public.normalize_registration_token(s.model_name_raw))
        when 'segment' then s.segment
        when 'body_type' then s.body_type
        when 'powertrain' then s.powertrain
        when 'oem_group' then s.oem_group
        when 'market_position' then s.market_position
        when 'import_type' then s.import_type
        when 'origin_country' then s.origin_country
        when 'brand_origin' then s.brand_origin
        when 'registration_type' then s.registration_type
        when 'market_scope' then s.market_scope
      end as key,
      case p_dimension
        when 'brand' then s.brand_name
        when 'model' then concat_ws(' ', nullif(s.brand_name, ''), nullif(s.model_name, ''))
        when 'segment' then s.segment
        when 'body_type' then s.body_type
        when 'powertrain' then s.powertrain
        when 'oem_group' then s.oem_group
        when 'market_position' then s.market_position
        when 'import_type' then s.import_type
        when 'origin_country' then s.origin_country
        when 'brand_origin' then s.brand_origin
        when 'registration_type' then s.registration_type
        when 'market_scope' then s.market_scope
      end as label,
      s.registrations
    from scoped s
  ), grouped as (
    select l.key, l.label, sum(l.registrations)::bigint as units
    from labelled l
    where l.key is not null and l.key <> ''
    group by l.key, l.label
  ), ranked as (
    select
      g.key,
      g.label,
      g.units,
      sum(g.units) over ()::bigint as total,
      dense_rank() over (order by g.units desc, g.key) as rank
    from grouped g
  )
  select
    r.key,
    r.label,
    r.units,
    r.total,
    round(100.0 * r.units / nullif(r.total, 0), 2),
    r.rank,
    c.raw_units,
    c.mapped_units,
    round(100.0 * c.mapped_units / nullif(c.raw_units, 0), 1)
  from ranked r
  cross join coverage c
  order by r.rank, r.key
  limit v_limit;
end;
$$;

revoke execute on function public.registration_market_slice(
  date, date, text, text[], text[], text[], text[], text[], text[], text[],
  text[], text[], text[], text[], text[], boolean, integer
) from public, anon, authenticated;
grant execute on function public.registration_market_slice(
  date, date, text, text[], text[], text[], text[], text[], text[], text[],
  text[], text[], text[], text[], text[], boolean, integer
) to service_role;

comment on function public.registration_market_slice(
  date, date, text, text[], text[], text[], text[], text[], text[], text[],
  text[], text[], text[], text[], text[], boolean, integer
) is
  'Service-only market slicer over active canonical vehicle dimensions. The grouped dimension ignores its own scope filter so rank/share denominators remain competitive. Price is intentionally absent until canonical PriceLedger coverage and period semantics are sufficient.';
