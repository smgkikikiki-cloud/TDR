-- Phase E: registration analytics ingest and reviewed DLT crosswalk.
--
-- Registration facts remain a separate paid-intelligence dataset.  They are
-- never folded into Vehicle Master / MarketTrim.  A registration row may link
-- to an editorial model only through a reviewed alias; otherwise model_id stays
-- NULL and the raw DLT brand/model strings are retained losslessly.

create or replace function public.normalize_registration_token(value text)
returns text
language sql
immutable
parallel safe
as $$
  select regexp_replace(lower(coalesce(value, '')), '[^a-z0-9]+', '', 'g')
$$;

alter table public.registrations
  add column if not exists registration_type text not null default '*';

alter table public.registrations
  add column if not exists mapping_method text not null default 'unmapped';

alter table public.registrations
  drop constraint if exists registrations_period_brand_name_raw_model_name_raw_key;

alter table public.registrations
  drop constraint if exists registrations_period_type_brand_model_key;

alter table public.registrations
  add constraint registrations_period_type_brand_model_key
  unique (period, registration_type, brand_name_raw, model_name_raw);

create index if not exists registrations_model_period_idx
  on public.registrations(model_id, period);

create table if not exists public.registration_brand_aliases (
  raw_brand_norm text primary key,
  brand_id uuid not null references public.brands(id) on delete cascade,
  notes text,
  reviewed_at timestamptz not null default now()
);

create table if not exists public.registration_model_aliases (
  brand_id uuid not null references public.brands(id) on delete cascade,
  registration_type text not null default '*',
  alias_norm text not null,
  model_id uuid not null references public.models(id) on delete cascade,
  match_mode text not null default 'prefix' check (match_mode in ('exact', 'prefix')),
  notes text,
  reviewed_at timestamptz not null default now(),
  primary key (brand_id, registration_type, alias_norm)
);

create index if not exists registration_model_aliases_lookup_idx
  on public.registration_model_aliases(brand_id, registration_type, alias_norm);

alter table public.registration_brand_aliases enable row level security;
alter table public.registration_model_aliases enable row level security;
revoke all on table public.registration_brand_aliases from anon, authenticated;
revoke all on table public.registration_model_aliases from anon, authenticated;
grant select, insert, update, delete on table public.registration_brand_aliases to service_role;
grant select, insert, update, delete on table public.registration_model_aliases to service_role;

-- Canonical brand spellings are reviewed aliases by definition.  Keep the
-- crosswalk separate so registration routing never depends on MarketTrim.
insert into public.registration_brand_aliases(raw_brand_norm, brand_id, notes)
select public.normalize_registration_token(slug), id, 'canonical brand slug'
from public.brands
where public.normalize_registration_token(slug) <> ''
on conflict (raw_brand_norm) do nothing;

insert into public.registration_brand_aliases(raw_brand_norm, brand_id, notes)
select public.normalize_registration_token(name_en), id, 'canonical English brand name'
from public.brands
where public.normalize_registration_token(name_en) <> ''
on conflict (raw_brand_norm) do nothing;

-- DLT sometimes emits GWM sub-brand labels in the brand column.  These are
-- reviewed brand-level aliases only; the model still has to match separately.
insert into public.registration_brand_aliases(raw_brand_norm, brand_id, notes)
select public.normalize_registration_token(v.raw_brand), b.id, 'reviewed DLT GWM brand alias'
from (values
  ('GWM TANK', 'gwm'),
  ('HAVAL',    'gwm'),
  ('POER',     'gwm'),
  ('ORA',      'gwm')
) as v(raw_brand, brand_slug)
join public.brands b on b.slug = v.brand_slug
on conflict (raw_brand_norm) do update
set brand_id = excluded.brand_id,
    notes = excluded.notes,
    reviewed_at = now();

-- Promote only aliases that identify exactly one model inside a brand.  Shared
-- pickup aliases such as "D-Max" and "Hilux Revo" are intentionally excluded
-- here and handled below with registration-class-specific reviewed rules.
with candidate_aliases as (
  select m.brand_id, m.id as model_id, public.normalize_registration_token(a.alias) as alias_norm
  from public.models m
  cross join lateral unnest(
    array_append(coalesce(m.dlt_aliases, '{}'::text[]), coalesce(m.name_en, ''))
  ) as a(alias)
), unambiguous as (
  select brand_id, alias_norm, min(model_id::text)::uuid as model_id
  from candidate_aliases
  where alias_norm <> ''
  group by brand_id, alias_norm
  having count(distinct model_id) = 1
)
insert into public.registration_model_aliases(
  brand_id, registration_type, alias_norm, model_id, match_mode, notes
)
select brand_id, '*', alias_norm, model_id, 'prefix', 'reviewed canonical/DLT alias'
from unambiguous
on conflict (brand_id, registration_type, alias_norm) do nothing;

