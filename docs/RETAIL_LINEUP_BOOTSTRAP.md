# TDR Retail Lineup Bootstrap / Reset

Status: **GO**. This is the rare, admin-only, highest-authority pipeline for repairing the retail identity layer before continuous Price Feed / trim monitoring takes over.

## Goal

The workbook declares the complete **target CURRENT lineup** for one or more existing models/generations. The system computes the transition. It must be able to:

- KEEP an existing CURRENT MarketTrim.
- CREATE a completely new MarketTrim identity.
- REACTIVATE an existing non-current/historical MarketTrim safely.
- ARCHIVE an old CURRENT MarketTrim omitted from the target state.
- Replace the model's authoritative CURRENT-retail set with the target set.
- Preserve all old price/spec/campaign/source/audit history.

It is not a daily updater. After bootstrap, Price Feed and Vehicle Specs enrich/maintain the identities created here.

## Existing primitives that make this feasible

- `UPSERT_MODEL_BUNDLE` already materializes new MarketTrim identities in base Catalog and validates the whole Catalog.
- `REPLACE_CURRENT_RETAIL_SET` already makes one supplied set the full authoritative CURRENT set for a model.
- The canonical input pipeline already supports `UPSERT_MODEL_BUNDLE` followed by `REPLACE_CURRENT_RETAIL_SET` in the same staged batch; the second command sees the newly-created trim.
- `tools/import_vehicle_specs.py` proves a workbook can compile deterministically, apply to a full sandbox, and promote only after all batches pass.
- Admin upload → `import_runs` → GitHub worker → canonical commit → exact-revision publish already exists.

## Gaps that must be solved

1. An omitted trim in an approved current-retail set currently normally becomes `UNVERIFIED`, not literal `HISTORICAL`. Bootstrap semantics must explicitly archive `old CURRENT - target CURRENT`.
2. The normal Import page executes after upload. This weapon must be two-phase: **Upload/Compile/Preview → explicit Admin Apply**.

Do not globally change existing `REPLACE_CURRENT_RETAIL_SET` semantics. Bootstrap gets its own orchestration layer.

## Workbook contract

### `TARGET_LINEUP`

Required logical columns:

- `model_id`
- `generation_id`
- `trim_name`
- `powertrain`
- `canonical_trim_id` (optional; force reuse of an existing identity)
- `notes` (optional)

One row means: **this MarketTrim must exist and must be CURRENT after apply**.

All rows for a model are the **whole target CURRENT lineup**. The user never types CREATE/KEEP/ARCHIVE commands; the compiler derives them.

### `CURRENT_SNAPSHOT`

Read-only informational export: current IDs, names, powertrains, lifecycle, price/spec/campaign presence. Ignored for writes.

### `IMPORT_META`

Must carry at least:

- `schema_version`
- `generated_at`
- `catalog_year`
- `base_release_id`
- `baseline_hash`
- `mode = REPLACE_AND_ARCHIVE`

## Identity rules

No fuzzy matching during write.

Resolution order:

1. Explicit `canonical_trim_id` → must exist and belong to submitted model/generation; name and powertrain must not contradict it.
2. No explicit ID → compute identity using the exact existing canonical MarketTrim identity function.
3. If that deterministic identity exists → reuse it.
4. If it does not exist → CREATE a new MarketTrim.
5. Ambiguous/collision/contradictory state → fail closed.

Powertrain is identity-critical, required, and may never be `UNKNOWN`.

Bootstrap MVP creates new **trims under existing model/generation only**. Creating a brand-new model or generation is out of scope for V1.

## Diff semantics

Per model:

```text
OLD_CURRENT = resolved current base-Catalog MarketTrims
TARGET_CURRENT = workbook target identities

KEEP       = target identities already CURRENT
CREATE     = target identities absent from Catalog
REACTIVATE = target identities present in Catalog but not CURRENT
ARCHIVE    = OLD_CURRENT - TARGET_CURRENT
```

Final authoritative set is exactly `TARGET_CURRENT`.

Old trims are never deleted. Price/spec/campaign/source history stays attached to the old canonical ID.

## New-trim creation

New MarketTrim creation is a core requirement. Minimum identity payload:

- existing brand/model/generation parent
- `name`
- exact `powertrain`
- deterministic canonical/local ID
- aliases default empty

Do not fabricate or copy price, drivetrain, engine, battery, dimensions, wheels/tyres, equipment, range, power/torque or source refs. Downstream pipelines own enrichment.

## Stale-workbook guard

