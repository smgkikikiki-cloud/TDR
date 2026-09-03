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
