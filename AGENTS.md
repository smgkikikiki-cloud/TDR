# TDR repository instructions

`smgkikikiki-cloud/TDR` is the single active repository for TDR Automotive Intelligence.

## Canonical vehicle boundary

All vehicle market facts belong under `automotive/vehicle_master/`, including Brand, Model, Generation, Variant, MarketTrim, exact powertrain, specifications, fitment, source evidence, Price Ledger, campaigns, ECO ingestion, DLT resolution, canonical releases, and price harvesting.

Registration facts remain separate from MarketTrim and join only through reviewed identities. TDR editorial, news, industry, plant, company, and analytical surfaces may reference canonical vehicle IDs but must not redefine canonical vehicle facts.

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
