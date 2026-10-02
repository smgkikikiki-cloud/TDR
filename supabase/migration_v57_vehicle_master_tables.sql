-- Vehicle DB v3, Phase 0 step 2: master tables (docs/vehicle-db/VEHICLE_DB_V3.md §2, §3).
--
-- Purely additive. No existing table, view or function is altered or dropped:
-- the current_* views keep reading canonical_*_projection through
-- canonical_vehicle_state, and nothing here is readable by anon/authenticated.
-- Switching serving onto these tables is step 3 (parity), not this migration.
--
-- Two kinds of state are seeded, both pinned to ONE release (its release_id and
-- as_of, recorded in vehicle_master_state):
--
--  1. Serving identity/state, copied row-for-row from that release's
--     projections by vehicle_master_seed_from_release(). Values that the engine
--     computes against as_of (model generation_id/status/retail price band,
--     trim status/current_list_price/campaign_quote/price_history, resolved spec
--     facts) are stored exactly as served and stamped with served_as_of.
--  2. Master state the release does not carry (ENGINE_INVENTORY.md §8): analytical
--     variants, raw catalog trim specs, retracted price rows, campaigns/options,
--     the full spec-fact history (PROVISIONAL / superseded / not-yet-effective),
--     ECO evidence, the HUMAN lifecycle/current-retail/operational sidecars and
--     legacy identity bindings. These come from the canonical JSON tree at the
--     release's canonical_revision via vehicle_master_seed_supplemental(), fed by
--     automotive/vehicle_master/tools/vehicle_master_seed.py, which refuses to
--     run unless rebuilding that tree at as_of reproduces the release source_hash.
--
-- Every canonical id, legacy tdr_*_id and public slug is copied, never derived.
-- No release_id column: these tables are the master, not a snapshot.

-- --------------------------------------------------------------------------
-- Seed pin and run log
-- --------------------------------------------------------------------------

create table if not exists public.vehicle_master_state (
  scope text primary key check (scope = 'vehicle_master'),
  seed_release_id text not null,
  seed_as_of date not null,
  seed_source_hash text not null,
  seed_canonical_revision text not null,
  release_counts jsonb not null,
  release_seeded_at timestamptz not null default now(),
  supplemental_expected jsonb,
  supplemental_seeded_at timestamptz
);

