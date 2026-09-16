-- Canonical official-media storage for Vehicle Master.
-- Assets are content-addressed in the public vehicle-media bucket; metadata
-- remains review-gated so the product only reads approved rows.

create table if not exists public.vehicle_media_assets (
  id bigint generated always as identity primary key,
  vehicle_id text not null,
  visual_key text not null,
  source_url text not null,
  source_type text not null check (source_type in ('manufacturer_media','official_site','press_release')),
  source_domain text not null,
  image_url_original text not null,
  storage_bucket text not null default 'vehicle-media',
  storage_path text not null,
  public_url text not null,
  image_type text not null check (image_type in ('hero','front_3q','rear_3q','side','dashboard','interior','cargo','detail','unknown')),
  market text not null default 'TH',
  model_year integer,
  confidence smallint not null check (confidence between 0 and 100),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  width integer check (width is null or width > 0),
  height integer check (height is null or height > 0),
  status text not null check (status in ('approved','review','rejected')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (visual_key, image_type, sha256)
);

create index if not exists vehicle_media_assets_visual_slot_idx
  on public.vehicle_media_assets (visual_key, image_type, status, confidence desc);
create index if not exists vehicle_media_assets_vehicle_idx
  on public.vehicle_media_assets (vehicle_id);

create table if not exists public.vehicle_media_bindings (
  entity_id text primary key,
  entity_type text not null check (entity_type in ('generation','trim')),
  visual_key text not null,
  inherited_from text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists vehicle_media_bindings_visual_idx
  on public.vehicle_media_bindings (visual_key);

alter table public.vehicle_media_assets enable row level security;
alter table public.vehicle_media_bindings enable row level security;

drop policy if exists "public read approved vehicle media" on public.vehicle_media_assets;
create policy "public read approved vehicle media" on public.vehicle_media_assets
  for select to anon, authenticated using (status = 'approved');

drop policy if exists "public read vehicle media bindings" on public.vehicle_media_bindings;
create policy "public read vehicle media bindings" on public.vehicle_media_bindings
  for select to anon, authenticated using (true);

grant select on public.vehicle_media_assets, public.vehicle_media_bindings to anon, authenticated;
grant all on public.vehicle_media_assets, public.vehicle_media_bindings to service_role;
grant usage, select on sequence public.vehicle_media_assets_id_seq to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'vehicle-media',
  'vehicle-media',
  true,
  20971520,
  array['image/jpeg','image/png','image/webp','image/avif']::text[]
)
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
