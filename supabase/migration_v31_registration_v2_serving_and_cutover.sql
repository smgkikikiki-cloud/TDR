-- Phase 3: v2 registration serving projection + reversible cutover switch.
--
-- Purely additive plus three `create or replace view` redefinitions of
-- existing registration dashboard views (registration_analytics_coverage,
-- registration_monthly_brand, registration_monthly_model) that change only
-- their FROM/JOIN source, never their SELECT list, WHERE logic, or grouping.
-- `registrations`, `registration_brand_aliases`, `registration_model_aliases`,
-- `match_registration_model`, `ingest_registration_snapshot`, and every
-- other registration_* object are untouched. No row of `registrations` is
-- ever read differently by any consumer that already went through one of
-- these three views or through `registrations` directly at another entry
-- point (there is none in this repository besides the ones redirected
-- here and `ingest_registration_snapshot`'s own writer, which this
-- migration does not touch).
--
-- Design (docs/vehicle-platform/PHASE3_CUTOVER.md):
--
-- 1. registration_serving_state - a single-row config table (the same
--    pattern canonical_vehicle_state already uses for the Vehicle Master
--    release pointer): active_source ('legacy' | 'v2', default 'legacy' -
--    applying this migration changes nothing until an operator explicitly
--    flips it) and v2_source_boundary_period (the deterministic period/
--    source ownership boundary from
--    vehreg.registration_v2_parity.authoritative_source_for_period -
--    periods on or before it are legacy_registrations_backfill-
--    authoritative, after it are dlt_ckan-authoritative).
-- 2. set_registration_serving_source(text) / set_registration_v2_source_
--    boundary(text) - the atomic, reversible switch. Each is a single
--    UPDATE of a one-row table inside a security definer function; flipping
--    active_source back to 'legacy' is instant and requires no data
--    reconstruction - legacy `registrations` is never touched by any of
--    this, so it is always exactly as it was.
-- 3. registration_facts_v2_serving - the v2 serving projection: MODEL facts
--    count directly, VARIANT facts roll up to their canonical model, BRAND
--    facts are never distributed into models (mirrors
--    vehreg/registration_v2_rollup.py's rollup rule exactly), and only the
--    period-authoritative source_kind (rule #1) contributes.
-- 4. registration_reporting_source - the ONE compatibility boundary: a view
--    shaped like `registrations` (plus a `canonical_model_id` passthrough
--    and a `fact_source` tag) that reads from `registrations` when
--    active_source = 'legacy' and from the v2 serving projection when
--    active_source = 'v2'. A v2-sourced row's `model_id` is the *reverse*
--    crosswalk of its canonical_model_id through current_vehicle_models
--    (best-effort, NULL when no legacy model row exists for it) - purely a
--    compatibility shim so every existing model_id-keyed
--    view/join/filter keeps working unmodified; nothing in the v2 pipeline
--    itself ever treats that uuid as canonical (see DLT_V2_ARCHITECTURE.md).
--    A v2 BRAND-grain fact (canonical_model_id NULL) presents as model_id
--    NULL, identically to legacy's own "unmapped" representation - the same
--    honest coarsening, not a new concept.
-- 5. registration_analytics_coverage / registration_monthly_brand /
--    registration_monthly_model now read `registration_reporting_source`
--    instead of `registrations` directly - every view built on top of
--    those three (registration_brand_share, registration_model_share,
--    registration_monthly_segment, registration_monthly_powertrain,
--    registration_chinese_bev_rank, registration_model_mom) inherits the
--    switch with zero changes of their own, since none of them reads
--    `registrations` directly.

create table if not exists public.registration_serving_state (
  scope text primary key default 'registration_analytics',
  active_source text not null default 'legacy'
    check (active_source in ('legacy', 'v2')),
  v2_source_boundary_period text,   -- 'YYYY-MM'; null = no direct-ingest period is authoritative yet
  switched_at timestamptz not null default now(),
  switched_by text
);
insert into public.registration_serving_state (scope, active_source)
values ('registration_analytics', 'legacy')
on conflict (scope) do nothing;

alter table public.registration_serving_state enable row level security;
revoke all on table public.registration_serving_state from anon, authenticated;
grant select on table public.registration_serving_state to service_role;

comment on table public.registration_serving_state is
  'Phase 3 cutover switch: which registration source (legacy registrations vs the v2 shadow) registration_reporting_source reads from, plus the v2 source-ownership boundary period. Change only via set_registration_serving_source/set_registration_v2_source_boundary. Default legacy -- applying this migration changes no behavior.';

create or replace function public.set_registration_serving_source(
  p_source text, p_switched_by text default null
)
returns public.registration_serving_state
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare result public.registration_serving_state;
begin
  update public.registration_serving_state
  set active_source = p_source, switched_at = now(), switched_by = p_switched_by
  where scope = 'registration_analytics'
  returning * into result;
  if result is null then
    raise exception 'registration_serving_state row missing for scope=registration_analytics';
  end if;
  return result;
end;
$$;
revoke all on function public.set_registration_serving_source(text, text) from public, anon, authenticated;
grant execute on function public.set_registration_serving_source(text, text) to service_role;

comment on function public.set_registration_serving_source is
  'The reversible cutover switch. A single UPDATE of one row -- switching back to legacy is instant and requires no data reconstruction, since registrations is never touched by any part of this migration.';

create or replace function public.set_registration_v2_source_boundary(
  p_boundary_period text
)
returns public.registration_serving_state
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare result public.registration_serving_state;
begin
  if p_boundary_period is not null and p_boundary_period !~ '^[0-9]{4}-[0-9]{2}$' then
    raise exception 'boundary period must be YYYY-MM or null, got %', p_boundary_period;
  end if;
  update public.registration_serving_state
  set v2_source_boundary_period = p_boundary_period, switched_at = now()
  where scope = 'registration_analytics'
  returning * into result;
  return result;
end;
$$;
revoke all on function public.set_registration_v2_source_boundary(text) from public, anon, authenticated;
grant execute on function public.set_registration_v2_source_boundary(text) to service_role;

comment on function public.set_registration_v2_source_boundary is
  'Sets the deterministic period/source ownership boundary (vehreg.registration_v2_parity.authoritative_source_for_period): periods on or before it are legacy_registrations_backfill-authoritative, after it are dlt_ckan-authoritative. Null (the default) means every period is still backfill-authoritative.';

-- 3. v2 serving projection: the authoritative OBSERVATION set is the volume
--    source of truth, and fact resolution is optional -- `registration_
--    observations_v2 LEFT JOIN registration_facts_v2`, not the other way
--    around. An observation whose resolution produced no fact at all (brand
--    not found - Invariant 6) still contributes a row here, with
--    canonical_id/canonical_model_id/canonical_brand_id/grain all null and
--    its raw_brand/raw_model/units retained - it is not silently dropped.
--    Every authoritative observation contributes its units exactly once:
--    registration_facts_v2's primary key is observation_id, so this LEFT
--    JOIN can never fan out to more than one row per observation. MODEL/
--    VARIANT/BRAND rollup behavior is unchanged from before. Mirrors
--    vehreg/registration_v2_rollup.py's ServingRow/serving_reconciles
--    exactly - see that module for the offline-testable reference
--    implementation this view's semantics must keep matching.
create or replace view public.registration_facts_v2_serving
with (security_invoker = true)
as
with state as (
  select v2_source_boundary_period
  from public.registration_serving_state
  where scope = 'registration_analytics'
)
select
  o.observation_id,
  o.period,
  o.registration_type,
  f.grain,
  case when f.grain is null or f.grain = 'BRAND' then null
       else split_part(f.canonical_id, '.', 1) || '.' || split_part(f.canonical_id, '.', 2)
  end as canonical_model_id,
  case when f.grain is null then null
       else split_part(f.canonical_id, '.', 1)
  end as canonical_brand_id,
  f.canonical_id,
  o.units,
  o.source_kind,
  o.raw_brand,
  o.raw_model
from public.registration_observations_v2 o
left join public.registration_facts_v2 f on f.observation_id = o.observation_id
cross join state
where
  (o.source_kind = 'legacy_registrations_backfill'
    and (state.v2_source_boundary_period is null
         or o.period <= state.v2_source_boundary_period))
  or
  (o.source_kind = 'dlt_ckan'
    and state.v2_source_boundary_period is not null
    and o.period > state.v2_source_boundary_period);

revoke all on table public.registration_facts_v2_serving from anon, authenticated;
grant select on table public.registration_facts_v2_serving to service_role;

comment on view public.registration_facts_v2_serving is
  'v2 serving projection: authoritative OBSERVATIONS (registration_observations_v2, filtered by set_registration_v2_source_boundary''s period-ownership rule) LEFT JOIN their optional resolved fact. A completely unresolved observation still contributes a row -- canonical_id/canonical_model_id/canonical_brand_id/grain null, raw_brand/raw_model/units retained -- never silently dropped. canonical_model_id is null for BRAND-grain facts (never distributed into a model) and for unresolved rows; canonical_brand_id is populated for every resolved grain (BRAND/MODEL/VARIANT) and null only when unresolved. Every authoritative observation contributes exactly once (registration_facts_v2 is keyed by observation_id, so the LEFT JOIN cannot fan out). Mirrors vehreg/registration_v2_rollup.py exactly -- see that module for the offline-testable reference implementation.';

-- 4. The one compatibility boundary.
create or replace view public.registration_reporting_source
with (security_invoker = true)
as
with state as (
  select active_source from public.registration_serving_state
  where scope = 'registration_analytics'
)
select
  r.id, r.period, r.registration_type, r.brand_name_raw, r.model_name_raw,
  r.model_id, cvm.canonical_id as canonical_model_id,
  r.registrations, r.source_id, r.mapping_method, r.created_at,
  'legacy'::text as fact_source
from public.registrations r
cross join state
left join public.current_vehicle_models cvm on cvm.tdr_model_id = r.model_id
where state.active_source = 'legacy'

union all

select
  null::uuid as id,
  (v.period || '-01')::date as period,
  v.registration_type,
  v.raw_brand as brand_name_raw,
  v.raw_model as model_name_raw,
  cvm2.tdr_model_id as model_id,
  v.canonical_model_id,
  v.units::integer as registrations,
  null::uuid as source_id,
  'v2'::text as mapping_method,
  null::timestamptz as created_at,
  'v2'::text as fact_source
from public.registration_facts_v2_serving v
cross join state
left join public.current_vehicle_models cvm2 on cvm2.canonical_id = v.canonical_model_id
where state.active_source = 'v2';

revoke all on table public.registration_reporting_source from anon, authenticated;
grant select on table public.registration_reporting_source to service_role;

comment on view public.registration_reporting_source is
  'Phase 3 compatibility boundary: shaped like registrations (plus canonical_model_id/fact_source). Reads legacy registrations or the v2 serving projection depending on registration_serving_state.active_source. A v2 row''s model_id is a best-effort reverse crosswalk for compatibility only -- never a resolution input anywhere in the v2 pipeline. Every existing registration_* view below this one is redirected to read from here instead of registrations directly, so the switch reaches all of them through one boundary.';

-- 5. Redirect the three views that read `registrations` directly. Every
--    other registration_* view (registration_brand_share,
--    registration_model_share, registration_monthly_segment,
--    registration_monthly_powertrain, registration_chinese_bev_rank,
--    registration_model_mom) is built on top of these three and needs no
--    change of its own.
create or replace view public.registration_analytics_coverage with (security_invoker=true) as
select r.period,count(*)::bigint raw_rows,sum(r.registrations)::bigint total_registrations,count(*) filter(where r.model_id is not null)::bigint mapped_rows,sum(r.registrations) filter(where r.model_id is not null)::bigint mapped_registrations,
round(100.0*coalesce(sum(r.registrations) filter(where r.model_id is not null),0)/nullif(sum(r.registrations),0),1) mapped_unit_pct
from public.registration_reporting_source r group by r.period;

create or replace view public.registration_monthly_brand with (security_invoker=true) as
select r.period,coalesce(b.slug,public.normalize_registration_token(r.brand_name_raw)) brand_key,coalesce(b.name_en,r.brand_name_raw) brand_name,sum(r.registrations)::bigint registrations
from public.registration_reporting_source r left join public.registration_brand_aliases rba on rba.raw_brand_norm=public.normalize_registration_token(r.brand_name_raw) left join public.brands b on b.id=rba.brand_id
group by r.period,brand_key,brand_name;

create or replace view public.registration_monthly_model
with (security_invoker = true)
as
with normalized as (
  select r.period,
         case when r.model_id is not null then 'model:' || r.model_id::text
              else 'raw:' || public.normalize_registration_token(r.brand_name_raw) || ':' ||
                   public.normalize_registration_token(r.model_name_raw) end as entity_key,
         r.model_id,
         coalesce(b.slug, public.normalize_registration_token(r.brand_name_raw)) as brand_key,
         coalesce(b.name_en, r.brand_name_raw) as brand_name,
         coalesce(m.name_en, r.model_name_raw) as model_name,
         m.segment,
         m.body_type,
         m.powertrains,
         r.registrations
  from public.registration_reporting_source r
  left join public.models m on m.id = r.model_id
  left join public.registration_brand_aliases rba
    on rba.raw_brand_norm = public.normalize_registration_token(r.brand_name_raw)
  left join public.brands b on b.id = coalesce(m.brand_id, rba.brand_id)
)
select period, entity_key, model_id, brand_key, brand_name, model_name,
       segment, body_type, powertrains,
       sum(registrations)::bigint as registrations,
       count(*)::bigint as source_rows,
       bool_and(model_id is not null) as canonically_mapped
from normalized
group by period, entity_key, model_id, brand_key, brand_name, model_name,
         segment, body_type, powertrains;

comment on view public.registration_monthly_model is
  'One monthly row per canonical model; multiple reviewed DLT raw spellings roll up. Unmapped raw identities remain separate. Reads registration_reporting_source, not registrations directly -- see migration_v31.';
