# Vehicle Spec Excel Import — WORKUPDATE

Branch: `feature/vehicle-spec-excel-importer`
PR: `#164` — Add deterministic vehicle spec Excel importer

Goal: finish a deterministic Excel -> canonical vehicle spec importer for existing MarketTrims, covering the full current field inventory without AI field guessing and without requiring source/evidence data in the workbook.

## Completed

### 2026-09-28 — Skeleton contracts

- Input contract: `docs/vehicle-spec-excel-import/INPUT_CONTRACT.md` (`72687d539e91e3c20a55020d282757d3e3d103fd`)
- Write contract: `docs/vehicle-spec-excel-import/WRITE_CONTRACT.md` (`6a594e097b187d44b02ce8566bae567a94638fd7`)

Locked behavior: one row = one existing MarketTrim; `canonical_trim_id` is authoritative; blank = no-op; fixed machine headers; qualifier-dependent values encode the qualifier; no fuzzy matching; no mandatory source/evidence columns.

### 2026-09-28 — Deterministic compiler

`automotive/vehicle_master/vehreg/spec_excel.py`

Implemented:

- Registry-driven field recognition/type/unit validation.
- Sparse writes: blank cells produce no command.
- Existing `canonical_trim_id` required; no vehicle creation or fuzzy matching.
- BOOLEAN accepts YES/NO, TRUE/FALSE, 1/0; NUMBER, ENUM/TEXT and SET are parsed deterministically.
- Explicit states: `UNKNOWN`, `NOT_AVAILABLE`, `NOT_APPLICABLE`; ambiguous `-` is rejected.
- Powertrain applicability from registry.
- Qualifier-aware fixed aliases plus generic `field.key__qualifier=value` syntax.
- Bare headers are rejected for registry fields that require qualifier context.
- Qualifier-aware stable fact IDs so NEDC/WLTP/CLTC values coexist instead of overwriting.
- Sparse MarketTrim core + comparable-spec dual writes where both representations exist.
- `battery.catalog_capacity_kwh` also updates `MarketTrim.battery_kwh`.

Code discovery that directly affected implementation: canonical `APPEND_SPEC` defaults to one `admin:{trim}:{field}` fact ID, so two qualifier contexts collide unless this importer supplies qualifier-aware fact IDs.

Latest compiler fix commit: `4164e54dbf126ed70f520a5efd40b5562b279f43`.

### 2026-09-28 — Import CLI and worker route

- Added `automotive/vehicle_master/tools/import_vehicle_specs.py`.
- Reads CSV or the `SPECS` sheet of XLSX with `keep_default_na=False`.
- Human display columns are ignored for placement; only `canonical_trim_id` places a row.
- Loads current Catalog + SpecRegistry + SpecLedger.
- Supports dry-run and `--apply` through existing staged canonical input pipeline.
- Added `VEHICLE_SPECS` to `tools/import_worker.py`; canonical-changing runs wait for commit + publish, no-op runs finish without a fake pending publish.

Worker route commit: `edaff7faa376e45bf0403c7672a50f019fdb9a30`.
Display-column CLI update: `311de8f1d7fb7ff3f30150571d5854d1f3cc17c0`.

### 2026-09-28 — Workbook template exporter

Added `automotive/vehicle_master/tools/export_vehicle_spec_template.py` (`b9dc63b11a923df78b5feab754ecda7f1eeb39b7`).

It generates:

- `SPECS`: exact canonical trim rows + deterministic editable headers.
- `FIELD_DICTIONARY`: every current registry field, type, unit, applicable powertrains, qualifier names, ready fixed columns and generic qualified-header rule.
- `README`: only the workbook rules needed to fill it.

Qualified registry fields are not emitted as ambiguous bare value columns. Common qualifier cases are fixed columns; uncommon cases remain fully supported through the documented generic qualified-header syntax.

### 2026-09-28 — Admin upload route

- `app/admin/import-actions.ts` now accepts `VEHICLE_SPECS` (`d12ed22efb251792c3f76e38bb8a4f72be84697e`).
- `/admin/import` exposes `Vehicle Specs / Canonical Excel` and defaults to it (`71d322ad87d3da01ff48553179c6a5d4040bb4d7`).
- Existing ECO and DLT routes remain separate.

### 2026-09-28 — Focused tests

Added `automotive/vehicle_master/tests/test_spec_excel.py` (`bd237e9ddb208d4a06c79631e64e93da496e3fd7`).

Covers:

- YES/NO boolean parsing.
- NEDC + WLTP coexist with distinct fact IDs.
- ambiguous bare qualified fields reject.
- generic qualified-header parsing.
- blank = no-op.
- unknown canonical trim rejects.
- ambiguous `-` rejects.
- core/spec dual write including battery capacity.
- powertrain contradiction rejects.
- same existing fact becomes no-op.

## CI

PR #164 opened. Repository PR workflows are running against the implementation branch. Do not merge until CI result is checked and any failures are fixed.

## Remaining

1. Check PR #164 CI.
2. Fix any real failures.
3. Record final green status here.

## Handoff rule

Do not redesign the scope into a new ingestion/evidence system. The workbook is a direct deterministic canonical-edit interface for existing trims.

Do not add new requirements unless current Vehicle Master code makes them technically necessary. If a new constraint is discovered, record the exact code reason here before implementing it.
