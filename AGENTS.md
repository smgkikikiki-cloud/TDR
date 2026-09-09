# TDR repository instructions

`smgkikikiki-cloud/TDR` is the single active repository for TDR Automotive Intelligence.

## Canonical vehicle boundary

All vehicle market facts belong under `automotive/vehicle_master/`, including Brand, Model, Generation, Variant, MarketTrim, exact powertrain, specifications, fitment, source evidence, Price Ledger, campaigns, ECO ingestion, DLT resolution, canonical releases, and price harvesting.

Registration facts remain separate from MarketTrim and join only through reviewed identities. TDR editorial, news, industry, plant, company, and analytical surfaces may reference canonical vehicle IDs but must not redefine canonical vehicle facts.

## Retired repository prohibition

`smgkikikiki-cloud/vehicle-market-master` is historical only. Do not route implementation tasks, fixes, data updates, workflows, repository dispatches, scheduled jobs, pull requests, issues, or agent commands to it. Do not revive automation there.

When a task mentions Vehicle Master, treat `automotive/vehicle_master/` inside this repository as the target unless the user explicitly asks to inspect historical material.
