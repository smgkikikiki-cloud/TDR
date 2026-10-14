# BASIC identity Production decision card

**Status: NOT AUTHORIZED FOR PRODUCTION.** This card prepares the bounded pilot and its controls. It does not approve CREATE, migration, deployment, merge, or an Ice/R6 link.

## Proposed pilot batch

The isolated full-catalog evidence used these eight BASIC identity proposals, representing 47,109 registration units in simulation:

| Canonical ID | Proposed model |
|---|---|
| `honda.jazz` | Honda Jazz |
| `jaecoo.j6` | Jaecoo J6 |
| `toyota.vios` | Toyota Vios |
| `gwm.ora_5` | GWM ORA 5 |
| `nissan.march` | Nissan March |
| `nissan.note` | Nissan Note |
| `zeekr.7x` | Zeekr 7X |
| `toyota.sienta` | Toyota Sienta |

These are pilot candidates, not eight live CREATE approvals. The independent authorized Admin must approve an immutable batch hash and exact operation set after reviewing the latest source evidence. The approval excludes Ice crosswalk writes. The 76 candidate-only targets remain excluded; Ford Ranger Raptor remains `HOLD`. The 244 frozen decisions and ledger SHA remain unchanged.

## Gates before any live action

1. Vehicle Master DB owner supplies a fresh SELECT-only schema, migration ledger/checksum, ACL/RLS, and catalog/view parity readback for the target project.
2. Migration owner resolves C02 and explicitly allocates new monotonic migration IDs. Do not infer an ID from repository filenames or the old v64 snapshot.
3. Admin/security owner assigns stable Admin principal UUIDs and approves the session-to-issuer trust contract. DB security owner provisions separately credentialed issuer and executor roles; neither role is `service_role`, and no principal may issue and execute the same approval.
4. Independent QA accepts the full-catalog evidence, approval-chain tests, rollback procedure, hosted CI, and exact Enforcer admission for the existing PR stack.
5. Owner approves each live CREATE batch by exact canonical IDs, batch/payload hash, operation set, approver, executor, expiry, and source references. This does not authorize any Ice/R6 link.
6. Change owner approves the maintenance window and verified recoverable backup. Record reviewed migration SHA-256 and exact preflight/postflight SQL before execution.

## Execution and verification after separate authorization

1. Confirm the project reference and target database identity; reject staging/Production ambiguity. Capture the approved read-only baseline and backup identifiers.
2. Apply only the separately numbered, reviewed additive migration in a transaction where supported. Confirm legacy CATALOG rows, key counts, six serving views, grants, RLS, and all market/price/fact tables match the baseline before any identity write.
3. An authenticated Admin reviews the exact eight proposals and signs the immutable approval record. The trusted issuer binds approval to the batch hash, CREATE operation set, distinct executor, expiry, nonce, and evidence reference.
4. The executor invokes the existing structural RPC in `SERIALIZABLE` isolation once. It must recheck canonical and normalized name/alias collisions and expected revisions against locked live rows. On any hold, changed hash, stale revision, authorization mismatch, or partial request, abort the entire transaction.
5. Read back all eight canonical IDs and BASIC fields, audit/receipt rows, and current serving outputs. Confirm unknown lifecycle/generation/spec/price fields remain unknown; BASIC rows do not leak into retail/catalog views; no Ice crosswalk row was changed; and the 244-decision ledger hash is unchanged.
6. Stop after this pilot for independent post-write QA. Later CREATE batches and every scoped R6 link require their own approvals.

## Rollback behavior

- Before commit, transaction failure rolls back the whole batch and leaves no identity/audit/receipt partial state; verify the failed batch has no receipt and no BASIC target rows.
- After a successful commit, do not hard-delete rows or run a reverse `DROP COLUMN` migration. Disable the Admin route/issuer credential if the deployment must be paused, then request a separate immutable `REVERT` approval for the exact revision IDs. The existing RPC performs compensating soft-hide/revision writes and refuses revert if dependent facts, trims, retail rows, or Ice links exist.
- Keep the additive schema in place during application rollback. Removing it would destroy append-only approval/audit evidence and may fail against historical BASIC rows. A schema teardown is a separate reviewed migration and is not part of this pilot.
- If catalog/view/security parity differs after schema application, stop before CREATE and use the verified database backup and DB-owner recovery procedure. Never use the identity revert RPC as a schema rollback.

This decision card is a procedure draft only. The Phase 1C SQL remains unnumbered and local-only until C02, migration allocation, security review, Enforcer admission, and explicit owner approval are complete.