-- Pickups are split into cab and double-cab canonical models.  The long-form
-- DLT source carries registration class, which makes the generic nameplate
-- alias reviewable: RY1 -> passenger/double cab, RY3 -> private truck/cab.
-- Pivot-only months use '*' and therefore do NOT guess this split.
insert into public.registration_model_aliases(
  brand_id, registration_type, alias_norm, model_id, match_mode, notes
)
select m.brand_id, v.registration_type,
       public.normalize_registration_token(v.raw_alias), m.id,
       'prefix', 'reviewed pickup split from DLT registration class'
from (values
  ('isuzu-dmax-double-cab',          'RY1', 'D-MAX'),
  ('isuzu-dmax-cab',                 'RY3', 'D-MAX'),
  ('toyota-hilux-revo-double-cab',   'RY1', 'HILUX REVO'),
  ('toyota-hilux-revo-cab',          'RY3', 'HILUX REVO'),
  ('toyota-hilux-travo-double-cab',  'RY1', 'HILUX TRAVO'),
  ('toyota-hilux-travo-cab',         'RY3', 'HILUX TRAVO'),
  ('ford-ranger-double-cab',         'RY1', 'RANGER'),
  ('ford-ranger-cab',                'RY3', 'RANGER'),
  ('mitsubishi-triton-double-cab',   'RY1', 'TRITON'),
  ('mitsubishi-triton-cab',          'RY3', 'TRITON'),
  ('nissan-navara-double-cab',       'RY1', 'NAVARA'),
  ('nissan-navara-cab',              'RY3', 'NAVARA')
) as v(model_slug, registration_type, raw_alias)
join public.models m on m.slug = v.model_slug
on conflict (brand_id, registration_type, alias_norm) do update
set model_id = excluded.model_id,
    match_mode = excluded.match_mode,
    notes = excluded.notes,
    reviewed_at = now();

-- GWM TANK can appear with the sub-brand in the DLT brand column, leaving only
-- "300 ..." / "500 ..." in the model column.
insert into public.registration_model_aliases(
  brand_id, registration_type, alias_norm, model_id, match_mode, notes
)
select m.brand_id, '*', public.normalize_registration_token(v.raw_alias), m.id,
       'prefix', 'reviewed GWM TANK sub-brand model alias'
from (values
  ('gwm-tank300', '300'),
  ('gwm-tank500', '500')
) as v(model_slug, raw_alias)
join public.models m on m.slug = v.model_slug
on conflict (brand_id, registration_type, alias_norm) do update
set model_id = excluded.model_id,
    match_mode = excluded.match_mode,
    notes = excluded.notes,
    reviewed_at = now();

create or replace function public.match_registration_model(
  raw_brand text,
  raw_model text,
  raw_registration_type text default '*'
)
returns table(model_id uuid, mapping_method text)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  with input as (
    select public.normalize_registration_token(raw_brand) as brand_norm,
           public.normalize_registration_token(raw_model) as model_norm,
           coalesce(nullif(raw_registration_type, ''), '*') as registration_type
  ), brand_match as (
    select ba.brand_id, i.brand_norm, i.model_norm, i.registration_type,
           case when i.model_norm like i.brand_norm || '%' and i.brand_norm <> ''
                then substr(i.model_norm, length(i.brand_norm) + 1)
                else i.model_norm end as model_without_raw_brand
    from input i
    join public.registration_brand_aliases ba on ba.raw_brand_norm = i.brand_norm
  ), scored as (
    select a.model_id, a.registration_type as alias_registration_type,
           a.alias_norm, a.match_mode,
           case when a.registration_type = b.registration_type then 1 else 0 end as class_specific,
           length(a.alias_norm) as alias_length,
           dense_rank() over (
             order by
               case when a.registration_type = b.registration_type then 1 else 0 end desc,
               length(a.alias_norm) desc
           ) as score_rank
    from brand_match b
    join public.registration_model_aliases a
      on a.brand_id = b.brand_id
     and a.registration_type in ('*', b.registration_type)
     and (
       (a.match_mode = 'exact' and
        (b.model_norm = a.alias_norm or b.model_without_raw_brand = a.alias_norm))
       or
       (a.match_mode = 'prefix' and
        (b.model_norm like a.alias_norm || '%' or
         b.model_without_raw_brand like a.alias_norm || '%'))
     )
  ), best as (
    select * from scored where score_rank = 1
  )
  select min(model_id::text)::uuid,
         case when max(class_specific) = 1
              then 'reviewed-class-alias'
              else 'reviewed-alias' end
  from best
  having count(distinct model_id) = 1
