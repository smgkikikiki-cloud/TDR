## Vehicle DB Phase 1D — compatibility evidence and explicit blockers

This Draft PR continues from Phase 1C at `01ff6af90d488e5b3b990a74dc89ad5a2af7bbb2`. It reuses the existing Structural Identity Writer, BASIC serializer contract and Phase 1C RPC. It does not add a second engine, connect a production adapter, number or execute SQL, or advance C01/C02/R6.

The dated authorized read-only identity snapshot is partial: 62 brands, 323 models and 326 generations, with no variants, trims, full price/release/lifecycle rows, serving outputs, live schema or ACLs. Consequently the full catalog comparison remains `FULL_CATALOG_ACCEPTANCE_BLOCKED`. The actual checked-in Admin session helpers are exercised by focused tests, but the deployed immutable principal/approval record and session-to-DB issuer boundary are unavailable; `ADMIN_AUTH_ACCEPTANCE_BLOCKED` remains. C02 and the previously reported exact-base Enforcer admission errors also remain `MIGRATION_GATE_BLOCKED` / `ENFORCER_ADMISSION_BLOCKED`.

The report preserves the 244 frozen owner decisions and source totals unchanged. The eight identities/47,109 units and 98.819047% remain simulations only; Ford Ranger Raptor stays on HOLD for 12,839 units. No new approved or servable registrations are claimed.

### Validation

`npm run check` passes. The full Vehicle Master suite passes from `automotive/vehicle_master` (1,923 passed, 379 skipped, 4,357 subtests passed; one existing warning), compileall passes, and `python -m vehreg market validate` reports valid/0 problems. Enforcer preflight passes and its two offline admission suites pass 42/42. The Phase 1C PostgreSQL suite is rerun unchanged with 61 SQL assertions in isolated PostgreSQL 16. Its one-Toyota parity fixture is not full-catalog acceptance. Exact commands, hashes and caveats are recorded in `docs/vehicle-db/phase1d/acceptance_report.json`. No live DB access or writes are used.

### Required next owners

1. Vehicle Master data owner: provide/perform complete, consistent and authorized SELECT-only catalog/schema/ACL snapshot.
2. Admin/security owner and independent DB reviewer: approve stable principal, immutable approval evidence and trusted issuer/executor binding.
3. Portfolio migration owner: reconcile C02 and explicitly authorize fresh migration allocations; Vehicle Master/Toolkit owners approve their respective schema scopes.
4. Enforcer owner: authorize the exact stacked dependency/base path through existing policy.

Stop for independent QA. Do not merge, migrate, deploy, activate a route, or bypass Enforcer.
