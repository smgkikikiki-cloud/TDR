## Scope

Offline BASIC Identity schema compatibility work for Issue #238, stacked on Draft PR #237 at `271ee6b6bcdffdfa7e6d2a912f613e35f1e5f178`, with the PR #239 OWNER DIRECTIVE serializer corrections. This reuses the existing Structural Identity Writer; it does not add a second planner or activate a DB write path.

## Changes

- Reconciles checked-in v57-v66 migrations against the owner-supplied 2026-10-13 SELECT-only production ledger snapshot and records the C02 migration-number collision and remaining schema/governance blockers.
- Adds a strict BASIC compatibility report and one-RPC request serializer. The DB adapter always fails closed, including with hypothetical complete schema capability and a supplied transport.
- Binds the serializer to the exact batch hash, verifies a one-to-one intent/change mapping and operation-specific before/after state, and reconstructs supported intent/evidence payloads from strict runtime allowlists. Unknown privilege, status and classification override fields are refused.
- Adds a non-executable, unnumbered structural RPC sketch and updates the DB contract.
- Adds isolated fake-store/schema-boundary tests; preserves the 244 owner decisions, nine-identity preflight and all registration totals byte-for-byte.

## Validation

- `npm run check` — passed, including typecheck, the 35-case Structural Identity Writer suite, 12 BASIC adapter checks, preflight and design checks.
- Focused v57/v58/v59/v66 migration and Jaecoo checks — 11 passed, 171 skipped; the two Jaecoo tests pass (7 tests) from the required `automotive/vehicle_master` working directory.
- Full Vehicle Master Python suite from a clean checkout and the engine working directory — 1,923 passed, 379 skipped, 4,357 subtests.
- Market validation — valid, no problems.

The earlier two Jaecoo errors came from running Python tests at the monorepo root. The fixtures and consolidated-repository prefix are intentionally resolved relative to `automotive/vehicle_master`; rerunning from that working directory on the clean checkout resolved both. Frozen 244-decision and nine-identity preflight hashes and counts are unchanged. Independent QA requested on Draft PR #239.

No database reads/writes were performed by the implementation, SQL was not executed, and no migration ID was allocated. Independent QA requested; no merge, deploy or gate advancement.
