# Vehicle Spec Excel Import — WORKUPDATE

Branch: `feature/vehicle-spec-excel-importer`
PR: `#164` — Add deterministic vehicle spec Excel importer — **MERGED**

## Goal

Deterministic Excel/CSV -> canonical vehicle spec editor for existing MarketTrims.

No AI/fuzzy placement. No mandatory source/evidence columns. `canonical_trim_id` is authoritative. Blank = no-op. Type/unit/applicability come from the live SpecRegistry. Qualifier context is carried by machine headers.

## Implemented

### Compiler

`automotive/vehicle_master/vehreg/spec_excel.py`

- exact existing `canonical_trim_id`; no vehicle creation
- registry-driven NUMBER / BOOLEAN / ENUM / TEXT / SET parsing
- YES/NO, TRUE/FALSE, 1/0 for boolean
- explicit `UNKNOWN`, `NOT_AVAILABLE`, `NOT_APPLICABLE`; ambiguous `-` rejected
- powertrain applicability validation
- fixed qualifier aliases plus generic `field.key__qualifier=value`
- bare qualified fields rejected
- qualifier-aware fact IDs so NEDC/WLTP/CLTC can coexist
- sparse MarketTrim core + comparable-spec dual writes where canonical storage has both
- `battery.catalog_capacity_kwh` also updates `MarketTrim.battery_kwh`

### Source-free direct canonical facts

The compiler emits no `source`, `source_ref`, or `source_locator` fields.

`SpecLedger` permits source/source_ref to be absent on direct `admin:` facts; non-admin/external facts still require them. `observed_at` is infrastructure-generated ordering metadata, not workbook evidence.

`CanonicalWritePipeline._append_spec()` writes the source-free payload as-is. Batch-level `source_kind=ADMIN` / `source_ref=vehicle-spec-excel` remains operational audit metadata only and is not copied into the vehicle fact.

Supabase staged release publishing stores `spec_facts` as payload JSON and does not impose a separate source/source_ref NOT NULL requirement, so the source-free facts reach the serving release path.

Relevant commits:

- `2b70724c1008822e003271b01ed55e0c3a16b804` — remove fabricated source metadata
- `8c649fea9f86a77f40c3724a2cf62373a82ea66b` — source-free direct admin validation
- `8ba7ede647420e98f146df224ea0f1f5161be362` — source-free regression tests

### Template

`automotive/vehicle_master/tools/export_vehicle_spec_template.py`

Generates:

- `SPECS` — exact canonical trim rows + editable machine headers
- `FIELD_DICTIONARY` — current registry field/type/unit/powertrain/qualifier/header mapping
- `README` — fill rules

Tests require every current SpecRegistry field to have a machine-readable template route.

### Import CLI / worker / admin

- `automotive/vehicle_master/tools/import_vehicle_specs.py`
- `automotive/vehicle_master/tools/import_worker.py`
- `app/admin/import-actions.ts`
- `app/admin/(secure)/import/page.tsx`

`VEHICLE_SPECS` is accepted by the admin upload route and worker. CSV and XLSX are supported. ECO/DLT parsing remains separate.

### Supabase import-run gate

Production already has the constraint allowing `VEHICLE_SPECS`.

During the pre-merge audit this was also made reproducible in repo migration history:

- `supabase/migration_v52_vehicle_specs_import_kind.sql`
- production-side historical record remains `docs/vehicle-spec-excel-import/SUPABASE_MIGRATION.sql`

Commit: `3eb46a1a7c8f0940081a11aee029147aca5cc378`.

## Pre-merge audit — 2026-09-29

### Critical issue found and fixed: multi-batch partial apply

A large workbook can exceed one canonical input batch. Before the audit, `import_vehicle_specs.py` applied those batches directly to live `DATA_DIR` one at a time.

Failure mode:

`batch 1 succeeds -> batch 2 fails -> run becomes FAILED -> batch 1 files remain dirty and source-import workflow can still commit them`

That meant a FAILED workbook could partially land.

Fix:

