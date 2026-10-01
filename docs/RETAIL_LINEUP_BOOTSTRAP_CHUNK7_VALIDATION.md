# Retail Lineup Bootstrap — Chunk 7 validation

Status: **COMPLETE**

Runtime/test implementation head: `625261c430e4c6d331a85f1fa8fbd0759d199bc1`

This file is the validation completion marker for Chunk 7 and supersedes the earlier `IMPLEMENTED, VALIDATION PENDING` checkpoint in `docs/RETAIL_LINEUP_BOOTSTRAP_PROGRESS.md`.

## What Chunk 7 now covers

- `RETAIL_LINEUP_BOOTSTRAP` is wired as a durable `import_runs.source_kind` through `supabase/migration_v56_retail_lineup_import_kind.sql`.
- Uploaded XLSX is compiled by the dedicated server-side worker into exactly one immutable `PREVIEW_READY` plan linked to the import run.
- Compile retries recover through the durable `import_run_id` linkage instead of generating a second preview.
- Admin Apply executes only the already-reviewed stored `compiled_plan`; the XLSX is never parsed or identity-resolved again during Apply.
- The Chunk-4 whole-tree transaction is used for canonical writes.
- The apply workflow shares `concurrency.group = canonical-vehicle-input` with the canonical writers.
- The pushed commit is recorded before publish, the exact revision is published, and the durable plan reaches `COMPLETED` only after the serving release is confirmed.
- A 15-minute recovery sweep covers lost Apply dispatches.
- `WRITTEN_PENDING_PUBLISH` recovery only republishes when `main` is still the exact recorded commit; it refuses to force-publish an older revision after main advanced.

## CI result

PR CI for runtime/test head `625261c430e4c6d331a85f1fa8fbd0759d199bc1` completed as follows:

- TypeScript: **PASS**
- Consolidated web build: **PASS**
- Official media target audit: **PASS**
- Python compile: **PASS**
- Full Vehicle Master test suite: **1629 passed / 11 failed / 4334 subtests passed**

The 11 failures are the same repository-baseline failures already present before Chunk 7:

1. BYD ATTO 1 / Seagull DLT legacy-label expectation
2. GEELY EX5 pilot ECO provenance expectation
3. pilot fitment-value legacy guard
4. ECO snapshot resolved-count expectation
5. price-editing retract legacy expectation
6. price-editing close legacy expectation
7. price-editing file-count legacy expectation
8. price-editing supersede legacy expectation
9. product-master price-history ordering expectation
10. TDR bridge canonical model-count expectation
11. `canonical-input.yml` legacy concurrency-group expectation

No `retail_lineup_bootstrap*` or Chunk-7 worker test appears in the failure list.

## Production boundary

Chunk 7 validation does **not** activate production.

Still intentionally not done here:

- migrations v53-v56 have not been applied to production Supabase;
- PR #171 has not been merged to `main`;
- no production canonical write has occurred;
- no real bootstrap workbook has been applied.

The next step is controlled production integration, then a deliberately tiny end-to-end smoke test before the 73-model reset is allowed.
