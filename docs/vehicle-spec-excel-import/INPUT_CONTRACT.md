# Vehicle Spec Excel Import — Input Contract

Status: skeleton / implementation target

## Purpose

Define the deterministic Excel shape used to update specs for existing canonical MarketTrims.

This importer is **not** an evidence/source ingestion path and must not require source URLs, source names, or observed-at metadata in the workbook.

## Identity

One data row represents one existing canonical MarketTrim.

Required machine identity column:

- `canonical_trim_id`

The importer must use `canonical_trim_id` as the authority for placement. Human-readable brand/model/generation/trim labels may be included for readability but must not create or fuzzy-match vehicle identities.

If `canonical_trim_id` does not resolve to an existing trim, the row is invalid.

## Field columns

Vehicle data is expressed through fixed machine headers. Each supported header maps deterministically to exactly one canonical field definition.

Examples only:

- `seats`
- `length_mm`
- `width_mm`
- `battery_usable_kwh`
- `aeb`
- `range_nedc_km`
- `range_wltp_km`

The complete supported header list will be generated from the current Vehicle Master field inventory before parser implementation.

## Qualifiers

A value that is meaningless without a qualifier must encode that qualifier in the machine column itself.

Example:

- `range_nedc_km = 300`
- `range_wltp_km = 270`

Do not use a generic `range_km = 300` and ask the importer to infer NEDC/WLTP/CLTC.

The same rule applies to any other canonical field whose meaning depends on a qualifier.

## Cell semantics

- Blank cell: no-op; do not change the existing canonical value.
- Non-blank cell: parse and validate according to the mapped canonical field type.
- Invalid type/value: reject that input instead of guessing.

Special value-state tokens will be defined from the existing canonical registry rather than invented independently by the Excel parser.

## Type handling

The importer must obtain field type/allowed-value behavior from the canonical field registry wherever possible. It must not infer field meaning from cell content.

Typical canonical types include:

- boolean
- integer/number
- enum
- text
- set/value-state where supported by Vehicle Master

## Non-goals

The workbook must not:

- create Brand, Model, Generation, or MarketTrim identities;
- fuzzy-match trim names;
- contain mandatory source/evidence metadata;
- require AI interpretation to decide destination fields;
- delete values merely because cells are blank.

## Next implementation step

Build the exact machine-header inventory by inspecting the current MarketTrim/core fields and comparable-spec registry, then bind each Excel header to its canonical destination and qualifier metadata.
