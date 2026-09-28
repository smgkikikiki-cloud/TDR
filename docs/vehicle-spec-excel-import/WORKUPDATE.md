# Vehicle Spec Excel Import — WORKUPDATE

Branch: `feature/vehicle-spec-excel-importer`

Goal: finish a deterministic Excel -> canonical vehicle spec importer for existing MarketTrims, covering the full current field inventory without AI field guessing and without requiring source/evidence data in the workbook.

## Completed

### 2026-09-28 — Skeleton contracts

- Input contract: `docs/vehicle-spec-excel-import/INPUT_CONTRACT.md` (`72687d539e91e3c20a55020d282757d3e3d103fd`)
- Write contract: `docs/vehicle-spec-excel-import/WRITE_CONTRACT.md` (`6a594e097b187d44b02ce8566bae567a94638fd7`)

Locked behavior: one row = one existing MarketTrim; `canonical_trim_id` is authoritative; blank = no-op; fixed machine headers; qualifier-dependent values encode the qualifier; no fuzzy matching; no mandatory source/evidence columns.

### 2026-09-28 — Deterministic compiler

Added `automotive/vehicle_master/vehreg/spec_excel.py` (`d73405bd8b6ea84bc7ce78bd750f3b4567c6d4fa`).

Implemented:

- Registry-driven field recognition and type validation for current comparable-spec fields.
- Sparse writes: blank cells produce no command.
- Existing `canonical_trim_id` required; no vehicle creation or fuzzy matching.
- BOOLEAN accepts YES/NO, TRUE/FALSE, 1/0; NUMBER, ENUM/TEXT and SET are parsed deterministically.
- Explicit value states: `UNKNOWN`, `NOT_AVAILABLE`, `NOT_APPLICABLE`; ambiguous `-` is rejected.
- Powertrain applicability is checked from the registry.
- Qualifier-aware headers. Common aliases include NEDC/CLTC/WLTP/WLTC/EPA ranges, electric-only ranges, laden/unladen ground clearance and common DC SOC windows. Generic registry qualifiers use `field.key__qualifier=value`.
- Qualifier-aware stable fact IDs so NEDC and WLTP for the same field do not overwrite each other.
- Sparse MarketTrim core updates plus comparable-spec writes.

Code discovery that directly affected implementation: canonical `APPEND_SPEC` defaults to one `admin:{trim}:{field}` fact ID, so two qualifier contexts would collide unless the importer supplies qualifier-aware fact IDs itself.

### 2026-09-28 — Import CLI and worker route

Added `automotive/vehicle_master/tools/import_vehicle_specs.py` (`55112e61f47c7fd806aa3624151107955db5e038`).

- Reads CSV/XLSX with `keep_default_na=False`.
- Loads current Catalog + SpecRegistry + SpecLedger.
- Compiles workbook into existing canonical input batches.
- Supports dry-run and `--apply`.
- Reuses the existing staged/validated canonical pipeline and produces a machine report for the upload worker.

Updated `automotive/vehicle_master/tools/import_worker.py` (`edaff7faa376e45bf0403c7672a50f019fdb9a30`).

- Added `VEHICLE_SPECS` handler.
- Treats it as a canonical-writing upload, therefore waits for commit + publish exactly like ECO when it actually changes data.
- Invalid workbooks fail their own run; they are never routed into ECO/DLT parsing.
- No-op workbooks complete without waiting for a publish that has no diff.

## In progress

1. Add usable workbook/template export from current registry + existing trim IDs.
2. Expose `VEHICLE_SPECS` in the existing admin upload UI.
3. Add focused tests for blank/no-op, type validation, exact identity and qualifier coexistence.
4. Run test suite / branch CI and fix failures.

## Handoff rule

Do not redesign the scope into a new ingestion/evidence system. The workbook is a direct deterministic canonical-edit interface for existing trims.

Do not add new requirements unless current Vehicle Master code makes them technically necessary. If a new constraint is discovered, record the exact code reason here before implementing it.
