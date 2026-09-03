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
