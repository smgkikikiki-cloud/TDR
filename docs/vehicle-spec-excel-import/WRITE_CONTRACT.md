# Vehicle Spec Excel Import — Canonical Write Contract

Status: implemented / current contract

## Purpose

The Vehicle Specs workbook is a direct deterministic canonical editor for existing MarketTrims. It is not an ECO/DLT/OEM evidence ingestion workflow.

## Normalized input

The compiler resolves every non-blank workbook cell before it reaches the canonical writer:

- exact `canonical_trim_id`
- exact registry field key or explicit MarketTrim core destination
- normalized value/value-state
- canonical unit from SpecRegistry
- qualifier metadata encoded by the machine header

No vehicle identity, field destination, unit, or qualifier is inferred from free text.

## Destinations

Supported columns resolve to one of:

1. comparable-spec fact
2. MarketTrim/core field
3. both, only where the current canonical model stores the same current value in both representations

The implemented mapping lives in `automotive/vehicle_master/vehreg/spec_excel.py`; registry metadata remains the authority for comparable-spec type/unit/applicability.

## Write semantics

- blank cells produce no command
- valid supplied values replace/revise the current direct canonical value for that trim/field/qualifier
- re-importing an identical value is a no-op
- distinct qualified values may coexist, e.g. NEDC and WLTP range
- unknown trims, invalid values, and unsupported qualifier names are rejected rather than guessed
- the importer never creates vehicle identities

Direct comparable-spec facts created by this workbook are source-free. They retain infrastructure-generated `observed_at` only for deterministic ordering. External/non-admin facts continue to require source evidence under SpecLedger validation.

## Whole-workbook atomicity

A workbook may compile to more commands than one canonical input batch can hold. All batches are therefore applied to an outer temporary copy of Vehicle Master first.

Only after every batch succeeds are the changed files promoted to the live canonical tree. If any later batch fails, no earlier batch from that workbook is left in the live tree.

Implementation: `_apply_batches_atomically()` in `automotive/vehicle_master/tools/import_vehicle_specs.py`.

## Existing pipeline reused

The feature uses the existing canonical machinery:

`Excel/CSV -> spec_excel compiler -> canonical input batches -> CanonicalInputPipeline -> canonical files -> source-import workflow commit -> immutable release -> Supabase publish`

Admin upload kind is `VEHICLE_SPECS`. Inside Vehicle Master the canonical batch source kind remains `ADMIN`; that is operational audit metadata, not vehicle-spec source evidence.

## Hard boundaries

The importer does not:

- create Brand/Model/Generation/MarketTrim identities
- fuzzy-match trim names
- treat blank cells as deletion
- require source/evidence columns
- route Vehicle Specs through ECO/DLT parsers
- partially apply a multi-batch workbook that later fails

Operational status and verification are recorded in `docs/vehicle-spec-excel-import/WORKUPDATE.md`.