- the entire workbook now applies against an outer temporary copy of Vehicle Master
- every canonical batch must succeed there first
- only after all batches succeed are changed files promoted to live `DATA_DIR`
- a later-batch validation failure leaves the live canonical tree untouched
- promotion keeps normal data first / `canonical_state` audit files last, matching the existing canonical pipeline recovery order

Code commit: `01d5cf5038792e04fe29d3223255695a49a432fe`.

Regression tests: `automotive/vehicle_master/tests/test_spec_excel_atomic_apply.py`

- later batch fails -> live tree remains unchanged
- all batches pass -> all changed files are promoted

Test commit: `3abab48d2d24e129782abb130fbe7bd89eff2794`.

### Small audit issue fixed: deterministic promotion order

The atomic helper collected changed paths in a set and originally sorted only by whether the path belonged to `canonical_state`. Paths inside the same group could therefore inherit hash/set iteration order and make output/tests flaky.

The final ordering is now `(canonical_state_last, path_string)`, so promotion and reports are deterministic.

Commit: `4f78a29a421dcb18c7175c03b4516d65f0ecc4e2`.

### Audit checks that passed

- canonical batch `source_kind=ADMIN` is valid and is a different layer from `import_runs.source_kind=VEHICLE_SPECS`
- release builder includes comparable specs in `spec_facts`
- enriched release hashes `spec_facts`
- staged Supabase publisher publishes `spec_facts`
- source-free `spec_facts` are valid serving payloads; Supabase does not separately require source/source_ref columns
- source-import workflow commits `vehreg/data`, publishes the exact pushed revision, then finalizes runs
- source-import and canonical-input share the `canonical-vehicle-input` concurrency group, so another canonical writer cannot interleave with workbook staging/promotion
- generated qualifier aliases solve the NEDC/WLTP/CLTC ambiguity without AI inference

### Not treated as blockers

Existing `admin:` facts use synthetic `source=admin/source_ref=admin` compatibility markers. Excel revising a direct admin fact without those markers is consistent with this feature's source-free direct-canonical contract, so this is not being split into a second fact namespace without a concrete need.

Comparison qualifiers are not globally required to all be present: the registry uses some qualifier dimensions that may legitimately be unknown (for example charger power). The importer rejects bare qualified fields and unknown qualifier names but does not invent a blanket "every qualifier must be populated" rule.

## Contracts / handoff docs

Updated from stale skeleton text to current implemented behavior:

- `docs/vehicle-spec-excel-import/INPUT_CONTRACT.md`
- `docs/vehicle-spec-excel-import/WRITE_CONTRACT.md`

They now point to the real generated header inventory instead of obsolete example columns.

## Verification

Source-free head `8ba7ede647420e98f146df224ea0f1f5161be362`:

- Python compile: PASS
- Python: 1572 passed + 4334 subtests passed; 9 existing unrelated baseline/data-fixture failures
- production web build: PASS
- TypeScript: the same two unrelated lifecycle textual-smoke failures

Audited atomic head `fe9b1bffbdf7c893f818c92d1e0493a473d857e8`:

- Python compile: PASS
- Python: **1574 passed + 4334 subtests passed; same 9 unrelated failures**
- the +2 passes are the two new whole-workbook atomic regression tests
- no `test_spec_excel*` test failed
- production web build: PASS
- TypeScript: exactly the same two unrelated lifecycle textual-smoke failures (`workflow store enforces canonical parent CURRENT`, `workflow store exempts reopen from parent guard`)

Latest executable head `4f78a29a421dcb18c7175c03b4516d65f0ecc4e2` adds only the deterministic sort tie-breaker above:

- Python compile: PASS
- production web build: PASS
- TypeScript: same two unrelated lifecycle smoke failures confirmed
- full Python suite is still running at the time of this note; the immediately preceding atomic head already passed both new importer tests with no importer-specific failure

## Post-merge admin canonical-input wake-up incident — 2026-09-29

The importer PR is merged, but live testing of ordinary admin canonical saves exposed a separate latency/reliability problem in the canonical-input wake-up path.

