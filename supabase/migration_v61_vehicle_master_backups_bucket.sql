-- Vehicle DB v3, Phase 0 step 6: private Storage bucket for daily Vehicle
-- Master backups (docs/vehicle-db/VEHICLE_DB_V3.md §2.6).
--
-- This migration only creates the bucket. It does not touch any vehicle_*
-- table, any legacy canonical_* table, or any existing RPC -- the exporter
-- (automotive/vehicle_master/tools/vehicle_master_backup.py) reads the
-- vehicle_* tables with plain SELECTs through PostgREST and uploads here
-- with the service-role key. No anon/authenticated grant is added on this
-- bucket or on storage.objects/storage.buckets, so the default RLS-deny
-- behaviour applies -- the same pattern as the existing private
-- 'source-imports' (migration_v46) and 'retail-lineup-exports'
-- (migration_v55) buckets.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('vehicle-master-backups', 'vehicle-master-backups', false, 536870912,
        array['application/gzip', 'application/json'])
on conflict (id) do update
set name = excluded.name,
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
