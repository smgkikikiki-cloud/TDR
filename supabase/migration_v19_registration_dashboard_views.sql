-- Private serving projections for the paid registration dashboard.
-- Every derived dimension keeps its own coverage visible: we do not infer a
-- segment/powertrain when the canonical mapping cannot support it.

create or replace view public.registration_brand_share
with (security_invoker = true)
as
with base as (
  select period, brand_key, brand_name, registrations,
         sum(registrations) over (partition by period) as market_total
  from public.registration_monthly_brand
)
select period, brand_key, brand_name, registrations, market_total,
       round(100.0 * registrations / nullif(market_total, 0), 2) as market_share_pct,
       dense_rank() over (partition by period order by registrations desc, brand_key) as market_rank
from base;

create or replace view public.registration_model_share
with (security_invoker = true)
as
with base as (
  select m.*,
         sum(registrations) over (partition by period) as market_total
  from public.registration_monthly_model m
)
select *,
       round(100.0 * registrations / nullif(market_total, 0), 2) as market_share_pct,
       dense_rank() over (partition by period order by registrations desc, entity_key) as market_rank
from base;

create or replace view public.registration_monthly_segment
with (security_invoker = true)
as
with total as (
  select period, sum(registrations)::bigint as market_total
  from public.registration_monthly_model
  group by period
), classified as (
  select period, segment, sum(registrations)::bigint as registrations
  from public.registration_monthly_model
  where model_id is not null
    and segment is not null
    and segment <> ''
    and segment <> 'UNKNOWN'
  group by period, segment
), coverage as (
  select period, sum(registrations)::bigint as classified_total
  from classified
  group by period
)
select c.period, c.segment, c.registrations,
       cov.classified_total, t.market_total,
       round(100.0 * c.registrations / nullif(cov.classified_total, 0), 2) as share_of_classified_pct,
       round(100.0 * cov.classified_total / nullif(t.market_total, 0), 1) as market_coverage_pct,
       dense_rank() over (partition by c.period order by c.registrations desc, c.segment) as segment_rank
from classified c
join coverage cov using (period)
join total t using (period);

create or replace view public.registration_monthly_powertrain
with (security_invoker = true)
as
with total as (
  select period, sum(registrations)::bigint as market_total
  from public.registration_monthly_model
  group by period
), classified as (
  select period, powertrains[1] as powertrain,
         sum(registrations)::bigint as registrations
  from public.registration_monthly_model
  where model_id is not null
    and cardinality(powertrains) = 1
    and powertrains[1] is not null
    and powertrains[1] <> ''
    and powertrains[1] <> 'UNKNOWN'
  group by period, powertrains[1]
), coverage as (
  select period, sum(registrations)::bigint as classified_total
  from classified
  group by period
)
select c.period, c.powertrain, c.registrations,
       cov.classified_total, t.market_total,
       round(100.0 * c.registrations / nullif(cov.classified_total, 0), 2) as share_of_classified_pct,
       round(100.0 * cov.classified_total / nullif(t.market_total, 0), 1) as market_coverage_pct,
       dense_rank() over (partition by c.period order by c.registrations desc, c.powertrain) as powertrain_rank
from classified c
join coverage cov using (period)
join total t using (period);

create or replace view public.registration_chinese_bev_rank
with (security_invoker = true)
as
select mm.period, mm.model_id, mm.brand_key, mm.brand_name, mm.model_name,
       mm.registrations,
       dense_rank() over (
         partition by mm.period
         order by mm.registrations desc, mm.entity_key
       ) as bev_rank
from public.registration_monthly_model mm
join public.models m on m.id = mm.model_id
join public.brands b on b.id = m.brand_id
where b.country_origin = 'CN'
  and cardinality(mm.powertrains) = 1
  and mm.powertrains[1] = 'BEV';

revoke all on table public.registration_brand_share from anon, authenticated;
revoke all on table public.registration_model_share from anon, authenticated;
revoke all on table public.registration_monthly_segment from anon, authenticated;
revoke all on table public.registration_monthly_powertrain from anon, authenticated;
revoke all on table public.registration_chinese_bev_rank from anon, authenticated;

grant select on table public.registration_brand_share to service_role;
grant select on table public.registration_model_share to service_role;
grant select on table public.registration_monthly_segment to service_role;
grant select on table public.registration_monthly_powertrain to service_role;
grant select on table public.registration_chinese_bev_rank to service_role;

comment on view public.registration_monthly_segment is
  'Paid registration segment share. Share denominator is classified units and market_coverage_pct is explicit.';
comment on view public.registration_monthly_powertrain is
  'Paid powertrain share for single-powertrain canonical models only; coverage is explicit to prevent inferred powertrain counts.';
comment on view public.registration_chinese_bev_rank is
  'Paid model-level ranking for canonically mapped Chinese-origin single-powertrain BEVs.';
