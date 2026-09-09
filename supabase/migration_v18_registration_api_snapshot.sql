-- Extend the private registration loader to the stronger canonical DLT API
-- export snapshots.  API files carry one extra source-type column; the first
-- five columns are the same period/class/brand/model/units fact grain.

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
  api_snapshot boolean;
  expected_commas integer;
begin
  if p_expected_period <> date_trunc('month', p_expected_period)::date then
    raise exception 'expected period must be the first day of the month';
  end if;

  api_snapshot := p_snapshot_url ~ '/data/raw/dlt_[0-9]{4}-[0-9]{2}[.]csv$';
  if p_snapshot_url !~ '^https://raw[.]githubusercontent[.]com/smgkikikiki-cloud/TDR/main/automotive/vehicle_master/data/(raw/dlt_|raw_pivot/(long|pivot)_)[0-9]{4}-[0-9]{2}[.]csv$' then
    raise exception 'snapshot URL is outside the canonical TDR registration snapshot paths';
  end if;
  expected_commas := case when api_snapshot then 5 else 4 end;

  select (extensions.http_get(p_snapshot_url)).content::text into body;
  if body is null or body = '' then
    raise exception 'empty registration snapshot';
  end if;

  with lines as (
    select trim(both E'\r' from line) as line
    from regexp_split_to_table(body, E'\n') as line
    where line <> ''
      and line not like '%period,registration_type,brand,model,units%'
      and line not like '%เดือน,ประเภท,ยี่ห้อ,แบบรถ,จำนวน,%'
  )
  select count(*) into malformed
  from lines
  where length(line) - length(replace(line, ',', '')) <> expected_commas
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
      case when api_snapshot
        then 'Canonical DLT API export used by the private TDR registration analytics pipeline.'
        else 'Canonical repository snapshot used by the private TDR registration analytics pipeline.'
      end
    )
    returning id into source_uuid;
  end if;

  delete from public.registrations where period = p_expected_period;

  with lines as (
    select trim(both E'\r' from line) as line
    from regexp_split_to_table(body, E'\n') as line
    where line <> ''
      and line not like '%period,registration_type,brand,model,units%'
      and line not like '%เดือน,ประเภท,ยี่ห้อ,แบบรถ,จำนวน,%'
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
    'source_kind', case when api_snapshot then 'dlt-api-export' else 'repository-pivot' end,
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

revoke all on function public.ingest_registration_snapshot(text, date, text)
  from public, anon, authenticated;
grant execute on function public.ingest_registration_snapshot(text, date, text)
  to service_role;
