# Vehicle Master repository cutover

## Decision

`smgkikikiki-cloud/TDR` is the only active repository. The original `vehicle-market-master` repository is a read-only historical source after retirement and must not receive commands, data PRs, scheduled jobs, or fixes.

Canonical engine path: `automotive/vehicle_master/`.

## Completed transfer boundary

- Full Python engine, data, tests, tools, docs, Streamlit workbench, Phase 1–4 implementation, Phase 6 fitment contract, and Phase 3 price intelligence P1–P5 live under the canonical path.
- Public TDR catalog reads the active canonical release views, not legacy `models`/`trims` as vehicle authority.
- Vehicle releases include all canonical brands, models, generations, MarketTrims, Price Ledger records, campaign quotes, source references, and comparable spec facts currently present.
- Registration facts remain in their own entitlement boundary and join through reviewed identities only.
- TDR model administration no longer writes duplicate vehicle facts. Vehicle facts are edited in the canonical engine; TDR admin retains editorial/news/industry responsibilities.
- The scheduled price harvester and release publisher run from TDR.

## Active release flow

1. Change canonical data once under `automotive/vehicle_master/vehreg/data/` or use the canonical tools/workbench.
2. Validate the complete engine and release projection in CI.
3. Merge to TDR `main`.
4. `vehicle-release.yml` builds one release JSON and invokes the service-role-only `publish_vehicle_release` RPC.
5. Supabase stages all rows and atomically switches `canonical_vehicle_state.active_release_id`.
6. Every public route sees the same release. Rollback uses `rollback_vehicle_release` and changes only the release pointer.

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
