## Scope

Offline BASIC Identity schema compatibility work for Issue #238, stacked on Draft PR #237 at `271ee6b6bcdffdfa7e6d2a912f613e35f1e5f178`. This reuses the existing Structural Identity Writer; it does not add a second planner or activate a DB write path.

## Changes

- Reconciles checked-in v57-v66 migrations against the owner-supplied 2026-10-13 SELECT-only production ledger snapshot and records the C02 migration-number collision and remaining schema/governance blockers.
- Adds a strict BASIC compatibility report and one-RPC request serializer. The DB adapter always fails closed, including with hypothetical complete schema capability and a supplied transport.
- Adds a non-executable, unnumbered structural RPC sketch and updates the DB contract.
- Adds isolated fake-store/schema-boundary tests; preserves the 244 owner decisions, nine-identity preflight and all registration totals byte-for-byte.

## Validation

- `npm run check` — passed.
- `npm run check:structural-identity-writer` — passed (35 writer tests, 7 new adapter checks, preflight unchanged: 8 candidates / 47,109 registrations; 1 hold / 12,839).
- Focused v57/v58/v59/v66 migration tests — 4 passed, 171 skipped.
- Full Vehicle Master Python suite — 1,921 passed, 379 skipped, 4,357 subtests; two fixture failures: missing `vehreg/data/2026/product/specs/ecosticker/jaecoo.json`, and expected Jaecoo key absent in the consolidated P6 ledger test. Neither path was changed in this PR.

No database reads/writes were performed by the implementation, SQL was not executed, and no migration ID was allocated. Independent QA requested; no merge, deploy or gate advancement.
