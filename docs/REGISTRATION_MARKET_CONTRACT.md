# Registration Market Contract

This contract is the bridge from the retained Vehicle Master analytics engine to the new TDR Next.js paid market workspace. It is intentionally a data/query contract first; the customer UI and Admin Bench are separate follow-up work.

## Source of truth

Vehicle Master remains authoritative for vehicle dimensions. Paid registration analytics must derive vehicle classification from the same active canonical release used by the free catalogue:

`registrations -> current_vehicle_models -> current_vehicle_brands`

`public.models` is a legacy/editorial serving table and must not be the taxonomy authority for new analytics. Registration facts remain separate from MarketTrim and are never allowed to create or redefine a vehicle.

The transitional `registrations.model_id` UUID identifies the reviewed TDR model row. The canonical analytics projection resolves it through `current_vehicle_models.tdr_model_id` and exposes the stable text `canonical_model_id`. Future registration publishing should write canonical model identity directly so the legacy UUID hop can eventually disappear.

## Market denominator

The default analytical denominator is identifiable vehicle volume inside the selected market scope. Unmapped model rows remain available as coverage diagnostics and are not distributed into guessed models, segments, body types or powertrains.

Brand-only residuals are a special honest grain: if the model is unresolved but the reviewed brand crosswalk is known, a Brand / OEM Group / Brand Origin ranking may still count that volume at brand grain. Model-dependent dimensions do not inherit or guess the missing model classification.

When ranking by a dimension, that dimension's own filter is ignored. Example: if the user previously selected Toyota and then switches `Compare by` to Brand, the Brand scope opens so Toyota can be ranked against competitors. Other active filters remain in force. This preserves the denominator rule used by `automotive/vehicle_master/pages/3_Admin_Market_Intelligence.py`.

## Supported dimensions

The first canonical contract supports:

- Brand
- Model
- Segment
- Body type
- Powertrain
- OEM group
- Market position
- Import type (CBU / CKD / SKD / mixed/unknown as represented canonically)
- Production country
- Brand origin
- DLT registration type
- Market scope

Powertrain is conservative at this serving layer: one canonical powertrain is reported directly, no canonical powertrain is `UNKNOWN`, and a multi-powertrain nameplate is `MIXED`. The richer Vehicle Master rulebook remains the reference for later fact-level powertrain parity; the web contract must not invent allocations.

## Time windows and movement

Window arithmetic is calendar-based, not row-based:

- Month
- Rolling 3 months
- Rolling 6 months
- Rolling 12 months
- YTD

A requested window is rejected when a calendar month is missing. `LAG()` over the previous observed row is not sufficient because a model can disappear for a month and return later.

Comparisons support:

- Previous non-overlapping window (Month vs previous Month, Rolling 3M vs previous 3M, etc.)
- Same window one year earlier

Movement keeps raw unit delta for context but ranks competitive movement by share change in percentage points. Rank change is also returned.

## Coverage

Every market-slice response carries raw window units, canonically model-mapped units and model-mapping coverage. The UI must surface low coverage rather than silently treating a coarse month as a complete model market.

The existing Vehicle Master coverage/provisional logic remains the behavioral reference for default-period selection and warnings when the paid UI is built.

## Intentionally deferred

### Price range

Price range is a required product filter, but it is not part of this first RPC. The active canonical release currently has insufficient Price Ledger coverage to define most of the market, and price must be effective-date aware before it can classify historical registration facts. Do not fall back to legacy `public.models.retail_price_*` just to make this filter look complete.

### Province and trim-level registration

The current Supabase `registrations` fact contains model-level monthly registrations and DLT registration type, but not province, fact grain, raw trim identity or trim-ledger detail. Regional Market and Chinese EV trim ranking therefore remain Admin/Vehicle Master capabilities until a richer canonical registration fact projection is published.

### Historical backfill

The canonical warehouse retains substantially more registration history than the current Supabase serving table. Rolling 12M, YoY and multi-year product features must stay unavailable for windows that are not present in serving data rather than silently shortening the comparison.

## Transition rule

The existing static dashboard views and `/api/report/registration` remain untouched while the new contract is introduced. The current member dashboard therefore keeps working during migration.

Only after the new paid UI and Admin Bench pass parity checks should the legacy Streamlit presentation layer and static dashboard views be considered for retirement. Engine, data, audit rules and source history remain canonical regardless of UI retirement.
