# Vehicle DB Phase 1D — production compatibility evidence

**Issue #244 status: source data parity is verified; Phase 1C remains blocked on schema-definition compatibility.** The previous 15/21 fingerprint mismatch came from parsing and reserializing the 53.9 MB JSON backup through JavaScript numbers, which changed tokens such as `405.0` to `405`. The runner now validates parsed content but writes the original decompressed bytes unchanged. Their SHA-256s match (`76add61cb19c0f4bf97aa7cf7f9040aead2ae4b00c1ce193bff41405830c8266`), and all 21 original aggregate fingerprints plus all 61 source column fingerprints now match. No expected hash was changed. See [`issue244_full_catalog_rehearsal_report.json`](issue244_full_catalog_rehearsal_report.json).

The runner still stops before Phase 1C. The read-only source diagnostic and local PostgreSQL 16.10 comparison leaves eight definition-hash differences: six serving-view definitions and two validation-function definitions. The source diagnostic was captured on PostgreSQL 17 and warns its MD5 rendering can vary by engine; it does not contain the deployed SQL definitions needed to determine whether those differences are renderer-only or real schema drift. All 274 column definitions, 96 constraints, 29 triggers, and seven RLS policies match the diagnostic. The 63 effective role-ACL entries were replayed from that read-only diagnostic in the disposable database and then verified. A fresh full deployed SQL definition dump or an independently validated same-engine comparison is still needed before schema compatibility can be claimed. No Phase 1C SQL was applied, no BASIC identities were created, and no production/staging connections or writes occurred. The backup and raw rows remain outside GitHub.

This remains an offline review package. It does not add a writer, production adapter, migration, or route. The existing Structural Identity Writer, serializer and Phase 1C local PostgreSQL RPC remain the only implementation path under review.

The owner-provided backup supplies all 15 data tables and full row-level content for this offline rehearsal; its aggregate and column fingerprints match the recorded source baseline. The separate live diagnostic supplies schema metadata and hashes but not the deployed view/function SQL text, so compatibility remains blocked at those definitions. Production Admin-to-database authorization, C02, and Enforcer admission also remain unverified or unapproved. Older partial identity snapshots and historical manifests remain useful provenance, not substitutes for this run's full backup evidence.

## Evidence artifacts

- [`compatibility_matrix.csv`](compatibility_matrix.csv) — affected read/write surfaces and evidence limits.
- [`full_catalog_coverage_manifest.json`](full_catalog_coverage_manifest.json) — source provenance, exact available relation counts/hashes, missing classes, and deterministic blocked status.
- [`admin_trust_acl_review.md`](admin_trust_acl_review.md) — actual repository Admin session/auth and privileged DB boundary review; distinguishes code facts from deployed configuration.
- [`c02_migration_enforcer_decision_pack.md`](c02_migration_enforcer_decision_pack.md) — migration inventory, C02 choices, owner approvals and stacked PR/Enforcer constraints.
- [`isolated_rehearsal_runbook.md`](isolated_rehearsal_runbook.md) — future disposable-database rehearsal sequence, preflight checks and abort criteria.
- [`acceptance_report.json`](acceptance_report.json) — machine-readable status; no mock or Toyota-only result is labeled full acceptance.
- [`phase1c_replay_evidence.json`](phase1c_replay_evidence.json) and [`phase1c_replay_stdout.log`](phase1c_replay_stdout.log) — this branch's exact rerun evidence for the unchanged 61-assertion Phase 1C suite. The generated files in the Phase 1C draft directory were restored after capture so this stacked PR does not edit PR #241's artifacts.
- [`issue244_full_catalog_rehearsal_report.json`](issue244_full_catalog_rehearsal_report.json) — sanitized Issue #244 run result, including matched data fingerprints and the explicit fail-closed schema-definition state. It contains no raw catalog rows.
- [`issue244_live_source_schema_acl_diagnostic_2026-10-14.json`](issue244_live_source_schema_acl_diagnostic_2026-10-14.json) — read-only source metadata and column fingerprints; not a full deployed SQL dump.
- [`DRAFT_PR_BODY.md`](DRAFT_PR_BODY.md) — review-ready stacked PR handoff.

## Reproduction

Run from repository root:

```sh
npm run check:phase1d-evidence
npm run check:phase1d-admin-contract
npm run check:phase1c-postgres-acceptance
npm run check:phase1d-restore-bytes
npm run check:phase1d-full-catalog-postgres  # set TDR_VM_PRIVATE_BACKUP_GZIP to the private file outside the checkout
npm run check
(cd automotive/vehicle_master && /tmp/tdr-vm-venv/bin/python -m pytest -q tests --tb=short --basetemp=/workspace/.tdr-phase1d-pytest)
(cd automotive/vehicle_master && /tmp/tdr-vm-venv/bin/python -m compileall -q vehreg tools tests)
(cd automotive/vehicle_master && /tmp/tdr-vm-venv/bin/python -m vehreg market validate)
```

The Phase 1D evidence check verifies source hashes, the unchanged frozen 244-decision ledger, scope totals and hard-blocked acceptance labels. The Admin contract check calls the real `lib/admin-auth.ts` helpers with disposable test-only credentials; it proves helper behavior only, not deployment configuration, database authorization, or approval-record verification. The Phase 1C command runs the existing 61 PostgreSQL SQL assertions inside its pinned, disposable, network-isolated PostgreSQL 16 container and remains the only real PostgreSQL integration suite here. Its catalog parity fixture is one Toyota model and is not a full-catalog test.

The restore-byte regression proves that numeric lexemes `405.0` and `1.0` survive gzip decompression unchanged. The Issue #244 command now confirms 21/21 aggregate and 61/61 per-column data fingerprints, then correctly stops with `FULL_CATALOG_ACCEPTANCE_BLOCKED_SCHEMA_ACL_MISMATCH` because eight view/function definition hashes cannot be reconciled across PostgreSQL 17 vs 16.10 from the metadata-only diagnostic. The unchanged 61-case Phase 1C suite still uses its Toyota-only fixture and is not full-catalog acceptance.

Full-catalog acceptance, trusted production Admin boundary, fresh live schema/view/RLS/grant/ACL reconciliation, C02 decision, C01/R6 authorization and Enforcer admission for this stack are **not passed** by these commands.

The branch is pushed at the recorded final SHA. GitHub denied Draft PR creation through both GraphQL and REST with HTTP 403; the review-ready body is committed as [`DRAFT_PR_BODY.md`](DRAFT_PR_BODY.md). No hosted PR CI exists until repository PR-write access is available.
