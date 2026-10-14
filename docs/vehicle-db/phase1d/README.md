# Vehicle DB Phase 1D — production compatibility evidence

**Issue #244 status: full-catalog offline Phase 1C acceptance passes; production readiness remains separately gated.** The previous 15/21 fingerprint mismatch came from parsing and reserializing the 53.9 MB JSON backup through JavaScript numbers, which changed tokens such as `405.0` to `405`. The runner now validates parsed content but writes the original decompressed bytes unchanged. Their SHA-256s match (`76add61cb19c0f4bf97aa7cf7f9040aead2ae4b00c1ce193bff41405830c8266`), and all 21 original aggregate fingerprints plus all 61 source column fingerprints match. No expected hash was changed. See [`issue244_full_catalog_rehearsal_report.json`](issue244_full_catalog_rehearsal_report.json).

The runner uses the same PostgreSQL 17 major as the read-only source diagnostic. The owner-provided Base64 CSV definitions decode to bytes whose MD5 values match the unchanged source values; both PostgreSQL 17 function-definition hashes and full behavior result sets match. All six serving-view hashes match using `pg_get_viewdef(..., true)`. Schema/ACL comparison has zero metadata mismatches after source-function replay across all 274 column definitions, 96 constraints, 29 triggers, seven RLS policies, 63 effective role-ACL entries, and the source function set. The existing unnumbered Phase 1C SQL/RPC was then applied only in the disposable full-catalog database. The existing Writer created and exercised exactly eight BASIC identities (47,109 registrations); rollback, audit, replay, collision and revert checks passed, while all source table and view fingerprints remained unchanged. The backup and raw rows remain outside GitHub.

This remains an offline review package. It does not add a writer, production adapter, migration, or route. The existing Structural Identity Writer, serializer and Phase 1C local PostgreSQL RPC remain the only implementation path under review.

The owner-provided backup supplies all 15 data tables and full row-level content for this offline rehearsal; its aggregate and column fingerprints match the recorded source baseline. The direct function-definition CSV was verified and used only in the disposable database. Production Admin-to-database authorization, C02, migration approval and Enforcer admission remain unverified or unapproved. Older partial identity snapshots and historical manifests remain provenance, not substitutes for this full backup evidence.

## Evidence artifacts

- [`compatibility_matrix.csv`](compatibility_matrix.csv) — affected read/write surfaces and evidence limits.
- [`full_catalog_coverage_manifest.json`](full_catalog_coverage_manifest.json) — source provenance, exact available relation counts/hashes, missing classes, and deterministic blocked status.
- [`admin_trust_acl_review.md`](admin_trust_acl_review.md) — actual repository Admin session/auth and privileged DB boundary review; distinguishes code facts from deployed configuration.
- [`c02_migration_enforcer_decision_pack.md`](c02_migration_enforcer_decision_pack.md) — migration inventory, C02 choices, owner approvals and stacked PR/Enforcer constraints.
- [`isolated_rehearsal_runbook.md`](isolated_rehearsal_runbook.md) — future disposable-database rehearsal sequence, preflight checks and abort criteria.
- [`acceptance_report.json`](acceptance_report.json) — machine-readable status; no mock or Toyota-only result is labeled full acceptance.
- [`phase1c_replay_evidence.json`](phase1c_replay_evidence.json) and [`phase1c_replay_stdout.log`](phase1c_replay_stdout.log) — this branch's exact rerun evidence for the unchanged 61-assertion Phase 1C suite. The generated files in the Phase 1C draft directory were restored after capture so this stacked PR does not edit PR #241's artifacts.
- [`issue244_full_catalog_rehearsal_report.json`](issue244_full_catalog_rehearsal_report.json) — sanitized Issue #244 full-catalog and source schema/function parity evidence. It contains no source SQL or raw catalog rows.
- [`identity_target_reconciliation_2026-10-14.json`](identity_target_reconciliation_2026-10-14.json) — deterministic comparison of all 114 planned targets against the verified catalog backup and frozen owner ledger; it contains only target IDs, source references and registration counts.
- [`operational_readiness_2026-10-14.md`](operational_readiness_2026-10-14.md) — exact gate-by-gate handoff separating local evidence, Production blockers, target approvals and R6 authorization.
- [`issue244_live_source_schema_acl_diagnostic_2026-10-14.json`](issue244_live_source_schema_acl_diagnostic_2026-10-14.json) — read-only source metadata and column fingerprints; not a full deployed SQL dump.
- [`DRAFT_PR_BODY.md`](DRAFT_PR_BODY.md) — review-ready stacked PR handoff.

