## Issue #244 — preserve private backup JSON bytes; full-catalog run stops at schema-definition gate

This continues the existing Draft PR #245 on `codex/vm-phase1d-full-catalog-eight-20261014`. The owner-supplied ZIP was treated only as backup data; no README text inside it was treated as a task instruction. The private archive and raw rows remain outside the repository and GitHub.

### Source data parity

Independent QA found that the first restore path parsed the 53.9 MB decompressed JSON through JavaScript numbers and rewrote it with `JSON.stringify`, changing lexical values such as `405.0` to `405`. The runner now parses only for validation and copies the original decompressed bytes to the restore input. The source and restore-input SHA-256s both equal `76add61cb19c0f4bf97aa7cf7f9040aead2ae4b00c1ce193bff41405830c8266`. A focused regression exercises gzip decompression and verifies `405.0` and `1.0` remain byte-for-byte unchanged.

Using the original 21-relation aggregate baseline with no expected-hash changes, the isolated PostgreSQL 16.10 restore now matches **21/21** relation/view fingerprints. It also matches **61/61** source per-column fingerprints for variants, trims, facts, and eco evidence. All 15 source tables / 28,319 rows restore with expected counts. This confirms the JSON numeric reserialization explained the earlier six aggregate differences.

### Schema compatibility blocker

The runner compares the local v57–v64 schema against `issue244_live_source_schema_acl_diagnostic_2026-10-14.json` before applying Phase 1C. It matches all 274 column definitions, 96 constraints, 29 triggers, and seven RLS policies. The 63 effective role-ACL entries from the read-only diagnostic were reconstructed only in the disposable database and verified there.

Eight definition hashes still differ: six serving-view definitions and `vehicle_master_seed_check()` / `vehicle_serving_parity_check()`. The source diagnostic was captured on PostgreSQL 17 while the pinned full-catalog rehearsal uses PostgreSQL 16.10; the diagnostic warns that definition MD5s can vary by engine and does not include source SQL text. These differences cannot currently be classified as renderer-only or as actual deployed schema drift. The run therefore fails closed before Phase 1C. It applied no Phase 1C SQL, created zero BASIC identities, made no production/staging connections or writes, and left all 244 frozen decisions unchanged. No expected hashes were altered or suppressed.

### Validation

- `npm run check:phase1d-restore-bytes` — pass; confirms the numeric-token preservation regression.
- `npm run check:phase1d-full-catalog-postgres` — full data fingerprints pass (21/21 and 61/61); stops before Phase 1C on eight unresolved definition hashes.
- `npm run check:phase1c-postgres-acceptance` — existing 61 SQL assertions pass separately in isolated PostgreSQL 16; its fixture remains Toyota-only and is not full-catalog acceptance.
- `npm run check` — pass.
- Vehicle Master pytest — 1,923 passed, 379 skipped, 4,357 subtests passed; compileall and `python -m vehreg market validate` pass.

### Required next evidence

Provide the deployed view/function SQL definitions or run an independent same-engine schema-definition comparison against the source PostgreSQL 17 version. Resolve the eight hashes without changing source expectations. Only after that compatibility gate passes may the existing unnumbered Phase 1C SQL and the exact eight BASIC identities run in the disposable full-catalog database. Admin authorization, C02, and Enforcer gates remain separate and closed.

Stop for independent QA. Do not create Production writes, migrations, R6 links, merge, deploy, or bypass Enforcer.