$$;

revoke all on function public.match_registration_model(text, text, text) from public, anon, authenticated;
grant execute on function public.match_registration_model(text, text, text) to service_role;

-- Controlled snapshot loader.  It accepts only CSV snapshots in this repo and
-- rejects malformed lines instead of silently corrupting a month.  Re-running a
-- period replaces that month atomically, so removed/corrected rows do not linger.
create or replace function public.ingest_registration_snapshot(
  p_snapshot_url text,
  p_expected_period date,
  p_source_title text default null
)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions, pg_temp
as $$
declare
  body text;
  source_uuid uuid;
  malformed integer;
  inserted_rows integer;
  inserted_units bigint;
  mapped_rows integer;
  mapped_units bigint;
begin
  if p_expected_period <> date_trunc('month', p_expected_period)::date then
    raise exception 'expected period must be the first day of the month';
  end if;

  if p_snapshot_url !~ '^https://raw[.]githubusercontent[.]com/smgkikikiki-cloud/TDR/main/automotive/vehicle_master/data/raw_pivot/(long|pivot)_[0-9]{4}-[0-9]{2}[.]csv$' then
    raise exception 'snapshot URL is outside the canonical TDR registration snapshot path';
  end if;

  select (extensions.http_get(p_snapshot_url)).content::text into body;
  if body is null or body = '' then
    raise exception 'empty registration snapshot';
  end if;

  with lines as (
    select trim(both E'\r' from line) as line
    from regexp_split_to_table(body, E'\n') as line
    where line <> '' and line not like '%period,registration_type,brand,model,units%'
  )
  select count(*) into malformed
  from lines
  where length(line) - length(replace(line, ',', '')) <> 4
     or split_part(line, ',', 1) <> to_char(p_expected_period, 'YYYY-MM')
     or split_part(line, ',', 2) = ''
     or split_part(line, ',', 3) = ''
     or split_part(line, ',', 4) = ''
     or split_part(line, ',', 5) !~ '^[0-9]+$';

  if malformed > 0 then
    raise exception 'registration snapshot contains % malformed/mismatched rows', malformed;
  end if;

  select id into source_uuid
  from public.sources
  where url = p_snapshot_url
  order by created_at desc
  limit 1;

  if source_uuid is null then
    insert into public.sources(title, publisher, url, published_date, notes)
    values (
      coalesce(p_source_title, 'DLT registration snapshot ' || to_char(p_expected_period, 'YYYY-MM')),
      'Department of Land Transport / TDR snapshot',
      p_snapshot_url,
      p_expected_period,
      'Canonical repository snapshot used by the private TDR registration analytics pipeline.'
    )
    returning id into source_uuid;
  end if;

  delete from public.registrations where period = p_expected_period;

  with lines as (
    select trim(both E'\r' from line) as line
    from regexp_split_to_table(body, E'\n') as line
    where line <> '' and line not like '%period,registration_type,brand,model,units%'
  ), parsed as (
    select to_date(split_part(line, ',', 1) || '-01', 'YYYY-MM-DD') as period,
           split_part(line, ',', 2) as registration_type,
           split_part(line, ',', 3) as brand_name_raw,
           split_part(line, ',', 4) as model_name_raw,
           split_part(line, ',', 5)::integer as registrations
    from lines
  )
  insert into public.registrations(
    period, registration_type, brand_name_raw, model_name_raw,
    model_id, registrations, source_id, mapping_method
  )
  select p.period, p.registration_type, p.brand_name_raw, p.model_name_raw,
         mm.model_id, p.registrations, source_uuid,
         coalesce(mm.mapping_method, 'unmapped')
  from parsed p
  left join lateral public.match_registration_model(
    p.brand_name_raw, p.model_name_raw, p.registration_type
  ) mm on true;

  select count(*), coalesce(sum(registrations), 0),
         count(*) filter (where model_id is not null),
         coalesce(sum(registrations) filter (where model_id is not null), 0)
  into inserted_rows, inserted_units, mapped_rows, mapped_units
  from public.registrations
  where period = p_expected_period;

  return jsonb_build_object(
    'period', to_char(p_expected_period, 'YYYY-MM'),
    'rows', inserted_rows,
    'units', inserted_units,
    'mapped_rows', mapped_rows,
    'mapped_units', mapped_units,
    'mapped_unit_pct', case when inserted_units = 0 then 0
      else round(100.0 * mapped_units / inserted_units, 1) end,
    'source_url', p_snapshot_url
  );
