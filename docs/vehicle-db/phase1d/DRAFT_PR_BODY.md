## Issue #244 — offline Full Catalog rehearsal (blocked before Phase 1C)

This Draft PR is stacked on PR #243's `codex/vm-phase1d-prod-compat-20261013` branch. It reuses the existing Structural Identity Writer, BASIC adapter contract and Phase 1C RPC; it adds no replacement writer, numbered migration, or production connection.

The owner-provided backup was verified against compressed SHA-256 `8b7dc88cf42c27516ec08ddf170173feff85891ac655caa9a6f3eb5511d8b962` and payload SHA-256 `c51c20966be5f49dd0fe9a953793e666f6becf0f4d27a986158b6805e7659dad`. All 15 tables and 28,319 rows were restored to an isolated PostgreSQL 16.10 container with Docker networking disabled and database storage on tmpfs. The local v57–v64 restore and all relation row counts matched.

Before Phase 1C, the runner compares 15 source relations and six serving views to the authorized handoff's aggregate row counts and MD5 fingerprints. Only 15/21 fingerprints matched. The six mismatches are `vehicle_variants`, `vehicle_trims`, `vehicle_facts`, `vehicle_eco_evidence`, `current_market_trims`, and `current_spec_facts`; all six row counts match. Their expected and restored hashes are in `issue244_full_catalog_rehearsal_report.json`. The rehearsal fails closed here: Phase 1C was not applied, zero BASIC identities were created, and no production/staging connection or write occurred. The cause of the mismatches is not established. The backup is roughly 17 hours older than the reference snapshot and was exported without an MVCC snapshot guarantee; those facts are caveats, not a proven explanation.

The frozen 244-decision ledger and all source totals are unchanged. The eight candidates remain only proposed test inputs; this blocked run does not prove they can be safely materialized. Ford Ranger Raptor remains HOLD. Existing 61-case Phase 1C PostgreSQL test still passes separately on its one-Toyota fixture; it is not full-catalog acceptance.

### Validation

- `npm run check` — pass.
- Vehicle Master pytest — 1,923 passed, 379 skipped, 4,357 subtests passed (one existing warning).
- `python -m compileall -q vehreg tools tests` — pass.
- `python -m vehreg market validate` — valid, zero problems.
- `npm run check:phase1c-postgres-acceptance` — 61 assertions pass in isolated PostgreSQL 16; Toyota-only fixture.
- `npm run check:phase1d-full-catalog-postgres` — correctly blocks on 6/21 aggregate mismatches before Phase 1C.

### Remaining dependencies

1. Vehicle Master data owner: provide a consistent, authorized catalog snapshot or reconcile the six fingerprint differences with complete field-level evidence.
2. Vehicle Master/platform owner: provide a fresh deployed schema, serving-view definition, RLS, grants, and ACL manifest; repository SQL v57–v64 alone does not prove deployed parity.
3. Admin/security owner and independent DB reviewer: approve the deployed immutable principal, approval evidence, and issuer/executor binding.
4. Portfolio migration owner: resolve C02 and authorize migration allocations; Vehicle Master/Toolkit owners approve their respective scopes.
5. Enforcer owner: authorize exact stacked dependency/base admission through existing policy.

Stop for independent QA. Do not merge, migrate, deploy, activate a route, or bypass Enforcer.
