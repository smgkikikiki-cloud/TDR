# TDR repository instructions

`smgkikikiki-cloud/TDR` is the single active repository for TDR Automotive Intelligence.

## Mandatory Master Roadmap bootstrap (owner-approved v1.0)

**Before planning, modifying, reviewing or dispatching any TDR development task**, read:
1. `docs/portfolio/TDR_MASTER_ROADMAP_V1.md` — approved portfolio scope, product boundaries, Layer 3 order and G0–G5 delivery dependencies.
2. `docs/portfolio/portfolio.plan.json` — machine-readable owner approval, execution permissions and task queue. This JSON is **non-executable unless its explicitly controlled execution gate permits a real, owner-approved task**.
3. `docs/portfolio/ENGINE_VALIDITY_AND_DEPENDENCIES.md` and `docs/portfolio/DOMAIN_BOUNDARIES.md` — common validity requirements and workstream boundaries. Read the specific methodology/review attachment for the affected engine; proposed numerical formulas remain separate from roadmap approval.
4. The existing authoritative `docs/WORK_STATE.md` and the **applicable** gate/contract: Ice → `docs/market-track/ROADMAP.md`, Vehicle Master → `docs/vehicle-db/VEHICLE_DB_V3.md`, website design → `docs/MERGE_DECISIONS.md` and `design/GRAFT_PLAN.md`. A portfolio milestone cannot override a domain's permission flag.

Each task handoff must name the **roadmap version**, the exact **source commit SHA**, the **domain**, any **source/acceptance contract**, a **bounded file scope** and **tests**. If a source/roadmap conflict or required permission remains unresolved, report the specific blocker; do not let two AI agents approve each other or treat a draft contract as adopted.

**Enforcement distinction:** `orchestration/preflight.mjs` is the deterministic, read-only gate for machine checks. An LLM merely asserting “I read the roadmap” does not pass the gate. Agent prompts are advisory by themselves. The GitHub workflow can verify repository invariants, but making its check required for merging must be configured and independently verified in GitHub branch protection/rulesets.

**Current safety locks:** roadmap v1.0 APPROVED, but `portfolio.plan.json` still has `execution.enabled=false`, `task_queue=[]`, no autonomous implementer dispatch, auto-merge, deployment, production write, paid API or Ice gate advancement. These controls cannot be bypassed by a prompt, branch convention, or local environment flag. Existing independently authorized manual/offline PR work retains its own gate.

**Existing, pre-roadmap branches** do not inherit a file merged later into `main` automatically: their agent sessions must load the approved v1.0 from `main` and apply domain contracts without rewriting or silently rebasing active work. A future Enforcer must pin the actual source commit and reject stale/unapproved task packets.

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

## Ice Market Track execution gate

For any Ice Full Package, Ice market-engine, crosswalk, or market-cutover work, `docs/market-track/ROADMAP.md` defines the fixed execution order and stop conditions. Read it together with `docs/WORK_STATE.md` before changing code.

Rules:
- execute only the roadmap's `CURRENT_GATE`; do not work ahead because a later step appears easy;
- the owner-supplied M6.0 package inspected on 2026-10-06 is trial/fixture-only and is never production authority;
- a structurally valid package is not automatically an authorized production release;
- no production Ice import, production crosswalk generation/approval, or M5 cutover while the corresponding roadmap flag is false;
- never infer missing redirects, access scope, release state, `period_from`, or other package metadata;
- after finishing a gate, run its tests and update `docs/WORK_STATE.md` in the same session.

Claude Code users should run `/market-next` from the repository root to apply this protocol explicitly.

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
