# Vehicle Spec Excel Import — WORKUPDATE

Branch: `feature/vehicle-spec-excel-importer`
PR: `#164` — Add deterministic vehicle spec Excel importer

Goal: deterministic Excel -> canonical vehicle spec importer for existing MarketTrims, covering the full current SpecRegistry inventory without AI field guessing and without requiring source/evidence columns in the workbook.

## Completed

### Skeleton contracts

- Input contract: `docs/vehicle-spec-excel-import/INPUT_CONTRACT.md` (`72687d539e91e3c20a55020d282757d3e3d103fd`)
- Write contract: `docs/vehicle-spec-excel-import/WRITE_CONTRACT.md` (`6a594e097b187d44b02ce8566bae567a94638fd7`)

Locked behavior:

- one row = one existing MarketTrim;
- `canonical_trim_id` is authoritative;
- blank = no-op;
- fixed machine headers;
- qualifier-dependent values encode qualifier context in the header;
- no fuzzy vehicle/field matching;
- no source/evidence columns are required in the workbook.

### Deterministic compiler

`automotive/vehicle_master/vehreg/spec_excel.py`

Implemented:

- Registry-driven field recognition/type/unit validation.
- Existing `canonical_trim_id` required; no vehicle creation or fuzzy matching.
- BOOLEAN accepts YES/NO, TRUE/FALSE, 1/0; NUMBER, ENUM/TEXT and SET parse deterministically.
- Explicit states: `UNKNOWN`, `NOT_AVAILABLE`, `NOT_APPLICABLE`; ambiguous `-` is rejected.
- Powertrain applicability comes from SpecRegistry.
- Qualifier-aware fixed aliases plus generic `field.key__qualifier=value` syntax.
- Bare headers are rejected for registry fields that require qualifier context.
- Qualifier-aware stable fact IDs allow NEDC/WLTP/CLTC etc. to coexist.
- Sparse MarketTrim core + comparable-spec dual writes where the current canonical model stores both.
- `battery.catalog_capacity_kwh` also updates `MarketTrim.battery_kwh`.
- `NOT_APPLICABLE` on a field excluded by the trim powertrain is a deterministic no-op because SpecLedger itself does not store such a fact.

Important discovery: canonical `APPEND_SPEC` defaults to one `admin:{trim}:{field}` fact ID. Qualified values would collide without importer-supplied qualifier-aware fact IDs, so the importer always supplies stable qualifier-aware IDs.

Relevant fixes:

- `4164e54dbf126ed70f520a5efd40b5562b279f43` — enforce qualifiers + sync catalog battery capacity
- `5eeb56e0c8d9bdf234d0a345f67e2bd16a01eb62` — inapplicable fields deterministic no-op
- `0322d6f1c33b7ae27d2f3a663772c1fb1211a9bf` — test inapplicable no-op

### Import CLI and worker route

- Added `automotive/vehicle_master/tools/import_vehicle_specs.py`.
- Reads CSV or the `SPECS` sheet of XLSX with `keep_default_na=False`.
- Human display columns are ignored for placement; only `canonical_trim_id` places a row.
- Loads current Catalog + SpecRegistry + SpecLedger.
- Supports dry-run and `--apply` through the existing staged canonical input pipeline.
- Added `VEHICLE_SPECS` to `tools/import_worker.py`.
- Canonical-changing runs wait for commit + publish; no-op runs complete without fake pending-publish state.

Relevant commits:

- `55112e61f47c7fd806aa3624151107955db5e038` — importer CLI
- `edaff7faa376e45bf0403c7672a50f019fdb9a30` — worker route
- `311de8f1d7fb7ff3f30150571d5854d1f3cc17c0` — display-column handling

### Workbook template exporter

Added `automotive/vehicle_master/tools/export_vehicle_spec_template.py`.

Generated workbook:

- `SPECS`: exact canonical trim rows + deterministic editable machine headers.
- `FIELD_DICTIONARY`: current registry fields with type, unit, applicable powertrains, qualifier names and accepted headers.
- `README`: only rules needed to fill the workbook.

Coverage fixes:

- `b9dc63b11a923df78b5feab754ecda7f1eeb39b7` — initial exporter
- `3b9d73340a84df5dcb9a273f5e3a8f840dbdbb84` — emit every qualified live-registry field
- `d5b58ec729856d5dadd341768694c6c3b5d2c5e7` — require live registry coverage in tests

The generated template now has a machine-readable route for every current SpecRegistry field. Qualified fields are never emitted as ambiguous bare columns.

### Admin upload route

