# TDR repository instructions

`smgkikikiki-cloud/TDR` is the single active repository for TDR Automotive Intelligence.

## Canonical vehicle boundary

Vehicle-market facts — Brand, Model, Generation, Variant, MarketTrim, exact powertrain, specifications, fitment, source evidence, Price Ledger, campaigns, ECO ingestion, DLT resolution, price harvesting — are authoritative in the **Supabase Vehicle Master tables** (`vehicle_brands`, `vehicle_models`, `vehicle_generations`, `vehicle_variants`, `vehicle_trims`, `vehicle_facts`, `vehicle_price_ledger`, `vehicle_campaigns`, `vehicle_promotions`, and related tables — `migration_v57` onward). The Vehicle Master DB is the **sole canonical source of truth** for these facts. All future editing/writer work for it follows `docs/vehicle-db/VEHICLE_DB_V3.md`.

`automotive/vehicle_master/` remains the **engine, tooling and code boundary** — validation rules, release/backup/check tooling, tests — and is **not** a file-backed canonical data authority. `vehreg/data/` is retained read-only history.

`current_vehicle_brands`, `current_vehicle_models`, `current_vehicle_generations`, `current_market_trims`, `current_price_ledger`, `current_spec_facts` are **serving views** read from the Vehicle Master. They are a read target for pages and APIs, never a write target.

The legacy file/release write path is **retired and read-only history** (Vehicle DB v3 Phase 0 step 5, `migration_v60`): `canonical_input_batches`, every `canonical_*` projection/release table, `vehreg/data` release publication, and the old enqueue/worker/publish/stage/activate/rollback/prune workflows and RPCs. Do not enqueue, publish, activate, or otherwise write through any of them — see `docs/CANONICAL_INPUT.md`.

**Do not invent an interim writer.** Phase 1 of `docs/vehicle-db/VEHICLE_DB_V3.md` (the DB-master write layer: permissions, change log, observations → reconcile → apply/propose) is not implemented yet. Until it exists there is no supported path for a new Vehicle Master edit; record the need in `docs/WORK_STATE.md` and wait, rather than reopening the retired path or improvising a new one.

Registration facts remain separate from Vehicle Master and join only through reviewed identities (crosswalk). Do not fold registration ingestion or analytics into Vehicle Master tables or treat them as the same authority.

The daily Vehicle Master backup (Phase 0 step 6; private Storage bucket `vehicle-master-backups`) is export/recovery infrastructure, not authority. Never edit a backup file and re-import it as a normal write path.

TDR editorial, news, industry, plant, company, and analytical surfaces may reference canonical vehicle IDs but must not redefine canonical vehicle facts.

## Persistent execution state

For any long-running multi-step TDR audit, data repair, batch, migration, or agent handoff, read `docs/WORK_STATE.md` before continuing work.

`docs/WORK_STATE.md` is the execution source of truth for batch identity, frozen/approved work, active step, and next action. Do not infer these from chat memory alone.

Rules:
- approved/frozen work must not be re-audited unless the user explicitly reopens it;
- historical audit lot numbers and repair lot numbers are separate namespaces and must not be conflated;
- an implementation prompt must carry every recorded required change 1:1;
- do not silently add scope, repeat research already completed for the active step, or guess unresolved batch membership;
- after completing a step, update `docs/WORK_STATE.md` so the next agent inherits the correct state.

## Retired repository prohibition

`smgkikikiki-cloud/vehicle-market-master` is historical only. Do not route implementation tasks, fixes, data updates, workflows, repository dispatches, scheduled jobs, pull requests, issues, or agent commands to it. Do not revive automation there.

When a task mentions Vehicle Master, treat `automotive/vehicle_master/` inside this repository as the target unless the user explicitly asks to inspect historical material.

## Design system migration

The TDR design system and the page-by-page graft plan live in `design/`. Read `design/README.md` for the reading order; `docs/MERGE_DECISIONS.md` records the owner's decisions and wins over everything else in `design/`.

Rules:
- Read `docs/WORK_STATE.md` before multi-step work.
- Design PRs never touch the active repair batch or `automotive/vehicle_master/`.
- Editorial tables (upcoming, analysis) may link canonical IDs but never redefine vehicle facts.
- One PR per row of `design/GRAFT_PLAN.md`, on `design/<name>` (features: `feat/<name>`). Nothing in a later row starts without the owner's go.
- No data, permission, or payment logic in design PRs.
- Roadmap (owner, 1 Oct 2569): this graft IS the overhaul. Never keep an old page or leave a temporary old UX because an overhaul was "scheduled for later"; UI is built to its final design now behind an explicit data contract, and the unready data source (e.g. the replacement market engine, blocker 11) plugs in later. See `design/GRAFT_PLAN.md` §0.
- Colours only through `var(--token)` from `design/tokens.css`; edit `design/tokens.json` and run `npm run build:design-tokens` (never hand-edit `tokens.css`). Files migrated to the design system are listed in `design/migrated.json` and enforced by `npm run check:design`.
