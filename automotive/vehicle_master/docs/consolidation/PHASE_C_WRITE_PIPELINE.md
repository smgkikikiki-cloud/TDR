# Consolidation Phase C — canonical write pipeline

Status: implementation branch `consolidation/phase-c-write-pipeline-v4`.

Phase B put the canonical Vehicle Master and the TDR web in one repository. Phase C makes the distinction between **canonical automotive facts** and **TDR serving/editorial rows** enforceable in code before any destructive cutover.

## Ownership after this phase

Canonical automotive facts are written through `vehreg.canonical_write.CanonicalWritePipeline`:

- Brand / Model / Generation identity
- analytical Variant
- retail MarketTrim
- PriceLedger records
- comparable SpecLedger facts

The following remain TDR-owned and are intentionally not moved into that writer:

- `image_url`
- `consumer_description`
- `featured`
- editorial/news content
- plant / production-program / Local Content / MiT facts

Supabase `brands`, `models`, `model_powertrains` and `trims` remain a legacy serving/editor surface during shadow mode. They are **not** promoted to canonical truth by this phase.

## Canonical write contract

A command has a stable `command_id`, operation, year, actor/reason, optional stable canonical ID and operation-specific payload.

Supported operations:

```text
UPSERT_MODEL_BUNDLE
WITHDRAW_MODEL
APPEND_PRICE
APPEND_SPEC
```

The writer stages and validates the canonical state before changing files. Successful writes create:

```text
vehreg/data/<year>/canonical_state/revisions.jsonl
vehreg/data/<year>/canonical_state/outbox.jsonl
vehreg/data/<year>/canonical_state/shadow/<revision_id>.json
```

`command_id` is idempotent. Retrying the same command returns the existing revision instead of creating a second write.

`WITHDRAW_MODEL` never deletes identity. It changes retail status to historical and can close a generation with an explicit end date.

`APPEND_PRICE` writes only to PriceLedger. It cannot populate `MarketTrim.price_thb` or TDR `trims.price_baht` as canonical state.

`APPEND_SPEC` writes only to the comparable-spec ledger and is checked against its registry and MarketTrim identity.

Operational CLI:

```bash
cd automotive/vehicle_master
python tools/canonical_write.py command.json
```

## Supabase bridge

`supabase/migration_v12_canonical_write_pipeline.sql` adds four private/server-only tables:

- `canonical_object_map`
- `canonical_write_commands`
- `canonical_write_revisions`
- `canonical_publish_outbox`

RLS is enabled and no anon/authenticated policy is added.

`canonical_object_map` is the only bridge from legacy TDR UUIDs to stable Vehicle Master IDs. A row is executable only when `status = 'verified'`. A candidate produced from a name/slug comparison must stay `unmatched`/`ambiguous` until somebody verifies the identity; name equality is not authority.

At deployment, inventory every legacy TDR model into `canonical_object_map` as `unmatched`. Then promote only reviewed mappings to `verified`.

## Legacy editor shadow mode

`app/admin/catalog-actions.ts` still performs the old Supabase write for now. After it succeeds, it calls `enqueueCanonicalModelShadow()`.

The shadow command intentionally excludes:

- trim `priceBaht` — PriceLedger owns price
- `image_url`, `featured`, `consumer_description` — TDR owns editorial display

If a verified model crosswalk exists, the command is queued. If no verified mapping exists, it is recorded as `needs_crosswalk`. If the Phase-C migration has not been deployed yet, the shadow call disables itself rather than breaking the production editor.

This shadow period is deliberate. The legacy editor cannot become the active canonical writer merely because model names look similar: generation, Variant and MarketTrim semantics differ between the old TDR schema and Vehicle Master.

## Crosswalk rule

For every legacy object:

```text
TDR UUID
  -> candidate(s)
  -> human/evidence review
  -> VERIFIED stable canonical ID
```

Never:

```text
TDR name == Vehicle Master name
  -> silently assume same object
```

The first live pilot is Jaecoo 5 EV because its TDR row and canonical model were inspected directly. It may be seeded as a deliberately verified model-level mapping; this does not imply its legacy child powertrain/trim rows can be mapped without separate evidence.

## What Phase C does not activate

- no registration import to Supabase
- no `publish_market`
- no change to the currently open legacy registration RLS (Phase D closes entitlement first)
- no deletion of old TDR vehicle rows
- no automatic conversion of 327 legacy models by name
- no public `/production` or `/plants` cleanup yet
- no archive of `vehicle-market-master`

## Cutover gate to retire duplicate writes

Do not disable the legacy vehicle editor until all of these are true:

1. canonical create/update/withdraw commands pass end-to-end;
2. model and required child-object crosswalks are verified for the object being edited;
3. canonical revision + outbox is produced for a save;
4. a shadow serving projection can be reconciled with the legacy page output;
5. rollback to the previous canonical revision is tested;
6. PriceLedger and SpecLedger remain the only active truth for their domains.

At that point Phase H can remove/disable duplicate Supabase vehicle write paths. Phase E will own the serving projection itself.

## Verification

The Phase-C test module checks:

- atomic catalog writes;
- invalid writes leave canonical files untouched;
- idempotent command replay;
- revision/outbox/shadow emission;
- non-destructive withdrawal;
- PriceLedger ownership;
- SpecLedger ownership.

The repository CI also reruns the complete Vehicle Master suite and the TDR Next.js build on every PR.
