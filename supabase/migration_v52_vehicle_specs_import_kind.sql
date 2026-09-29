-- Allow the deterministic canonical Vehicle Specs workbook importer to create
-- import_runs rows. Production already received the equivalent migration when
-- the feature was developed; this file makes the schema change reproducible.

alter table public.import_runs
  drop constraint if exists import_runs_source_kind_check;

alter table public.import_runs
  add constraint import_runs_source_kind_check
  check (source_kind = any (array[
    'ECO'::text,
    'OEM'::text,
    'MEDIA'::text,
    'DLT'::text,
    'PRICE'::text,
    'VEHICLE_SPECS'::text
  ]));
