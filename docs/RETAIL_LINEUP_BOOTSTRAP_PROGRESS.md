# Retail Lineup Bootstrap — Progress

Branch: `feature/retail-lineup-bootstrap`

Draft CI PR: #171 — **do not merge yet**.

Source-of-truth design: `docs/RETAIL_LINEUP_BOOTSTRAP.md`.

This file is the handoff marker. The feature is intentionally being built in independent chunks; production/main remain untouched until the later integration/smoke-test chunks.

## Chunk 1 — COMPLETE

Pure deterministic planner:

- `automotive/vehicle_master/vehreg/retail_lineup_bootstrap.py`
- exact identity resolution only; no fuzzy write matching
- KEEP / CREATE / REACTIVATE / ARCHIVE classification
- deterministic new MarketTrim identity
- target-model baseline hash
- immutable plan hash
- no canonical writes

## Chunk 2 — COMPLETE

Staged apply semantics:

- `automotive/vehicle_master/vehreg/retail_lineup_bootstrap_apply.py`
- CREATE materialises a real base-Catalog MarketTrim through the existing canonical writer
- REACTIVATE explicitly reopens a historical trim
- target set becomes the authoritative CURRENT set
- omitted old CURRENT trims become literal HISTORICAL, never deleted
- plan-hash tamper detection, baseline recheck and idempotent exact-post-state replay

## Chunk 3 — COMPLETE

Workbook contract / compile-only tooling:

- `automotive/vehicle_master/vehreg/retail_lineup_workbook.py`
- `automotive/vehicle_master/tools/retail_lineup_bootstrap_workbook.py`
- `automotive/vehicle_master/tests/test_retail_lineup_workbook.py`

Workbook sheets:

1. `TARGET_LINEUP` — editable target truth
2. `CURRENT_SNAPSHOT` — informational/read-only
3. `IMPORT_META` — schema, scope and stale-baseline metadata

The compiler never applies canonical writes. It rejects stale baselines, formulas/unknown headers, target rows outside scope and an explicitly targeted model with zero valid target trims.

## Chunk 4 — COMPLETE

Whole-workbook atomic transaction boundary:

- `automotive/vehicle_master/vehreg/retail_lineup_bootstrap_transaction.py`
- `automotive/vehicle_master/tests/test_retail_lineup_bootstrap_transaction.py`

Semantics:

- copy the whole canonical data tree to a sandbox
- apply the immutable plan only in the sandbox
- build and enrich the serving release from the sandbox
- verify target trims serve CURRENT and omitted trims serve HISTORICAL
- recheck semantic baseline before promotion
- compare live-file SHA-256 fingerprints before promotion to prevent overwriting a concurrent writer in shared sidecars
- promote only staged changed files
- roll back already-promoted files after a mid-promotion failure

Final Chunk-4 CI head `46f51035e875de8030a64ba81a7ee74ee8f94504` produced **1599 passed / 11 repository-baseline failures / 4334 subtests passed** with no Retail Lineup Bootstrap failure.

## Chunk 5 — COMPLETE

Durable immutable preview-plan state / confirmation handoff is now implemented. This chunk still does **not** expose the Admin UI and does **not** wire a new source kind into `import_runs`; those remain later chunks.

### Durable Supabase state

Implemented migrations:

- `supabase/migration_v53_retail_lineup_plans.sql`
- `supabase/migration_v54_retail_lineup_plan_state_hardening.sql`

New server-only table: `public.retail_lineup_plans`.

A preview persists the exact reviewed object rather than relying on a future recompile:

- source workbook SHA-256
- canonical baseline hash
- immutable plan hash
- full compiled plan JSON
- immutable review summary
- compiler actor
- approval/apply/publish audit identity
- optional `import_run_id` (left nullable until Chunk 7 source-import integration)

State machine:

```text
PREVIEW_READY
    -> APPLYING
        -> WRITTEN_PENDING_PUBLISH
            -> COMPLETED
        -> FAILED
        -> STALE
    -> STALE
    -> CANCELLED

FAILED -> APPLYING | STALE | CANCELLED
```

`COMPLETED`, `STALE` and `CANCELLED` are terminal.

The repository write and serving publish remain deliberately separate states. A canonical commit that has not been confirmed as the serving release may be `WRITTEN_PENDING_PUBLISH`; it must never be reported as completed.

### Immutable confirmation contract

The migration exposes service-role-only compare-and-set RPCs:

- `tdr_begin_retail_lineup_plan_apply(...)`
- `tdr_mark_retail_lineup_plan_written(...)`
- `tdr_complete_retail_lineup_plan(...)`
- `tdr_fail_retail_lineup_plan_apply(...)`
- `tdr_mark_retail_lineup_plan_stale(...)`

