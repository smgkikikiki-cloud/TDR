create extension if not exists pgcrypto;

create table if not exists brands (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  name_th text not null,
  name_en text,
  country_origin text,
  status text not null default 'active',
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists plants (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  name_th text not null,
  name_en text,
  maker_group text,
  province text,
  district text,
  capacity_annual integer,
  opened_year integer,
  status text not null default 'active',
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists companies (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  name_th text not null,
  name_en text,
  company_type text not null default 'supplier',
  parent_company text,
  province text,
  products_services text,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists models (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  brand_id uuid references brands(id) on delete set null,
  name_th text not null,
  name_en text,
  generation text,
  body_type text,
  segment text,
  market_position text,
  powertrain text,
  powertrains text[] not null default '{}',
  production_type text,
  production_country text,
  thai_plant_id uuid references plants(id) on delete set null,
  launch_month smallint,
  launch_year smallint,
  launch_date date,
  sop_date date,
  eop_date date,
  status text,
  upcoming_status text,
  unconfirmed_fields text[] not null default '{}',
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists model_plants (
  model_id uuid not null references models(id) on delete cascade,
  plant_id uuid not null references plants(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (model_id, plant_id)
);

create table if not exists events (
  id uuid primary key default gen_random_uuid(),
  title_th text not null,
  title_en text,
  event_date date not null default current_date,
  event_type text not null default 'news',
  summary_th text,
  source_name text,
  source_url text,
  related_brand_id uuid references brands(id) on delete set null,
  related_model_id uuid references models(id) on delete set null,
  related_plant_id uuid references plants(id) on delete set null,
  related_company_id uuid references companies(id) on delete set null,
  published boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists sources (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  publisher text,
  url text not null,
  published_date date,
  retrieved_at timestamptz not null default now(),
  notes text,
  created_at timestamptz not null default now()
);

create table if not exists entity_sources (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references sources(id) on delete cascade,
  entity_type text not null check (entity_type in ('brand','model','plant','company','event')),
  entity_id uuid not null,
  fact_note text,
  confidence text default 'confirmed',
  created_at timestamptz not null default now()
);

create table if not exists registrations (
  id uuid primary key default gen_random_uuid(),
  period date not null,
  brand_name_raw text not null,
  model_name_raw text not null,
  model_id uuid references models(id) on delete set null,
  registrations integer not null,
  source_id uuid references sources(id) on delete set null,
  created_at timestamptz not null default now(),
  unique(period, brand_name_raw, model_name_raw)
);

create index if not exists models_brand_idx on models(brand_id);
create index if not exists models_plant_idx on models(thai_plant_id);
create index if not exists model_plants_model_idx on model_plants(model_id);
create index if not exists model_plants_plant_idx on model_plants(plant_id);
create index if not exists models_launch_period_idx on models(launch_year, launch_month);
create index if not exists models_launch_idx on models(launch_date);
create index if not exists events_date_idx on events(event_date desc);
create index if not exists registrations_period_idx on registrations(period);

create or replace function set_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

do $$ begin
  create trigger brands_updated before update on brands for each row execute function set_updated_at();
exception when duplicate_object then null; end $$;
do $$ begin
  create trigger plants_updated before update on plants for each row execute function set_updated_at();
exception when duplicate_object then null; end $$;
do $$ begin
  create trigger companies_updated before update on companies for each row execute function set_updated_at();
exception when duplicate_object then null; end $$;
do $$ begin
  create trigger models_updated before update on models for each row execute function set_updated_at();
exception when duplicate_object then null; end $$;
do $$ begin
  create trigger events_updated before update on events for each row execute function set_updated_at();
exception when duplicate_object then null; end $$;

alter table brands enable row level security;
alter table plants enable row level security;
alter table companies enable row level security;
alter table models enable row level security;
alter table events enable row level security;
alter table model_plants enable row level security;
alter table sources enable row level security;
alter table entity_sources enable row level security;
alter table registrations enable row level security;

do $$ begin create policy "public read brands" on brands for select using (true); exception when duplicate_object then null; end $$;
do $$ begin create policy "public read plants" on plants for select using (true); exception when duplicate_object then null; end $$;
do $$ begin create policy "public read companies" on companies for select using (true); exception when duplicate_object then null; end $$;
do $$ begin create policy "public read models" on models for select using (true); exception when duplicate_object then null; end $$;
do $$ begin create policy "public read model_plants" on model_plants for select using (true); exception when duplicate_object then null; end $$;
do $$ begin create policy "public read published events" on events for select using (published = true); exception when duplicate_object then null; end $$;
-- sources, entity_sources and registrations remain private to the service-role/admin layer by default.
-- TDR Automotive Intelligence V0.5
-- Run this ONCE in Supabase SQL Editor after the original schema.sql.

alter table plants add column if not exists maker_group text;

alter table models add column if not exists market_position text;
alter table models add column if not exists powertrains text[] not null default '{}';
alter table models add column if not exists launch_month smallint;
alter table models add column if not exists launch_year smallint;

-- Unknown is a legitimate state for upcoming / incomplete records.
alter table models alter column status drop not null;

-- Keep old V0 columns for backwards compatibility, but the editor no longer uses them.
-- powertrain, thai_plant_id, launch_date, sop_date, eop_date remain in place for now.

-- Migrate any simple legacy powertrain value into the new multi-value field.
update models
set powertrains = regexp_split_to_array(upper(trim(powertrain)), E'\\s*/\\s*|\\s*,\\s*')
where coalesce(array_length(powertrains, 1), 0) = 0
  and powertrain is not null
  and trim(powertrain) <> '';

create table if not exists model_plants (
  model_id uuid not null references models(id) on delete cascade,
  plant_id uuid not null references plants(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (model_id, plant_id)
);

insert into model_plants (model_id, plant_id)
select id, thai_plant_id from models
where thai_plant_id is not null
on conflict do nothing;

alter table model_plants enable row level security;
do $$ begin
  create policy "public read model_plants" on model_plants for select using (true);
exception when duplicate_object then null; end $$;

create index if not exists model_plants_model_idx on model_plants(model_id);
create index if not exists model_plants_plant_idx on model_plants(plant_id);
create index if not exists models_launch_period_idx on models(launch_year, launch_month);

-- Preload major Thai vehicle assembly plants. These are editable in Admin later.
insert into plants (slug, name_th, name_en, maker_group, province, district, capacity_annual, status)
values
  ('toyota-samrong', 'Toyota Samrong', 'Toyota Samrong Plant', 'Toyota', 'สมุทรปราการ', 'พระประแดง', 240000, 'active'),
  ('toyota-gateway', 'Toyota Gateway', 'Toyota Gateway Plant', 'Toyota', 'ฉะเชิงเทรา', 'แปลงยาว', 300000, 'active'),
  ('toyota-ban-pho', 'Toyota Ban Pho', 'Toyota Ban Pho Plant', 'Toyota', 'ฉะเชิงเทรา', 'บ้านโพธิ์', 230000, 'active'),
  ('honda-prachinburi', 'Honda Prachinburi', 'Honda Automobile Prachinburi Plant', 'Honda', 'ปราจีนบุรี', null, null, 'active'),
  ('isuzu-samrong', 'Isuzu Samrong', 'Isuzu Motors Thailand Samrong Plant', 'Isuzu', 'สมุทรปราการ', 'พระประแดง', null, 'active'),
  ('isuzu-gateway', 'Isuzu Gateway', 'Isuzu Motors Thailand Gateway Plant', 'Isuzu', 'ฉะเชิงเทรา', 'แปลงยาว', null, 'active'),
  ('mitsubishi-laem-chabang-1', 'Mitsubishi Laem Chabang Plant 1', 'Mitsubishi Motors Thailand Laem Chabang Plant 1', 'Mitsubishi', 'ชลบุรี', 'ศรีราชา', null, 'active'),
  ('mitsubishi-laem-chabang-2', 'Mitsubishi Laem Chabang Plant 2', 'Mitsubishi Motors Thailand Laem Chabang Plant 2', 'Mitsubishi', 'ชลบุรี', 'ศรีราชา', null, 'active'),
  ('mitsubishi-laem-chabang-3', 'Mitsubishi Laem Chabang Plant 3', 'Mitsubishi Motors Thailand Laem Chabang Plant 3', 'Mitsubishi', 'ชลบุรี', 'ศรีราชา', null, 'active'),
  ('ford-thailand-manufacturing', 'Ford Thailand Manufacturing (FTM)', 'Ford Thailand Manufacturing', 'Ford', 'ระยอง', 'ปลวกแดง', 135000, 'active'),
  ('autoalliance-thailand', 'AutoAlliance Thailand (AAT)', 'AutoAlliance Thailand', 'Ford / Mazda', 'ระยอง', 'ปลวกแดง', 270000, 'active'),
  ('nissan-samut-prakan', 'Nissan Samut Prakan', 'Nissan Motor Thailand Samut Prakan Plant', 'Nissan', 'สมุทรปราการ', null, null, 'active'),
  ('gwm-rayong', 'GWM Rayong Smart Factory', 'GWM Rayong New Energy Factory', 'GWM', 'ระยอง', 'ปลวกแดง', 80000, 'active'),
  ('byd-rayong', 'BYD Thailand Rayong', 'BYD Thailand Factory', 'BYD', 'ระยอง', null, 150000, 'active'),
  ('saic-motor-cp-chonburi', 'SAIC Motor-CP Chonburi', 'SAIC Motor-CP Plant', 'MG', 'ชลบุรี', null, 100000, 'active'),
  ('changan-rayong', 'CHANGAN Rayong', 'CHANGAN Automobile Rayong Factory', 'CHANGAN', 'ระยอง', null, null, 'active'),
  ('gac-aion-rayong', 'GAC AION Rayong', 'GAC AION Thailand Smart Factory', 'GAC AION', 'ระยอง', null, null, 'active'),
  ('neta-bangchan-bgac', 'NETA / Bangchan General Assembly', 'NETA / Bangchan General Assembly Plant', 'NETA', 'กรุงเทพมหานคร', null, 30000, 'active'),
  ('bmw-rayong', 'BMW Group Manufacturing Thailand', 'BMW Group Manufacturing Thailand Rayong Plant', 'BMW / MINI', 'ระยอง', null, null, 'active'),
  ('thonburi-automotive-assembly', 'Thonburi Automotive Assembly Plant', 'Thonburi Automotive Assembly Plant', 'Mercedes-Benz', 'สมุทรปราการ', 'เมืองสมุทรปราการ', null, 'active')
on conflict (slug) do update set
  name_th = excluded.name_th,
  name_en = excluded.name_en,
  maker_group = excluded.maker_group,
  province = excluded.province,
  district = excluded.district,
  capacity_annual = coalesce(excluded.capacity_annual, plants.capacity_annual),
  status = excluded.status;
-- TDR Automotive Intelligence V0.5
-- Run this ONCE in Supabase SQL Editor after the original schema.sql.

alter table plants add column if not exists maker_group text;

alter table models add column if not exists market_position text;
alter table models add column if not exists powertrains text[] not null default '{}';
alter table models add column if not exists launch_month smallint;
alter table models add column if not exists launch_year smallint;

-- Unknown is a legitimate state for upcoming / incomplete records.
alter table models alter column status drop not null;

-- Keep old V0 columns for backwards compatibility, but the editor no longer uses them.
-- powertrain, thai_plant_id, launch_date, sop_date, eop_date remain in place for now.

-- Migrate any simple legacy powertrain value into the new multi-value field.
update models
set powertrains = regexp_split_to_array(upper(trim(powertrain)), E'\\s*/\\s*|\\s*,\\s*')
where coalesce(array_length(powertrains, 1), 0) = 0
  and powertrain is not null
  and trim(powertrain) <> '';

create table if not exists model_plants (
  model_id uuid not null references models(id) on delete cascade,
  plant_id uuid not null references plants(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (model_id, plant_id)
);

insert into model_plants (model_id, plant_id)
select id, thai_plant_id from models
where thai_plant_id is not null
on conflict do nothing;

alter table model_plants enable row level security;
do $$ begin
  create policy "public read model_plants" on model_plants for select using (true);
exception when duplicate_object then null; end $$;

create index if not exists model_plants_model_idx on model_plants(model_id);
create index if not exists model_plants_plant_idx on model_plants(plant_id);
create index if not exists models_launch_period_idx on models(launch_year, launch_month);

-- Preload major Thai vehicle assembly plants. These are editable in Admin later.
insert into plants (slug, name_th, name_en, maker_group, province, district, capacity_annual, status)
values
  ('toyota-samrong', 'Toyota Samrong', 'Toyota Samrong Plant', 'Toyota', 'สมุทรปราการ', 'พระประแดง', 240000, 'active'),
  ('toyota-gateway', 'Toyota Gateway', 'Toyota Gateway Plant', 'Toyota', 'ฉะเชิงเทรา', 'แปลงยาว', 300000, 'active'),
  ('toyota-ban-pho', 'Toyota Ban Pho', 'Toyota Ban Pho Plant', 'Toyota', 'ฉะเชิงเทรา', 'บ้านโพธิ์', 230000, 'active'),
  ('honda-prachinburi', 'Honda Prachinburi', 'Honda Automobile Prachinburi Plant', 'Honda', 'ปราจีนบุรี', null, null, 'active'),
  ('isuzu-samrong', 'Isuzu Samrong', 'Isuzu Motors Thailand Samrong Plant', 'Isuzu', 'สมุทรปราการ', 'พระประแดง', null, 'active'),
  ('isuzu-gateway', 'Isuzu Gateway', 'Isuzu Motors Thailand Gateway Plant', 'Isuzu', 'ฉะเชิงเทรา', 'แปลงยาว', null, 'active'),
  ('mitsubishi-laem-chabang-1', 'Mitsubishi Laem Chabang Plant 1', 'Mitsubishi Motors Thailand Laem Chabang Plant 1', 'Mitsubishi', 'ชลบุรี', 'ศรีราชา', null, 'active'),
  ('mitsubishi-laem-chabang-2', 'Mitsubishi Laem Chabang Plant 2', 'Mitsubishi Motors Thailand Laem Chabang Plant 2', 'Mitsubishi', 'ชลบุรี', 'ศรีราชา', null, 'active'),
  ('mitsubishi-laem-chabang-3', 'Mitsubishi Laem Chabang Plant 3', 'Mitsubishi Motors Thailand Laem Chabang Plant 3', 'Mitsubishi', 'ชลบุรี', 'ศรีราชา', null, 'active'),
  ('ford-thailand-manufacturing', 'Ford Thailand Manufacturing (FTM)', 'Ford Thailand Manufacturing', 'Ford', 'ระยอง', 'ปลวกแดง', 135000, 'active'),
  ('autoalliance-thailand', 'AutoAlliance Thailand (AAT)', 'AutoAlliance Thailand', 'Ford / Mazda', 'ระยอง', 'ปลวกแดง', 270000, 'active'),
  ('nissan-samut-prakan', 'Nissan Samut Prakan', 'Nissan Motor Thailand Samut Prakan Plant', 'Nissan', 'สมุทรปราการ', null, null, 'active'),
  ('gwm-rayong', 'GWM Rayong Smart Factory', 'GWM Rayong New Energy Factory', 'GWM', 'ระยอง', 'ปลวกแดง', 80000, 'active'),
  ('byd-rayong', 'BYD Thailand Rayong', 'BYD Thailand Factory', 'BYD', 'ระยอง', null, 150000, 'active'),
  ('saic-motor-cp-chonburi', 'SAIC Motor-CP Chonburi', 'SAIC Motor-CP Plant', 'MG', 'ชลบุรี', null, 100000, 'active'),
  ('changan-rayong', 'CHANGAN Rayong', 'CHANGAN Automobile Rayong Factory', 'CHANGAN', 'ระยอง', null, null, 'active'),
  ('gac-aion-rayong', 'GAC AION Rayong', 'GAC AION Thailand Smart Factory', 'GAC AION', 'ระยอง', null, null, 'active'),
  ('neta-bangchan-bgac', 'NETA / Bangchan General Assembly', 'NETA / Bangchan General Assembly Plant', 'NETA', 'กรุงเทพมหานคร', null, 30000, 'active'),
  ('bmw-rayong', 'BMW Group Manufacturing Thailand', 'BMW Group Manufacturing Thailand Rayong Plant', 'BMW / MINI', 'ระยอง', null, null, 'active'),
  ('thonburi-automotive-assembly', 'Thonburi Automotive Assembly Plant', 'Thonburi Automotive Assembly Plant', 'Mercedes-Benz', 'สมุทรปราการ', 'เมืองสมุทรปราการ', null, 'active')
on conflict (slug) do update set
  name_th = excluded.name_th,
  name_en = excluded.name_en,
  maker_group = excluded.maker_group,
  province = excluded.province,
  district = excluded.district,
  capacity_annual = coalesce(excluded.capacity_annual, plants.capacity_annual),
  status = excluded.status;

-- V0.6: field-level uncertainty flags. Each value is the field key that is currently unconfirmed.
alter table models add column if not exists unconfirmed_fields text[] not null default '{}';
create index if not exists models_unconfirmed_fields_gin_idx on models using gin(unconfirmed_fields);
-- TDR Automotive Intelligence V0.8
-- Consumer catalog + Thailand production / industrial dossier layer.
-- Safe to run after schema.sql / migration_v06_model_editor.sql.

alter table brands add column if not exists logo_url text;

alter table models add column if not exists image_url text;
alter table models add column if not exists consumer_description text;
alter table models add column if not exists retail_price_min integer;
alter table models add column if not exists retail_price_max integer;
alter table models add column if not exists retail_price_updated_month smallint;
alter table models add column if not exists retail_price_updated_year smallint;
alter table models add column if not exists dlt_aliases text[] not null default '{}';

alter table plants add column if not exists address_text text;
alter table plants add column if not exists estimated_production_annual integer;
alter table plants add column if not exists utilization_estimate_year smallint;
alter table plants add column if not exists capacity_note text;

create table if not exists production_programs (
  id uuid primary key default gen_random_uuid(),
  model_id uuid not null references models(id) on delete cascade,
  plant_id uuid references plants(id) on delete set null,
  production_type text,
  status text,
  platform text,
  story_th text,
  sop_month smallint,
  sop_year smallint,
  eop_month smallint,
  eop_year smallint,
  annual_production_estimate integer,
  production_volume_year smallint,
  export_volume_estimate integer,
  export_volume_year smallint,
  export_markets text,
  source_name text,
  source_url text,
  unconfirmed_fields text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists model_powertrains (
  id uuid primary key default gen_random_uuid(),
  model_id uuid not null references models(id) on delete cascade,
  label text,
  powertrain_type text,
  engine_code text,
  displacement_cc integer,
  engine_description text,
  motor_description text,
  battery_description text,
  system_output_ps numeric,
  transmission text,
  drivetrain text,
  notes text,
  unconfirmed_fields text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists local_content_declarations (
  id uuid primary key default gen_random_uuid(),
  production_program_id uuid not null references production_programs(id) on delete cascade,
  percentage numeric,
  announced_by text,
  announcement_month smallint,
  announcement_year smallint,
  source_name text,
  source_url text,
  unconfirmed boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists mit_approvals (
  id uuid primary key default gen_random_uuid(),
  production_program_id uuid not null references production_programs(id) on delete cascade,
  approved boolean not null default true,
  valid_from_year smallint,
  valid_to_year smallint,
  reference_note text,
  source_name text,
  source_url text,
  unconfirmed boolean not null default false,
  created_at timestamptz not null default now()
);

create index if not exists production_programs_model_idx on production_programs(model_id);
create index if not exists production_programs_plant_idx on production_programs(plant_id);
create index if not exists model_powertrains_model_idx on model_powertrains(model_id);
create index if not exists local_content_program_idx on local_content_declarations(production_program_id);
create index if not exists mit_program_idx on mit_approvals(production_program_id);

alter table production_programs enable row level security;
alter table model_powertrains enable row level security;
alter table local_content_declarations enable row level security;
alter table mit_approvals enable row level security;

do $$ begin create policy "public read production_programs" on production_programs for select using (true); exception when duplicate_object then null; end $$;
do $$ begin create policy "public read model_powertrains" on model_powertrains for select using (true); exception when duplicate_object then null; end $$;
do $$ begin create policy "public read local_content_declarations" on local_content_declarations for select using (true); exception when duplicate_object then null; end $$;
do $$ begin create policy "public read mit_approvals" on mit_approvals for select using (true); exception when duplicate_object then null; end $$;

do $$ begin create trigger production_programs_updated before update on production_programs for each row execute function set_updated_at(); exception when duplicate_object then null; end $$;
do $$ begin create trigger model_powertrains_updated before update on model_powertrains for each row execute function set_updated_at(); exception when duplicate_object then null; end $$;

-- Consumer model pages may show registration figures. Raw import/admin remain write-protected.
do $$ begin create policy "public read registrations" on registrations for select using (true); exception when duplicate_object then null; end $$;
-- TDR Automotive Intelligence V1.0 model-editor cleanup
-- Add quarter-based launch field. Old date/month columns are intentionally left in place for compatibility but are no longer used by the editor.
alter table models add column if not exists launch_quarter text;
-- TDR Automotive Intelligence V1.1
-- Consumer-facing catalog + structured powertrain + trims.
-- Additive migration: keeps existing records and compatibility columns.

alter table models add column if not exists seats integer;
alter table models add column if not exists payload_capacity_kg numeric;
alter table models add column if not exists featured boolean not null default false;
alter table models add column if not exists image_url text;
alter table models add column if not exists consumer_description text;
alter table models add column if not exists launch_quarter text;
alter table models add column if not exists unconfirmed_fields text[] not null default '{}';

alter table brands add column if not exists logo_url text;

create table if not exists model_powertrains (
  id uuid primary key default gen_random_uuid(),
  model_id uuid not null references models(id) on delete cascade,
  label text,
  powertrain_type text,
  engine_code text,
  displacement_cc integer,
  battery_capacity_kwh numeric,
  battery_chemistry text,
  motor_output_kw numeric,
  horsepower_ps numeric,
  torque_nm numeric,
  engine_description text,
  motor_description text,
  battery_description text,
  system_output_ps numeric,
  transmission text,
  drivetrain text,
  notes text,
  unconfirmed_fields text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table model_powertrains add column if not exists battery_capacity_kwh numeric;
alter table model_powertrains add column if not exists battery_chemistry text;
alter table model_powertrains add column if not exists motor_output_kw numeric;
alter table model_powertrains add column if not exists horsepower_ps numeric;
alter table model_powertrains add column if not exists torque_nm numeric;
alter table model_powertrains add column if not exists unconfirmed_fields text[] not null default '{}';

create table if not exists trims (
  id uuid primary key default gen_random_uuid(),
  model_id uuid not null references models(id) on delete cascade,
  name text not null,
  price_baht integer,
  status text not null default 'current',
  description text,
  seats_override integer,
  payload_capacity_kg_override numeric,
  sort_order integer not null default 0,
  unconfirmed_fields text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists trim_powertrains (
  trim_id uuid not null references trims(id) on delete cascade,
  powertrain_id uuid not null references model_powertrains(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (trim_id, powertrain_id)
);

create index if not exists model_powertrains_model_idx on model_powertrains(model_id);
create index if not exists trims_model_idx on trims(model_id);
create index if not exists trims_status_idx on trims(status);
create index if not exists trim_powertrains_trim_idx on trim_powertrains(trim_id);
create index if not exists trim_powertrains_powertrain_idx on trim_powertrains(powertrain_id);

alter table trims enable row level security;
alter table trim_powertrains enable row level security;
alter table model_powertrains enable row level security;

do $$ begin create policy "public read trims" on trims for select using (true); exception when duplicate_object then null; end $$;
do $$ begin create policy "public read trim_powertrains" on trim_powertrains for select using (true); exception when duplicate_object then null; end $$;
do $$ begin create policy "public read model_powertrains" on model_powertrains for select using (true); exception when duplicate_object then null; end $$;

do $$ begin create trigger trims_updated before update on trims for each row execute function set_updated_at(); exception when duplicate_object then null; end $$;
do $$ begin create trigger model_powertrains_updated before update on model_powertrains for each row execute function set_updated_at(); exception when duplicate_object then null; end $$;

-- Normalize legacy market-status values from early prototypes.
update models set status='current' where status is null or status in ('on_sale','upcoming','active');
