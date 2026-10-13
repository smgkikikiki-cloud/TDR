# Structural BASIC identity compatibility rehearsal runbook

**Rehearsal plan only.** No production/staging connection or database write is permitted by this document. Do not number or execute its SQL until separate owner/security approvals and a migration task exist.

## Evidence prerequisites

1. Obtain an authorized read-only snapshot procedure from the Vehicle Master data owner and confirm exact project ref, role, allowed data classes, SELECT-only privileges, source schema version, cutoff/consistency method and no PII/customer/payment data.
2. Snapshot all relevant Vehicle Master catalog relations and definitions: brands, models, generations, variants, trims, facts, prices, campaigns/promotions, seed/release/current-retail/lifecycle state, serving views, constraints, triggers, helpers, policies and effective grants. Record counts, canonical sorted key hashes and file hashes before extraction. Reconcile completeness and take no oversized/raw registration export.
3. Independently verify deployed migration ledger names/checksums and schema version. Stop if it differs from the reviewed source snapshot or repository prerequisite.
4. Obtain owner adoption of BASIC semantics, stable Admin actor/approval contract, C02 allocation, revision/audit design, scoped private schema/RPC grants and explicit independent security sign-off. Enforcer must admit exact branch/base/task.
5. Preserve the frozen inputs unchanged: 244 owner decisions and ledger hash `9f251b6120d88e52c33215c5127fb6f87cd8c6cc334c39dc227bb540860ae1a8`; 1,407 scopes / 4,141,987 units (4,123,704 effective + 18,283 excluded); eight proposals / 47,109 units; Ranger Raptor remains HOLD / 12,839.

## Isolated rehearsal sequence

1. Provision a fresh disposable PostgreSQL 16 database in a network-isolated environment. Verify database name/marker, container digest, no published port, no production credentials, no shared database URL, ephemeral storage and guaranteed teardown.
2. Restore baseline schema and the verified read-only catalog fixture. Capture relation definitions, constraints/triggers, RLS/grants/owners/search paths, row counts, stable keys/fingerprints, serving view outputs and relevant API response shapes. This is the before-state.
3. Replay v57–v64 only in the proven disposable DB when source provenance confirms that sequence. Reconcile baseline outputs against the snapshot before applying Phase 1C draft SQL. Stop on any mismatch; never resolve differences by suppressing a uniqueness conflict.
4. Apply the unnumbered Phase 1C SQL files to the isolated database only. Run all existing 61 PostgreSQL SQL assertions. Then repeat every before-state measurement and exact CATALOG row/view/role parity comparison. All legacy brands/models/generations/variants/trims/prices/release/current-retail/lifecycle values and permissions must match. BASIC rows must be hidden from retail/current catalog views and visible only through reviewed private identity lookup.
5. Exercise real catalog alias collisions, Unicode normalization, sibling identities, stale snapshot drift, NULL/unknown evidence, v59 deferred checks, legacy authorized update behavior, grant inheritance, direct DML, regular/authenticated users, service-role attempts, fake admin claims, propose-only identity, expired/revoked/forged approval, actor rebinding, replay and rollback. Assert issuer≠executor independent of request JSON.
6. Export sanitized hashes/counts, manifests, exact commands, PostgreSQL version/image digest, ACL/role summary without secrets, and all error diffs. Teardown disposable DB and verify removal. An incomplete source catalog remains a blocked result even when every isolated SQL assertion passes.

## Abort and rollback criteria

Abort without applying if source authority, snapshot consistency, role scope, schema version, migration ledger or owner approval is uncertain. Abort and preserve the isolated evidence if any CATALOG key/value/view/permission/count/hash changes unexpectedly; unknown conflicts must be reported with owner and remediation, never silently skipped. For a future approved live operation, require a verified recoverable backup, explicit change-window owner, exact reviewed migration checksum and independent post-apply SELECT-only checklist before scheduling; this PR supplies no live rollback authorization.

No live database endpoint, credentials, gates, writer route, branch policy or production data are changed by this runbook.