end
$$;

revoke all on function public.ingest_registration_snapshot(text, date, text) from public, anon, authenticated;
grant execute on function public.ingest_registration_snapshot(text, date, text) to service_role;

-- Private serving projections.  These remain service-role only; member access
-- must go through the entitlement-aware server surface rather than public RLS.
create or replace view public.registration_analytics_coverage
with (security_invoker = true)
as
select r.period,
       count(*)::bigint as raw_rows,
       sum(r.registrations)::bigint as total_registrations,
       count(*) filter (where r.model_id is not null)::bigint as mapped_rows,
       sum(r.registrations) filter (where r.model_id is not null)::bigint as mapped_registrations,
       round(
         100.0 * coalesce(sum(r.registrations) filter (where r.model_id is not null), 0)
         / nullif(sum(r.registrations), 0), 1
       ) as mapped_unit_pct
from public.registrations r
group by r.period;

create or replace view public.registration_monthly_model
with (security_invoker = true)
as
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
       sum(r.registrations)::bigint as registrations,
       count(*)::bigint as source_rows,
       bool_and(r.model_id is not null) as canonically_mapped
from public.registrations r
left join public.models m on m.id = r.model_id
left join public.registration_brand_aliases rba
  on rba.raw_brand_norm = public.normalize_registration_token(r.brand_name_raw)
left join public.brands b on b.id = coalesce(m.brand_id, rba.brand_id)
group by r.period, entity_key, r.model_id, b.slug, b.name_en,
         r.brand_name_raw, r.model_name_raw, m.name_en, m.segment, m.body_type, m.powertrains;

create or replace view public.registration_monthly_brand
with (security_invoker = true)
as
select r.period,
       coalesce(b.slug, public.normalize_registration_token(r.brand_name_raw)) as brand_key,
       coalesce(b.name_en, r.brand_name_raw) as brand_name,
       sum(r.registrations)::bigint as registrations
from public.registrations r
left join public.registration_brand_aliases rba
  on rba.raw_brand_norm = public.normalize_registration_token(r.brand_name_raw)
left join public.brands b on b.id = rba.brand_id
group by r.period, brand_key, brand_name;

create or replace view public.registration_model_mom
with (security_invoker = true)
as
with base as (
  select *, lag(registrations) over (partition by entity_key order by period) as previous_registrations
  from public.registration_monthly_model
)
select *,
       registrations - previous_registrations as mom_delta,
       round(100.0 * (registrations - previous_registrations) /
             nullif(previous_registrations, 0), 1) as mom_pct
from base;

revoke all on table public.registration_analytics_coverage from anon, authenticated;
revoke all on table public.registration_monthly_model from anon, authenticated;
revoke all on table public.registration_monthly_brand from anon, authenticated;
revoke all on table public.registration_model_mom from anon, authenticated;
grant select on table public.registration_analytics_coverage to service_role;
grant select on table public.registration_monthly_model to service_role;
grant select on table public.registration_monthly_brand to service_role;
grant select on table public.registration_model_mom to service_role;

comment on table public.registration_brand_aliases is
  'Reviewed registration-only brand crosswalk. Separate from Vehicle Master / MarketTrim.';
comment on table public.registration_model_aliases is
  'Reviewed registration-only model aliases. A missing/ambiguous match must remain NULL rather than guessed.';
comment on view public.registration_analytics_coverage is
  'Private per-month mapping coverage; dashboards should surface this when canonical dimensions are used.';
