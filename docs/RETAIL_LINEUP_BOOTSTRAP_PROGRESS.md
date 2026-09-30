# Retail Lineup Bootstrap — Progress

Branch: `feature/retail-lineup-bootstrap`

This file is the handoff/progress marker for the implementation described in `docs/RETAIL_LINEUP_BOOTSTRAP.md`.

## Chunk 1 — COMPLETE

Pure deterministic planner implemented in `automotive/vehicle_master/vehreg/retail_lineup_bootstrap.py`.

Owns:
- exact identity resolution only
- KEEP / CREATE / REACTIVATE / ARCHIVE classification
- baseline hash
- immutable plan hash
- no canonical writes

## Chunk 2 — COMPLETE

Staged apply semantics implemented in `automotive/vehicle_master/vehreg/retail_lineup_bootstrap_apply.py`.

Owns:
- CREATE by materializing a new base-Catalog MarketTrim
- explicit historical reopen for REACTIVATE
- authoritative current-retail-set replacement
- literal HISTORICAL archival for omitted old CURRENT trims
- baseline recheck
- plan-hash tamper detection
- idempotent replay of an already-landed exact post-state

No Admin UI and no whole-workbook live-tree promotion yet.

## Chunk 3 — COMPLETE

Implemented files:

- `automotive/vehicle_master/vehreg/retail_lineup_workbook.py`
- `automotive/vehicle_master/tools/retail_lineup_bootstrap_workbook.py`
- `automotive/vehicle_master/tests/test_retail_lineup_workbook.py`

Chunk 3 is intentionally **compile-only**. It does not call the Chunk 2 apply engine and does not mutate canonical data.

### Workbook contract

The generated workbook contains exactly these logical sheets:

1. `TARGET_LINEUP`
   - editable owner target state
   - `model_id`
   - `generation_id`
   - `trim_name`
   - `powertrain`
   - optional `canonical_trim_id`
   - optional `notes`

2. `CURRENT_SNAPSHOT`
   - read-only informational snapshot
   - current/known canonical trims
   - lifecycle/current flags
   - price/spec/campaign presence counts
   - ignored completely by compile/write semantics

3. `IMPORT_META`
   - schema version
   - generated timestamp
   - as-of date
   - catalog year
   - base release ID
   - baseline hash
   - mode `REPLACE_AND_ARCHIVE`
   - explicit target model scope

### Compile behavior

`compile_retail_lineup_workbook()`:

- accepts `.xlsx` only
- validates exact TARGET_LINEUP headers
- rejects formulas in write-bearing sheets
- rejects missing required values
- rejects a row outside the declared model scope
- rejects a targeted model with zero target rows
- rejects stale baseline before returning a plan
- delegates identity/diff semantics back to Chunk 1 instead of reimplementing them
- returns source SHA-256 + immutable plan
- performs no apply/write

### Generator behavior

`generate_retail_lineup_workbook()`:

- accepts one or many existing model IDs
- seeds TARGET_LINEUP from currently resolved CURRENT trims
- exports every known trim for the selected models into CURRENT_SNAPSHOT
- records current lifecycle/approved-set/resolved-current state
- records price/spec/campaign presence counts for operator context
- embeds the baseline hash used by the compiler
- protects CURRENT_SNAPSHOT and IMPORT_META against accidental edits
- provides exact powertrain dropdown values: ICE / HEV / PHEV / REEV / BEV / FCEV

A model with no resolved CURRENT trim does not silently become an empty target. The workbook inserts a visible `FILL REQUIRED` row and compile refuses it until the operator supplies at least one complete target trim.

### CLI

Generate:

```bash
python -m tools.retail_lineup_bootstrap_workbook generate \
  --model-id toyota.camry \
  --model-id honda.accord \
  --base-release-id vehicle-2026-... \
  --out lineup.xlsx
```

Compile preview:

```bash
python -m tools.retail_lineup_bootstrap_workbook compile lineup.xlsx --report plan.json
```

There is deliberately no `apply` subcommand in Chunk 3.

### Chunk 3 test contract

Coverage includes:

- generator emits the three-sheet contract
- target sheet is seeded from resolved current lineup
- snapshot includes informational price/spec/campaign presence
- untouched workbook compiles to all KEEP
- edited workbook compiles KEEP + CREATE + ARCHIVE
- CURRENT_SNAPSHOT edits do not affect the plan
- stale workbook fails `STALE_BASELINE`
- empty model target never means whole-model withdrawal
- formulas are rejected
- unknown/extra target headers are rejected
- target-model scope cannot silently change through row deletion/addition

### Validation