`begin_apply` requires the exact `plan_hash` and `baseline_hash` the Admin reviewed. A stale hash, terminal plan or unknown plan fails closed. There is no fallback that silently recompiles a newer workbook/canonical state behind the operator's back.

`migration_v54` additionally prevents privileged same-status rewrites of approval identity, commit SHA or release ID. Audit fields may only change on the state transition that owns them. A retry from FAILED records a fresh approval timestamp/actor.

RLS is enabled and table/RPC access is revoked from public/anon/authenticated; only `service_role` receives the required access.

### Server-side plan store

Implemented:

- `automotive/vehicle_master/tools/retail_lineup_plan_store.py`
- `automotive/vehicle_master/tests/test_retail_lineup_plan_store.py`

The helper can persist/fetch an immutable PREVIEW_READY plan, atomically begin apply with both reviewed hashes, record canonical commit identity, record completed serving release identity, and record FAILED/STALE state. It performs no workbook compilation and no canonical write.

### Exact persisted-plan decoder

Implemented:

- `automotive/vehicle_master/vehreg/retail_lineup_plan_codec.py`
- `automotive/vehicle_master/tests/test_retail_lineup_plan_codec.py`

This rebuilds the frozen Chunk-1 dataclasses from the **stored `compiled_plan` JSON**, not from the source workbook and not by rerunning identity resolution.

The decoder requires the exact persisted JSON schema, rejects unknown fields/wrong types/duplicate identities, verifies model/item ownership, recomputes action counts, checks the durable row hashes, and independently recomputes the immutable plan hash before returning the plan. Payload tampering therefore fails before Chunk 4 can apply it.

Additional audit-state static guard:

- `automotive/vehicle_master/tests/test_retail_lineup_plan_state_hardening.py`

### Chunk 5 commits

- `f0aca31f938b9eeddf62aea233b09cf70b26836c` — durable preview-plan migration
- `098a34c997de662b6dcfc880682195c7bce766cc` — Supabase plan-store helper
- `b306bd6fdbce17a510ba0641e11e4649a06fa152` — plan-store tests
- `39d36bdf4515efac68cdc7d5c560758643daaae0` — strict persisted-plan decoder
- `2de280e86725056a48d381bd3d5a97c915e17f3e` — decoder/tamper tests
- `b6c0ba0f6b6b35517352f5fa947651399ad5ad83` — audit transition hardening
- `738774d91e793e72a96526120b86780f4eaf6fdb` — audit-state static guard

### Validation

Full Vehicle Master CI on code head `2de280e86725056a48d381bd3d5a97c915e17f3e` completed with **1612 passed / 11 failed / 4334 subtests passed**. The 11 failures are the same repository-baseline failures already observed before Chunk 5; no Retail Lineup Bootstrap plan-store/codec test appears in the failure list.

The exact final Chunk-5 code/test head `738774d91e793e72a96526120b86780f4eaf6fdb` additionally passed Python compilation and the TypeScript job. Changes after the full validated code head are SQL state-machine hardening plus its static file-contract test; they do not touch canonical runtime/apply logic.

No v53/v54 migration has been applied to production Supabase. No main merge or production write has occurred.

## Chunk 6 — COMPLETE

Dedicated Admin UI / explicit confirmation surface is implemented. Chunk 6 deliberately stops before the source-import compiler and apply/publish workers; those remain Chunk 7.

### Level-0 Admin workspace

Implemented:

- `app/admin/(secure)/retail-lineup-bootstrap/page.tsx`
- `app/admin/(secure)/retail-lineup-bootstrap/[planId]/page.tsx`
- `app/admin/retail-lineup-actions.ts`
- `lib/retail-lineup-admin.ts`
- Admin navigation/home links marking this as a separate **LEVEL 0** operation

The workflow presented to the owner is:

```text
Generate workbook -> edit TARGET_LINEUP -> upload -> immutable Preview
-> inspect KEEP / CREATE / REACTIVATE / ARCHIVE -> explicit Apply
-> APPLYING -> WRITTEN_PENDING_PUBLISH -> COMPLETED
```

The detail page renders the stored plan rather than reconstructing a diff in TypeScript. It shows source SHA-256, baseline hash, plan hash, base release, actor/approver, every model and every planned item including canonical ID and identity-resolution basis.

### Explicit Apply safety

The Admin Apply request:

- requires a separate confirmation checkbox
- submits the rendered `plan_id`, `plan_hash` and `baseline_hash`
- re-fetches the durable plan and verifies both hashes still match
- calls only `tdr_begin_retail_lineup_plan_apply(...)`
- never parses the XLSX again
- never reruns identity resolution
- never calls the canonical writer or Chunk-4 transaction in the Vercel request
- dispatches the approved plan ID for the Chunk-7 worker, which must decode the stored `compiled_plan`

