-- TDR Automotive Intelligence V1.2
-- Consumer catalog: body dimensions, trim wheel/tire and EV range.
-- Additive only; existing data is preserved.

alter table models add column if not exists length_mm integer;
alter table models add column if not exists width_mm integer;
alter table models add column if not exists wheelbase_mm integer;

alter table trims add column if not exists tire_size_front text;
alter table trims add column if not exists tire_size_rear text;
alter table trims add column if not exists wheel_size_front text;
alter table trims add column if not exists wheel_size_rear text;

alter table trims add column if not exists published_range_km numeric;
alter table trims add column if not exists published_range_cycle text;
alter table trims add column if not exists standardized_wltp_km numeric;
alter table trims add column if not exists standardized_epa_km numeric;
alter table trims add column if not exists range_source_url text;

create index if not exists trims_published_range_idx on trims(published_range_km);
create index if not exists trims_wltp_range_idx on trims(standardized_wltp_km);
