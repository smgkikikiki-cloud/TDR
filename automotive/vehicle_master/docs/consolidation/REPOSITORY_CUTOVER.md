# Vehicle Master repository cutover

## Decision

`smgkikikiki-cloud/TDR` is the only active repository. The original `vehicle-market-master` repository is a read-only historical source after retirement and must not receive commands, data PRs, scheduled jobs, or fixes.

Canonical engine path: `automotive/vehicle_master/`.

## Completed transfer boundary

- Full Python engine, data, tests, tools, docs, Streamlit workbench, Phase 1–4 implementation, Phase 6 fitment contract, and Phase 3 price intelligence P1–P5 live under the canonical path.
- Public TDR catalog reads the active canonical release views, not legacy `models`/`trims` as vehicle authority.
- Vehicle releases include all canonical brands, models, generations, MarketTrims, Price Ledger records, campaign quotes, source references, and comparable spec facts currently present.
- Registration facts remain in their own entitlement boundary and join through reviewed identities only.
- TDR model administration no longer writes duplicate vehicle facts. Vehicle facts are authoritative in the Supabase Vehicle Master DB (see the retirement note below); `automotive/vehicle_master/` is engine/tooling code, not a file-backed authority, and no active Vehicle Master writer exists yet (Phase 1 is not started). TDR admin retains editorial/news/industry responsibilities.
- The legacy scheduled price harvester and release publisher that used to run from TDR are retired/closed (see the retirement note below).

## Release flow — retired (Vehicle DB v3 Phase 0 step 5)

The six-step file/release flow this section used to describe (edit `vehreg/data/` → CI → merge
→ `vehicle-release.yml` → `publish_vehicle_release` RPC → `canonical_vehicle_state` pointer
switch → rollback via `rollback_vehicle_release`) is **retired**, as of
`supabase/migration_v60_close_legacy_vehicle_write_path.sql`. Every RPC it named now
unconditionally raises a "closed (Phase 0 step 5)" error; `vehicle-release.yml` is a fail-fast
stub. Do not revive any of it.

The Supabase Vehicle Master tables (`migration_v57` onward) are the canonical source of truth
now, and `current_*` serves from them (`migration_v58`). See `docs/CANONICAL_INPUT.md` for what
is retired and `docs/vehicle-db/VEHICLE_DB_V3.md` for the live rule set — there is no supported
Vehicle Master write layer yet (Phase 1 is not implemented).

## Routing prohibition

Do not add repository dispatch, reusable workflow, checkout, push, pull request, issue automation, bot instruction, or scheduled job whose target is `vehicle-market-master`. CI scans active routing files for the retired repository name. Historical attribution in import documentation is allowed.

## Retirement gates

The old repository may be archived only after all gates are green:

- TDR `main` contains the canonical engine and current data.
- Canonical release builds and publishes from TDR.
- Public pages read canonical release views.
- Direct duplicate vehicle-fact editing in TDR is disabled.
- Price and release workflows exist in TDR and pass CI.
- No active workflow or command route targets the old repository.

After archiving, preserve history. Do not delete the old repository.
