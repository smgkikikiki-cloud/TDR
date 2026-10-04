# Canonical vehicle publishing — retired (Vehicle DB v3 Phase 0 step 5)

The file-backed release flow this README used to describe (`python -m tdr_bridge.release` →
the service-role-only `publish_vehicle_release` RPC) is **retired**, as of Vehicle DB v3 Phase 0
step 5 (`supabase/migration_v60_close_legacy_vehicle_write_path.sql`). `publish_vehicle_release`
and the other release RPCs now unconditionally raise a "closed (Phase 0 step 5)" error — do not
invoke them, and do not edit `vehreg/data/` as a write path.

The Supabase **Vehicle Master** tables (`migration_v57` onward) are the canonical source of
truth now; the `current_*` views serve from them. See `docs/CANONICAL_INPUT.md` for exactly
what is retired and `docs/vehicle-db/VEHICLE_DB_V3.md` for the live rule set — there is no
supported Vehicle Master write layer yet (Phase 1 is not implemented).

Registration rows never create MarketTrim records. They are a separate paid analytics input
joined through the reviewed canonical-to-TDR crosswalk.
