-- Phase 3 preflight fix #1: registration_observations_v2 must actually be
-- immutable, not merely documented as such.
--
-- migration_v29 granted service_role select/insert/update/delete on all
-- three DLT v2 shadow tables uniformly. That let ordinary tooling UPDATE a
-- raw observation row in place -- if a source's payload changed under an
-- unchanged observation_id (a re-fetched DLT month whose figures were
-- revised, say), a merge-upsert would silently overwrite the original
-- evidence with no record anything had changed. This migration closes that
-- gap at two independent layers:
--
--   1. Grants: service_role loses UPDATE/DELETE on
--      registration_observations_v2 entirely -- only SELECT/INSERT remain.
--      Ordinary tooling (the backfill/DLT-ingest CLIs) can now only ever
--      plain-INSERT a row, never modify or remove one.
--   2. A BEFORE UPDATE/DELETE trigger that unconditionally raises, as
--      defense in depth beyond grants alone -- a small, ordinary trigger
--      function, not an event-sourcing system.
--
-- registration_facts_v2 and registration_resolution_review_v2 are
-- unaffected: they are derived from an observation and are expected to be
-- regenerated/upserted freely as resolution logic improves
-- (vehreg/registration_v2_writer.py's own "fact/review rows remain derived"
-- rule) -- only the raw observation is write-once.
--
-- The write-side half of this invariant (detecting a same-id, different-
-- payload conflict *before* ever attempting a write, and blocking the whole
-- run when one exists) lives in
-- vehreg/registration_v2_writer.py::plan_observation_writes/writes_to_apply
-- -- this migration is what makes the database itself refuse the write even
-- if that Python-side check were ever bypassed or had a bug.

create or replace function public.reject_registration_observation_v2_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'registration_observations_v2 rows are immutable: % is not permitted (id=%). '
    'A changed source payload under the same observation_id is a source-drift conflict, not an '
    'update -- see vehreg/registration_v2_writer.py::plan_observation_writes.',
    tg_op, coalesce(old.observation_id, 'unknown');
end;
$$;

drop trigger if exists registration_observations_v2_immutable on public.registration_observations_v2;
create trigger registration_observations_v2_immutable
  before update or delete on public.registration_observations_v2
  for each row execute function public.reject_registration_observation_v2_mutation();

revoke update, delete on table public.registration_observations_v2 from service_role;
grant select, insert on table public.registration_observations_v2 to service_role;

comment on table public.registration_observations_v2 is
  'DLT v2 shadow pipeline (Phase 2/3): immutable raw source rows, one per DLT/legacy-registration observation. Write-once -- service_role holds only SELECT/INSERT (see migration_v30), and a trigger rejects UPDATE/DELETE unconditionally. A changed source payload under an existing observation_id is a source-drift conflict to be reported, never a silent overwrite. Internal/service-role only - not a new public API. Does not affect registrations, registration_brand_aliases, registration_model_aliases, match_registration_model, or any registration_* analytics view.';
