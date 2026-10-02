# Vehicle Master tables (Phase 0 step 2)

Migration: `supabase/migration_v57_vehicle_master_tables.sql`.
Seed: `automotive/vehicle_master/tools/vehicle_master_seed.py`.
Check: `automotive/vehicle_master/tools/vehicle_master_seed_check.py`.
Tests: `automotive/vehicle_master/tests/test_vehicle_master_tables_migration_v57.py`.

This step only adds tables and functions. No existing table, view or function changes. Pages and
serving functions still read the `current_*` views over `canonical_*_projection`. Switching
serving onto these tables is step 3, after the parity test.

## Tables

| Table | Key | From the release | From the pinned JSON tree |
|---|---|---|---|
| `vehicle_brands` | `canonical_id` | every row and column, incl. `tdr_brand_id`, `slug` | — |
| `vehicle_models` | `canonical_id` | every row and column, incl. `tdr_model_id`, `slug`, as-of values | — |
| `vehicle_generations` | `canonical_id` | every row | — |
| `vehicle_variants` | `canonical_id` | — | `asdict(Variant)` for every analytical variant |
| `vehicle_trims` | `canonical_id` | every row, incl. `status`, `current_list_price`, `campaign_quote`, `price_history` | `catalog_payload` = `asdict(MarketTrim)`; `origin` = `CATALOG`/`OVERLAY` |
| `vehicle_price_ledger` | `record_id` | served rows (`in_release = true`) | retracted rows (`in_release = false`), with `retraction_reason`, `reviewed_by` |
| `vehicle_facts` | `fact_id` | served resolved facts (`served_in_release = true`) | the rest of the fact store: PROVISIONAL, superseded, not yet effective |
| `vehicle_campaigns` | `campaign_id` | — | `to_jsonable(Campaign)` verbatim |
| `vehicle_promotions` | `(campaign_id, option_id)` | — | one row per campaign option; v3 §7 columns |
| `vehicle_eco_evidence` | `trim_id` | — | ECO homologation rows (`product/specs/ecosticker`) |
| `vehicle_current_retail_sets` | `model_id` | — | `market/trims/current_retail.json` |
| `vehicle_trim_lifecycle_decisions` | `trim_id` | — | `market/retail_lifecycle/trim_review.json` |
| `vehicle_model_operational_states` | `model_id` | — | `market/operational_state/model_state.json` |
| `vehicle_legacy_identities` | binding key | — | `integration_data/external_identity_registry.json` |
| `vehicle_master_state` | `'vehicle_master'` | the pin: release id, `as_of`, `source_hash`, `canonical_revision`, counts | expected supplemental counts |
| `vehicle_master_seed_runs` | id | run log | run log |

These are the master tables, so they have no `release_id`. Values the engine computes against a
date (ENGINE_INVENTORY §9.1) are stored exactly as served, with `served_as_of`. Every entity has
`revision` and `deleted_at` for v3 §1.5 soft delete. RLS is on and no policies exist, so only
`service_role` can read or write.

## Pinning

Every seed and check is pinned to one release: `release_id` plus that release's `as_of`.

1. `vehicle_master_seed_from_release(release_id, as_of)` refuses to run unless that release is
   the active one and its `as_of` matches. It copies the six projections row for row, checks the
   counts against `canonical_vehicle_releases.counts`, and records the pin. Re-running it returns
   `already_seeded`. A different release can never seed over an existing pin.
2. The seed tool extracts `automotive/vehicle_master` at the release's `canonical_revision`. It
   rebuilds the release there with the pinned `as_of`, using that revision's own code. It stops
   unless `release_id`, `source_hash`, `canonical_revision`, `as_of` and `counts` all match.
   Only then does it build the supplemental sections.
3. `vehicle_master_seed_supplemental(...)` accepts rows only for the pinned release. A row that
   already exists must be identical. A non-retracted price must already be a served row. A
   catalog trim must already be a release trim.
4. `vehicle_master_finish_supplemental(...)` closes the seed once every section's total equals
   what the tool built. After that, the supplemental stage refuses writes.

Verified locally on 2026-10-02 against `vehicle-2026-a8e647b7db765c78` (`as_of` 2026-10-01,
revision `04b02ea8d`). The rebuild reproduced the production `source_hash`. All parity and
integrity checks passed:

| | Release | Supplemental |
|---|---|---|
| Brands / models / generations | 62 / 323 / 326 | — |
| Trims | 1,569 | 1,466 catalog + 103 overlay |
| Price ledger | 1,004 | 1,004 total (0 retracted at this revision) |
| Spec facts | 23,083 | 24,492 total (1,409 not served; 1 `UNKNOWN`) |
| Variants / campaigns / options | — | 370 / 44 / 48 |
| ECO evidence / current-retail sets / lifecycle decisions / operational states | — | 3 / 61 / 15 / 0 |
| Legacy tdr ids | 62 brands, 321 models | 1 registry binding |

## Running

The seed needs Python 3.10+ (CI uses 3.12), the vehicle_master requirements, and a full clone
that contains the release's `canonical_revision`. Apply migration v57 first.

```bash
cd automotive/vehicle_master
# Read-only: builds and verifies everything, writes the sections, sends nothing.
python -m tools.vehicle_master_seed --release-id <active id> --as-of <its as_of> --dry-run --out /tmp/vm-seed
# Writes (needs SUPABASE_URL + SUPABASE_SECRET_KEY / SUPABASE_SERVICE_ROLE_KEY).
python -m tools.vehicle_master_seed --release-id <active id> --as-of <its as_of> --apply
python -m tools.vehicle_master_seed_check        # exit 1 on any failed check
```

`vehicle_master_seed_check()` returns these rows:

- `pin`: the release still exists and is still active, and `as_of` and `source_hash` still match.
- `release`: for each of the six sections, the row count, ids missing from the master, ids not
  in the release, and rows whose served columns or payload differ.
- `integrity`: supplemental totals equal the expected counts, and there are no dangling variant,
  campaign or option references. `in_release` equals "not retracted". Served ECO evidence equals
  stored ECO evidence. Current-retail members belong to their model. Legacy bindings point at
  existing ids.
- `report`: the preserved state the release does not serve. These rows are informational and
  always `ok`.

If a newer release is activated after seeding, `release_still_active` fails. The master must then
be reconciled before step 3's parity test means anything.

## Left for later steps (not decided here)

- `authority`, `locked`, `vat_included` and the typed v3 §7 promotion columns (`scope`, `type`,
  amounts, `status`) are left null. Assigning authority tiers to legacy rows and mapping legacy
  campaigns onto §7 are owner decisions for Phase 1. `vehicle_promotions` keeps the legacy
  option fields that `campaign_quote` serves.
- The one `UNKNOWN` fact is kept. v3 §3 drops UNKNOWN rows, which is a Phase 1 change
  (ENGINE_INVENTORY §9.9).
- `vehicle_trims.variant_id` has no FK, because variants arrive after trims. The check reports
  dangling ids instead.
- `canonical_write_revisions` and `admin_edit_sessions` are not extended. That is Phase 1 work,
  and this step must not alter existing tables.
- Not migrated: crosswalk inputs (only the resolved `tdr_*_id` and slugs are kept), the release
  manifest's `historical_model_state` (it stays on `canonical_vehicle_releases`), and the
  price-coverage and ECO review sidecars (they are workflow metadata, not served state).
