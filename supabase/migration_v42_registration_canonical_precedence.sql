-- registration_reporting_source's legacy branch derived canonical_model_id
-- only through the reverse crosswalk (current_vehicle_models.tdr_model_id
-- = registrations.model_id), so it never saw v41's own
-- registrations.canonical_model_id column at all. A row created by
-- assignRegistrationIdentity for a car with no legacy row yet --
-- model_id NULL, canonical_model_id set directly -- came out of this view
-- as canonical_model_id NULL: unmapped, even though it had just been
-- mapped.
--
-- Precedence, matching lib/registration-canonical-resolve.ts:
--   1. registrations.canonical_model_id, when the row carries one.
--   2. the legacy bridge (model_id -> tdr_model_id reverse crosswalk).
--   3. unresolved.
--
-- Purely a `create or replace view` of the same two views migration_v31
-- already defines. Nothing dropped, nothing else touched, and applying
-- this to a database with no canonical_model_id values yet set changes no
-- output at all (coalesce falls through to exactly the old expression).

create or replace view public.registration_reporting_source
with (security_invoker = true)
as
with state as (
  select active_source from public.registration_serving_state
  where scope = 'registration_analytics'
)
select
  r.id, r.period, r.registration_type, r.brand_name_raw, r.model_name_raw,
  r.model_id, coalesce(r.canonical_model_id, cvm.canonical_id) as canonical_model_id,
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
  'Phase 3 compatibility boundary: shaped like registrations (plus canonical_model_id/fact_source). Reads legacy registrations or the v2 serving projection depending on registration_serving_state.active_source. A legacy row''s canonical_model_id is registrations.canonical_model_id when set directly (v41), else the reverse crosswalk through model_id -- see migration_v42. A v2 row''s model_id is a best-effort reverse crosswalk for compatibility only -- never a resolution input anywhere in the v2 pipeline. Every existing registration_* view below this one is redirected to read from here instead of registrations directly, so the switch reaches all of them through one boundary.';

-- registration_analytics_coverage's "mapped" test was `model_id is not
-- null`, which is exactly the check that can never see a canonical-only
-- row. Once registration_reporting_source.canonical_model_id reflects the
-- full precedence (above), mapped_rows/mapped_registrations switch to
-- testing canonical_model_id directly -- the same coalesced value, so this
-- inherits the fix with no logic of its own to get wrong twice.
create or replace view public.registration_analytics_coverage with (security_invoker=true) as
select r.period,count(*)::bigint raw_rows,sum(r.registrations)::bigint total_registrations,
count(*) filter(where r.canonical_model_id is not null)::bigint mapped_rows,
sum(r.registrations) filter(where r.canonical_model_id is not null)::bigint mapped_registrations,
round(100.0*coalesce(sum(r.registrations) filter(where r.canonical_model_id is not null),0)/nullif(sum(r.registrations),0),1) mapped_unit_pct
from public.registration_reporting_source r group by r.period;

comment on view public.registration_analytics_coverage is
  'Monthly coverage: raw rows/units vs mapped. Mapped means registration_reporting_source.canonical_model_id is not null, which is true for a row carrying registrations.canonical_model_id directly (no legacy row required) as well as one resolved through the legacy model_id crosswalk -- see migration_v42.';
