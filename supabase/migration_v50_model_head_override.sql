-- Model head override within the existing media tables.
-- An empty model binding is an intentional blank and suppresses generation fallback.
alter table public.vehicle_media_bindings
  drop constraint if exists vehicle_media_bindings_entity_type_check;
alter table public.vehicle_media_bindings
  add constraint vehicle_media_bindings_entity_type_check
  check (entity_type in ('model','generation','trim'));

alter table public.vehicle_media_assets
  drop constraint if exists vehicle_media_assets_source_type_check;
alter table public.vehicle_media_assets
  add constraint vehicle_media_assets_source_type_check
  check (source_type in ('manufacturer_media','official_site','press_release','automotive_publication','manual'));
