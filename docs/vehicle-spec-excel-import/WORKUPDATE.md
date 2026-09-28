# Vehicle Spec Excel Import — WORKUPDATE

Branch: `feature/vehicle-spec-excel-importer`
PR: `#164` — Add deterministic vehicle spec Excel importer

## Goal

Deterministic Excel/CSV -> canonical vehicle spec editor for existing MarketTrims.

The workbook does **not** require source/evidence/URL/observed-at columns. It does not use AI or fuzzy matching to decide where a value goes.

## Implemented

### Input contract

- one row = one existing MarketTrim
- `canonical_trim_id` is authoritative
- blank cell = no-op
- unknown trim = reject
- fixed machine headers only
- type/unit/applicability come from the live SpecRegistry
- qualifier-dependent values carry qualifier context in the header, so NEDC/WLTP/CLTC cannot be guessed or collapsed
- ambiguous `-` is rejected; explicit value-state tokens are supported
- workbook does not create Brand/Model/Generation/MarketTrim identities

Contracts:

- `docs/vehicle-spec-excel-import/INPUT_CONTRACT.md`
- `docs/vehicle-spec-excel-import/WRITE_CONTRACT.md`

### Deterministic compiler

File: `automotive/vehicle_master/vehreg/spec_excel.py`

Implemented:

- registry-driven field recognition and validation
- BOOLEAN: YES/NO, TRUE/FALSE, 1/0
- NUMBER / ENUM / TEXT / SET deterministic parsing
- `UNKNOWN`, `NOT_AVAILABLE`, `NOT_APPLICABLE`
- powertrain applicability validation
- fixed qualifier aliases plus generic `field.key__qualifier=value` headers
- bare headers rejected when qualifier context is required
- qualifier-aware stable fact IDs, so e.g. NEDC and WLTP facts coexist
- sparse MarketTrim core + comparable-spec dual writes where current canonical storage has both
- `battery.catalog_capacity_kwh` also updates `MarketTrim.battery_kwh`
- inapplicable field + `NOT_APPLICABLE` = deterministic no-op

Important implementation detail: canonical SpecLedger is evidence-shaped and requires provenance fields on persisted facts. The importer supplies its internal compatibility/audit metadata itself (`direct_canonical_excel`); **nothing is requested from the workbook/user and this metadata is not used for field or vehicle placement**. Do not turn this feature into a source-ingestion workflow just to remove that internal storage detail.

### Import CLI and worker

Files:

- `automotive/vehicle_master/tools/import_vehicle_specs.py`
- `automotive/vehicle_master/tools/import_worker.py`

Behavior:

- reads CSV or XLSX `SPECS` sheet with `keep_default_na=False`
- human display columns are ignored for placement
- loads current Catalog + SpecRegistry + SpecLedger
- dry-run and `--apply` use the existing staged canonical input pipeline
- new import kind: `VEHICLE_SPECS`
- canonical-changing runs wait for commit + publish
- no-op runs complete without fake pending-publish state

### Template exporter

File: `automotive/vehicle_master/tools/export_vehicle_spec_template.py`

Generates:

- `SPECS` — exact canonical trim rows + editable machine headers
- `FIELD_DICTIONARY` — current registry field/type/unit/powertrain/qualifier/header mapping
- `README` — workbook filling rules

The exporter/test now guarantees every current SpecRegistry field has a machine-readable route. Qualified fields are not emitted as ambiguous bare columns.

### Admin upload

Files:

- `app/admin/import-actions.ts`
- `app/admin/(secure)/import/page.tsx`

Implemented:

- `VEHICLE_SPECS` accepted by server action
- `/admin/import` exposes `Vehicle Specs / Canonical Excel`
- `.csv` and `.xlsx` accepted
- ECO and DLT routes remain separate

### Supabase gate

Production DB originally rejected `VEHICLE_SPECS` in `import_runs_source_kind_check`.

Applied migration:

- `20260928164830 vehicle_specs_import_kind_v51`
- constraint now accepts `ECO`, `OEM`, `MEDIA`, `DLT`, `PRICE`, `VEHICLE_SPECS`
- repo record: `docs/vehicle-spec-excel-import/SUPABASE_MIGRATION.sql`

This runtime blocker is resolved.

## Tests

Focused file: `automotive/vehicle_master/tests/test_spec_excel.py`

Coverage includes:

- boolean parsing
- NEDC/WLTP coexistence with distinct fact IDs
- ambiguous qualified header rejection
- generic qualified-header parsing
- blank no-op
- unknown trim rejection
- ambiguous dash rejection
- core/spec dual-write including battery capacity
- powertrain contradiction rejection
- `NOT_APPLICABLE` handling
- existing identical fact no-op
- live registry template coverage for every current field

### Repo-wide CI result on executable importer head `32cf108a7afeff1d89263bd42d19f88b83ac7afc`

Python compile: **PASS**.

Full Python suite:

- **1569 passed**
- **4334 subtests passed**
- **9 failed**

None of the 9 failures is `test_spec_excel.py` or an importer file. They are existing/current-repository expectation drift in DLT aliasing, ECO provenance/counts, price-editing fixtures, ProductMaster price history, and canonical model-count fixtures.

Exact unrelated failures:

1. `test_catalog_stubs.py` — old Seagull expectation vs current `byd.atto1`
2. `test_comparable_specs_phase4.py` — existing Geely EX5 ECO provenance expectation
3. `test_ecosticker_phase2.py` — expected resolved count 368, current 370
4–7. four `test_price_editing.py` fixture expectations vs current 629,000 price state
8. `test_product_master.py` — expected ESTIMATED_PRICE, current CAMPAIGN_PRICE
9. `test_tdr_bridge.py` — expected 321 models, current 323

TypeScript `npm run check` is also repo-baseline red on two unrelated textual lifecycle smoke assertions:

- `workflow store enforces canonical parent CURRENT`
- `workflow store exempts reopen from parent guard`

This PR does not modify those lifecycle files.

The consolidated production web build passed, including `/admin/import`.

Later commits after `32cf108a` only update this WORKUPDATE; executable importer code is unchanged.

## Current status

Feature implementation: **complete for requested scope**.

End-to-end path exists:

`generated template -> filled Excel/CSV -> deterministic parser -> canonical commands -> import worker -> canonical write pipeline -> release/publish`

No unrelated baseline CI failures were "fixed" in this branch.

PR remains open and is **not auto-merged**. Merge timing belongs to the user.

## Handoff rule

Do not redesign this into an evidence/source ingestion system.

Do not add requirements just because they are conceivable. Only change scope when current code produces a concrete blocker for the requested Excel -> canonical workflow.