create table if not exists public.vehicle_master_seed_runs (
  id bigint generated always as identity primary key,
  release_id text not null,
  as_of date not null,
  stage text not null check (stage in ('RELEASE','SUPPLEMENTAL','FINISH')),
  section text,
  row_count integer not null default 0,
  detail jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- --------------------------------------------------------------------------
-- Identity
-- --------------------------------------------------------------------------

create table if not exists public.vehicle_brands (
  canonical_id text primary key,
  tdr_brand_id uuid,
  slug text not null unique,
  name_en text not null,
  name_th text,
  origin_country text,
  payload jsonb not null,
  served_as_of date not null,
  revision integer not null default 1 check (revision >= 1),
  seed_release_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table if not exists public.vehicle_models (
  canonical_id text primary key,
  brand_id text not null references public.vehicle_brands(canonical_id),
  tdr_model_id uuid,
  slug text not null unique,
  name_en text not null,
  name_th text,
  -- As served on served_as_of (ENGINE_INVENTORY §5.2): current generation,
  -- lifecycle status, segment of that generation, price-eligible LIST band.
  generation_id text,
  status text not null check (status in ('CURRENT','HISTORICAL','UNVERIFIED')),
  segment text,
  body_type text,
  retail_price_min numeric,
  retail_price_max numeric,
  payload jsonb not null,
  served_as_of date not null,
  revision integer not null default 1 check (revision >= 1),
  seed_release_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create index if not exists vehicle_models_brand_idx on public.vehicle_models(brand_id);

create table if not exists public.vehicle_generations (
  canonical_id text primary key,
  model_id text not null references public.vehicle_models(canonical_id),
  code text,
  segment text,
  launched date,
  ended date,
  payload jsonb not null,
  revision integer not null default 1 check (revision >= 1),
  seed_release_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create index if not exists vehicle_generations_model_idx on public.vehicle_generations(model_id);

-- A model's served generation_id must name one of its own generations. Deferred
-- so a model and its generations can be written in one transaction.
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'vehicle_models_generation_fk') then
    alter table public.vehicle_models
      add constraint vehicle_models_generation_fk foreign key (generation_id)
      references public.vehicle_generations(canonical_id)
      deferrable initially deferred;
  end if;
end $$;

-- Analytical spec lines (registration grain). Not in any release; they drive
-- the served model payload's powertrains / production_type / production_country.
create table if not exists public.vehicle_variants (
  canonical_id text primary key,
  generation_id text not null references public.vehicle_generations(canonical_id),
  model_id text not null references public.vehicle_models(canonical_id),
  name text not null,
  powertrain text not null,
  import_type text not null,
  origin_country text,
  payload jsonb not null,
  revision integer not null default 1 check (revision >= 1),
  seed_release_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create index if not exists vehicle_variants_generation_idx on public.vehicle_variants(generation_id);

create table if not exists public.vehicle_trims (
  canonical_id text primary key,
  model_id text not null references public.vehicle_models(canonical_id),
  generation_id text not null references public.vehicle_generations(canonical_id),
  -- Not an FK yet: variants arrive in the supplemental stage, after trims.
  -- vehicle_master_seed_check() reports any dangling reference.
  variant_id text,
  name text not null,
  powertrain text not null,
  -- As served on served_as_of (ENGINE_INVENTORY §5.3 / §5.4).
  status text not null check (status in ('CURRENT','HISTORICAL','UNVERIFIED')),
  payload jsonb not null,
  current_list_price jsonb,
  campaign_quote jsonb not null default '{}'::jsonb,
  price_history jsonb not null default '[]'::jsonb,
  source_refs jsonb not null default '{}'::jsonb,
  served_as_of date not null,
  -- asdict(MarketTrim) as the base catalog holds it. Null for overlay/fragment
  -- trims, which exist only in market/trims/canonical*.json (§4.5, §9.5).
  catalog_payload jsonb,
  origin text generated always as
    (case when catalog_payload is null then 'OVERLAY' else 'CATALOG' end) stored,
  revision integer not null default 1 check (revision >= 1),
  seed_release_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create index if not exists vehicle_trims_model_idx on public.vehicle_trims(model_id);
create index if not exists vehicle_trims_generation_idx on public.vehicle_trims(generation_id);

-- --------------------------------------------------------------------------
-- Facts, prices, promotions
-- --------------------------------------------------------------------------

-- Every SpecFact, not only the resolved VERIFIED ones the release serves.
-- served_in_release marks the rows current_spec_facts carried on served_as_of.
create table if not exists public.vehicle_facts (
  fact_id text primary key,
  trim_id text not null references public.vehicle_trims(canonical_id),
  field_key text not null,
  value_state text not null
    check (value_state in ('KNOWN','UNKNOWN','NOT_AVAILABLE','NOT_APPLICABLE','ABSENT')),
  value jsonb,
  unit text not null default '',
  qualifiers jsonb not null default '{}'::jsonb,
  effective_from date,
  effective_to date,
  observed_at date,
  claim_ids jsonb not null default '[]'::jsonb,
  verification_status text not null check (verification_status in ('VERIFIED','PROVISIONAL')),
  source text not null default '',
  source_ref text not null default '',
  source_locator text not null default '',
  -- v3 §2 authority / lock. Left null/false by the seed: assigning an authority
  -- tier to legacy rows is a Phase 1 decision, not something to infer here.
  authority text check (authority in ('ADMIN','OFFICIAL','AI')),
  locked boolean not null default false,
  served_in_release boolean not null,
  payload jsonb not null,
  revision integer not null default 1 check (revision >= 1),
  seed_release_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists vehicle_facts_trim_field_idx on public.vehicle_facts(trim_id, field_key);

-- Append-only price ledger. record_id is the release's own id
-- (sha256 of the canonical row JSON, first 24 hex), so served rows keep it.
create table if not exists public.vehicle_price_ledger (
  record_id text primary key,
  trim_id text not null references public.vehicle_trims(canonical_id),
  amount_thb bigint not null check (amount_thb > 0),
  price_type text not null check (price_type in (
    'LIST_PRICE','INTRODUCTORY_PRICE','CAMPAIGN_PRICE','FINANCE_PRICE',
    'ESTIMATED_PRICE','DEALER_PRICE','ECO_STICKER_PRICE','UNKNOWN')),
  effective_from date,
  effective_to date,
  observed_at date,
  campaign_id text,
  option_id text,
  source text,
  source_ref text,
  source_document_id text not null default '',
  notes text not null default '',
  reference_price_thb bigint,
  retracted_at date,
  retraction_reason text not null default '',
  reviewed_by text not null default '',
  -- v3 §6.B / §2. Null = not stated by the legacy row; not inferred.
  vat_included boolean,
  authority text check (authority in ('ADMIN','OFFICIAL','AI')),
  in_release boolean not null,
  payload jsonb not null,
  seed_release_id text not null,
  created_at timestamptz not null default now()
);

create index if not exists vehicle_price_ledger_trim_idx
  on public.vehicle_price_ledger(trim_id, price_type);

-- Campaign storage, verbatim (to_jsonable(Campaign)). campaign_quote is built
-- from these plus CAMPAIGN/FINANCE ledger rows (ENGINE_INVENTORY §5.4).
create table if not exists public.vehicle_campaigns (
  campaign_id text primary key,
  brand_id text not null references public.vehicle_brands(canonical_id),
  name text not null default '',
  starts date,
  ends date,
  source text not null default '',
  source_ref text not null default '',
  quota_units integer,
  payload jsonb not null,
  seed_release_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- v3 §7 promotions. Seeded one row per legacy campaign option; the §7 typed
-- columns (scope/type/amounts/status/authority) are left null by the seed
-- because mapping legacy campaigns onto them needs owner decisions. The
-- legacy option fields that campaign_quote serves are kept verbatim.
create table if not exists public.vehicle_promotions (
  campaign_id text not null references public.vehicle_campaigns(campaign_id),
  option_id text not null,
  scope text check (scope in ('TRIM','MODEL')),
  trim_id text references public.vehicle_trims(canonical_id),
  model_id text references public.vehicle_models(canonical_id),
  type text check (type in ('PROMO_PRICE','DISCOUNT','FREEBIE','FINANCE')),
  promo_price_thb bigint,
  amount_thb bigint,
  description text,
  valid_from date,
  valid_to date,
  valid_to_assumed boolean not null default false,
  last_seen_at date,
  source text,
  authority text check (authority in ('ADMIN','OFFICIAL','AI')),
  status text check (status in ('ACTIVE','EXPIRED')),
  option_label text not null default '',
  option_status text not null check (option_status in ('ACTIVE','SOLD_OUT','WITHDRAWN','SUPERSEDED')),
  closed_at date,
  conditions jsonb not null default '{}'::jsonb,
  payload jsonb not null,
  seed_release_id text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (campaign_id, option_id)
);

-- --------------------------------------------------------------------------
-- Evidence, sidecars, legacy identity
-- --------------------------------------------------------------------------

create table if not exists public.vehicle_eco_evidence (
  trim_id text primary key references public.vehicle_trims(canonical_id),
  source_ref text not null,
  payload jsonb not null,
  seed_release_id text not null,
  created_at timestamptz not null default now()
);

-- HUMAN owner-approved CURRENT sets (market/trims/current_retail.json).
create table if not exists public.vehicle_current_retail_sets (
  model_id text primary key references public.vehicle_models(canonical_id),
  trim_ids text[] not null check (cardinality(trim_ids) > 0),
  reviewer text not null,
  reviewed_at date not null,
  source_ref text not null default '',
  notes text not null default '',
  payload jsonb not null,
  seed_release_id text not null,
  created_at timestamptz not null default now()
);

-- HUMAN trim CURRENT/HISTORICAL decisions (market/retail_lifecycle/trim_review.json).
create table if not exists public.vehicle_trim_lifecycle_decisions (
  trim_id text primary key references public.vehicle_trims(canonical_id),
  status text not null check (status in ('CURRENT','HISTORICAL')),
  reviewer text not null,
  reviewed_at date not null,
  source_ref text not null default '',
  notes text not null default '',
  payload jsonb not null,
  seed_release_id text not null,
  created_at timestamptz not null default now()
);

-- HUMAN UNDER_MAINTENANCE flags (market/operational_state/model_state.json).
create table if not exists public.vehicle_model_operational_states (
  model_id text primary key references public.vehicle_models(canonical_id),
  status text not null check (status = 'UNDER_MAINTENANCE'),
  reviewer text not null,
  reviewed_at date not null,
  source_ref text not null default '',
  notes text not null default '',
  payload jsonb not null,
  seed_release_id text not null,
  created_at timestamptz not null default now()
);

-- Reviewed legacy uuid <-> canonical bindings
-- (integration_data/external_identity_registry.json). The release-resolved
-- tdr_brand_id / tdr_model_id / slug live on vehicle_brands / vehicle_models.
create table if not exists public.vehicle_legacy_identities (
  namespace text not null,
  external_entity_type text not null,
  external_id text not null,
  canonical_entity_type text not null,
  canonical_id text not null,
  state text not null,
  authority_basis text,
  verified_at timestamptz,
  verified_by text,
  payload jsonb not null,
  seed_release_id text not null,
  created_at timestamptz not null default now(),
  primary key (namespace, external_entity_type, external_id, canonical_entity_type)
);

-- --------------------------------------------------------------------------
-- Access: server-side only. No policies, so RLS denies every browser role.
-- --------------------------------------------------------------------------

alter table public.vehicle_master_state enable row level security;
alter table public.vehicle_master_seed_runs enable row level security;
alter table public.vehicle_brands enable row level security;
alter table public.vehicle_models enable row level security;
alter table public.vehicle_generations enable row level security;
alter table public.vehicle_variants enable row level security;
alter table public.vehicle_trims enable row level security;
alter table public.vehicle_facts enable row level security;
alter table public.vehicle_price_ledger enable row level security;
alter table public.vehicle_campaigns enable row level security;
alter table public.vehicle_promotions enable row level security;
alter table public.vehicle_eco_evidence enable row level security;
alter table public.vehicle_current_retail_sets enable row level security;
alter table public.vehicle_trim_lifecycle_decisions enable row level security;
alter table public.vehicle_model_operational_states enable row level security;
alter table public.vehicle_legacy_identities enable row level security;

revoke all on public.vehicle_master_state, public.vehicle_master_seed_runs,
  public.vehicle_brands, public.vehicle_models, public.vehicle_generations,
  public.vehicle_variants, public.vehicle_trims, public.vehicle_facts,
  public.vehicle_price_ledger, public.vehicle_campaigns, public.vehicle_promotions,
  public.vehicle_eco_evidence, public.vehicle_current_retail_sets,
  public.vehicle_trim_lifecycle_decisions, public.vehicle_model_operational_states,
  public.vehicle_legacy_identities
  from public, anon, authenticated;

grant select, insert, update, delete on public.vehicle_master_state, public.vehicle_master_seed_runs,
  public.vehicle_brands, public.vehicle_models, public.vehicle_generations,
  public.vehicle_variants, public.vehicle_trims, public.vehicle_facts,
  public.vehicle_price_ledger, public.vehicle_campaigns, public.vehicle_promotions,
  public.vehicle_eco_evidence, public.vehicle_current_retail_sets,
  public.vehicle_trim_lifecycle_decisions, public.vehicle_model_operational_states,
  public.vehicle_legacy_identities
  to service_role;

-- --------------------------------------------------------------------------
-- Seed stage 1: serving identity/state from the pinned release.
-- --------------------------------------------------------------------------

create or replace function public.vehicle_master_seed_from_release(p_release_id text, p_as_of date)
returns jsonb
language plpgsql
set search_path = public, pg_temp
set statement_timeout = '120s'
as $$
declare
  rel public.canonical_vehicle_releases%rowtype;
  active_id text;
  st public.vehicle_master_state%rowtype;
  actual jsonb;
  section text;
begin
  perform pg_advisory_xact_lock(hashtext('vehicle_master_seed'));

  select * into rel from public.canonical_vehicle_releases where release_id = p_release_id;
  if not found then
    raise exception 'unknown release %', p_release_id;
  end if;
  if rel.as_of is distinct from p_as_of then
    raise exception 'release % has as_of %, not the pinned %', p_release_id, rel.as_of, p_as_of;
  end if;
  select active_release_id into active_id
    from public.canonical_vehicle_state where scope = 'vehicle_catalog';
  if active_id is distinct from p_release_id then
    raise exception 'release % is not the active release (active: %)', p_release_id, active_id;
  end if;

  select * into st from public.vehicle_master_state where scope = 'vehicle_master';
  if found then
    if st.seed_release_id <> p_release_id or st.seed_as_of <> p_as_of then
      raise exception 'vehicle master already seeded from % (as_of %)', st.seed_release_id, st.seed_as_of;
    end if;
    return jsonb_build_object('status', 'already_seeded', 'release_id', p_release_id,
                              'as_of', p_as_of, 'counts', st.release_counts);
  end if;
  if exists (select 1 from public.vehicle_brands) or exists (select 1 from public.vehicle_trims)
     or exists (select 1 from public.vehicle_price_ledger) or exists (select 1 from public.vehicle_facts) then
    raise exception 'vehicle master tables are not empty but have no seed pin';
  end if;

  insert into public.vehicle_brands
    (canonical_id, tdr_brand_id, slug, name_en, name_th, origin_country, payload,
     served_as_of, seed_release_id)
  select canonical_id, tdr_brand_id, slug, name_en, name_th, origin_country, payload,
         p_as_of, p_release_id
  from public.canonical_brand_projection where release_id = p_release_id;

  insert into public.vehicle_models
    (canonical_id, brand_id, tdr_model_id, slug, name_en, name_th, generation_id, status,
     segment, body_type, retail_price_min, retail_price_max, payload, served_as_of, seed_release_id)
  select canonical_id, brand_id, tdr_model_id, slug, name_en, name_th, generation_id, status,
         segment, body_type, retail_price_min, retail_price_max, payload, p_as_of, p_release_id
  from public.canonical_model_projection where release_id = p_release_id;

  insert into public.vehicle_generations
    (canonical_id, model_id, code, segment, launched, ended, payload, seed_release_id)
  select canonical_id, model_id, code, segment, launched, ended, payload, p_release_id
  from public.canonical_generation_projection where release_id = p_release_id;

  insert into public.vehicle_trims
    (canonical_id, model_id, generation_id, variant_id, name, powertrain, status, payload,
     current_list_price, campaign_quote, price_history, source_refs, served_as_of, seed_release_id)
  select canonical_id, model_id, generation_id, variant_id, name, powertrain, status, payload,
         current_list_price, campaign_quote, price_history, source_refs, p_as_of, p_release_id
  from public.canonical_market_trim_projection where release_id = p_release_id;

  insert into public.vehicle_price_ledger
    (record_id, trim_id, amount_thb, price_type, effective_from, effective_to, observed_at,
     campaign_id, option_id, source, source_ref, source_document_id, notes,
     reference_price_thb, retracted_at, retraction_reason, reviewed_by, in_release, payload,
     seed_release_id)
  select p.record_id, p.trim_id, p.amount_thb, p.price_type, p.effective_from, p.effective_to,
         p.observed_at, p.campaign_id, p.option_id, p.source, p.source_ref,
         coalesce(p.payload->>'source_document_id', ''), coalesce(p.payload->>'notes', ''),
         (p.payload->>'reference_price_thb')::bigint, (p.payload->>'retracted_at')::date,
         coalesce(p.payload->>'retraction_reason', ''), coalesce(p.payload->>'reviewed_by', ''),
         true, p.payload, p_release_id
  from public.canonical_price_projection p where p.release_id = p_release_id;

  insert into public.vehicle_facts
    (fact_id, trim_id, field_key, value_state, value, unit, qualifiers, effective_from,
     effective_to, observed_at, claim_ids, verification_status, source, source_ref,
     source_locator, served_in_release, payload, seed_release_id)
  select s.fact_id, s.trim_id, coalesce(s.field_key, s.payload->>'field_key'),
         s.payload->>'value_state', s.payload->'value', coalesce(s.payload->>'unit', ''),
         coalesce(s.payload->'qualifiers', '{}'::jsonb), (s.payload->>'effective_from')::date,
         (s.payload->>'effective_to')::date, (s.payload->>'observed_at')::date,
         coalesce(s.payload->'claim_ids', '[]'::jsonb),
         coalesce(s.verification_status, s.payload->>'verification_status'),
         coalesce(s.payload->>'source', ''), coalesce(s.payload->>'source_ref', ''),
         coalesce(s.payload->>'source_locator', ''), true, s.payload, p_release_id
  from public.canonical_spec_projection s where s.release_id = p_release_id;

  actual := jsonb_build_object(
    'brands', (select count(*) from public.vehicle_brands),
    'models', (select count(*) from public.vehicle_models),
    'generations', (select count(*) from public.vehicle_generations),
    'market_trims', (select count(*) from public.vehicle_trims),
    'price_ledger', (select count(*) from public.vehicle_price_ledger),
    'spec_facts', (select count(*) from public.vehicle_facts));
  foreach section in array array['brands','models','generations','market_trims','price_ledger','spec_facts'] loop
    if (actual->>section)::bigint is distinct from (rel.counts->>section)::bigint then
      raise exception 'seeded % rows for %, release counts say %',
        actual->>section, section, rel.counts->>section;
    end if;
  end loop;

  insert into public.vehicle_master_state
    (scope, seed_release_id, seed_as_of, seed_source_hash, seed_canonical_revision, release_counts)
  values ('vehicle_master', p_release_id, p_as_of, rel.source_hash, rel.canonical_revision, actual);
  insert into public.vehicle_master_seed_runs (release_id, as_of, stage, row_count, detail)
  values (p_release_id, p_as_of, 'RELEASE',
          (select sum(value::bigint) from jsonb_each_text(actual)), actual);

  return jsonb_build_object('status', 'seeded', 'release_id', p_release_id, 'as_of', p_as_of,
                            'source_hash', rel.source_hash,
                            'canonical_revision', rel.canonical_revision, 'counts', actual);
end;
$$;

-- --------------------------------------------------------------------------
-- Seed stage 2: master state the release does not carry. Idempotent per row:
-- a row already present must be identical, so a chunk can be resent safely
-- and a drifted source is refused instead of silently merged.
-- --------------------------------------------------------------------------

create or replace function public.vehicle_master_seed_supplemental(
  p_release_id text, p_as_of date, p_section text, p_rows jsonb)
returns jsonb
language plpgsql
set search_path = public, pg_temp
set statement_timeout = '60s'
as $$
declare
  st public.vehicle_master_state%rowtype;
  n integer;
  bad text;
begin
  perform pg_advisory_xact_lock(hashtext('vehicle_master_seed'));
  select * into st from public.vehicle_master_state where scope = 'vehicle_master';
  if not found or st.seed_release_id <> p_release_id or st.seed_as_of <> p_as_of then
    raise exception 'vehicle master is not seeded from % (as_of %)', p_release_id, p_as_of;
  end if;
  if st.supplemental_seeded_at is not null then
    raise exception 'supplemental seed already finished at %', st.supplemental_seeded_at;
  end if;
  if jsonb_typeof(p_rows) <> 'array' then
    raise exception 'rows must be a JSON array';
  end if;
  n := jsonb_array_length(p_rows);

  create temporary table if not exists _vm_in (k text primary key, payload jsonb not null) on commit drop;
  truncate _vm_in;

  if p_section = 'variants' then
    insert into _vm_in select r->>'canonical_id', r->'payload' from jsonb_array_elements(p_rows) r;
    insert into public.vehicle_variants
      (canonical_id, generation_id, model_id, name, powertrain, import_type, origin_country,
       payload, seed_release_id)
    select i.k, i.payload->>'generation_id', g.model_id, i.payload->>'name',
           i.payload->>'powertrain', i.payload->>'import_type', i.payload->>'origin_country',
           i.payload, p_release_id
    from _vm_in i left join public.vehicle_generations g on g.canonical_id = i.payload->>'generation_id'
    on conflict (canonical_id) do nothing;
    select i.k into bad from _vm_in i join public.vehicle_variants v on v.canonical_id = i.k
      where v.payload <> i.payload limit 1;

  elsif p_section = 'catalog_trims' then
    insert into _vm_in select r->>'canonical_id', r->'payload' from jsonb_array_elements(p_rows) r;
    select i.k into bad from _vm_in i
      left join public.vehicle_trims t on t.canonical_id = i.k where t.canonical_id is null limit 1;
    if bad is not null then
      raise exception 'catalog trim % is not in the seeded release', bad;
    end if;
    update public.vehicle_trims t set catalog_payload = i.payload
      from _vm_in i where t.canonical_id = i.k and t.catalog_payload is null;
    select i.k into bad from _vm_in i join public.vehicle_trims t on t.canonical_id = i.k
      where t.catalog_payload <> i.payload limit 1;

  elsif p_section = 'prices' then
    insert into _vm_in select r->>'record_id', r->'payload' from jsonb_array_elements(p_rows) r;
    -- Every non-retracted ledger row is served; only retracted rows may be new.
    select i.k into bad from _vm_in i
      left join public.vehicle_price_ledger p on p.record_id = i.k
      where p.record_id is null and nullif(i.payload->>'retracted_at', '') is null limit 1;
    if bad is not null then
      raise exception 'non-retracted price % is not in the seeded release', bad;
    end if;
    insert into public.vehicle_price_ledger
      (record_id, trim_id, amount_thb, price_type, effective_from, effective_to, observed_at,
       campaign_id, option_id, source, source_ref, source_document_id, notes,
       reference_price_thb, retracted_at, retraction_reason, reviewed_by, in_release, payload,
       seed_release_id)
    select i.k, i.payload->>'trim_id', (i.payload->>'amount_thb')::bigint, i.payload->>'price_type',
           (i.payload->>'effective_from')::date, (i.payload->>'effective_to')::date,
           (i.payload->>'observed_at')::date, i.payload->>'campaign_id', i.payload->>'option_id',
           i.payload->>'source', i.payload->>'source_ref',
           coalesce(i.payload->>'source_document_id', ''), coalesce(i.payload->>'notes', ''),
           (i.payload->>'reference_price_thb')::bigint, (i.payload->>'retracted_at')::date,
           coalesce(i.payload->>'retraction_reason', ''), coalesce(i.payload->>'reviewed_by', ''),
           false, i.payload, p_release_id
    from _vm_in i
    on conflict (record_id) do nothing;
    select i.k into bad from _vm_in i join public.vehicle_price_ledger p on p.record_id = i.k
      where (p.payload - 'record_id') <> (i.payload - 'record_id') limit 1;

  elsif p_section = 'campaigns' then
    insert into _vm_in select r->>'campaign_id', r->'payload' from jsonb_array_elements(p_rows) r;
    insert into public.vehicle_campaigns
      (campaign_id, brand_id, name, starts, ends, source, source_ref, quota_units, payload,
       seed_release_id)
    select i.k, i.payload->>'brand_id', coalesce(i.payload->>'name', ''),
           (i.payload->>'starts')::date, (i.payload->>'ends')::date,
           coalesce(i.payload->>'source', ''), coalesce(i.payload->>'source_ref', ''),
           (i.payload->>'quota_units')::integer, i.payload, p_release_id
    from _vm_in i
    on conflict (campaign_id) do nothing;
    insert into public.vehicle_promotions
      (campaign_id, option_id, description, valid_from, valid_to, source, option_label,
       option_status, closed_at, conditions, payload, seed_release_id)
    select i.k, o->>'id', nullif(o->'conditions'->>'text', ''),
           coalesce((o->>'starts')::date, (i.payload->>'starts')::date),
           coalesce((o->>'ends')::date, (i.payload->>'ends')::date),
           nullif(i.payload->>'source', ''), coalesce(o->>'label', ''),
           o->>'status', (o->>'closed_at')::date, coalesce(o->'conditions', '{}'::jsonb),
           o, p_release_id
    from _vm_in i cross join lateral jsonb_array_elements(i.payload->'options') o
    on conflict (campaign_id, option_id) do nothing;
    select i.k into bad from _vm_in i join public.vehicle_campaigns c on c.campaign_id = i.k
      where c.payload <> i.payload limit 1;

  elsif p_section = 'facts' then
    insert into _vm_in select r->>'fact_id', r->'payload' from jsonb_array_elements(p_rows) r;
    insert into public.vehicle_facts
      (fact_id, trim_id, field_key, value_state, value, unit, qualifiers, effective_from,
       effective_to, observed_at, claim_ids, verification_status, source, source_ref,
       source_locator, served_in_release, payload, seed_release_id)
    select i.k, i.payload->>'trim_id', i.payload->>'field_key', i.payload->>'value_state',
           i.payload->'value', coalesce(i.payload->>'unit', ''),
           coalesce(i.payload->'qualifiers', '{}'::jsonb), (i.payload->>'effective_from')::date,
           (i.payload->>'effective_to')::date, (i.payload->>'observed_at')::date,
           coalesce(i.payload->'claim_ids', '[]'::jsonb), i.payload->>'verification_status',
           coalesce(i.payload->>'source', ''), coalesce(i.payload->>'source_ref', ''),
           coalesce(i.payload->>'source_locator', ''), false, i.payload, p_release_id
    from _vm_in i
    on conflict (fact_id) do nothing;
    select i.k into bad from _vm_in i join public.vehicle_facts f on f.fact_id = i.k
      where f.payload <> i.payload limit 1;

  elsif p_section = 'eco_evidence' then
    insert into _vm_in select r->>'trim_id', r->'payload' from jsonb_array_elements(p_rows) r;
    insert into public.vehicle_eco_evidence (trim_id, source_ref, payload, seed_release_id)
    select i.k, i.payload->>'source_ref', i.payload, p_release_id from _vm_in i
    on conflict (trim_id) do nothing;
    select i.k into bad from _vm_in i join public.vehicle_eco_evidence e on e.trim_id = i.k
      where e.payload <> i.payload limit 1;

  elsif p_section = 'current_retail_sets' then
    insert into _vm_in select r->>'model_id', r->'payload' from jsonb_array_elements(p_rows) r;
    insert into public.vehicle_current_retail_sets
      (model_id, trim_ids, reviewer, reviewed_at, source_ref, notes, payload, seed_release_id)
    select i.k, array(select jsonb_array_elements_text(i.payload->'trim_ids')),
           i.payload->>'reviewer', (i.payload->>'reviewed_at')::date,
           coalesce(i.payload->>'source_ref', ''), coalesce(i.payload->>'notes', ''),
           i.payload, p_release_id
    from _vm_in i
    on conflict (model_id) do nothing;
    select i.k into bad from _vm_in i join public.vehicle_current_retail_sets c on c.model_id = i.k
      where c.payload <> i.payload limit 1;

  elsif p_section = 'trim_lifecycle_decisions' then
    insert into _vm_in select r->>'trim_id', r->'payload' from jsonb_array_elements(p_rows) r;
    insert into public.vehicle_trim_lifecycle_decisions
      (trim_id, status, reviewer, reviewed_at, source_ref, notes, payload, seed_release_id)
    select i.k, i.payload->>'status', i.payload->>'reviewer', (i.payload->>'reviewed_at')::date,
           coalesce(i.payload->>'source_ref', ''), coalesce(i.payload->>'notes', ''),
           i.payload, p_release_id
    from _vm_in i
    on conflict (trim_id) do nothing;
    select i.k into bad from _vm_in i join public.vehicle_trim_lifecycle_decisions d on d.trim_id = i.k
      where d.payload <> i.payload limit 1;

  elsif p_section = 'model_operational_states' then
    insert into _vm_in select r->>'model_id', r->'payload' from jsonb_array_elements(p_rows) r;
    insert into public.vehicle_model_operational_states
      (model_id, status, reviewer, reviewed_at, source_ref, notes, payload, seed_release_id)
    select i.k, i.payload->>'status', i.payload->>'reviewer', (i.payload->>'reviewed_at')::date,
           coalesce(i.payload->>'source_ref', ''), coalesce(i.payload->>'notes', ''),
           i.payload, p_release_id
    from _vm_in i
    on conflict (model_id) do nothing;
    select i.k into bad from _vm_in i join public.vehicle_model_operational_states m on m.model_id = i.k
      where m.payload <> i.payload limit 1;

  elsif p_section = 'legacy_identities' then
    insert into _vm_in
      select concat_ws('|', r->'payload'->>'namespace', r->'payload'->>'external_entity_type',
                       r->'payload'->>'external_id', r->'payload'->>'canonical_entity_type'),
             r->'payload'
      from jsonb_array_elements(p_rows) r;
    insert into public.vehicle_legacy_identities
      (namespace, external_entity_type, external_id, canonical_entity_type, canonical_id, state,
       authority_basis, verified_at, verified_by, payload, seed_release_id)
    select i.payload->>'namespace', i.payload->>'external_entity_type', i.payload->>'external_id',
           i.payload->>'canonical_entity_type', i.payload->>'canonical_id', i.payload->>'state',
           i.payload->>'authority_basis', (i.payload->>'verified_at')::timestamptz,
           i.payload->>'verified_by', i.payload, p_release_id
    from _vm_in i
    on conflict do nothing;
    select i.k into bad from _vm_in i join public.vehicle_legacy_identities l
      on concat_ws('|', l.namespace, l.external_entity_type, l.external_id, l.canonical_entity_type) = i.k
      where l.payload <> i.payload limit 1;

  else
    raise exception 'unknown supplemental section %', p_section;
  end if;

  if bad is not null then
    raise exception '% row % already exists with different content', p_section, bad;
  end if;

  insert into public.vehicle_master_seed_runs (release_id, as_of, stage, section, row_count)
  values (p_release_id, p_as_of, 'SUPPLEMENTAL', p_section, n);
  return jsonb_build_object('section', p_section, 'rows', n);
end;
$$;

-- Closes the supplemental stage once every section's total matches what the
-- seed tool built from the pinned tree. After this, stage 2 refuses writes.
create or replace function public.vehicle_master_finish_supplemental(
  p_release_id text, p_as_of date, p_expected jsonb)
returns jsonb
language plpgsql
set search_path = public, pg_temp
as $$
declare
  st public.vehicle_master_state%rowtype;
  actual jsonb;
  section text;
begin
  perform pg_advisory_xact_lock(hashtext('vehicle_master_seed'));
  select * into st from public.vehicle_master_state where scope = 'vehicle_master';
  if not found or st.seed_release_id <> p_release_id or st.seed_as_of <> p_as_of then
    raise exception 'vehicle master is not seeded from % (as_of %)', p_release_id, p_as_of;
  end if;
  if st.supplemental_seeded_at is not null then
    if st.supplemental_expected = p_expected then
      return jsonb_build_object('status', 'already_finished', 'counts', st.supplemental_expected);
    end if;
    raise exception 'supplemental seed already finished with different expected counts';
  end if;

  actual := public._vehicle_master_supplemental_counts();
  for section in select jsonb_object_keys(p_expected) loop
    if not actual ? section then
      raise exception 'unknown supplemental section %', section;
    end if;
    if (actual->>section)::bigint is distinct from (p_expected->>section)::bigint then
      raise exception 'supplemental % has % rows, expected %',
        section, actual->>section, p_expected->>section;
    end if;
  end loop;
  for section in select jsonb_object_keys(actual) loop
    if not p_expected ? section then
      raise exception 'expected counts are missing section %', section;
    end if;
  end loop;

  update public.vehicle_master_state
     set supplemental_expected = p_expected, supplemental_seeded_at = now()
   where scope = 'vehicle_master';
  insert into public.vehicle_master_seed_runs (release_id, as_of, stage, row_count, detail)
  values (p_release_id, p_as_of, 'FINISH',
          (select sum(value::bigint) from jsonb_each_text(actual)), actual);
  return jsonb_build_object('status', 'finished', 'counts', actual);
end;
$$;

-- Section totals in the same units the seed tool sends: every row of the
-- source, including the ones stage 1 already wrote from the release.
create or replace function public._vehicle_master_supplemental_counts()
returns jsonb
language sql
stable
set search_path = public, pg_temp
as $$
  select jsonb_build_object(
    'variants', (select count(*) from public.vehicle_variants),
    'catalog_trims', (select count(*) from public.vehicle_trims where catalog_payload is not null),
    'prices', (select count(*) from public.vehicle_price_ledger),
    'campaigns', (select count(*) from public.vehicle_campaigns),
    'facts', (select count(*) from public.vehicle_facts),
    'eco_evidence', (select count(*) from public.vehicle_eco_evidence),
    'current_retail_sets', (select count(*) from public.vehicle_current_retail_sets),
    'trim_lifecycle_decisions', (select count(*) from public.vehicle_trim_lifecycle_decisions),
    'model_operational_states', (select count(*) from public.vehicle_model_operational_states),
    'legacy_identities', (select count(*) from public.vehicle_legacy_identities));
$$;

-- --------------------------------------------------------------------------
-- Check: row counts, ID sets and served values against the pinned release,
-- integrity of the supplemental rows, and a report of preserved state.
-- Read-only. ok = false on any parity/integrity failure; kind = 'report'
-- rows are informational and always ok.
-- --------------------------------------------------------------------------

create or replace function public.vehicle_master_seed_check()
returns table (kind text, section text, check_name text, expected bigint, actual bigint, ok boolean)
language plpgsql
stable
set search_path = public, pg_temp
set statement_timeout = '120s'
as $$
declare
  st public.vehicle_master_state%rowtype;
  rel public.canonical_vehicle_releases%rowtype;
  rid text;
  active_id text;
  sup jsonb;
  s text;
begin
  select * into st from public.vehicle_master_state where scope = 'vehicle_master';
  if not found then
    kind := 'pin'; section := 'state'; check_name := 'seeded'; expected := 1; actual := 0; ok := false;
    return next;
    return;
  end if;
  rid := st.seed_release_id;
  select * into rel from public.canonical_vehicle_releases where release_id = rid;
  select active_release_id into active_id
    from public.canonical_vehicle_state where scope = 'vehicle_catalog';

  -- Pin -------------------------------------------------------------------
  kind := 'pin'; section := 'state';
  check_name := 'release_still_present'; expected := 1; actual := (rel.release_id is not null)::int;
  ok := actual = 1; return next;
  if rel.release_id is null then
    return;
  end if;
  check_name := 'release_still_active'; expected := 1; actual := (active_id = rid)::int;
  ok := actual = 1; return next;
  check_name := 'as_of_matches_release'; expected := 1; actual := (rel.as_of = st.seed_as_of)::int;
  ok := actual = 1; return next;
  check_name := 'source_hash_matches_release'; expected := 1;
  actual := (rel.source_hash = st.seed_source_hash)::int; ok := actual = 1; return next;
  check_name := 'supplemental_finished'; expected := 1;
  actual := (st.supplemental_seeded_at is not null)::int; ok := actual = 1; return next;

  -- Release parity: counts, ids both ways, served values ------------------
  kind := 'release';

  section := 'brands';
  check_name := 'row_count'; expected := (rel.counts->>'brands')::bigint;
  actual := (select count(*) from vehicle_brands); ok := actual = expected; return next;
  check_name := 'ids_missing_from_master'; expected := 0;
  actual := (select count(*) from canonical_brand_projection p where p.release_id = rid
             and not exists (select 1 from vehicle_brands m where m.canonical_id = p.canonical_id));
  ok := actual = 0; return next;
  check_name := 'ids_not_in_release'; expected := 0;
  actual := (select count(*) from vehicle_brands m where not exists
             (select 1 from canonical_brand_projection p where p.release_id = rid and p.canonical_id = m.canonical_id));
  ok := actual = 0; return next;
  check_name := 'served_values_differ'; expected := 0;
  actual := (select count(*) from canonical_brand_projection p join vehicle_brands m using (canonical_id)
             where p.release_id = rid and (p.tdr_brand_id, p.slug, p.name_en, p.name_th, p.origin_country, p.payload)
               is distinct from (m.tdr_brand_id, m.slug, m.name_en, m.name_th, m.origin_country, m.payload));
  ok := actual = 0; return next;

  section := 'models';
  check_name := 'row_count'; expected := (rel.counts->>'models')::bigint;
  actual := (select count(*) from vehicle_models); ok := actual = expected; return next;
  check_name := 'ids_missing_from_master'; expected := 0;
  actual := (select count(*) from canonical_model_projection p where p.release_id = rid
             and not exists (select 1 from vehicle_models m where m.canonical_id = p.canonical_id));
  ok := actual = 0; return next;
  check_name := 'ids_not_in_release'; expected := 0;
  actual := (select count(*) from vehicle_models m where not exists
             (select 1 from canonical_model_projection p where p.release_id = rid and p.canonical_id = m.canonical_id));
  ok := actual = 0; return next;
  check_name := 'served_values_differ'; expected := 0;
  actual := (select count(*) from canonical_model_projection p join vehicle_models m using (canonical_id)
             where p.release_id = rid and
               (p.tdr_model_id, p.brand_id, p.slug, p.name_en, p.name_th, p.generation_id, p.status,
                p.segment, p.body_type, p.retail_price_min, p.retail_price_max, p.payload)
               is distinct from
               (m.tdr_model_id, m.brand_id, m.slug, m.name_en, m.name_th, m.generation_id, m.status,
                m.segment, m.body_type, m.retail_price_min, m.retail_price_max, m.payload));
  ok := actual = 0; return next;

  section := 'generations';
  check_name := 'row_count'; expected := (rel.counts->>'generations')::bigint;
  actual := (select count(*) from vehicle_generations); ok := actual = expected; return next;
  check_name := 'ids_missing_from_master'; expected := 0;
  actual := (select count(*) from canonical_generation_projection p where p.release_id = rid
             and not exists (select 1 from vehicle_generations m where m.canonical_id = p.canonical_id));
  ok := actual = 0; return next;
  check_name := 'ids_not_in_release'; expected := 0;
  actual := (select count(*) from vehicle_generations m where not exists
             (select 1 from canonical_generation_projection p where p.release_id = rid and p.canonical_id = m.canonical_id));
  ok := actual = 0; return next;
  check_name := 'served_values_differ'; expected := 0;
  actual := (select count(*) from canonical_generation_projection p join vehicle_generations m using (canonical_id)
             where p.release_id = rid and (p.model_id, p.code, p.segment, p.launched, p.ended, p.payload)
               is distinct from (m.model_id, m.code, m.segment, m.launched, m.ended, m.payload));
  ok := actual = 0; return next;

  section := 'market_trims';
  check_name := 'row_count'; expected := (rel.counts->>'market_trims')::bigint;
  actual := (select count(*) from vehicle_trims); ok := actual = expected; return next;
  check_name := 'ids_missing_from_master'; expected := 0;
  actual := (select count(*) from canonical_market_trim_projection p where p.release_id = rid
             and not exists (select 1 from vehicle_trims m where m.canonical_id = p.canonical_id));
  ok := actual = 0; return next;
  check_name := 'ids_not_in_release'; expected := 0;
  actual := (select count(*) from vehicle_trims m where not exists
             (select 1 from canonical_market_trim_projection p where p.release_id = rid and p.canonical_id = m.canonical_id));
  ok := actual = 0; return next;
  check_name := 'served_values_differ'; expected := 0;
  actual := (select count(*) from canonical_market_trim_projection p join vehicle_trims m using (canonical_id)
             where p.release_id = rid and
               (p.model_id, p.generation_id, p.variant_id, p.name, p.powertrain, p.status, p.payload,
                p.current_list_price, p.campaign_quote, p.price_history, p.source_refs)
               is distinct from
               (m.model_id, m.generation_id, m.variant_id, m.name, m.powertrain, m.status, m.payload,
                m.current_list_price, m.campaign_quote, m.price_history, m.source_refs));
  ok := actual = 0; return next;

  section := 'price_ledger';
  check_name := 'row_count_in_release'; expected := (rel.counts->>'price_ledger')::bigint;
  actual := (select count(*) from vehicle_price_ledger where in_release); ok := actual = expected; return next;
  check_name := 'ids_missing_from_master'; expected := 0;
  actual := (select count(*) from canonical_price_projection p where p.release_id = rid
             and not exists (select 1 from vehicle_price_ledger m where m.record_id = p.record_id and m.in_release));
  ok := actual = 0; return next;
  check_name := 'ids_not_in_release'; expected := 0;
  actual := (select count(*) from vehicle_price_ledger m where m.in_release and not exists
             (select 1 from canonical_price_projection p where p.release_id = rid and p.record_id = m.record_id));
  ok := actual = 0; return next;
  check_name := 'served_values_differ'; expected := 0;
  actual := (select count(*) from canonical_price_projection p join vehicle_price_ledger m using (record_id)
             where p.release_id = rid and
               (p.trim_id, p.amount_thb, p.price_type, p.effective_from, p.effective_to, p.observed_at,
                p.campaign_id, p.option_id, p.source, p.source_ref, p.payload)
               is distinct from
               (m.trim_id, m.amount_thb, m.price_type, m.effective_from, m.effective_to, m.observed_at,
                m.campaign_id, m.option_id, m.source, m.source_ref, m.payload));
  ok := actual = 0; return next;

  section := 'spec_facts';
  check_name := 'row_count_in_release'; expected := (rel.counts->>'spec_facts')::bigint;
  actual := (select count(*) from vehicle_facts where served_in_release); ok := actual = expected; return next;
  check_name := 'ids_missing_from_master'; expected := 0;
  actual := (select count(*) from canonical_spec_projection p where p.release_id = rid
             and not exists (select 1 from vehicle_facts m where m.fact_id = p.fact_id and m.served_in_release));
  ok := actual = 0; return next;
  check_name := 'ids_not_in_release'; expected := 0;
  actual := (select count(*) from vehicle_facts m where m.served_in_release and not exists
             (select 1 from canonical_spec_projection p where p.release_id = rid and p.fact_id = m.fact_id));
  ok := actual = 0; return next;
  check_name := 'served_values_differ'; expected := 0;
  actual := (select count(*) from canonical_spec_projection p join vehicle_facts m using (fact_id)
             where p.release_id = rid and
               (p.trim_id, p.field_key, p.verification_status, p.payload)
               is distinct from (m.trim_id, m.field_key, m.verification_status, m.payload));
  ok := actual = 0; return next;

  -- Integrity of supplemental rows -----------------------------------------
  kind := 'integrity';

  section := 'supplemental';
  sup := public._vehicle_master_supplemental_counts();
  for s in select jsonb_object_keys(sup) loop
    check_name := s || '_count'; expected := (st.supplemental_expected->>s)::bigint;
    actual := (sup->>s)::bigint; ok := expected is not null and actual = expected; return next;
  end loop;

  section := 'market_trims';
  check_name := 'variant_id_without_variant'; expected := 0;
  actual := (select count(*) from vehicle_trims t where t.variant_id is not null
             and not exists (select 1 from vehicle_variants v where v.canonical_id = t.variant_id));
  ok := actual = 0; return next;
  check_name := 'eco_evidence_differs_from_served'; expected := 0;
  actual := (select count(*) from vehicle_trims t left join vehicle_eco_evidence e on e.trim_id = t.canonical_id
             where t.payload ? 'ecosticker_evidence'
               and (t.payload->'ecosticker_evidence') is distinct from coalesce(e.payload, 'null'::jsonb));
  ok := actual = 0; return next;

  section := 'price_ledger';
  check_name := 'in_release_disagrees_with_retracted'; expected := 0;
  actual := (select count(*) from vehicle_price_ledger where in_release = (retracted_at is not null));
  ok := actual = 0; return next;
  check_name := 'campaign_id_without_campaign'; expected := 0;
  actual := (select count(*) from vehicle_price_ledger p where p.campaign_id is not null
             and not exists (select 1 from vehicle_campaigns c where c.campaign_id = p.campaign_id));
  ok := actual = 0; return next;
  check_name := 'option_id_without_promotion'; expected := 0;
  actual := (select count(*) from vehicle_price_ledger p where p.option_id is not null
             and not exists (select 1 from vehicle_promotions o
                             where o.campaign_id = p.campaign_id and o.option_id = p.option_id));
  ok := actual = 0; return next;

  section := 'spec_facts';
  check_name := 'served_fact_not_verified'; expected := 0;
  actual := (select count(*) from vehicle_facts where served_in_release and verification_status <> 'VERIFIED');
  ok := actual = 0; return next;

  section := 'current_retail_sets';
  check_name := 'member_not_a_trim_of_model'; expected := 0;
  actual := (select count(*) from vehicle_current_retail_sets c cross join lateral unnest(c.trim_ids) tid
             where not exists (select 1 from vehicle_trims t where t.canonical_id = tid and t.model_id = c.model_id));
  ok := actual = 0; return next;

  section := 'legacy_identities';
  check_name := 'canonical_id_unknown'; expected := 0;
  actual := (select count(*) from vehicle_legacy_identities l where not (
               (l.canonical_entity_type = 'brand' and exists (select 1 from vehicle_brands b where b.canonical_id = l.canonical_id))
            or (l.canonical_entity_type = 'model' and exists (select 1 from vehicle_models m where m.canonical_id = l.canonical_id))
            or (l.canonical_entity_type = 'generation' and exists (select 1 from vehicle_generations g where g.canonical_id = l.canonical_id))
            or (l.canonical_entity_type = 'variant' and exists (select 1 from vehicle_variants v where v.canonical_id = l.canonical_id))
            or (l.canonical_entity_type = 'market_trim' and exists (select 1 from vehicle_trims t where t.canonical_id = l.canonical_id))));
  ok := actual = 0; return next;

  -- Report: preserved state the release does not serve -----------------------
  kind := 'report'; expected := null; ok := true;
  section := 'brands'; check_name := 'with_legacy_tdr_brand_id';
  actual := (select count(*) from vehicle_brands where tdr_brand_id is not null); return next;
  section := 'models'; check_name := 'with_legacy_tdr_model_id';
  actual := (select count(*) from vehicle_models where tdr_model_id is not null); return next;
  section := 'variants'; check_name := 'rows';
  actual := (select count(*) from vehicle_variants); return next;
  section := 'market_trims'; check_name := 'catalog_origin';
  actual := (select count(*) from vehicle_trims where origin = 'CATALOG'); return next;
  check_name := 'overlay_origin';
  actual := (select count(*) from vehicle_trims where origin = 'OVERLAY'); return next;
  section := 'price_ledger'; check_name := 'retracted_rows_not_served';
  actual := (select count(*) from vehicle_price_ledger where not in_release); return next;
  section := 'campaigns'; check_name := 'rows';
  actual := (select count(*) from vehicle_campaigns); return next;
  section := 'promotions'; check_name := 'options';
  actual := (select count(*) from vehicle_promotions); return next;
  section := 'spec_facts'; check_name := 'history_rows_not_served';
  actual := (select count(*) from vehicle_facts where not served_in_release); return next;
  check_name := 'provisional_rows';
  actual := (select count(*) from vehicle_facts where verification_status = 'PROVISIONAL'); return next;
  check_name := 'unknown_value_state_rows';
  actual := (select count(*) from vehicle_facts where value_state = 'UNKNOWN'); return next;
  section := 'eco_evidence'; check_name := 'rows';
  actual := (select count(*) from vehicle_eco_evidence); return next;
  section := 'current_retail_sets'; check_name := 'rows';
  actual := (select count(*) from vehicle_current_retail_sets); return next;
  section := 'trim_lifecycle_decisions'; check_name := 'rows';
  actual := (select count(*) from vehicle_trim_lifecycle_decisions); return next;
  section := 'model_operational_states'; check_name := 'rows';
  actual := (select count(*) from vehicle_model_operational_states); return next;
  section := 'legacy_identities'; check_name := 'rows';
  actual := (select count(*) from vehicle_legacy_identities); return next;
end;
$$;

revoke all on function public.vehicle_master_seed_from_release(text, date) from public, anon, authenticated;
revoke all on function public.vehicle_master_seed_supplemental(text, date, text, jsonb) from public, anon, authenticated;
revoke all on function public.vehicle_master_finish_supplemental(text, date, jsonb) from public, anon, authenticated;
revoke all on function public._vehicle_master_supplemental_counts() from public, anon, authenticated;
revoke all on function public.vehicle_master_seed_check() from public, anon, authenticated;
grant execute on function public.vehicle_master_seed_from_release(text, date) to service_role;
grant execute on function public.vehicle_master_seed_supplemental(text, date, text, jsonb) to service_role;
grant execute on function public.vehicle_master_finish_supplemental(text, date, jsonb) to service_role;
grant execute on function public._vehicle_master_supplemental_counts() to service_role;
grant execute on function public.vehicle_master_seed_check() to service_role;