Mandatory `baseline_hash` over the touched model identity/lifecycle state, including at least:

- model/generation identity and lifecycle
- known MarketTrim IDs/names/powertrains
- approved current-retail membership
- resolved CURRENT membership
- trim lifecycle decisions

At preview and again at apply, current hash must match. Otherwise `STALE_BASELINE`; do not auto-merge a stale authoritative reset.

## Preview / confirmation

Upload must not write canonical data. It produces an immutable plan showing, per model and total:

- KEEP
- CREATE
- REACTIVATE
- ARCHIVE
- before CURRENT count
- after CURRENT count
- invalid/stale rows

Persist source hash, baseline hash, plan hash and compiled plan. Apply must execute exactly that previewed plan after re-checking baseline and admin identity.

## Transaction boundary

Preferred: **whole workbook atomic**.

For a 73-model workbook, stage all models, validate the whole Catalog/release, then promote. If model 61 fails, model 1–60 must not remain written.

Empty target state must never mean withdraw model. A targeted model requires at least one target trim. Whole-model withdrawal remains a separate explicit operation.

## Historical reactivation

Current code correctly prevents an unreopened HUMAN-HISTORICAL trim from silently returning to an approved current set. Bootstrap must preserve that invariant.

A historical target identity previews as `REACTIVATE`; apply must explicitly reopen it before setting the final CURRENT set.

## Pipeline hierarchy

```text
LEVEL 0  Retail Lineup Bootstrap
         rare admin identity reset

LEVEL 1  Price Feed
         continuous price/promo/trim-existence maintenance

LEVEL 2  Vehicle Specs
         canonical spec enrichment

LEVEL 3  automated watchers
         drift/anomaly monitoring
```

Lower layers may enrich identity truth; they may not resurrect identities that Level 0 has archived.

## Implementation chunks

### CHUNK 1 — Pure deterministic planner

File: `vehreg/retail_lineup_bootstrap.py`

Inputs:

- target rows
- Catalog snapshot
- current-retail state
- lifecycle decisions
- as-of date
- optional expected baseline hash / base release ID

Outputs:

- immutable plan
- deterministic baseline hash
- deterministic plan hash
- per-model KEEP/CREATE/REACTIVATE/ARCHIVE classifications
- final target canonical IDs

No writes, no Admin UI, no fuzzy matching.

### CHUNK 2 — Apply semantics on staged tree

Materialize CREATE, reopen REACTIVATE where required, archive omitted old current trims, replace current set. No Admin yet.

### CHUNK 3 — Workbook generator/parser

Add `TARGET_LINEUP`, `CURRENT_SNAPSHOT`, `IMPORT_META`; compile-only default.

### CHUNK 4 — Whole-workbook outer sandbox

Generalize Vehicle Specs transaction pattern for identity/lifecycle files.

### CHUNK 5 — Durable preview plan state

Persist immutable plan, source/baseline/plan hashes and statuses.

### CHUNK 6 — Admin UI

Separate `/admin/retail-lineup-bootstrap`: generate workbook → upload → preview → apply → publish status.

### CHUNK 7 — Source-import integration

Add isolated `RETAIL_LINEUP_BOOTSTRAP` source kind/handler without disturbing ECO, DLT, VEHICLE_SPECS or Price Feed.

### CHUNK 8 — End-to-end smoke

Test model: old A CURRENT + old B CURRENT; target old B + brand-new C; after publish A HISTORICAL, B CURRENT, C CURRENT, A history preserved. Then one controlled real production model before enabling 73-model bulk use.

## Definition of Done

This is a production weapon only when all are true:

- separate admin-only surface
- workbook declares target state, not actions
- new MarketTrim creation works
- exact existing trim reuse works
- historical reactivation is explicit and safe
- omitted old CURRENT becomes literal HISTORICAL
- old history is preserved
- no fuzzy write identity matching
- UNKNOWN/ambiguous identity fails closed
- stale baseline hash checked at preview and apply
- upload creates preview only
- immutable plan is what apply executes
- whole workbook atomic
- full Catalog and serving release validate before promotion
- exact pushed revision is published and recorded
- retry is idempotent
- Price Feed cannot resurrect archived trims
- Vehicle Specs can enrich new trims immediately
- end-to-end history-preservation test passes
- controlled production smoke passes before 73-model bulk use

## Chunk 1 status

Branch: `feature/retail-lineup-bootstrap`

Chunk 1 owns **planning only**. It must remain side-effect free. Later chunks should treat its identity resolution, baseline hashing and action classification as the source of truth rather than reimplementing them.