Draft PR #171 was used only to exercise repository CI; it remains unmerged.

The first full run exposed one Chunk-3-specific bug: openpyxl read-only blank cells can be `EmptyCell` objects with no `.coordinate`. Commit `f76af345d63e006466a5472d4e5d19020255ae9e` removed that assumption while preserving formula rejection.

The next full Vehicle Master run completed with **1594 passed / 11 failed / 4334 subtests passed**. The remaining 11 failures are the same pre-existing failures reproduced on `main`; no Retail Lineup Bootstrap test remained in the failure list. Web build passed. Therefore Chunk 3 introduces no additional known test failure relative to the current repository baseline.

### Commits

- `54e3ae636b399ba0f9a71a8142fdc2d5c3fa47bb` — workbook contract
- `4975253c7eaf71a8e9f8b5295d6b2e13eefbeec7` — workbook CLI
- `8adf3dbd843df2784bb0ec7d98e0160663e7a8c9` — workbook tests
- `f76af345d63e006466a5472d4e5d19020255ae9e` — read-only EmptyCell regression fix

A draft integration PR exists only to run repository CI: PR #171. It must not be merged merely because Chunk 3 is complete; later chunks remain outstanding.

## Chunk 4 — COMPLETE

Implemented files:

- `automotive/vehicle_master/vehreg/retail_lineup_bootstrap_transaction.py`
- `automotive/vehicle_master/tests/test_retail_lineup_bootstrap_transaction.py`

Chunk 4 owns the **whole-workbook transaction boundary**. It still does not expose an Admin/Supabase apply surface.

### Transaction semantics

- copy the whole canonical data tree to a temporary sandbox
- apply the immutable Chunk-2 plan only inside that sandbox
- build `ReleaseBuilder` against the staged tree
- run the production `enrich_release()` path against the staged tree
- require every target trim to serve as CURRENT and every archived trim to serve as literal HISTORICAL
- recheck the target-model semantic baseline on live data immediately before promotion
- capture SHA-256 fingerprints of live files that the transaction may replace and compare them again immediately before promotion
- fail with `CONCURRENT_WRITE_BEFORE_PROMOTION` if any would-be-replaced live file changed, including a write to another model inside the same shared sidecar
- promote only the changed files reported by staged apply
- if a mid-promotion file replacement raises, restore already-promoted files from pre-promotion bytes and clean `.rlb-tmp` / `.rlb-rollback` files
- idempotent replay with zero changed files validates the staged serving release but performs no promotion

The file-level compare-and-swap guard is intentionally stricter than the model-scoped semantic baseline. `current_retail.json` and `trim_review.json` are shared across models; another writer may modify another model or only reviewer/notes without changing the target model's resolved CURRENT set. Such a write must still block promotion rather than be overwritten by an older staged copy.

### Chunk 4 test contract

Coverage includes:

- successful stage validation before promotion
- release-validation failure leaves live tree byte-for-byte unchanged
- simulated mid-promotion disk failure rolls back already-promoted files
- simulated concurrent target-model writer after staging triggers `STALE_BASELINE_BEFORE_PROMOTION`
- simulated shared-sidecar writer that leaves target-model membership semantically unchanged still triggers `CONCURRENT_WRITE_BEFORE_PROMOTION`
- the external writer's bytes remain intact after the rejected promotion

### Validation

Draft PR #171 remains the CI harness and is still unmerged.

The final Chunk-4 head tested by CI was `46f51035e875de8030a64ba81a7ee74ee8f94504`.

Full Vehicle Master CI completed with **1599 passed / 11 failed / 4334 subtests passed**. The 11 failures are the same repository-baseline failures already present before Chunk 4; there is no `retail_lineup_bootstrap*` failure in the final failure list. TypeScript passed, the web build passed, and the official media target audit passed.

Therefore Chunk 4 is complete with no additional known regression relative to the current repository baseline.

### Commits

- `22eaf696dfdd4e8cc83d6b207606d7539814d9f0` — whole-workbook transaction implementation
- `57118c17847ca099b1952889f9bcc694161275f1` — transaction-boundary tests
- `ba0636b307adb91ce2331e5056b9a52bda08fee5` — rollback temp-file cleanup hardening
- `0e0056293e6dd17d87f3264dbf462b50346a4a67` — file-level compare-and-swap concurrent-write guard
- `46f51035e875de8030a64ba81a7ee74ee8f94504` — shared-sidecar concurrent-write regression test

## Next

Chunk 5 is the next implementation boundary: durable preview-plan state / confirmation handoff. Do not merge the draft PR merely because Chunk 4 is complete; Admin UI and final apply/publish integration remain later chunks.
