-- Wire the owner-authoritative Retail Lineup Bootstrap workbook into the
-- existing durable import_runs queue. The source-import workflow routes this
-- kind to its own compile-only worker before the ordinary import worker runs.

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
    'VEHICLE_SPECS'::text,
    'RETAIL_LINEUP_BOOTSTRAP'::text
  ]));
