# Vehicle Spec Excel Import — Canonical Write Contract

Status: skeleton / implementation target

## Purpose

Define the deterministic destination behavior for values accepted from the Vehicle Spec Excel importer.

This path is direct canonical authoring for existing MarketTrims. It is not an external source/evidence ingestion workflow.

## Input to the writer

The parser must hand the writer normalized records containing at minimum:

- `canonical_trim_id`
- canonical field key or core-field destination
- normalized value/value-state
- qualifier metadata when the canonical field requires it

The writer must never infer vehicle identity, field destination, unit, or qualifier from free text.

## Destination classes

Every supported Excel field must be classified before implementation as one of:

1. MarketTrim/core field
2. comparable-spec field
3. dual representation only where the existing canonical model genuinely requires both

The field inventory/mapping table is the authority for this classification.

## Write semantics

- Blank Excel cells never produce write commands.
- A supplied valid value updates the current canonical value for that trim/field/qualifier.
- Re-importing the same value must not create duplicate logical values.
- Multiple qualified values for the same underlying field may coexist when the canonical model supports them, e.g. NEDC and WLTP range.
- Unknown trim IDs or invalid values must not be guessed into place.

## Source/evidence behavior

The Excel workbook must not be required to provide:

- source name
- source URL/reference
- observed-at date

If the existing comparable-spec writer currently requires evidence metadata, the importer needs a direct canonical/admin authoring path or adapter so the workbook remains source-free.

Operational audit metadata such as import run, actor, filename, or commit may be recorded by infrastructure, but it is not vehicle-spec source evidence and must not be required as workbook data.

## Existing integration points to reuse

Implementation should reuse the current canonical pipeline rather than write around it:

- Vehicle Master canonical file-backed data
- canonical command/input pipeline
- comparable-spec validation/registry
- existing import worker dispatch
- existing canonical release/publish path

The exact adapter will be chosen after inspecting the current core-field and spec-field write APIs together.

## Hard boundaries

This importer must not:

- create new canonical vehicle identities;
- use fuzzy matching;
- treat missing Excel cells as deletions;
- silently coerce an invalid qualifier or enum into a guessed value;
- route through ECO/DLT parsing logic simply because those import paths already exist.

## Next implementation step

Inventory all writable current vehicle fields and produce the concrete mapping table:

`excel_column -> destination_class -> canonical_key -> value_type -> qualifier/unit metadata`

Once that table is complete, implement the parser against it and then connect the normalized writes to the canonical pipeline.
