## Issue #244 — preserve private backup JSON bytes; full-catalog run stops at schema-definition gate

This continues the existing Draft PR #245 on `codex/vm-phase1d-full-catalog-eight-20261014`. The owner-supplied ZIP was treated only as backup data; no README text inside it was treated as a task instruction. The private archive and raw rows remain outside the repository and GitHub.

### Source data parity

Independent QA found that the first restore path parsed the 53.9 MB decompressed JSON through JavaScript numbers and rewrote it with `JSON.stringify`, changing lexical values such as `405.0` to `405`. The runner now parses only for validation and copies the original decompressed bytes to the restore input. The source and restore-input SHA-256s both equal `76add61cb19c0f4bf97aa7cf7f9040aead2ae4b00c1ce193bff41405830c8266`. A focused regression exercises gzip decompression and verifies `405.0` and `1.0` remain byte-for-byte unchanged.

Using the original 21-relation aggregate baseline with no expected-hash changes, the isolated PostgreSQL 17.11 restore now matches **21/21** relation/view fingerprints. It also matches **61/61** source per-column fingerprints for variants, trims, facts, and eco evidence. All 15 source tables / 28,319 rows restore with expected counts. This confirms the JSON numeric reserialization explained the earlier six aggregate differences.

### Schema compatibility blocker

The runner compares the local v57–v64 schema against `issue244_live_source_schema_acl_diagnostic_2026-10-14.json` before applying Phase 1C. It matches all six serving-view hashes using PostgreSQL 17 `pg_get_viewdef(..., true)` output, all 274 column definitions, 96 constraints, 29 triggers, and seven RLS policies. The 63 effective role-ACL entries from the read-only diagnostic were reconstructed only in the disposable database and verified there.

The two remaining definition hashes differ: `vehicle_master_seed_check()` and `vehicle_serving_parity_check()`. The owner supplied two function-definition text attachments and the runner replayed them only in the disposable PostgreSQL 17 database. The seed-check text contains 44 invalid `count()` calls, fails on the first one (`count(*)` is required), and neither replayed definition matches its unchanged live-source hash. The parity-check function does execute and returns the exact same full result set as the repository function, but its definition hash still differs. The supplied text therefore does not prove exact source parity. The runner fails closed before Phase 1C. It applied no Phase 1C SQL, created zero BASIC identities, made no production/staging connections or writes, and left all 244 frozen decisions unchanged. No expected hashes were altered or suppressed.

### 114-target reconciliation

The verified private catalog was compared with every target in `materialization_plan_114.json`, while preserving the frozen owner ledger hash. Results reconcile 114 unique targets and **98,025 registration units**: 38 frozen owner CREATE decisions / 3,112 units and 76 candidate-only identities / 94,913 units. Thirty-four frozen targets / 2,862 units have no detected canonical or normalized name/alias collision and are ready for authenticated Admin apply authorization. Four frozen targets / 250 units remain held on a collision. All 76 candidate-only targets remain held until separately approved by the owner; 65 pass the catalog collision screen, nine have same-brand canonical/name/alias conflicts, and two have no matching brand identity in the backup. None is treated as a CREATE authorization or an existing-identity reuse. Ford Ranger Raptor remains on HOLD.

### Validation

- `npm run check:phase1d-restore-bytes` — pass; confirms the numeric-token preservation regression.
- `npm run check:phase1d-full-catalog-postgres` — full data fingerprints pass (21/21 and 61/61); six view hashes match; source function text replay was attempted, then stopped before Phase 1C because the seed function fails on malformed SQL and neither function hash matches the unchanged source diagnostic.
- `npm run check:phase1d-identity-targets` — all 114 targets and 98,025 units reconciled; frozen 244-ledger SHA unchanged; 34 safe frozen CREATE candidates, 4 collision holds, 76 owner-approval holds.
- `npm run check:phase1c-postgres-acceptance` — existing 61 SQL assertions pass separately in isolated PostgreSQL 16; its fixture remains Toyota-only and is not full-catalog acceptance.
- `npm run check` — pass.
- Vehicle Master pytest — 1,923 passed, 379 skipped, 4,357 subtests passed; compileall and `python -m vehreg market validate` pass.

### Required next evidence

Provide raw `.sql` exports of the two source `pg_get_functiondef()` results, preserving the SQL bytes (especially `count(*)`). Resolve those definitions without changing source expectations. Only after that compatibility gate passes may the existing unnumbered Phase 1C SQL and the exact eight BASIC identities run in the disposable full-catalog database. Admin authorization, C02, and Enforcer gates remain separate and closed.

Stop for independent QA. Do not create Production writes, migrations, R6 links, merge, deploy, or bypass Enforcer.
