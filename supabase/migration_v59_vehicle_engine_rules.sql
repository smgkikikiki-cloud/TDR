-- Vehicle DB v3, Phase 0 step 4: port the engine rules (docs/vehicle-db/VEHICLE_DB_V3.md §2.4).
--
-- A parity port of the rules automotive/vehicle_master enforces today
-- (docs/vehicle-db/ENGINE_INVENTORY.md §2–§4), onto the v57 master tables, so
-- the master stays valid once the release engine is no longer the validator.
-- The full rule-by-rule map, with what is deferred and why, is
-- docs/vehicle-db/ENGINE_RULES.md.
--
-- Placement:
--   * CHECK constraints: invariants of one row (Model/Variant/MarketTrim.validate,
--     PriceRecord.validate, Campaign.validate, the registry-independent SpecFact
--     rules, ECOStickerSpec.validate, the sidecar row rules, id composition).
--   * Triggers: rules across rows that must not be bypassable (same-start price
--     and spec conflicts, append-only prices, immutable ids, base-catalog-only
--     references, approved-set vs HISTORICAL exclusivity, the ECO cross-check,
--     variant rules that depend on the model's `incomplete` flag).
--   * lib/vehicle-engine/*.ts: rules that need the comparable-spec registry
--     (which v3 §3 keeps in lib/spec-field-registry.ts), the facet resolution
--     chain, write planning, or the §5 computations.
--
-- Nothing here changes what the current_* views serve, adds v3 Phase 1
-- semantics (authority, observations, change log, ABSENT/tombstones, soft-delete
-- redesign), or touches the old write path (Phase 0 step 5). Where an old rule
-- conflicts with a later v3 rule the old rule is kept and the conflict is listed
-- in ENGINE_RULES.md (e.g. UNKNOWN / NOT_AVAILABLE fact states stay valid).
--
-- Existing rows: every CHECK is validated by Postgres as it is added, and the
-- gate at the end runs vehicle_engine_rules_check() so the trigger-enforced
-- rules are proven against the existing rows too. Any violation rolls the whole
-- migration back.

begin;

-- Re-runnable: drop this migration's foreign keys first, because they depend
-- on the unique keys it (re)creates below.
alter table public.vehicle_trims
  drop constraint if exists vm_rule_trim_variant,
  drop constraint if exists vm_rule_trim_generation_model;
alter table public.vehicle_variants drop constraint if exists vm_rule_variant_generation_model;
alter table public.vehicle_price_ledger
  drop constraint if exists vm_rule_price_option,
  drop constraint if exists vm_rule_price_campaign;

-- --------------------------------------------------------------------------
-- Helpers (immutable, used by the CHECK constraints)
-- --------------------------------------------------------------------------

-- Python truthiness of a JSON value: null, false, 0, "", [] and {} are falsy.
create or replace function public._vm_truthy(v jsonb)
returns boolean language sql immutable parallel safe as $$
  select case
    when v is null then false
    when jsonb_typeof(v) = 'null' then false
    when jsonb_typeof(v) = 'boolean' then v = 'true'::jsonb
    when jsonb_typeof(v) = 'number' then (v #>> '{}')::numeric <> 0
    when jsonb_typeof(v) = 'string' then (v #>> '{}') <> ''
    when jsonb_typeof(v) = 'array' then jsonb_array_length(v) > 0
    else v <> '{}'::jsonb
  end
$$;

-- A JSON value that is absent or JSON null (Python `is None`).
create or replace function public._vm_none(v jsonb)
returns boolean language sql immutable parallel safe as $$
  select v is null or jsonb_typeof(v) = 'null'
$$;

-- Numeric value of a JSON number, else null.
create or replace function public._vm_num(v jsonb)
returns numeric language sql immutable parallel safe as $$
  select case when jsonb_typeof(v) = 'number' then (v #>> '{}')::numeric end
$$;

-- Python `type(v) is int` for a JSON number: no fraction, no exponent, not bool.
create or replace function public._vm_is_int(v jsonb)
returns boolean language sql immutable parallel safe as $$
  select jsonb_typeof(v) = 'number' and (v #>> '{}') ~ '^-?[0-9]+$'
$$;

-- taxonomy.market_position_for_price (PRICE_BAND_EDGES).
create or replace function public._vm_price_band(p numeric)
returns text language sql immutable parallel safe as $$
  select case when p is null then 'UNKNOWN'
              when p < 500000 then 'ENTRY' when p < 1000000 then 'VOLUME'
              when p < 1800000 then 'UPPER' else 'LUXURY' end
$$;

-- One canonical id segment as vehreg.normalize.slug can produce it: runs of
-- [0-9a-z] and the Thai block joined by single underscores, with Thai combining
-- marks removed. This checks the shape only; deriving a segment from a name
-- stays in Python (one implementation, ENGINE_INVENTORY §2).
create or replace function public._vm_slug_segment(p text)
returns boolean language sql immutable parallel safe as $$
  select coalesce(p ~ '^[0-9a-z฀-๿]+(_[0-9a-z฀-๿]+)*$' and p !~ '[ัิ-ฺ็-๎]', false)
$$;

-- `parent || sep || <slug segment>`.
create or replace function public._vm_child_id(id text, parent text, sep text)
returns boolean language sql immutable parallel safe as $$
  select coalesce(left(id, length(parent) + length(sep)) = parent || sep
                  and public._vm_slug_segment(substr(id, length(parent) + length(sep) + 1)), false)
$$;

-- reviewer/actor must be a named human (current_retail / retail_lifecycle_review /
-- model_operational_state _validated_reviewer).
create or replace function public._vm_human(reviewer text)
returns boolean language sql immutable parallel safe as $$
  select coalesce(btrim(reviewer) <> ''
                  and lower(btrim(reviewer)) not in ('system', 'agent', 'agent-proposed'), false)
$$;

-- Empty, or an http(s) URL.
create or replace function public._vm_http_or_empty(ref text)
returns boolean language sql immutable parallel safe as $$
  select ref = '' or ref ~ '^https?://'
$$;

-- Every entry non-blank and none repeated (current_retail trim_ids).
create or replace function public._vm_distinct_nonblank(a text[])
returns boolean language sql immutable parallel safe as $$
  select cardinality(a) = (select count(distinct x) from unnest(a) x)
     and not exists (select 1 from unnest(a) x where btrim(x) = '')
$$;

-- `YYYY-MM-DD` string or JSON null (pricing._iso_date / comparable_specs._iso_date).
create or replace function public._vm_iso_or_null(v jsonb)
returns boolean language plpgsql immutable parallel safe as $$
begin
  if public._vm_none(v) or v = '""'::jsonb then
    return true;
  end if;
  if jsonb_typeof(v) <> 'string' or (v #>> '{}') !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' then
    return false;
  end if;
  perform (v #>> '{}')::date;
  return true;
exception when others then
  return false;
end;
$$;

create or replace function public._vm_date(v jsonb)
returns date language sql immutable parallel safe as $$
  select case when public._vm_iso_or_null(v) and jsonb_typeof(v) = 'string' and (v #>> '{}') <> ''
              then (v #>> '{}')::date end
$$;

-- --------------------------------------------------------------------------
-- B. Taxonomy and entities (vehreg/taxonomy.py, vehreg/entities.py)
-- --------------------------------------------------------------------------

-- Model.validate + the per-model parts of Catalog.validate.
create or replace function public._vm_model_problems(p jsonb)
returns text[] language plpgsql immutable parallel safe as $$
declare
  out text[] := '{}';
  body text := p->>'body_type';
  cab text := p->>'cab_type';
  reg text := p->>'registration_type';
  expected text;
begin
  if body is null or body not in ('HATCHBACK','SEDAN','CROSSOVER','PPV','OFFROAD','COUPE','MPV',
                                  'PICKUP','WAGON','VAN','TRUCK','OTHER') then
    out := out || format('unknown body_type %s', coalesce(body, 'null'));
  end if;
  if cab is null or cab not in ('DOUBLE_CAB','SINGLE_SMART','SMART_CAB','SINGLE_CAB','NOT_APPLICABLE') then
    out := out || format('unknown cab_type %s', coalesce(cab, 'null'));
  end if;
  if reg is null or reg not in ('RY1','RY2','RY3','RY12','OTHER') then
    out := out || format('unknown registration_type %s', coalesce(reg, 'null'));
  end if;
  if coalesce(p->>'market_scope', '') not in ('CORE','NICHE','GREY','COMMERCIAL','UNKNOWN') then
    out := out || format('unknown market_scope %s', coalesce(p->>'market_scope', 'null'));
  end if;
  if coalesce(p->>'retail_status', '') not in ('CURRENT','HISTORICAL','UNVERIFIED') then
    out := out || format('unknown retail_status %s', coalesce(p->>'retail_status', 'null'));
  end if;
  if coalesce(btrim(p->>'name_en'), '') = '' then
    out := out || 'name_en is required'::text;
  end if;
  -- taxonomy.check_registration
  expected := case when body = 'PICKUP' then case when cab = 'DOUBLE_CAB' then 'RY1' else 'RY3' end
                   when body = 'TRUCK' then 'RY3' else 'RY1' end;
  if reg is distinct from 'RY2' and body not in ('VAN','TRUCK') and reg is distinct from expected then
    out := out || format('%s/%s is registered %s, not %s', body, cab, expected, reg);
  end if;
  if body = 'PICKUP' and cab = 'NOT_APPLICABLE' then
    out := out || 'a pickup model must name its cab_type'::text;
  end if;
  if body is distinct from 'PICKUP' and cab is distinct from 'NOT_APPLICABLE' then
    out := out || format('cab_type is only valid for PICKUP, got %s', body);
  end if;
  if p->>'retail_status' = 'CURRENT'
     and not (public._vm_truthy(p->'retail_checked_at') and public._vm_truthy(p->'retail_source')) then
    out := out || 'retail_status CURRENT needs retail_source and retail_checked_at'::text;
  end if;
  -- Catalog.validate: a model that does not declare itself incomplete must
  -- have a real body type.
  if not public._vm_truthy(p->'incomplete') and body = 'OTHER' then
    out := out || 'body_type not set'::text;
  end if;
  return out;
end;
$$;

-- Variant.validate (the caller skips variants of `incomplete` models, exactly
-- as Catalog.validate does) plus the loader's facet parsing.
create or replace function public._vm_variant_problems(p jsonb)
returns text[] language plpgsql immutable parallel safe as $$
declare
  out text[] := '{}';
  pt text := p->>'powertrain';
  it text := p->>'import_type';
  country text;
  low numeric; high numeric; price numeric;
begin
  if pt is null or pt not in ('ICE','HEV','PHEV','REEV','BEV','FCEV','UNKNOWN') then
    out := out || format('unknown powertrain %s', coalesce(pt, 'null'));
  end if;
  if coalesce(p->>'drivetrain', '') not in ('FWD','RWD','AWD','4WD','UNKNOWN') then
    out := out || format('unknown drivetrain %s', coalesce(p->>'drivetrain', 'null'));
  end if;
  if it is null or it not in ('CBU','SKD','CKD','UNKNOWN') then
    out := out || format('unknown import_type %s', coalesce(it, 'null'));
  end if;
  if coalesce(btrim(p->>'name'), '') = '' then
    out := out || 'name is required'::text;
  end if;
  -- taxonomy.check_powertrain, skipped for a declared-incomplete variant
  if not public._vm_truthy(p->'incomplete') then
    if pt = 'BEV' and public._vm_truthy(p->'engine_cc') then
      out := out || 'BEV must not declare engine_cc'::text;
    end if;
    if pt = 'ICE' and public._vm_truthy(p->'battery_kwh') then
      out := out || 'plain ICE must not declare a traction battery'::text;
    end if;
    if pt in ('PHEV','REEV') and not public._vm_truthy(p->'engine_cc') then
      out := out || format('%s needs engine_cc', pt);
    end if;
    if pt in ('BEV','PHEV','REEV') and not public._vm_truthy(p->'battery_kwh') then
      out := out || format('%s needs battery_kwh', pt);
    end if;
  end if;
  -- taxonomy.check_origin (normalize_country: falsy -> UNKNOWN, else strip/upper)
  country := case when not public._vm_truthy(p->'origin_country') then 'UNKNOWN'
                  else upper(btrim(p->>'origin_country')) end;
  if it in ('SKD','CKD') and country <> 'TH' then
    out := out || format('%s means assembled in Thailand, but origin_country=%s', it, country);
  end if;
  -- LOCKED_AT_MODEL
  if jsonb_typeof(p->'overrides') = 'object' and (p->'overrides' ? 'body_type' or p->'overrides' ? 'cab_type') then
    out := out || 'cannot override body_type/cab_type on a variant'::text;
  end if;
  low := case when public._vm_truthy(p->'price_min_thb') then public._vm_num(p->'price_min_thb') end;
  high := case when public._vm_truthy(p->'price_max_thb') then public._vm_num(p->'price_max_thb') end;
  price := case when public._vm_truthy(p->'price_thb') then public._vm_num(p->'price_thb') end;
  if low is not null and high is not null and low > high then
    out := out || format('price_min_thb %s > price_max_thb %s', low, high);
  end if;
  if low is not null and high is not null and public._vm_price_band(low) <> public._vm_price_band(high) then
    out := out || format('folded trims span %s to %s', public._vm_price_band(low), public._vm_price_band(high));
  end if;
  if (low is not null or high is not null) and price is not null
     and not (coalesce(low, 0) <= price and price <= coalesce(high, price)) then
    out := out || 'price_thb is outside price_min_thb..price_max_thb'::text;
  end if;
  return out;
end;
$$;

-- MarketTrim.validate + the loader rules, over the base-catalog row
-- (vehicle_trims.catalog_payload = asdict(MarketTrim)).
create or replace function public._vm_market_trim_problems(p jsonb)
returns text[] language plpgsql immutable parallel safe as $$
declare
  out text[] := '{}';
  f text;
  v jsonb;
begin
  if coalesce(p->>'powertrain', '') not in ('ICE','HEV','PHEV','REEV','BEV','FCEV') then
    out := out || 'powertrain must be exact; UNKNOWN is not valid for MarketTrim'::text;
  end if;
  if coalesce(p->>'drivetrain', '') not in ('FWD','RWD','AWD','4WD','UNKNOWN') then
    out := out || format('unknown drivetrain %s', coalesce(p->>'drivetrain', 'null'));
  end if;
  if coalesce(btrim(p->>'name'), '') = '' then
    out := out || 'name is required'::text;
  end if;
  foreach f in array array['engine_cc','seats','length_mm','width_mm','height_mm','wheelbase_mm'] loop
    v := p->f;
    if not public._vm_none(v) and not (public._vm_is_int(v) and public._vm_num(v) > 0) then
      out := out || format('%s must be a positive finite integer', f);
    end if;
  end loop;
  v := p->'battery_kwh';
  if not public._vm_none(v) and not (jsonb_typeof(v) = 'number' and public._vm_num(v) > 0) then
    out := out || 'battery_kwh must be a positive finite number'::text;
  end if;
  v := p->'price_thb';
  if not public._vm_none(v) and not (jsonb_typeof(v) = 'number' and public._vm_num(v) >= 0) then
    out := out || 'price_thb must be a positive finite number'::text;
  end if;
  if public._vm_is_int(p->'wheelbase_mm') and public._vm_is_int(p->'length_mm')
     and public._vm_num(p->'wheelbase_mm') >= public._vm_num(p->'length_mm') then
    out := out || 'wheelbase_mm must be less than length_mm'::text;
  end if;
  if p->>'powertrain' = 'BEV' and (not public._vm_none(p->'engine_cc') or public._vm_truthy(p->'engine_code')) then
    out := out || 'BEV cannot have a combustion engine'::text;
  end if;
  return out;
end;
$$;

-- Retail overlay / verified-fragment row rules (trim_reconciliation,
-- trim_fragments) for a trim that exists only in that grain.
create or replace function public._vm_overlay_trim_problems(
  canonical_id text, generation_id text, name text, powertrain text, variant_id text,
  source_refs jsonb, specs jsonb)
returns text[] language plpgsql immutable parallel safe as $$
declare
  out text[] := '{}';
  local text := substr(canonical_id, length(generation_id) + length('.trim.') + 1);
  bad int;
begin
  if local !~ '^[a-z0-9][a-z0-9_]*$' then
    out := out || format('overlay local id %s must match ^[a-z0-9][a-z0-9_]*$', local);
  end if;
  if coalesce(btrim(name), '') = '' then
    out := out || 'name is required'::text;
  end if;
  if coalesce(powertrain, '') not in ('ICE','HEV','PHEV','REEV','BEV','FCEV') then
    out := out || 'powertrain must be exact'::text;
  end if;
  if variant_id is not null then
    out := out || 'overlay variant_id must be empty'::text;
  end if;
  if jsonb_typeof(source_refs) <> 'object' or source_refs = '{}'::jsonb then
    out := out || 'source_refs must be a non-empty object'::text;
  else
    select count(*) into bad from jsonb_each(source_refs) e
     where jsonb_typeof(e.value) <> 'array' or jsonb_array_length(e.value) = 0
        or exists (select 1 from jsonb_array_elements(e.value) x
                    where jsonb_typeof(x) <> 'string' or btrim(x #>> '{}') = '');
    if bad > 0 then
      out := out || 'source_refs values must be non-empty string lists'::text;
    end if;
  end if;
  if jsonb_typeof(specs) <> 'object' then
    out := out || 'specs must be an object'::text;
  elsif specs ? 'aliases' and (jsonb_typeof(specs->'aliases') <> 'array'
        or exists (select 1 from jsonb_array_elements(specs->'aliases') x where jsonb_typeof(x) <> 'string')) then
    out := out || 'aliases must be a list of strings'::text;
  end if;
  return out;
end;
$$;

-- --------------------------------------------------------------------------
-- C. Price ledger and campaigns (vehreg/pricing.py)
-- --------------------------------------------------------------------------

-- PriceRecord.validate + PriceLedger.add_payload parsing, over one stored row.
create or replace function public._vm_price_problems(r public.vehicle_price_ledger)
returns text[] language plpgsql immutable parallel safe as $$
declare
  out text[] := '{}';
  p jsonb := r.payload;
  extra text[];
begin
  select array_agg(k order by k) into extra from jsonb_object_keys(p) k
   where k not in ('record_id','trim_id','amount_thb','price_type','effective_from','effective_to',
                   'observed_at','source','source_ref','source_document_id','notes','campaign_id',
                   'option_id','reference_price_thb','retracted_at','retraction_reason','reviewed_by');
  if extra is not null then
    out := out || format('unknown price fields: %s', extra);
  end if;
  if btrim(r.trim_id) = '' then
    out := out || 'trim_id is required'::text;
  end if;
  if r.amount_thb is null or r.amount_thb <= 0 then
    out := out || 'amount_thb must be a positive integer'::text;
  end if;
  if r.source_document_id <> '' and r.source_document_id !~ '^sha256:[0-9a-f]{64}$' then
    out := out || 'source_document_id must be a sha256: hex digest'::text;
  end if;
  if r.reference_price_thb is not null and r.reference_price_thb <= 0 then
    out := out || 'reference_price_thb must be a positive integer'::text;
  end if;
  if r.price_type in ('CAMPAIGN_PRICE','FINANCE_PRICE') and coalesce(r.campaign_id, '') = '' then
    out := out || format('%s requires a campaign_id', r.price_type);
  end if;
  if coalesce(r.option_id, '') <> '' and coalesce(r.campaign_id, '') = '' then
    out := out || 'option_id without campaign_id'::text;
  end if;
  if coalesce(r.campaign_id, '') <> '' and r.price_type not in ('CAMPAIGN_PRICE','FINANCE_PRICE') then
    out := out || format('%s must not belong to a campaign', r.price_type);
  end if;
  if r.retracted_at is not null and r.retraction_reason = '' then
    out := out || 'a retracted price must say why'::text;
  end if;
  if r.price_type = 'LIST_PRICE' and r.effective_from is null and r.observed_at is null then
    out := out || 'LIST_PRICE requires effective_from or observed_at'::text;
  end if;
  if r.effective_from is not null and r.effective_to is not null and r.effective_from > r.effective_to then
    out := out || 'effective_from is after effective_to'::text;
  end if;
  if not (public._vm_iso_or_null(p->'effective_from') and public._vm_iso_or_null(p->'effective_to')
          and public._vm_iso_or_null(p->'observed_at') and public._vm_iso_or_null(p->'retracted_at')) then
    out := out || 'dates must be YYYY-MM-DD'::text;
  end if;
  -- The stored payload is the served row; it may not say anything the columns do not.
  if (p->>'record_id') is distinct from r.record_id
     or (p->>'trim_id') is distinct from r.trim_id
     or public._vm_num(p->'amount_thb') is distinct from r.amount_thb
     or (p->>'price_type') is distinct from r.price_type
     or public._vm_date(p->'effective_from') is distinct from r.effective_from
     or public._vm_date(p->'effective_to') is distinct from r.effective_to
     or public._vm_date(p->'observed_at') is distinct from r.observed_at
     or public._vm_date(p->'retracted_at') is distinct from r.retracted_at
     or nullif(p->>'campaign_id', '') is distinct from r.campaign_id
     or nullif(p->>'option_id', '') is distinct from r.option_id
     or coalesce(p->>'source', '') is distinct from coalesce(r.source, '')
     or coalesce(p->>'source_ref', '') is distinct from coalesce(r.source_ref, '')
     or coalesce(p->>'source_document_id', '') is distinct from r.source_document_id
     or coalesce(p->>'notes', '') is distinct from r.notes
     or public._vm_num(p->'reference_price_thb') is distinct from r.reference_price_thb
     or coalesce(p->>'retraction_reason', '') is distinct from r.retraction_reason
     or coalesce(p->>'reviewed_by', '') is distinct from r.reviewed_by then
    out := out || 'payload disagrees with the row columns'::text;
  end if;
  -- A row is served exactly when it is not retracted (ENGINE_INVENTORY §5.2).
  if r.in_release is distinct from (r.retracted_at is null) then
    out := out || 'in_release must equal "not retracted"'::text;
  end if;
  return out;
end;
$$;

-- Campaign.validate + _parse_campaign / _parse_conditions, over the stored payload.
create or replace function public._vm_campaign_problems(campaign_id text, brand_id text, p jsonb)
returns text[] language plpgsql immutable parallel safe as $$
declare
  out text[] := '{}';
  extra text[];
  o jsonb;
  c jsonb;
  oid text;
  seen text[] := '{}';
  status text;
begin
  if jsonb_typeof(p) <> 'object' then
    return array['campaign must be an object'];
  end if;
  select array_agg(k order by k) into extra from jsonb_object_keys(p) k
   where k not in ('id','brand_id','name','starts','ends','source','source_ref','options',
                   'quota_units','gifts','notes');
  if extra is not null then
    out := out || format('unknown campaign fields: %s', extra);
  end if;
  if coalesce(btrim(p->>'id'), '') = '' then
    out := out || 'campaign id is required'::text;
  end if;
  if (p->>'id') is distinct from campaign_id or (p->>'brand_id') is distinct from brand_id then
    out := out || 'payload id/brand_id disagree with the row'::text;
  end if;
  if coalesce(btrim(p->>'brand_id'), '') = '' then
    out := out || 'brand_id is required'::text;
  end if;
  if not public._vm_none(p->'quota_units') and not (public._vm_is_int(p->'quota_units') and public._vm_num(p->'quota_units') > 0) then
    out := out || 'quota_units must be a positive integer'::text;
  end if;
  if not (public._vm_iso_or_null(p->'starts') and public._vm_iso_or_null(p->'ends')) then
    out := out || 'starts/ends must be YYYY-MM-DD'::text;
  elsif public._vm_date(p->'starts') > public._vm_date(p->'ends') then
    out := out || 'starts is after ends'::text;
  end if;
  if jsonb_typeof(p->'options') is distinct from 'array' then
    out := out || 'campaign options must be an array'::text;
    return out;
  end if;
  if jsonb_array_length(p->'options') = 0 then
    out := out || 'at least one option is required'::text;
  end if;
  for o in select * from jsonb_array_elements(p->'options') loop
    if jsonb_typeof(o) <> 'object' then
      out := out || 'campaign option must be an object'::text;
      continue;
    end if;
    select array_agg(k order by k) into extra from jsonb_object_keys(o) k
     where k not in ('id','label','conditions','starts','ends','status','closed_at','notes');
    if extra is not null then
      out := out || format('unknown option fields: %s', extra);
    end if;
    oid := coalesce(btrim(o->>'id'), '');
    if oid = '' then
      out := out || 'option id is required'::text;
    end if;
    if oid = any(seen) then
      out := out || format('duplicate option %s', oid);
    end if;
    seen := seen || oid;
    status := upper(btrim(coalesce(nullif(o->>'status', ''), 'ACTIVE')));
    if status not in ('ACTIVE','SOLD_OUT','WITHDRAWN','SUPERSEDED') then
      out := out || format('option %s: unknown offer status %s', oid, o->>'status');
    end if;
    if not (public._vm_iso_or_null(o->'starts') and public._vm_iso_or_null(o->'ends')
            and public._vm_iso_or_null(o->'closed_at')) then
      out := out || format('option %s: dates must be YYYY-MM-DD', oid);
    elsif public._vm_date(o->'starts') > public._vm_date(o->'ends') then
      out := out || format('option %s: starts is after ends', oid);
    end if;
    if status <> 'ACTIVE' and not public._vm_truthy(o->'closed_at') then
      out := out || format('option %s: %s must say closed_at', oid, status);
    end if;
    if public._vm_truthy(o->'closed_at') and status = 'ACTIVE' then
      out := out || format('option %s: closed_at needs a closed status', oid);
    end if;
    c := coalesce(o->'conditions', '{}'::jsonb);
    if jsonb_typeof(c) = 'null' then
      c := '{}'::jsonb;
    end if;
    if jsonb_typeof(c) <> 'object' then
      out := out || 'conditions must be an object'::text;
      continue;
    end if;
    select array_agg(k order by k) into extra from jsonb_object_keys(c) k
     where k not in ('booking_from','booking_to','delivery_by','quota_units','finance_required','text');
    if extra is not null then
      out := out || format('unknown condition fields: %s', extra);
    end if;
    if not (public._vm_iso_or_null(c->'booking_from') and public._vm_iso_or_null(c->'booking_to')
            and public._vm_iso_or_null(c->'delivery_by')) then
      out := out || format('option %s: condition dates must be YYYY-MM-DD', oid);
    elsif public._vm_date(c->'booking_from') > public._vm_date(c->'booking_to') then
      out := out || format('option %s: booking_from is after booking_to', oid);
    end if;
    if not public._vm_none(c->'quota_units') and not (public._vm_is_int(c->'quota_units') and public._vm_num(c->'quota_units') > 0) then
      out := out || format('option %s: quota_units must be a positive integer', oid);
    end if;
    if c ? 'finance_required' and jsonb_typeof(c->'finance_required') <> 'boolean' then
      out := out || 'finance_required must be boolean'::text;
    end if;
    if not public._vm_none(p->'quota_units') and not public._vm_none(c->'quota_units') then
      out := out || format('option %s restates the campaign quota; a shared pool is counted once', oid);
    end if;
  end loop;
  return out;
end;
$$;

-- --------------------------------------------------------------------------
-- D. Comparable spec facts (vehreg/comparable_specs.py) -- the rules that do
-- not need the field registry. Registry-dependent rules (field registered,
-- value type/unit, allowed qualifiers, applicable powertrains) are enforced in
-- lib/vehicle-engine/specs.ts, next to lib/spec-field-registry.ts.
-- --------------------------------------------------------------------------

create or replace function public._vm_fact_problems(r public.vehicle_facts)
returns text[] language plpgsql immutable parallel safe as $$
declare
  out text[] := '{}';
  p jsonb := r.payload;
  extra text[];
  value_is_null boolean := r.value is null or jsonb_typeof(r.value) = 'null';
begin
  select array_agg(k order by k) into extra from jsonb_object_keys(p) k
   where k not in ('fact_id','trim_id','field_key','value_state','value','unit','qualifiers',
                   'effective_from','effective_to','observed_at','claim_ids','verification_status',
                   'source','source_ref','source_locator');
  if extra is not null then
    out := out || format('invalid/unknown fact fields: %s', extra);
  end if;
  if btrim(r.fact_id) = '' or btrim(r.trim_id) = '' or btrim(r.field_key) = '' then
    out := out || 'fact_id, trim_id and field_key are required'::text;
  end if;
  -- Money never becomes a comparable spec (PRICE_WORDS).
  if lower(r.field_key || ' ' || r.unit) ~ '(price|msrp|thb|baht|cost|ราคา)' then
    out := out || 'prices belong in PriceLedger, not the spec store'::text;
  end if;
  if r.value_state <> 'KNOWN' and not value_is_null then
    out := out || 'non-KNOWN value_state requires null value'::text;
  end if;
  if r.value_state = 'KNOWN' and value_is_null then
    out := out || 'KNOWN requires a value'::text;
  end if;
  if r.observed_at is null then
    out := out || 'observed_at is required'::text;
  end if;
  if r.fact_id like 'admin:%' then
    if (r.source = '') <> (r.source_ref = '') then
      out := out || 'admin fact source and source_ref must be both present or both absent'::text;
    end if;
  elsif r.source = '' or r.source_ref = '' then
    out := out || 'source and source_ref are required'::text;
  end if;
  if r.effective_from is not null and r.effective_to is not null and r.effective_from > r.effective_to then
    out := out || 'effective_from is after effective_to'::text;
  end if;
  if jsonb_typeof(r.qualifiers) <> 'object'
     or exists (select 1 from jsonb_each(r.qualifiers) e where jsonb_typeof(e.value) <> 'string') then
    out := out || 'qualifiers must be an object of strings'::text;
  end if;
  if not (public._vm_iso_or_null(p->'effective_from') and public._vm_iso_or_null(p->'effective_to')
          and public._vm_iso_or_null(p->'observed_at')) then
    out := out || 'dates must be YYYY-MM-DD'::text;
  end if;
  if (p->>'fact_id') is distinct from r.fact_id or (p->>'trim_id') is distinct from r.trim_id
     or (p->>'field_key') is distinct from r.field_key or (p->>'value_state') is distinct from r.value_state
     or coalesce(p->'value', 'null'::jsonb) is distinct from coalesce(r.value, 'null'::jsonb)
     or coalesce(p->>'unit', '') is distinct from r.unit
     or coalesce(p->'qualifiers', '{}'::jsonb) is distinct from r.qualifiers
     or public._vm_date(p->'effective_from') is distinct from r.effective_from
     or public._vm_date(p->'effective_to') is distinct from r.effective_to
     or public._vm_date(p->'observed_at') is distinct from r.observed_at
     or coalesce(p->'claim_ids', '[]'::jsonb) is distinct from r.claim_ids
     or coalesce(nullif(p->>'verification_status', ''), 'VERIFIED') is distinct from r.verification_status
     or coalesce(p->>'source', '') is distinct from r.source
     or coalesce(p->>'source_ref', '') is distinct from r.source_ref
     or coalesce(p->>'source_locator', '') is distinct from r.source_locator then
    out := out || 'payload disagrees with the row columns'::text;
  end if;
  return out;
end;
$$;

-- --------------------------------------------------------------------------
-- E. ECO homologation evidence (vehreg/homologation.py) -- ECOStickerSpec.validate
-- --------------------------------------------------------------------------

create or replace function public._vm_eco_problems(trim_id text, source_ref text, p jsonb)
returns text[] language plpgsql immutable parallel safe as $$
declare
  out text[] := '{}';
  f text;
  price_keys text[];
begin
  select array_agg(k order by k) into price_keys from jsonb_object_keys(p) k where lower(k) like '%price%';
  if price_keys is not null then
    out := out || format('price fields are not allowed in ECO spec data: %s', price_keys);
  end if;
  if btrim(coalesce(trim_id, '')) = '' then
    out := out || 'trim_id is required'::text;
  end if;
  if btrim(coalesce(source_ref, '')) = '' then
    out := out || 'source_ref is required'::text;
  end if;
  if (p->>'trim_id') is distinct from trim_id or (p->>'source_ref') is distinct from source_ref then
    out := out || 'payload trim_id/source_ref disagree with the row'::text;
  end if;
  if coalesce(p->>'powertrain', '') not in ('ICE','HEV','PHEV','REEV','BEV','FCEV') then
    out := out || 'powertrain must be exact'::text;
  end if;
  foreach f in array array['seats','battery_voltage_v','declared_total_weight_kg','rated_range_km'] loop
    if not public._vm_none(p->f) and not (jsonb_typeof(p->f) = 'number' and public._vm_num(p->f) > 0) then
      out := out || format('%s must be positive', f);
    end if;
  end loop;
  return out;
end;
$$;

-- --------------------------------------------------------------------------
-- Row constraints. Every CHECK is validated against the existing rows here.
-- --------------------------------------------------------------------------

-- A. identity: composed ids, payload identity fields, non-empty names.
alter table public.vehicle_brands
  drop constraint if exists vm_rule_brand_identity,
  add constraint vm_rule_brand_identity check (
    public._vm_slug_segment(canonical_id) and payload->>'id' = canonical_id
    and btrim(name_en) <> '' and payload->>'name_en' = name_en);

alter table public.vehicle_models
  drop constraint if exists vm_rule_model_identity,
  add constraint vm_rule_model_identity check (
    public._vm_child_id(canonical_id, brand_id, '.') and payload->>'id' = canonical_id
    and payload->>'brand_id' = brand_id and payload->>'name_en' = name_en
    and payload->>'body_type' = body_type),
  drop constraint if exists vm_rule_model_validate,
  add constraint vm_rule_model_validate check (public._vm_model_problems(payload) = '{}'),
  drop constraint if exists vm_rule_model_segment,
  add constraint vm_rule_model_segment check (
    segment is null or segment in ('A','B','C','D','E','F','UNKNOWN'));

alter table public.vehicle_generations
  drop constraint if exists vm_rule_generation_identity,
  add constraint vm_rule_generation_identity check (
    public._vm_child_id(canonical_id, model_id, '.') and payload->>'id' = canonical_id
    and payload->>'model_id' = model_id),
  drop constraint if exists vm_rule_generation_segment,
  add constraint vm_rule_generation_segment check (
    segment is null or segment in ('A','B','C','D','E','F','UNKNOWN'));

-- (canonical_id, model_id) is unique because canonical_id is the key; the extra
-- constraint lets variants and trims reference their generation *and* model.
alter table public.vehicle_generations
  drop constraint if exists vm_rule_generation_model_key,
  add constraint vm_rule_generation_model_key unique (canonical_id, model_id);

alter table public.vehicle_variants
  drop constraint if exists vm_rule_variant_identity,
  add constraint vm_rule_variant_identity check (
    public._vm_child_id(canonical_id, generation_id, '.') and payload->>'id' = canonical_id
    and payload->>'generation_id' = generation_id and payload->>'name' = name
    and payload->>'powertrain' = powertrain and payload->>'import_type' = import_type),
  drop constraint if exists vm_rule_variant_generation_model,
  add constraint vm_rule_variant_generation_model foreign key (generation_id, model_id)
    references public.vehicle_generations(canonical_id, model_id),
  drop constraint if exists vm_rule_variant_generation_key,
  add constraint vm_rule_variant_generation_key unique (canonical_id, generation_id);

alter table public.vehicle_trims
  drop constraint if exists vm_rule_trim_identity,
  add constraint vm_rule_trim_identity check (
    public._vm_child_id(canonical_id, generation_id, '.trim.')
    and payload->'specs'->>'id' = canonical_id and payload->'specs'->>'generation_id' = generation_id
    and payload->>'model_id' = model_id and payload->'specs'->>'name' = name
    and payload->'specs'->>'powertrain' = powertrain
    and nullif(payload->'specs'->>'variant_id', '') is not distinct from variant_id
    and (catalog_payload is null or (catalog_payload->>'id' = canonical_id
         and catalog_payload->>'generation_id' = generation_id and catalog_payload->>'name' = name
         and catalog_payload->>'powertrain' = powertrain
         and nullif(catalog_payload->>'variant_id', '') is not distinct from variant_id))),
  drop constraint if exists vm_rule_trim_generation_model,
  add constraint vm_rule_trim_generation_model foreign key (generation_id, model_id)
    references public.vehicle_generations(canonical_id, model_id),
  -- Catalog._resolve_trim_variant_ref: the variant must be under the same generation.
  drop constraint if exists vm_rule_trim_variant,
  add constraint vm_rule_trim_variant foreign key (variant_id, generation_id)
    references public.vehicle_variants(canonical_id, generation_id),
  drop constraint if exists vm_rule_trim_validate,
  add constraint vm_rule_trim_validate check (
    case when catalog_payload is not null
         then public._vm_market_trim_problems(catalog_payload) = '{}'
         else public._vm_overlay_trim_problems(canonical_id, generation_id, name, powertrain,
                variant_id, source_refs, payload->'specs') = '{}' end);

-- C. prices and campaigns
alter table public.vehicle_price_ledger
  drop constraint if exists vm_rule_price_validate,
  add constraint vm_rule_price_validate check (
    public._vm_price_problems(vehicle_price_ledger) = '{}'),
  drop constraint if exists vm_rule_price_campaign,
  add constraint vm_rule_price_campaign foreign key (campaign_id)
    references public.vehicle_campaigns(campaign_id),
  drop constraint if exists vm_rule_price_option,
  add constraint vm_rule_price_option foreign key (campaign_id, option_id)
    references public.vehicle_promotions(campaign_id, option_id);

alter table public.vehicle_campaigns
  drop constraint if exists vm_rule_campaign_validate,
  add constraint vm_rule_campaign_validate check (
    public._vm_campaign_problems(campaign_id, brand_id, payload) = '{}'
    and coalesce(payload->>'name', '') = name
    and public._vm_date(payload->'starts') is not distinct from starts
    and public._vm_date(payload->'ends') is not distinct from ends);

alter table public.vehicle_promotions
  drop constraint if exists vm_rule_promotion_option,
  add constraint vm_rule_promotion_option check (
    payload->>'id' = option_id and (option_status = 'ACTIVE') = (closed_at is null));

-- D. facts
alter table public.vehicle_facts
  drop constraint if exists vm_rule_fact_validate,
  add constraint vm_rule_fact_validate check (public._vm_fact_problems(vehicle_facts) = '{}');

-- E. ECO evidence
alter table public.vehicle_eco_evidence
  drop constraint if exists vm_rule_eco_validate,
  add constraint vm_rule_eco_validate check (public._vm_eco_problems(trim_id, source_ref, payload) = '{}');

-- F. HUMAN sidecars
alter table public.vehicle_current_retail_sets
  drop constraint if exists vm_rule_current_retail_row,
  add constraint vm_rule_current_retail_row check (
    public._vm_human(reviewer) and public._vm_http_or_empty(source_ref)
    and public._vm_distinct_nonblank(trim_ids)
    and payload->>'model_id' = model_id and payload->'trim_ids' = to_jsonb(trim_ids)
    and payload->>'reviewer' = reviewer and payload->>'reviewed_at' = reviewed_at::text);

alter table public.vehicle_trim_lifecycle_decisions
  drop constraint if exists vm_rule_trim_lifecycle_row,
  add constraint vm_rule_trim_lifecycle_row check (
    public._vm_human(reviewer) and public._vm_http_or_empty(source_ref)
    and payload->>'trim_id' = trim_id and payload->>'status' = status
    and payload->>'reviewer' = reviewer and payload->>'reviewed_at' = reviewed_at::text);

alter table public.vehicle_model_operational_states
  drop constraint if exists vm_rule_model_operational_row,
  add constraint vm_rule_model_operational_row check (
    public._vm_human(reviewer) and payload->>'model_id' = model_id and payload->>'status' = status);

-- --------------------------------------------------------------------------
-- Cross-row rules. Each is one function that reports violations, used both by
-- its trigger (scoped to the rows a statement touched) and by
-- vehicle_engine_rules_check() (everything), so the rule exists once.
-- --------------------------------------------------------------------------

-- C. Same-start conflicts (PriceLedger.validate): for every LIST_PRICE start, and
-- every CAMPAIGN/FINANCE start inside one campaign+option scope, the
-- non-retracted rows starting that day and active on it must agree on amount.
create or replace function public._vm_price_conflicts(p_trim_id text default null)
returns table (trim_id text, price_type text, campaign_id text, option_id text, start date, amounts bigint[])
language sql stable set search_path = public, pg_temp as $$
  select p.trim_id, p.price_type,
         case when p.price_type = 'LIST_PRICE' then null else p.campaign_id end,
         case when p.price_type = 'LIST_PRICE' then null else p.option_id end,
         coalesce(p.effective_from, p.observed_at) as start,
         array_agg(distinct p.amount_thb order by p.amount_thb)
    from public.vehicle_price_ledger p
   where p.retracted_at is null
     and (p_trim_id is null or p.trim_id = p_trim_id)
     and coalesce(p.effective_from, p.observed_at) is not null
     and (p.effective_to is null or p.effective_to >= coalesce(p.effective_from, p.observed_at))
     and (p.price_type = 'LIST_PRICE'
          or (p.price_type in ('CAMPAIGN_PRICE','FINANCE_PRICE')
              and coalesce(p.campaign_id, '') <> '' and coalesce(p.option_id, '') <> ''))
   group by 1, 2, 3, 4, 5
  having count(distinct p.amount_thb) > 1
$$;

-- D. Same (trim, field, qualifier context, start) with a different
-- (value_state, value) is a conflict (SpecLedger.validate). The qualifier
-- context drops empty values, which is what spec_conflict_key's
-- `str(qualifiers.get(key, ""))` amounts to once qualifiers are limited to the
-- field's comparison_qualifiers (enforced in lib/vehicle-engine/specs.ts).
-- value::text keeps 5 and 5.0 apart exactly as json.dumps does.
create or replace function public._vm_fact_qualifier_key(q jsonb)
returns jsonb language sql immutable parallel safe as $$
  select coalesce(jsonb_object_agg(e.key, e.value), '{}'::jsonb)
    from jsonb_each_text(coalesce(q, '{}'::jsonb)) e where e.value <> ''
$$;

create or replace function public._vm_fact_conflicts(p_trim_id text default null)
returns table (trim_id text, field_key text, qualifiers jsonb, start date, fact_ids text[])
language sql stable set search_path = public, pg_temp as $$
  select f.trim_id, f.field_key, public._vm_fact_qualifier_key(f.qualifiers),
         coalesce(f.effective_from, f.observed_at),
         array_agg(f.fact_id order by f.fact_id)
    from public.vehicle_facts f
   where p_trim_id is null or f.trim_id = p_trim_id
   group by 1, 2, 3, 4
  having count(distinct f.value_state || ':' || coalesce(f.value::text, 'null')) > 1
$$;

-- Every structural rule that spans rows, as (rule, key, detail). The trigger
-- functions below call this with the keys a statement touched.
create or replace function public._vm_structure_problems(p_key text default null)
returns table (rule text, key text, detail text)
language sql stable set search_path = public, pg_temp as $$
  -- Catalog._add_model: a model needs at least one generation.
  select 'model_has_generation', m.canonical_id, 'model has no generations'
    from public.vehicle_models m
   where (p_key is null or m.canonical_id = p_key)
     and not exists (select 1 from public.vehicle_generations g where g.model_id = m.canonical_id)
  union all
  -- Catalog.validate: a complete model has at least one variant.
  select 'model_has_variant', m.canonical_id, 'no variants'
    from public.vehicle_models m
   where (p_key is null or m.canonical_id = p_key)
     and not public._vm_truthy(m.payload->'incomplete')
     and not exists (select 1 from public.vehicle_variants v where v.model_id = m.canonical_id)
  union all
  -- Catalog.validate: Variant.validate, skipped for variants of incomplete models.
  select 'variant_validate', v.canonical_id, array_to_string(public._vm_variant_problems(v.payload), '; ')
    from public.vehicle_variants v join public.vehicle_models m on m.canonical_id = v.model_id
   where (p_key is null or v.model_id = p_key or v.canonical_id = p_key)
     and not public._vm_truthy(m.payload->'incomplete')
     and public._vm_variant_problems(v.payload) <> '{}'
  union all
  -- Catalog.validate: a trim's powertrain equals its analytical variant's.
  select 'trim_variant_powertrain', t.canonical_id,
         format('powertrain %s does not match analytical variant %s (%s)', t.powertrain, v.canonical_id, v.powertrain)
    from public.vehicle_trims t join public.vehicle_variants v on v.canonical_id = t.variant_id
   where (p_key is null or t.canonical_id = p_key or v.canonical_id = p_key or t.model_id = p_key)
     and v.powertrain <> 'UNKNOWN' and t.powertrain <> v.powertrain
  union all
  -- Prices, facts, ECO evidence and HUMAN decisions attach to base-catalog
  -- trims only (Catalog.trims; overlay trims are invisible to it, §9.5).
  select 'price_on_catalog_trim', p.record_id, format('trim %s is not a base-catalog trim', p.trim_id)
    from public.vehicle_price_ledger p join public.vehicle_trims t on t.canonical_id = p.trim_id
   where (p_key is null or p.trim_id = p_key or p.record_id = p_key) and t.catalog_payload is null
  union all
  select 'fact_on_catalog_trim', f.fact_id, format('trim %s is not a base-catalog trim', f.trim_id)
    from public.vehicle_facts f join public.vehicle_trims t on t.canonical_id = f.trim_id
   where (p_key is null or f.trim_id = p_key or f.fact_id = p_key) and t.catalog_payload is null
  union all
  select 'eco_on_catalog_trim', e.trim_id, 'trim is not a base-catalog trim'
    from public.vehicle_eco_evidence e join public.vehicle_trims t on t.canonical_id = e.trim_id
   where (p_key is null or e.trim_id = p_key) and t.catalog_payload is null
  union all
  select 'lifecycle_on_catalog_trim', d.trim_id, 'trim is not a base-catalog trim'
    from public.vehicle_trim_lifecycle_decisions d join public.vehicle_trims t on t.canonical_id = d.trim_id
   where (p_key is null or d.trim_id = p_key) and t.catalog_payload is null
  union all
  -- ECOStickerSpecStore.validate_against_catalog
  select 'eco_cross_check', e.trim_id, x.problem
    from public.vehicle_eco_evidence e
    join public.vehicle_trims t on t.canonical_id = e.trim_id and t.catalog_payload is not null
    cross join lateral (
      select 'ECO source_ref is not attached to MarketTrim' as problem
       where not coalesce((t.catalog_payload->'source_refs'->'ecosticker') ? e.source_ref, false)
      union all
      select format('ECO powertrain %s != MarketTrim %s', e.payload->>'powertrain', t.catalog_payload->>'powertrain')
       where (e.payload->>'powertrain') is distinct from (t.catalog_payload->>'powertrain')
      union all
      select format('ECO seats %s != MarketTrim %s', e.payload->'seats', t.catalog_payload->'seats')
       where not public._vm_none(e.payload->'seats') and not public._vm_none(t.catalog_payload->'seats')
         and public._vm_num(e.payload->'seats') is distinct from public._vm_num(t.catalog_payload->'seats')
      union all
      select format('ECO tyre %s != %s %s', e.payload->>'tire_size', side, tyre)
        from (values ('front', t.catalog_payload->>'tire_front'), ('rear', t.catalog_payload->>'tire_rear')) s(side, tyre)
       where coalesce(e.payload->>'tire_size', '') <> ''
         and upper(replace(coalesce(tyre, ''), ' ', '')) <> ''
         and upper(replace(e.payload->>'tire_size', ' ', '')) <> upper(replace(tyre, ' ', ''))
    ) x
   where p_key is null or e.trim_id = p_key
  union all
  -- current_retail.validate_current_retail_sets: every approved id is a
  -- base-catalog trim of that model.
  select 'current_retail_member', c.model_id, format('MarketTrim %s does not belong to this model or is not in the base catalog', x)
    from public.vehicle_current_retail_sets c cross join lateral unnest(c.trim_ids) x
   where (p_key is null or c.model_id = p_key or x = p_key)
     and not exists (select 1 from public.vehicle_trims t where t.canonical_id = x
                       and t.model_id = c.model_id and t.catalog_payload is not null)
  union all
  -- Campaign storage: vehicle_promotions holds exactly the campaign's options.
  select 'campaign_options', c.campaign_id, 'vehicle_promotions rows differ from the campaign options'
    from public.vehicle_campaigns c
   where (p_key is null or c.campaign_id = p_key)
     and (select coalesce(array_agg(o->>'id' order by o->>'id'), '{}') from jsonb_array_elements(c.payload->'options') o)
         is distinct from
         (select coalesce(array_agg(pr.option_id order by pr.option_id), '{}') from public.vehicle_promotions pr
           where pr.campaign_id = c.campaign_id)
$$;

-- --------------------------------------------------------------------------
-- Triggers
-- --------------------------------------------------------------------------

-- A. Existing ids never change (ENGINE_INVENTORY §2; v3 §2.2 / §3).
create or replace function public._vm_freeze_keys()
returns trigger language plpgsql set search_path = public, pg_temp as $$
declare
  col text;
begin
  foreach col in array tg_argv loop
    if (to_jsonb(new) -> col) is distinct from (to_jsonb(old) -> col) then
      raise exception using errcode = 'P0001',
        message = format('%s.%s is immutable: %s cannot become %s', tg_table_name, col,
                         to_jsonb(old) ->> col, to_jsonb(new) ->> col);
    end if;
  end loop;
  return new;
end;
$$;

drop trigger if exists vm_rule_freeze_ids on public.vehicle_brands;
create trigger vm_rule_freeze_ids before update on public.vehicle_brands
  for each row execute function public._vm_freeze_keys('canonical_id');
drop trigger if exists vm_rule_freeze_ids on public.vehicle_models;
create trigger vm_rule_freeze_ids before update on public.vehicle_models
  for each row execute function public._vm_freeze_keys('canonical_id', 'brand_id');
drop trigger if exists vm_rule_freeze_ids on public.vehicle_generations;
create trigger vm_rule_freeze_ids before update on public.vehicle_generations
  for each row execute function public._vm_freeze_keys('canonical_id', 'model_id');
drop trigger if exists vm_rule_freeze_ids on public.vehicle_variants;
create trigger vm_rule_freeze_ids before update on public.vehicle_variants
  for each row execute function public._vm_freeze_keys('canonical_id', 'generation_id', 'model_id');
drop trigger if exists vm_rule_freeze_ids on public.vehicle_trims;
create trigger vm_rule_freeze_ids before update on public.vehicle_trims
  for each row execute function public._vm_freeze_keys('canonical_id', 'generation_id', 'model_id');
-- fact_id only: APPEND_SPEC revises a fact in place under its id (§9.8).
drop trigger if exists vm_rule_freeze_ids on public.vehicle_facts;
create trigger vm_rule_freeze_ids before update on public.vehicle_facts
  for each row execute function public._vm_freeze_keys('fact_id');
drop trigger if exists vm_rule_freeze_ids on public.vehicle_campaigns;
create trigger vm_rule_freeze_ids before update on public.vehicle_campaigns
  for each row execute function public._vm_freeze_keys('campaign_id', 'brand_id');
drop trigger if exists vm_rule_freeze_ids on public.vehicle_promotions;
create trigger vm_rule_freeze_ids before update on public.vehicle_promotions
  for each row execute function public._vm_freeze_keys('campaign_id', 'option_id');
drop trigger if exists vm_rule_freeze_ids on public.vehicle_eco_evidence;
create trigger vm_rule_freeze_ids before update on public.vehicle_eco_evidence
  for each row execute function public._vm_freeze_keys('trim_id');
drop trigger if exists vm_rule_freeze_ids on public.vehicle_current_retail_sets;
create trigger vm_rule_freeze_ids before update on public.vehicle_current_retail_sets
  for each row execute function public._vm_freeze_keys('model_id');
drop trigger if exists vm_rule_freeze_ids on public.vehicle_trim_lifecycle_decisions;
create trigger vm_rule_freeze_ids before update on public.vehicle_trim_lifecycle_decisions
  for each row execute function public._vm_freeze_keys('trim_id');
drop trigger if exists vm_rule_freeze_ids on public.vehicle_model_operational_states;
create trigger vm_rule_freeze_ids before update on public.vehicle_model_operational_states
  for each row execute function public._vm_freeze_keys('model_id');

-- C. The price ledger is append-only. An existing row may only be closed
-- (effective_to), superseded (effective_to), or retracted (retracted_at,
-- retraction_reason), with reviewed_by/notes recording who and why
-- (product.correct_price / close_price). A retraction is never undone and no
-- row is ever deleted.
create or replace function public._vm_price_append_only()
returns trigger language plpgsql set search_path = public, pg_temp as $$
declare
  mutable text[] := array['effective_to','retracted_at','retraction_reason','reviewed_by','notes','in_release','payload'];
  mutable_payload text[] := array['effective_to','retracted_at','retraction_reason','reviewed_by','notes'];
  changed text[];
begin
  if tg_op = 'DELETE' then
    raise exception using errcode = 'P0001',
      message = format('vehicle_price_ledger is append-only: price %s cannot be deleted', old.record_id),
      hint = 'retract it (retracted_at + retraction_reason) or close it (effective_to) instead';
  end if;
  select array_agg(n.key order by n.key) into changed
    from jsonb_each(to_jsonb(new)) n
    join jsonb_each(to_jsonb(old)) o on o.key = n.key
   where n.value is distinct from o.value and not (n.key = any(mutable));
  if changed is not null then
    raise exception using errcode = 'P0001',
      message = format('vehicle_price_ledger is append-only: %s of price %s cannot change', changed, old.record_id),
      hint = 'append a new row and close or retract this one';
  end if;
  if (new.payload - mutable_payload) is distinct from (old.payload - mutable_payload) then
    raise exception using errcode = 'P0001',
      message = format('vehicle_price_ledger is append-only: payload of price %s may only change %s',
                       old.record_id, mutable_payload);
  end if;
  if old.retracted_at is not null and new.retracted_at is distinct from old.retracted_at then
    raise exception using errcode = 'P0001',
      message = format('price %s was retracted on %s; a retraction is never undone', old.record_id, old.retracted_at);
  end if;
  return new;
end;
$$;

drop trigger if exists vm_rule_price_append_only on public.vehicle_price_ledger;
create trigger vm_rule_price_append_only before update or delete on public.vehicle_price_ledger
  for each row execute function public._vm_price_append_only();

-- D. Spec facts are never deleted (there is no delete path in the engine; a
-- revision under the same fact_id is how APPEND_SPEC corrects one).
create or replace function public._vm_fact_no_delete()
returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  raise exception using errcode = 'P0001',
    message = format('vehicle_facts rows are not deleted: %s', old.fact_id),
    hint = 'revise the fact under the same fact_id';
end;
$$;

drop trigger if exists vm_rule_fact_no_delete on public.vehicle_facts;
create trigger vm_rule_fact_no_delete before delete on public.vehicle_facts
  for each row execute function public._vm_fact_no_delete();

-- Conflict and structure checks run at commit (deferred), because the engine
-- validates a whole write: a same-day price replacement retracts the old row
-- and appends the new one, a model arrives with its generations and variants.
create or replace function public._vm_check_price_conflicts()
returns trigger language plpgsql set search_path = public, pg_temp as $$
declare
  c record;
begin
  for c in select * from public._vm_price_conflicts(new.trim_id) loop
    raise exception using errcode = 'P0001',
      message = case when c.price_type = 'LIST_PRICE'
        then format('%s: conflicting LIST_PRICE at %s; review required', c.trim_id, c.start)
        else format('%s %s %s/%s: conflicting canonical prices at %s; review required',
                    c.trim_id, c.price_type, c.campaign_id, c.option_id, c.start) end,
      detail = format('amounts %s', c.amounts);
  end loop;
  return null;
end;
$$;

drop trigger if exists vm_rule_price_conflicts on public.vehicle_price_ledger;
create constraint trigger vm_rule_price_conflicts after insert or update on public.vehicle_price_ledger
  deferrable initially deferred for each row execute function public._vm_check_price_conflicts();

create or replace function public._vm_check_fact_conflicts()
returns trigger language plpgsql set search_path = public, pg_temp as $$
declare
  c record;
begin
  for c in select * from public._vm_fact_conflicts(new.trim_id) loop
    raise exception using errcode = 'P0001',
      message = format('conflicting comparable spec facts at (%s, %s, %s, %s)',
                       c.trim_id, c.field_key, c.qualifiers, c.start),
      detail = format('facts %s', c.fact_ids);
  end loop;
  return null;
end;
$$;

drop trigger if exists vm_rule_fact_conflicts on public.vehicle_facts;
create constraint trigger vm_rule_fact_conflicts after insert or update on public.vehicle_facts
  deferrable initially deferred for each row execute function public._vm_check_fact_conflicts();

-- One function for every structural trigger; TG_ARGV names which columns of
-- the touched row (old and new) identify what to re-check.
create or replace function public._vm_check_structure()
returns trigger language plpgsql set search_path = public, pg_temp as $$
declare
  col text;
  k text;
  keys text[] := '{}';
  p record;
begin
  foreach col in array tg_argv loop
    if tg_op <> 'DELETE' then
      k := to_jsonb(new) ->> col;
      if k is not null then keys := keys || k; end if;
    end if;
    if tg_op <> 'INSERT' then
      k := to_jsonb(old) ->> col;
      if k is not null then keys := keys || k; end if;
    end if;
  end loop;
  -- current_retail_sets keys are arrays of trims too
  if tg_table_name = 'vehicle_current_retail_sets' and tg_op <> 'DELETE' then
    keys := keys || new.trim_ids;
  end if;
  foreach k in array keys loop
    for p in select * from public._vm_structure_problems(k) loop
      raise exception using errcode = 'P0001',
        message = format('engine rule %s violated for %s: %s', p.rule, p.key, p.detail);
    end loop;
  end loop;
  return null;
end;
$$;

-- F. Approved current-retail set vs HUMAN HISTORICAL decision. These are
-- write-time rules in the engine, not a state invariant:
--   * replace_current_retail_set refuses a set that contains a trim carrying an
--     unreopened HISTORICAL decision;
--   * retail_lifecycle_review._upsert refuses a HISTORICAL decision for a member
--     of the approved set when the parent model is not CURRENT (with a CURRENT
--     parent the engine accepts it and the approved set keeps the trim CURRENT).
-- Checked at commit, against the state the whole write leaves.
create or replace function public._vm_check_retail_decisions()
returns trigger language plpgsql set search_path = public, pg_temp as $$
declare
  t text;
begin
  if tg_table_name = 'vehicle_current_retail_sets' then
    select x into t from unnest(new.trim_ids) x
      join public.vehicle_trim_lifecycle_decisions d on d.trim_id = x and d.status = 'HISTORICAL'
     order by x limit 1;
    if t is not null then
      raise exception using errcode = 'P0001',
        message = format('current_retail %s: MarketTrim %s still carries an unreopened HUMAN historical disposition', new.model_id, t),
        hint = 'reopen the trim lifecycle decision first';
    end if;
  elsif new.status = 'HISTORICAL' and exists (
      select 1 from public.vehicle_trims tr
        join public.vehicle_models m on m.canonical_id = tr.model_id
        join public.vehicle_current_retail_sets c on c.model_id = tr.model_id
       where tr.canonical_id = new.trim_id and new.trim_id = any(c.trim_ids)
         and coalesce(upper(btrim(m.payload->>'retail_status')), 'UNVERIFIED') <> 'CURRENT') then
    raise exception using errcode = 'P0001',
      message = format('trim %s is a member of the approved current-retail set; cannot record a contradictory historical disposition', new.trim_id);
  end if;
  return null;
end;
$$;

drop trigger if exists vm_rule_retail_decisions on public.vehicle_current_retail_sets;
create constraint trigger vm_rule_retail_decisions after insert or update on public.vehicle_current_retail_sets
  deferrable initially deferred for each row execute function public._vm_check_retail_decisions();
drop trigger if exists vm_rule_retail_decisions on public.vehicle_trim_lifecycle_decisions;
create constraint trigger vm_rule_retail_decisions after insert or update on public.vehicle_trim_lifecycle_decisions
  deferrable initially deferred for each row execute function public._vm_check_retail_decisions();

drop trigger if exists vm_rule_structure on public.vehicle_models;
create constraint trigger vm_rule_structure after insert or update on public.vehicle_models
  deferrable initially deferred for each row execute function public._vm_check_structure('canonical_id');
drop trigger if exists vm_rule_structure on public.vehicle_generations;
create constraint trigger vm_rule_structure after insert or update or delete on public.vehicle_generations
  deferrable initially deferred for each row execute function public._vm_check_structure('model_id');
drop trigger if exists vm_rule_structure on public.vehicle_variants;
create constraint trigger vm_rule_structure after insert or update or delete on public.vehicle_variants
  deferrable initially deferred for each row execute function public._vm_check_structure('canonical_id', 'model_id');
drop trigger if exists vm_rule_structure on public.vehicle_trims;
create constraint trigger vm_rule_structure after insert or update or delete on public.vehicle_trims
  deferrable initially deferred for each row execute function public._vm_check_structure('canonical_id', 'model_id');
drop trigger if exists vm_rule_structure on public.vehicle_price_ledger;
create constraint trigger vm_rule_structure after insert or update on public.vehicle_price_ledger
  deferrable initially deferred for each row execute function public._vm_check_structure('record_id');
drop trigger if exists vm_rule_structure on public.vehicle_facts;
create constraint trigger vm_rule_structure after insert or update on public.vehicle_facts
  deferrable initially deferred for each row execute function public._vm_check_structure('fact_id');
drop trigger if exists vm_rule_structure on public.vehicle_eco_evidence;
create constraint trigger vm_rule_structure after insert or update on public.vehicle_eco_evidence
  deferrable initially deferred for each row execute function public._vm_check_structure('trim_id');
drop trigger if exists vm_rule_structure on public.vehicle_current_retail_sets;
create constraint trigger vm_rule_structure after insert or update on public.vehicle_current_retail_sets
  deferrable initially deferred for each row execute function public._vm_check_structure('model_id');
drop trigger if exists vm_rule_structure on public.vehicle_trim_lifecycle_decisions;
create constraint trigger vm_rule_structure after insert or update on public.vehicle_trim_lifecycle_decisions
  deferrable initially deferred for each row execute function public._vm_check_structure('trim_id');
drop trigger if exists vm_rule_structure on public.vehicle_campaigns;
create constraint trigger vm_rule_structure after insert or update on public.vehicle_campaigns
  deferrable initially deferred for each row execute function public._vm_check_structure('campaign_id');
drop trigger if exists vm_rule_structure on public.vehicle_promotions;
create constraint trigger vm_rule_structure after insert or update or delete on public.vehicle_promotions
  deferrable initially deferred for each row execute function public._vm_check_structure('campaign_id');

-- --------------------------------------------------------------------------
-- Report: every rule over every row. Read-only; service_role only.
-- --------------------------------------------------------------------------

create or replace function public.vehicle_engine_rules_check()
returns table (rule text, key text, detail text)
language sql stable set search_path = public, pg_temp set statement_timeout = '120s' as $$
  select 'price_conflict', c.trim_id,
         format('%s %s/%s at %s: amounts %s', c.price_type, c.campaign_id, c.option_id, c.start, c.amounts)
    from public._vm_price_conflicts() c
  union all
  select 'fact_conflict', c.trim_id, format('%s %s at %s: %s', c.field_key, c.qualifiers, c.start, c.fact_ids)
    from public._vm_fact_conflicts() c
  union all
  select * from public._vm_structure_problems()
$$;

revoke all on function public.vehicle_engine_rules_check() from public, anon, authenticated;
grant execute on function public.vehicle_engine_rules_check() to service_role;

-- The rule functions run with the privileges of whoever writes: CHECK
-- expressions and the (non-definer) trigger bodies call them as the writing
-- role. Only service_role writes the master (browser roles have no write
-- privilege on it), so it -- and only it -- may execute them.
do $$
declare
  fn text;
begin
  for fn in select p.oid::regprocedure::text from pg_proc p join pg_namespace n on n.oid = p.pronamespace
             where n.nspname = 'public' and p.proname like '\_vm\_%' loop
    execute format('revoke all on function %s from public, anon, authenticated', fn);
    execute format('grant execute on function %s to service_role', fn);
  end loop;
end $$;

-- --------------------------------------------------------------------------
-- Gate: the existing master must already satisfy every trigger-enforced rule.
-- --------------------------------------------------------------------------

do $$
declare
  failures text;
begin
  select string_agg(format('%s %s: %s', rule, key, detail), E'\n' order by rule, key)
    into failures from (select * from public.vehicle_engine_rules_check() limit 50) x;
  if failures is not null then
    raise exception 'engine rules violated by existing master rows; nothing applied:%', E'\n' || failures;
  end if;
end $$;

commit;
