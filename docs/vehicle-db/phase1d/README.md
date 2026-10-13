# Vehicle DB Phase 1D — production compatibility evidence

**Issue #244 status: real full-catalog rehearsal attempted and blocked before Phase 1C.** The owner-provided private backup was available, its compressed SHA-256 and payload SHA-256 matched, and all 15 tables / 28,319 rows restored into a disposable PostgreSQL 16.10 container from the repository's v57–v64 SQL chain. All counts matched the authorized handoff, but only 15 of 21 pre-change aggregate fingerprints matched. The runner stopped before Phase 1C; it created zero BASIC identities and made no production or staging connections or writes. See [`issue244_full_catalog_rehearsal_report.json`](issue244_full_catalog_rehearsal_report.json). The backup and raw rows remain outside GitHub.

The mismatch is not explained by this rehearsal. Four restored source relations and two serving views have different MD5 aggregates despite matching row counts. The available backup was exported about 17 hours before the reference aggregates and the export was not a transactionally consistent snapshot, but no evidence establishes that either detail caused these differences. Full-catalog preservation therefore remains unproven. Separately, the available evidence does not include a fresh deployed schema, view-definition, RLS, grant, or ACL manifest; the repository migration chain is not proof of the live deployment.

This remains an offline review package. It does not add a writer, production adapter, migration, or route. The existing Structural Identity Writer, serializer and Phase 1C local PostgreSQL RPC remain the only implementation path under review.

The evidence available in this repository is insufficient to claim full-catalog parity or real deployed Admin-to-database authorization. A read-only identity snapshot exists, but contains only 62 brands, 323 models and 326 generations, with no variants, trims, prices, release/lifecycle rows, live RLS/grants, or current schema definitions. The dated owner-supplied migration reconciliation reports v57–v64 applied and v65/v66 absent, but it is not a fresh live read. Accordingly the machine report retains `FULL_CATALOG_ACCEPTANCE_BLOCKED`, `ADMIN_AUTH_ACCEPTANCE_BLOCKED` and `MIGRATION_GATE_BLOCKED`.

## Evidence artifacts

- [`compatibility_matrix.csv`](compatibility_matrix.csv) — affected read/write surfaces and evidence limits.
- [`full_catalog_coverage_manifest.json`](full_catalog_coverage_manifest.json) — source provenance, exact available relation counts/hashes, missing classes, and deterministic blocked status.
- [`admin_trust_acl_review.md`](admin_trust_acl_review.md) — actual repository Admin session/auth and privileged DB boundary review; distinguishes code facts from deployed configuration.
- [`c02_migration_enforcer_decision_pack.md`](c02_migration_enforcer_decision_pack.md) — migration inventory, C02 choices, owner approvals and stacked PR/Enforcer constraints.
- [`isolated_rehearsal_runbook.md`](isolated_rehearsal_runbook.md) — future disposable-database rehearsal sequence, preflight checks and abort criteria.
- [`acceptance_report.json`](acceptance_report.json) — machine-readable status; no mock or Toyota-only result is labeled full acceptance.
- [`phase1c_replay_evidence.json`](phase1c_replay_evidence.json) and [`phase1c_replay_stdout.log`](phase1c_replay_stdout.log) — this branch's exact rerun evidence for the unchanged 61-assertion Phase 1C suite. The generated files in the Phase 1C draft directory were restored after capture so this stacked PR does not edit PR #241's artifacts.
- [`issue244_full_catalog_rehearsal_report.json`](issue244_full_catalog_rehearsal_report.json) — sanitized Issue #244 run result, including the fingerprint mismatch and explicit fail-closed state. It contains no raw catalog rows.
- [`DRAFT_PR_BODY.md`](DRAFT_PR_BODY.md) — review-ready stacked PR handoff.

## Reproduction

Run from repository root:

```sh
npm run check:phase1d-evidence
npm run check:phase1d-admin-contract
npm run check:phase1c-postgres-acceptance
npm run check:phase1d-full-catalog-postgres  # set TDR_VM_PRIVATE_BACKUP_GZIP to the private file outside the checkout
npm run check
(cd automotive/vehicle_master && /tmp/tdr-vm-venv/bin/python -m pytest -q tests --tb=short --basetemp=/workspace/.tdr-phase1d-pytest)
(cd automotive/vehicle_master && /tmp/tdr-vm-venv/bin/python -m compileall -q vehreg tools tests)
(cd automotive/vehicle_master && /tmp/tdr-vm-venv/bin/python -m vehreg market validate)
```

The Phase 1D evidence check verifies source hashes, the unchanged frozen 244-decision ledger, scope totals and hard-blocked acceptance labels. The Admin contract check calls the real `lib/admin-auth.ts` helpers with disposable test-only credentials; it proves helper behavior only, not deployment configuration, database authorization, or approval-record verification. The Phase 1C command runs the existing 61 PostgreSQL SQL assertions inside its pinned, disposable, network-isolated PostgreSQL 16 container and remains the only real PostgreSQL integration suite here. Its catalog parity fixture is one Toyota model and is not a full-catalog test.

The Issue #244 command is expected to stop with `FULL_CATALOG_ACCEPTANCE_BLOCKED_SOURCE_FINGERPRINT_MISMATCH` against the currently available handoff fingerprints. That is an explicit blocker, not a passing acceptance. It must not be bypassed by ignoring or updating expected hashes without a newly authorized, consistent source baseline and independent explanation of the differences. The unchanged 61-case Phase 1C suite still uses its Toyota-only fixture and is not full-catalog evidence.

Full-catalog acceptance, trusted production Admin boundary, fresh live schema/view/RLS/grant/ACL reconciliation, C02 decision, C01/R6 authorization and Enforcer admission for this stack are **not passed** by these commands.

The branch is pushed at the recorded final SHA. GitHub denied Draft PR creation through both GraphQL and REST with HTTP 403; the review-ready body is committed as [`DRAFT_PR_BODY.md`](DRAFT_PR_BODY.md). No hosted PR CI exists until repository PR-write access is available.