Therefore a click cannot silently apply a newer interpretation than the object the Admin reviewed.

### Workbook generation surface

Workbook generation also avoids a parallel TypeScript implementation of the Excel contract.

Implemented:

- `supabase/migration_v55_retail_lineup_workbook_exports.sql`
- `automotive/vehicle_master/tools/retail_lineup_workbook_export_worker.py`
- `.github/workflows/retail-lineup-workbook-export.yml`
- `automotive/vehicle_master/tests/test_retail_lineup_workbook_export_worker.py`

Admin stores a durable generation request containing exact model scope, catalog year and base release. The read-only worker checks out `main`, calls the existing Chunk-3 `generate_retail_lineup_workbook()`, uploads the XLSX to the private `source-imports` bucket and records its baseline hash. The worker has no canonical write or git-push permission.

The export request state machine is `QUEUED -> PROCESSING -> READY | FAILED`; request identity is immutable and the table is service-role-only.

### Upload boundary

The UI accepts `.xlsx` only, maximum 4 MB, stores it in the existing private import bucket and queues the dedicated `RETAIL_LINEUP_BOOTSTRAP` source kind. Chunk 6 intentionally does **not** add that source kind to the current `import_runs` constraint or importer handler. That migration/compiler wiring is Chunk 7, so a feature-branch UI upload is not claimed to be operational yet.

This separation is deliberate: Chunk 6 proves the Admin contract without modifying the ordinary ECO/DLT/Vehicle-Specs import worker.

### Chunk 6 commits

- `d31ef618cb23ddc526dffdf8c1b6888367a50ec9` — workbook export queue migration
- `f17b75e5d3ab3b863c13e631ea8417c07770a5dd` — read-only workbook generator worker
- `23c4898c899409e477e98e85db6fbfbfb50bbcde` — generator workflow
- `5ea8377237c626eb3661d456275c5a91a3b3430e` — generator worker tests
- `bca45fb87f856c3d98cacd1017c573f0eb13d61c` — Admin read models
- `109082b25311ee5daff9d3cc8dd5c9adb087fe8b` — initial Admin server actions
- `404d3f04ba603992d6e61e52a33feae0375d210b` — Level-0 workspace page
- `c16bf51745159ac6766c9405b4ab9e5a728cb7cd` — immutable Preview detail page
- `576effb2e99e071d1d095587bbc5258c2bb0cc1f` — explicit Apply confirmation guard
- `f4bc16a33d80dcaa998f99a4be21b6dadd49eb1c` — Admin nav entry
- `d005a820acb7d67a71c2bd681efa32af37946e4b` — Admin-home entry
- `62d6886b240d728fb4642a22e0550238847a5623` — Admin safety-contract tests
- `fd02219933358ad14805f19f29cc165c08b80816` — Supabase secret-key compatibility for workbook storage

### Validation

The Chunk-6 runtime code head is `fd02219933358ad14805f19f29cc165c08b80816`; commits after it only update this handoff document.

Full Vehicle Master CI at Chunk-6 UI/action code head `f4bc16a33d80dcaa998f99a4be21b6dadd49eb1c` completed with **1618 passed / 11 failed / 4334 subtests passed**. The 11 failures are exactly the same repository-baseline failures already observed before Chunk 6; no Retail Lineup Bootstrap test appears in the failure list. TypeScript passed and the full Next.js web build passed on the same head.

The later runtime commits after `f4bc16a33d80dcaa998f99a4be21b6dadd49eb1c` only add the Admin-home link, static safety-contract tests and a small Storage credential-compatibility hardening; they do not change canonical transaction/apply logic.

No Retail Lineup Bootstrap migration (v53-v55) has been applied to production. No `main` merge and no production canonical write has occurred.

## Next — Chunk 7

Wire the two server-side execution paths while preserving the already-reviewed object boundary:

1. add `RETAIL_LINEUP_BOOTSTRAP` to the `import_runs` source-kind constraint and make source-import compile the uploaded XLSX into one immutable `PREVIEW_READY` row linked to that import run;
2. add the approved-plan apply worker that fetches/decodes the stored `compiled_plan`, runs the Chunk-4 transaction, commits exactly those promoted canonical files, publishes the exact commit/release and advances `APPLYING -> WRITTEN_PENDING_PUBLISH -> COMPLETED` (or FAILED/STALE).

Chunk 7 must include a scheduled recovery sweep so a lost repository-dispatch after Admin confirmation cannot strand an `APPLYING` plan forever.
