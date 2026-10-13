# Vehicle DB Phase 1D — production compatibility evidence

**Status: partially completed; all production-compatibility acceptance gates remain blocked.** This is an offline review package on the Phase 1D branch at the exact Phase 1C base. It does not add a writer, production adapter, migration, or route. The existing Structural Identity Writer, serializer and Phase 1C local PostgreSQL RPC remain the only implementation path under review.

The evidence available in this repository is insufficient to claim full-catalog parity or real deployed Admin-to-database authorization. A read-only identity snapshot exists, but contains only 62 brands, 323 models and 326 generations, with no variants, trims, prices, release/lifecycle rows, live RLS/grants, or current schema definitions. The dated owner-supplied migration reconciliation reports v57–v64 applied and v65/v66 absent, but it is not a fresh live read. Accordingly the machine report retains `FULL_CATALOG_ACCEPTANCE_BLOCKED`, `ADMIN_AUTH_ACCEPTANCE_BLOCKED` and `MIGRATION_GATE_BLOCKED`.

## Evidence artifacts

- [`compatibility_matrix.csv`](compatibility_matrix.csv) — affected read/write surfaces and evidence limits.
- [`full_catalog_coverage_manifest.json`](full_catalog_coverage_manifest.json) — source provenance, exact available relation counts/hashes, missing classes, and deterministic blocked status.
- [`admin_trust_acl_review.md`](admin_trust_acl_review.md) — actual repository Admin session/auth and privileged DB boundary review; distinguishes code facts from deployed configuration.
- [`c02_migration_enforcer_decision_pack.md`](c02_migration_enforcer_decision_pack.md) — migration inventory, C02 choices, owner approvals and stacked PR/Enforcer constraints.
- [`isolated_rehearsal_runbook.md`](isolated_rehearsal_runbook.md) — future disposable-database rehearsal sequence, preflight checks and abort criteria.
- [`acceptance_report.json`](acceptance_report.json) — machine-readable status; no mock or Toyota-only result is labeled full acceptance.
- [`phase1c_replay_evidence.json`](phase1c_replay_evidence.json) and [`phase1c_replay_stdout.log`](phase1c_replay_stdout.log) — this branch's exact rerun evidence for the unchanged 61-assertion Phase 1C suite. The generated files in the Phase 1C draft directory were restored after capture so this stacked PR does not edit PR #241's artifacts.
- [`DRAFT_PR_BODY.md`](DRAFT_PR_BODY.md) — review-ready stacked PR handoff.

## Reproduction

Run from repository root:

```sh
npm run check:phase1d-evidence
npm run check:phase1d-admin-contract
npm run check:phase1c-postgres-acceptance
npm run check
(cd automotive/vehicle_master && /tmp/tdr-vm-venv/bin/python -m pytest -q tests --tb=short --basetemp=/workspace/.tdr-phase1d-pytest)
(cd automotive/vehicle_master && /tmp/tdr-vm-venv/bin/python -m compileall -q vehreg tools tests)
(cd automotive/vehicle_master && /tmp/tdr-vm-venv/bin/python -m vehreg market validate)
```

The Phase 1D evidence check verifies source hashes, the unchanged frozen 244-decision ledger, scope totals and hard-blocked acceptance labels. The Admin contract check calls the real `lib/admin-auth.ts` helpers with disposable test-only credentials; it proves helper behavior only, not deployment configuration, database authorization, or approval-record verification. The Phase 1C command runs the existing 61 PostgreSQL SQL assertions inside its pinned, disposable, network-isolated PostgreSQL 16 container and remains the only real PostgreSQL integration suite here. Its catalog parity fixture is one Toyota model and is not a full-catalog test.

The full Vehicle Master catalog acceptance, trusted production Admin boundary, fresh live ledger/ACL reconciliation, C02 decision, C01/R6 authorization and Enforcer admission for this stack are **not passed** by these commands.