- `app/admin/import-actions.ts` accepts `VEHICLE_SPECS`.
- `/admin/import` exposes `Vehicle Specs / Canonical Excel` and defaults to it.
- Existing ECO and DLT parsers remain separate.
- UI accepts only the file formats actually handled by the importer (`.csv`, `.xlsx`).

Relevant commits:

- `d12ed22efb251792c3f76e38bb8a4f72be84697e`
- `71d322ad87d3da01ff48553179c6a5d4040bb4d7`
- `32cf108a7afeff1d89263bd42d19f88b83ac7afc`

### Supabase import-run gate

Production `import_runs_source_kind_check` originally rejected `VEHICLE_SPECS` even though the app/worker supported it. This was a real runtime blocker.

Applied migration:

- migration `20260928164830 vehicle_specs_import_kind_v51`
- current constraint permits `ECO`, `OEM`, `MEDIA`, `DLT`, `PRICE`, `VEHICLE_SPECS`
- repo record: `docs/vehicle-spec-excel-import/SUPABASE_MIGRATION.sql`
- tracking commit: `155b33c53e00c20689cf88500a9e42728dc14b80`

### Focused tests

`automotive/vehicle_master/tests/test_spec_excel.py` covers:

- YES/NO boolean parsing;
- NEDC + WLTP coexist with distinct fact IDs;
- ambiguous bare qualified fields reject;
- generic qualified-header parsing;
- blank = no-op;
- unknown canonical trim rejects;
- ambiguous `-` rejects;
- core/spec dual write including battery capacity;
- powertrain contradiction rejects;
- `NOT_APPLICABLE` no-op / real inapplicable values reject;
- same existing fact becomes no-op;
- generated headers parse against the live registry and cover every current field.

## CI status on importer head `32cf108a7afeff1d89263bd42d19f88b83ac7afc`

### Web / build

PASS.

The consolidated `web` job completed successfully, including `npm run build` and `/admin/import`.

### Python

Python compile PASS.

Full suite result:

- `1569 passed`
- `4334 subtests passed`
- `9 failed`

None of the nine failures is in `tests/test_spec_excel.py` or the importer files. The failures are in existing repository expectations around:

- DLT alias expectation for BYD ATTO 1 / old Seagull naming;
- ECO provenance expectation for an existing Geely EX5 trim;
- stale ECO resolved-count expectation (`368` vs current `370`);
- four existing price-editing expectations affected by current canonical price state;
- ProductMaster price-history expectation;
- stale canonical model-count expectation (`321` vs current `323`).

The same nine failures appear in both Vehicle Master workflow variants for this PR.

### TypeScript/check suite

`npm run check` fails on two existing textual smoke assertions in `scripts/check-trim-retail-lifecycle-review.ts`:

- `workflow store enforces canonical parent CURRENT`
- `workflow store exempts reopen from parent guard`

This importer PR does not modify the lifecycle implementation or its smoke script. The consolidated production web build passes.

## Important remaining blocker

The importer is not yet fully compliant with the explicit requirement: **no source**.

Current `spec_excel.py` still generates internal compatibility metadata for spec facts:

- `source = direct_canonical_excel`
- `source_ref = audit_ref`
- infrastructure-generated `observed_at`

This is not workbook input, but it is still fake source/evidence metadata and therefore should not be the final design.

Why it exists: `SpecLedger._validate_fact()` currently rejects every comparable-spec fact unless `observed_at`, `source`, and `source_ref` are present.

Final fix must be narrow: direct canonical/admin `admin:` facts written by this Excel path must be allowed to validate without external `source/source_ref`, while ECO/OEM/evidence facts must keep their existing provenance requirements. Do not globally weaken SpecLedger provenance validation.

## Current functional state

The end-to-end path exists:

`template -> Excel/CSV -> deterministic parser -> canonical commands -> worker route -> canonical pipeline -> release/publish path`

Supabase accepts `VEHICLE_SPECS`; web build passes; focused importer tests pass inside the full suite.

Feature status: **mostly implemented, not yet merge-ready** because the internal fake source/source_ref shim remains.

## Remaining

1. Remove internal fake `source/source_ref` from direct Excel facts using a narrowly scoped direct-admin canonical validation path.
2. Add focused tests proving direct admin facts can be source-free while normal evidence facts still require provenance.
3. Rerun focused importer tests + compile/build checks.
4. Record final commit and test results here.
5. Do not merge automatically; user decides merge timing.

## Handoff rule

Do not redesign this into an ingestion/evidence workflow. The workbook is a direct deterministic canonical-edit interface for existing trims.

Do not add new requirements unless current Vehicle Master code makes them technically necessary. If a new technical blocker is discovered, record the exact code reason here before implementing it.
