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
