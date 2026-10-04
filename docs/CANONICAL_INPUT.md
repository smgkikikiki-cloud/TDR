# Canonical vehicle input — retired legacy path / DB-master rules

**The flow this document used to describe is retired, as of Vehicle DB v3 Phase 0 step 5
(`supabase/migration_v60_close_legacy_vehicle_write_path.sql`).** This file is kept at this
path because other documents and code comments already link to it. It now records what is
closed and where the current rules live — it is not an active procedure.

## What is retired

- The `/admin/vehicle-input` → `canonical_input_batches` → scheduled worker → staged copy of
  `vehreg/data` → PR → merge → Supabase vehicle release flow this document used to describe.
- `canonical_input_batches`, `canonical_object_map`, `canonical_write_commands`,
  `canonical_publish_outbox`, `canonical_vehicle_releases`, `canonical_vehicle_state`,
  `canonical_release_chunks`, and every `canonical_*_projection` table: **read-only history**.
  `service_role` keeps `SELECT` only on all of them.
- The old enqueue / worker / publish / stage / activate / rollback / prune paths —
  `enqueue-canonical-batch.yml`, `canonical-input.yml`, `vehicle-release.yml`, and the
  `publish_vehicle_release` / `begin_vehicle_release` / `stage_vehicle_release_chunk` /
  `activate_vehicle_release` / `rollback_vehicle_release` / `prune_vehicle_releases` RPCs —
  are fail-fast stubs or now unconditionally raise a "closed (Phase 0 step 5)" error.
  **Do not revive any of them, and do not route a new edit through any of them.**

## What is canonical now

The Supabase **Vehicle Master** tables are the DB master (`vehicle_brands`, `vehicle_models`,
`vehicle_generations`, `vehicle_variants`, `vehicle_trims`, `vehicle_facts`,
`vehicle_price_ledger`, `vehicle_campaigns`, `vehicle_promotions`, and related tables —
`migration_v57` onward; see `docs/vehicle-db/MASTER_TABLES.md`). `current_vehicle_brands`,
`current_vehicle_models`, `current_vehicle_generations`, `current_market_trims`,
`current_price_ledger`, `current_spec_facts` serve from the master (`migration_v58`; see
`docs/vehicle-db/SERVING_CONTRACT.md`) — these views are a read target, never written to
directly.

## No interim writer

**Phase 1 (the new DB-master write layer) is not implemented yet.** Until it exists, do not
route a new vehicle edit through the retired path above, and do not invent an alternative
write mechanism. Future write semantics are governed entirely by
`docs/vehicle-db/VEHICLE_DB_V3.md` — read that document, not this one, before any future
Vehicle Master write-layer work. It covers, among other rules: authority order (`ADMIN` >
`OFFICIAL` > `AI`, lower never overwrites higher); the pipeline
`observations → reconcile → apply/propose → master → change log`; soft delete (delete = hide);
revisioning (every change logged, revert = a new compensating entry); admin authority always
winning with no review queue; and `UNKNOWN != NO` (absence of a row is never written as a "no").

## What is unaffected

- **Registration ingestion** remains a separate input. `source-import.yml` continues to import
  uploaded DLT registration files into `registrations` through
  `tdr_replace_registration_period`; any other uploaded kind (ECO, VEHICLE_SPECS, Retail Lineup
  Bootstrap) is marked `FAILED` with an explicit "closed" message instead of being imported, per
  the same Phase 0 step 5 closure.
- **The daily Vehicle Master backup** (Phase 0 step 6,
  `automotive/vehicle_master/tools/vehicle_master_backup.py`, private Storage bucket
  `vehicle-master-backups`) is export-only, read-only recovery infrastructure. It is not a write
  mechanism, and a backup file must never be edited and re-imported as though it were one.

See `docs/vehicle-db/VEHICLE_DB_V3.md` for the full rule set, `docs/vehicle-db/MASTER_TABLES.md` /
`SERVING_CONTRACT.md` / `ENGINE_RULES.md` for what is live today, and
`supabase/migration_v60_close_legacy_vehicle_write_path.sql` for exactly what was closed and why.
