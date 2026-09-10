# Step 6 — Admin parity / legacy retirement gate

This step moves legacy analyst and operator surfaces into the existing TDR Admin shell without creating a second vehicle master.

## New TDR Admin surfaces

- `/admin/market` — full registration market structure/movement diagnostics
- `/admin/registrations` — snapshot preview/ingest and reviewed DLT crosswalk queue
- `/admin/prices` — active canonical price/campaign/history inspection
- `/admin/data-quality` — explicit feature-parity and retirement gate

## Source boundaries

- Vehicle identity/spec/price authority remains `automotive/vehicle_master/vehreg/data`.
- Supabase canonical release tables are serving projections.
- Registration facts and registration-only aliases remain a separate input/crosswalk domain.
- Paid and Admin market ranking share the pure `lib/registration-market.ts` aggregation contract.

## Do not retire Streamlit yet

Red parity gates remain:

1. canonical queued commands for price supersede/retract/close and campaign maintenance;
2. period-aware price/import/origin facets in web analytics;
3. full historical registration backfill (old warehouse begins in 2021);
4. province/regional fact grain;
5. raw-trend full-filter semantics (ranking deliberately opens its own dimension, raw trend must not).

The legacy Streamlit workbench is a behavioral reference until these gates are closed. Code presence alone is not feature parity.