## Reproduction

Run from repository root:

```sh
npm run check:phase1d-evidence
npm run check:phase1d-admin-contract
npm run check:phase1c-postgres-acceptance
npm run check:phase1d-restore-bytes
npm run check:phase1d-full-catalog-postgres  # set TDR_VM_PRIVATE_BACKUP_GZIP and the two external source SQL paths
npm run check:phase1d-identity-targets      # same private input; verifies the 114-target plan and frozen ledger
npm run check
(cd automotive/vehicle_master && /tmp/tdr-vm-venv/bin/python -m pytest -q tests --tb=short --basetemp=/tmp/tdr-phase1d-pytest)
(cd automotive/vehicle_master && /tmp/tdr-vm-venv/bin/python -m compileall -q vehreg tools tests)
(cd automotive/vehicle_master && /tmp/tdr-vm-venv/bin/python -m vehreg market validate)
```

The Phase 1D evidence check verifies source hashes, the unchanged frozen 244-decision ledger, scope totals and hard-blocked acceptance labels. The Admin contract check calls the real `lib/admin-auth.ts` helpers with disposable test-only credentials; it proves helper behavior only, not deployment configuration, database authorization, or approval-record verification. The Phase 1C command runs the existing 61 PostgreSQL SQL assertions inside its pinned, disposable, network-isolated PostgreSQL 16 container and remains the only real PostgreSQL integration suite here. Its catalog parity fixture is one Toyota model and is not a full-catalog test.

The restore-byte regression proves that numeric lexemes `405.0` and `1.0` survive gzip decompression unchanged. The Issue #244 command verifies the owner-exported source-function Base64 bytes against their unchanged MD5s, replays them in PostgreSQL 17.11, and confirms both `pg_get_functiondef()` hashes and behavior. It now passes schema/ACL compatibility, all 21/21 aggregate and 61/61 per-column fingerprints, and full-catalog Phase 1C acceptance: exactly eight BASIC identities were created and exercised in the disposable database while the 15 source tables and six serving views remained unchanged. The separate 61-case Phase 1C suite still uses its Toyota-only fixture and is additional RPC/security coverage, not a replacement for full-catalog acceptance.

The 114-target reconciliation confirms 38 frozen owner CREATE decisions (3,112 registrations) and 76 candidate-only targets (94,913 registrations), totaling 98,025 without loss or duplication. Thirty-four frozen targets (2,862 registrations) have no canonical/name/alias collision and are ready for separate authenticated Admin apply authorization. Four frozen CREATE targets (250 registrations) remain held on collision. All 76 candidates remain held because no new owner CREATE approval exists: 65 pass the catalog collision screen, nine have same-brand canonical/alias conflicts, and two lack a verified brand identity. Ford Ranger Raptor remains on hold.

Full-catalog offline acceptance and owner-diagnostic schema/ACL parity are **PASS**. A trusted deployed Admin approval boundary, production migration/C02 decision, independent security/DB signoff, C01/R6 authorization and Enforcer admission for this stack are **not passed** by these commands.

The branch is pushed at the recorded final SHA. GitHub denied Draft PR creation through both GraphQL and REST with HTTP 403; the review-ready body is committed as [`DRAFT_PR_BODY.md`](DRAFT_PR_BODY.md). No hosted PR CI exists until repository PR-write access is available.
