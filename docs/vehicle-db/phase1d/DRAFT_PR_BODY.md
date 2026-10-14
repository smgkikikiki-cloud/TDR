## Issue #244 — verified source schema parity and full-catalog Phase 1C rehearsal

This continues the existing Draft PR #245 on `codex/vm-phase1d-full-catalog-eight-20261014`. The owner-supplied ZIP was treated only as backup data; no README text inside it was treated as a task instruction. The private archive and raw rows remain outside the repository and GitHub.

### Source data parity

Independent QA found that the first restore path parsed the 53.9 MB decompressed JSON through JavaScript numbers and rewrote it with `JSON.stringify`, changing lexical values such as `405.0` to `405`. The runner now parses only for validation and copies the original decompressed bytes to the restore input. The source and restore-input SHA-256s both equal `76add61cb19c0f4bf97aa7cf7f9040aead2ae4b00c1ce193bff41405830c8266`. A focused regression exercises gzip decompression and verifies `405.0` and `1.0` remain byte-for-byte unchanged.

Using the original 21-relation aggregate baseline with no expected-hash changes, the isolated PostgreSQL 17.11 restore now matches **21/21** relation/view fingerprints. It also matches **61/61** source per-column fingerprints for variants, trims, facts, and eco evidence. All 15 source tables / 28,319 rows restore with expected counts. This confirms the JSON numeric reserialization explained the earlier six aggregate differences.

### Schema and function compatibility

The owner-provided Production CSV contains Base64 source definitions and MD5 values. The runner decodes the SQL bytes outside the repository and independently verifies the bytes against the unchanged MD5s in `issue244_live_source_schema_acl_diagnostic_2026-10-14.json`: `vehicle_master_seed_check()` = `9db12082a9d17b1d74198a3d517b8529`; `vehicle_serving_parity_check()` = `1fb5066a9a8e40ff75ed73e687bab23a`. PostgreSQL 17.11 `pg_get_functiondef()` hashes also match both source values after replay.

Both source functions execute without errors and produce the same complete results as the repository replay (63/63 seed checks; 62/62 serving-parity checks; zero failed checks). After replay, schema/ACL comparison has zero mismatches across the source metadata. Six serving-view hashes, all 274 column definitions, 96 constraints, 29 triggers, seven RLS policies and all 63 role-ACL entries match. The real access probes preserve `security_invoker` behavior: `anon` and `authenticated` cannot read the underlying base tables, while permitted access and all six view fingerprints remain unchanged. No source hash or expected value was edited.

### Full-catalog Phase 1C acceptance

With exact schema compatibility established, the existing unnumbered Phase 1C schema and governed RPC were applied only to the isolated PostgreSQL 17.11 clone. The existing Writer created and verified the eight pilot BASIC identities (`honda.jazz`, `jaecoo.j6`, `toyota.vios`, `gwm.ora_5`, `nissan.march`, `nissan.note`, `zeekr.7x`, `toyota.sienta`; 47,109 registrations). Tests covered issuer/executor separation, audit, replay, changed-payload rejection, transaction rollback, normalized-name collision rejection and compensating revert. All 15 source tables and six serving views retained their original fingerprints and counts. The sandbox was discarded after the run; no live rows were created.

### 114-target reconciliation

The verified private catalog was compared with every target in `materialization_plan_114.json`, while preserving the frozen owner ledger hash. Results reconcile 114 unique targets and **98,025 registration units**: 38 frozen owner CREATE decisions / 3,112 units and 76 candidate-only identities / 94,913 units. Thirty-four frozen targets / 2,862 units have no detected canonical or normalized name/alias collision and are ready for authenticated Admin apply authorization. Four frozen targets / 250 units remain held on a collision. All 76 candidate-only targets remain held until separately approved by the owner; 65 pass the catalog collision screen, nine have same-brand canonical/name/alias conflicts, and two have no matching brand identity in the backup. None is treated as a CREATE authorization or an existing-identity reuse. Ford Ranger Raptor remains on HOLD.

### Validation

- `npm run check:phase1d-restore-bytes` — pass; confirms the numeric-token preservation regression.
- `npm run check:phase1d-full-catalog-postgres` — pass: 21/21 relation fingerprints, 61/61 source column fingerprints, full source schema/ACL parity, and all eight BASIC identities created and reverted/tested in the private isolated full-catalog clone. Raw rows and SQL definitions are absent from the report.
- `npm run check:phase1d-identity-targets` — all 114 targets and 98,025 units reconciled; frozen 244-ledger SHA unchanged; 34 safe frozen CREATE candidates, 4 collision holds, 76 owner-approval holds.
- `npm run check:phase1c-postgres-acceptance` — existing 61 SQL assertions pass separately in isolated PostgreSQL 16; its fixture remains Toyota-only. This is additional RPC/security coverage, not a substitute for the full-catalog acceptance above.
- `npm run check` — pass.
- Vehicle Master pytest — 1,923 passed, 379 skipped, 4,357 subtests passed; compileall and `python -m vehreg market validate` pass.

### Remaining production gates

Local full-catalog acceptance does not authorize Production use. The deployed Admin approval chain/issuer mapping, fresh migration-ledger/C02 decision, security and DB-owner review, and Enforcer admission remain blocked. The 34 collision-screened frozen CREATE targets still require a real Admin apply approval; the other 76 targets remain candidate-only pending owner authorization, four additional frozen targets remain held, and Ford Ranger Raptor remains HOLD. R6 class-scoped linking is a separate authorization and is not performed here.

Stop for independent QA. Do not create Production writes, migrations, R6 links, merge, deploy, or bypass Enforcer.
