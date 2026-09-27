# TDR repository instructions

`smgkikikiki-cloud/TDR` is the single active repository for TDR Automotive Intelligence.

## Canonical vehicle boundary

All vehicle market facts belong under `automotive/vehicle_master/`, including Brand, Model, Generation, Variant, MarketTrim, exact powertrain, specifications, fitment, source evidence, Price Ledger, campaigns, ECO ingestion, DLT resolution, canonical releases, and price harvesting.

Registration facts remain separate from MarketTrim and join only through reviewed identities. TDR editorial, news, industry, plant, company, and analytical surfaces may reference canonical vehicle IDs but must not redefine canonical vehicle facts.

## Persistent execution state

For any long-running multi-step TDR audit, data repair, batch, migration, or agent handoff, read `docs/WORK_STATE.md` before continuing work.

`docs/WORK_STATE.md` is the execution source of truth for batch identity, frozen/approved work, active step, and next action. Do not infer these from chat memory alone.

Rules:
- approved/frozen work must not be re-audited unless the user explicitly reopens it;
- historical audit lot numbers and repair lot numbers are separate namespaces and must not be conflated;
- an implementation prompt must carry every recorded required change 1:1;
- do not silently add scope, repeat research already completed for the active step, or guess unresolved batch membership;
- after completing a step, update `docs/WORK_STATE.md` so the next agent inherits the correct state.

## Retired repository prohibition

`smgkikikiki-cloud/vehicle-market-master` is historical only. Do not route implementation tasks, fixes, data updates, workflows, repository dispatches, scheduled jobs, pull requests, issues, or agent commands to it. Do not revive automation there.

When a task mentions Vehicle Master, treat `automotive/vehicle_master/` inside this repository as the target unless the user explicitly asks to inspect historical material.
