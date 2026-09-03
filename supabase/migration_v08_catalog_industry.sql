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