### Symptoms observed in production

- admin Save successfully inserts a durable row into `canonical_input_batches`
- the admin editor can immediately show the pending edit through its QUEUED/PROCESSING overlay
- the public UI remains on the previous active canonical release until the worker processes and publishes the batch
- two live admin batches observed during testing remained `QUEUED`, `attempts=0`, with no `release_id`
- GitHub Actions showed no `repository_dispatch` runs from those saves

This isolated the failure to `admin Save -> wake GitHub Actions`, not the Supabase queue, admin editor, canonical compiler, or public rendering path.

### Fixes already merged

Commit `69634cb38cadf35b652996904f51f63b87ccea79`:

- `app/admin/input-actions.ts` now calls `dispatchCanonicalInputWorker()` immediately after a genuinely new successful QUEUED insert
- duplicate-resubmit path does not dispatch again
- `.github/workflows/canonical-input.yml` keeps `repository_dispatch: types: [canonical-input]`
- fallback schedule is `*/5 * * * *`
- canonical-input keeps its dedicated `canonical-input-worker` concurrency group instead of the shared canonical writer group
- failed rebase attempts are aborted before the next push retry

Commit `765ff653d32c8c070b70c46d4df88ec3ebc1c738`:

- production runtime now derives `GITHUB_REPOSITORY` from `VERCEL_GIT_REPO_OWNER` + `VERCEL_GIT_REPO_SLUG` when `GITHUB_REPOSITORY` is not explicitly configured, matching `.env.example`

### Root cause confirmed in production

A live Save after the repository-resolution hotfix produced this Vercel runtime warning:

`canonical input queued but immediate dispatch is unavailable: GITHUB_DISPATCH_TOKEN is not configured`

The remaining blocker was therefore the missing server-only `GITHUB_DISPATCH_TOKEN` in Vercel Production. The durable Supabase queue was intact throughout.

### Resolution and live verification

A fine-grained GitHub token with access to `smgkikikiki-cloud/TDR` and repository **Contents — Read and write** permission was added to Vercel Production as `GITHUB_DISPATCH_TOKEN`, then Production was redeployed.

Live verification after redeploy:

- an admin MarketTrim Save completed at approximately `2026-09-29T04:22:01Z`
- GitHub Actions run `36521308420` (`Process canonical vehicle input`, run `#2046`) was created at `2026-09-29T04:22:06Z`
- the run event was **`repository_dispatch`**, proving the immediate wake-up path works instead of relying on cron
- the new batch plus two older queued admin batches were all pulled by the worker and moved to `PROCESSING`, `attempts=1`
- validation, commit, exact-revision publish, and `Mark the applied batches PUBLISHED` all completed successfully
- all three batches finished `PUBLISHED` with no error
- all three point to release `vehicle-2026-65979fa053990149`
- publish timestamps were approximately `2026-09-29T04:24:38Z`–`04:24:39Z`
- the user confirmed the edited values appeared on the public UI for all affected records

The worker intentionally drains queued backlog when woken; a new Save can therefore recover older `QUEUED` rows in the same validated/published release.

## Current status

The deterministic Vehicle Spec Excel importer is merged into `main`.

Importer/data correctness blockers found during the pre-merge audit were fixed. The post-merge admin canonical-input immediate wake-up incident is also **RESOLVED and verified end-to-end in production**.

Current live path:

`admin Save -> durable Supabase QUEUED row -> repository_dispatch within seconds -> canonical worker -> validate -> commit -> exact-revision publish -> PUBLISHED -> public UI`

Fallback `*/5` scheduled sweep remains as recovery if an immediate dispatch ever fails.

End-to-end importer path:

`generated template -> filled Excel/CSV -> deterministic compiler -> whole-workbook atomic staging -> canonical input batches -> canonical write -> worker commit -> immutable release -> Supabase publish`

## Handoff rule

Do not redesign this into an evidence/source ingestion workflow and do not add requirements unless a concrete current-code blocker is demonstrated.
