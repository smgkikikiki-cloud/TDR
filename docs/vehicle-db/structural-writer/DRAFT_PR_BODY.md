Vehicle Master has a governed price writer but no structural identity executor. This adds a bounded offline structural planner/executor in the existing Vehicle Engine, with server-authenticated permission boundaries and a fake serializable store for CREATE_BRAND, CREATE_MODEL_BASIC, UPDATE_MODEL_ALIAS and registration-class Ice links. It does not connect a production route/database adapter or assign/apply a migration.

Stacked on frozen Draft PR #235 at `b5a6bcff2870afb8d81d672dd284e7935e3cb4ac`; this PR's base is its existing branch, so the diff contains only Issue #236 work. PR #235 and all 244 frozen decisions remain unchanged. The owner task is preserved in `docs/vehicle-db/structural-writer/owner_task_236.txt`. Issue/PR API reads returned HTTP 403, so no unseen discussion is claimed as reviewed.

## Audit and reuse

The first commit independently audits legacy writers/callers and removes only the unused shadow bridge's database enqueue implementation, retaining a disabled compatibility guard. The legacy Python writer/worker, DB objects, history, RPCs and workflow guards remain intact. The implementation reuses existing taxonomy, stable canonical serialization, actor/audit conventions, scoped RY normalization and the existing master/inbox/observation/audit integration design. It never invokes the price RPC or retired canonical_input_batches path.

## Identity and permission behavior

- Deterministic Brand FK, canonical/name/slug/alias/granularity validation; new non-equivalent aliases require trusted reviewed equivalence evidence.
- New basic models preserve UNKNOWN classification/lifecycle/generation. Ice values remain immutable raw evidence; canonical Segment and Body Type require approved TDR evidence for the exact identity.
- Agents propose; only verified admin context can apply/approve/revert. Requests cannot assert actor/approval/R6 permissions, and payloads are copied before asynchronous authorization.
- Atomic apply, optimistic revisions, idempotent retry, concurrent duplicate protection, immutable observation/audit records and compensating soft-hide revert.
- Scoped links require exact class/source/version/ref/hash and separate R6 permission. No ALL/neighboring-class fallback, group-level RPC, registration mutation, or frozen-owner override.

## Real nine-identity preflight

The genuine M7.0 ZIP and frozen source hashes reconcile all 1,407 scopes / 4,141,987 registrations: 4,123,704 effective + 18,283 excluded; 244 owner decisions unchanged.

Nine initial candidates retain 59,948 registrations. Eight / 47,109 pass structural validation; Ford Ranger Raptor Double Cab / 12,839 is held because the current `ford.ranger_double_cab` identity owns alias `ranger raptor`. Its frozen target is preserved; no silent merge or unsafe CREATE is proposed. The mixed nine-create batch is rejected atomically; the eight-subset simulation runs only in the fake store; all link apply attempts remain R6-denied.

Existing candidates plus those eight simulate 98.819047%, below 99.1%. This corrects the previous nine-safe assumption. Newly approved/servable production registrations remain zero.

## Validation and dependencies

Local checks pass: 27 structural TypeScript tests; 1,923 Python tests passed, 379 skipped and 4,357 subtests passed; real preflight regeneration/hash checks; full `npm run check`, Python compile, market validator and roadmap repository preflight. GitHub-hosted CI and real database integration remain unverified.

The unnumbered DB contract documents v57/v59 BASIC identity/provenance/status/classification constraints, v66 structural observation keys, audit/inbox reuse, the authenticated structural RPC/adapter, concurrent uniqueness protection and scoped-link CAS. Current DB compatibility is not claimed. C02 migration reconciliation and separate production authorization are required; C01/R6 remains a separate link blocker. No production writes, state-changing SQL, migrations, Price Fetcher work, autonomous dispatch, gate changes, merge or deployment.

Stop for independent QA.

Refs #236
