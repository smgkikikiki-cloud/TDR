# Vehicle Spec Excel Import — WORKUPDATE

Branch: `feature/vehicle-spec-excel-importer`

Goal: finish a deterministic Excel -> canonical vehicle spec importer for existing MarketTrims, covering the full current field inventory without AI field guessing and without requiring source/evidence data in the workbook.

## Completed

### 2026-09-28 — Skeleton contracts

Created input-side contract:

- `docs/vehicle-spec-excel-import/INPUT_CONTRACT.md`
- commit `72687d539e91e3c20a55020d282757d3e3d103fd`

Key decisions captured:

- one row = one existing MarketTrim;
- `canonical_trim_id` is authoritative identity;
- blank = no-op;
- fixed machine headers;
- qualifier-dependent values encode qualifier in the column (e.g. `range_nedc_km`);
- no fuzzy matching;
- no mandatory source/evidence columns.

Created destination-side contract:

- `docs/vehicle-spec-excel-import/WRITE_CONTRACT.md`
- commit `6a594e097b187d44b02ce8566bae567a94638fd7`

Key decisions captured:

- deterministic normalized writes;
- classify each field as MarketTrim/core, comparable spec, or genuine dual representation;
- supplied values update current canonical state;
- same logical value must not duplicate on re-import;
- qualified values such as NEDC/WLTP may coexist;
- reuse canonical pipeline/release path;
- workbook remains source/evidence-free.

## Next

1. Inspect the complete current writable field inventory: MarketTrim/core plus comparable-spec registry.
2. Build the concrete mapping table for all current factors.
3. Identify every field that requires qualifier-specific Excel columns.
4. Implement parser/normalizer against that mapping.
5. Add direct canonical/admin write adapter where current spec writer requires source evidence.
6. Wire the new workbook kind into the existing admin upload/import worker.
7. Test sparse updates and full-field workbook import.

## Handoff rule

Do not redesign the scope into a new ingestion/evidence system. The workbook is a direct deterministic canonical-edit interface for existing trims.

Do not add new requirements unless current Vehicle Master code makes them technically necessary. If a new constraint is discovered, record the exact code reason here before implementing it.
