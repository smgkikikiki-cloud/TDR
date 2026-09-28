-- Applied to Supabase project TDR Auto on 2026-09-28.
-- Required so /admin/import can create import_runs rows for the deterministic
-- canonical Vehicle Specs workbook importer.

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
