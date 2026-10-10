# Ice Market Track — Execution Roadmap

**Owner:** กี้  
**Execution date:** 2026-10-06, R3 completed 2026-10-07, R5 completed 2026-10-10  
**Scope:** Ice Full Package → TDR production market engine  
**Current gate:** `R6_PRODUCTION_CROSSWALK` (R5 is DONE; R6 has not been started and needs the owner's explicit go)

> This file is the fixed execution order for the Market Track.  
> `docs/WORK_STATE.md` records the live state. This roadmap records the order and stop conditions.  
> If an older Market Track note conflicts with this file, follow this file unless the owner explicitly changes the plan.

## Machine-readable safety state

- `PRODUCTION_IMPORT_ALLOWED = false` (the single owner-authorized R5 import has run; any further import needs fresh owner authorization)
- `PRODUCTION_CROSSWALK_ALLOWED = false`
- `LIVE_CUTOVER_ALLOWED = false`
- `TRIAL_PACKAGE_AUTHORITY = fixture_only`
- `CURRENT_GATE = R6_PRODUCTION_CROSSWALK`

These flags are descriptive instructions for agents, not application config. Do not flip them by inference. Only update them when the corresponding gate below is actually completed and the owner has authorized the transition.

## Current state

- **M1 — Serving contract:** done.
- **M2 — Ice importer infrastructure:** implemented and production schema `migration_v62` is live; no production Ice Full Package has been imported.
- **M3 — Crosswalk infrastructure:** implemented and production schema `migration_v63` is live; no production crosswalk has been generated or approved.
- **M4 — Ice market engine:** implementation and tests complete (R3, 2026-10-07); PR #189 merged to main 2026-10-07 (CI green), package-independent, not wired to live pages.
- **M5 — Cutover:** not started; legacy registration display remains live.

### Trial package inspected

The owner supplied `TDR_FULL_2569-09_v1_M6.0.zip` as a **trial / near-final package only**. It is not authority and must not be imported into production.

The trial confirmed the real delivery shape:

- six panels are present: `reg_province`, `reg_trend`, `reg_powertrain`, `rim_province`, `tyre_province`, `dims`;
- outer `full_package.json`, `CHANGELOG.csv`, shipped `validate_package.py`, and `สำหรับ_AI/` are present;
- per-panel manifests carry `period_from` / `period_to`;
- per-panel metadata carries `access` / `free_scope`;
- outer status/sign-off can look production-ready even when the owner still considers the package a trial.

The trial also exposed release-hygiene gaps that must be handled before a production import:

- README/contract describes `id_changes.csv`, but the inspected trial did not contain it;
- the trial CHANGELOG contained one still-`เสนอ` row among released rows;
- a package can present `status = พร้อมส่ง` and two sign-offs while still being a trial by owner intent, so TDR must not treat those fields alone as sufficient authority.

### Final package declared (2026-10-09)

The owner declared **`TDR_FULL_2569-09_v3_M7.0.zip`** (md5 `04b3c2509ef2e82ee5eadeb5bff7effb`,
sha256 `c558d2d4cc3ed667f8b30ea028dbb66c4030cdce4e7daabe735df870cb94677d`) the final Ice package,
superseding the M6.0 trial above. Re-verified directly from this exact ZIP (not assumed from
the trial or from any summary): all six panels shipped-validator-clean; every manifest
`confirmed_by: ["Ice", "กี้"]`; `CHANGELOG.csv` has 41 rows, all `ออกเวอร์ชัน` (the trial's one
`เสนอ` row is gone); `id_changes.csv` present at the zip root (81 rows); `dims/model_group.csv`
`model_group_id` now genuinely unique (the trial's duplicate is gone). Offline `--check` with
`--owner-declared-final TDR_FULL_2569-09_v3_M7.0.zip`: 0 structural problems, 0 authority
problems.

This package also proved a real TDR-side schema gap (`ice_reg_powertrain`'s primary key was one
column narrower than Ice's own declared contract — 254 real collisions in the M7.0 data, which
would have made a real `--apply` fail outright). A compatibility patch
(`migration_v64_ice_panel_grain_fix.sql` + importer/engine updates) was prepared on a dedicated
branch to fix this — see `docs/WORK_STATE.md`'s "R4 compatibility patch" entry for full detail.
**This did not run `--apply` and did not advance `CURRENT_GATE` past R4** — R5 (below) is the
actual production import, still a separate, explicit, not-yet-taken action.

## Fixed execution order

### R0 — Freeze trial authority

**Status: DONE**

Allowed:
- inspect the trial package;
- run offline validation;
- use it as a read-only compatibility fixture;
- compare parser/schema behavior against its real files.

Forbidden:
- no production `--apply`;
- no production crosswalk `--match`;
- no crosswalk approval or seeding from trial data;
- no page/API cutover;
- no copying trial data into canonical production market tables.

Exit condition: trial is explicitly recorded as fixture-only in `WORK_STATE.md` and repository instructions.

---

### R1 — M2.1: persist panel metadata + harden the outer release gate

**Status: DONE (2026-10-06).** Implemented in `vehreg/ice_package.py` and `tools/ice_package_import.py`; see `WORK_STATE.md`. Metadata persists through `ice_package_imports.panels`. Real-Postgres migration tests not run locally; they run in CI.

Implement package-independent support for the real metadata now confirmed by the trial:

1. Persist enough per-panel release metadata for downstream serving, at minimum:
   - `panel_id`
   - `period_from`
   - `period_to`
   - `access`
   - `free_scope`
   - package/master/version linkage
2. Do not make M4 infer or hard-code any publish start period.
3. Add an outer-package release gate in TDR in addition to the shipped panel validator.
4. The outer gate must refuse a production import when any required release condition is unresolved.

Minimum release checks:

- exact six-panel set;
- package and panel hashes/bytes match the declared index;
- release status is production-eligible;
- two sign-offs are present;
- `changelog_since` continuity matches the last imported master;
- the package's shipped validator passes;
- unresolved/proposed CHANGELOG semantics are not silently treated as released facts;
- when entity/model-group identity changes require redirect handling, the machine-readable `id_changes.csv` contract must be satisfied; if the package is ambiguous, stop and ask Ice rather than infer redirects from prose.

Tests:
- use synthetic fixtures for deterministic unit tests;
- use the owner-supplied M6.0 trial as a local read-only compatibility fixture when available;
- no test may write the trial into production.

Exit condition:
- metadata is persisted and readable by M4;
- outer release gate tests cover the trial-discovered gaps;
- `--check` can explain why a trial/faulty package is refused without touching production.

---

### R2 — Trial compatibility pass

**Status: DONE (2026-10-06).** The trial is a passing read-only fixture: structurally valid, not production-authorized. See WORK_STATE.md.

Run the real trial package through the updated **offline/read-only** path.

Required proof:
- all six panel schemas parse;
- real `period_from/access/free_scope` metadata round-trips through the importer model;
- shipped panel validator still passes;
- TDR outer gate can distinguish “structurally valid package” from “authorized production release”;
- no Supabase production mutation occurs.

Do not “fix” Ice numbers locally. Any data defect is reported back to Ice.

Exit condition: trial package is a passing compatibility fixture while remaining non-importable as production authority.

---

### R3 — Finish and merge M4 (#189)

**Status: DONE (implementation + tests, 2026-10-07).** PR #189 rebased onto current main
(after R1/R2 + #192), wired to R1's persisted panel metadata, tests expanded, pushed to
`feat/ice-market-engine-m4`. CI pending; **the actual GitHub merge is an owner/CI action and
has not happened yet** — do not treat this status as "PR #189 merged."

Before merge:

- wire M4 to persisted metadata instead of an unavailable/hard-coded `period_from` — **done**:
  `lib/ice-market-engine.ts`'s `findPanelRelease` + `lib/ice-market-data.ts`'s
  `latestIcePanelRelease`/`iceWheelTyreAvailability` read the real per-panel
  `period_from` from `ice_package_imports.panels`;
- access/free-scope enforcement must consume persisted package metadata — **done**:
  `iceAccessAllows(access, capability, tier)` reads the persisted capability->tier[]
  object with no invented tiers; `free_scope` is passed through exactly as persisted
  (including `null` when Ice omits it), never defaulted;
- remove/resolve M4 comments that say the M2 metadata does not exist — **done**, including
  `scripts/ice-market-acceptance.ts`'s wheel/tyre section;
- keep panel separation intact — unchanged;
- keep Ice `model_group_id` as market identity — unchanged;
- unmatched Ice models remain visible — unchanged;
- powertrain certainty remains exact/family/range without false precision — unchanged;
- wheel/tyre outputs retain coverage — unchanged;
- Buddhist `YYYY-MM` period strings remain strings — unchanged.

Required checks:
- M4 synthetic engine checks pass — **119 checks, all pass** (`npm run check` includes
  `scripts/check-ice-market-engine.ts`);
- TypeScript passes — **`npx tsc --noEmit` clean**;
- full repo check passes — **`npm run check` exits 0**;
- trial compatibility does not reveal a serving-contract mismatch — no change to the
  frozen contract surface; M4 remains unwired to any live page/route.

Exit condition: PR #189 merged, still not wired live. **Implementation/tests side of this
exit condition is met; the merge itself is still pending (owner/CI).**

---

### R4 — WAIT FOR ICE FINAL

**Status: HARD STOP after R3**

Do not advance merely because a file is named `TDR_FULL_*.zip`.

A production import is allowed only when:
- the owner explicitly says the package is final;
- R1 outer release gate passes;
- shipped validator passes;
- no unresolved release/identity ambiguity remains.

At this gate update:
- `PRODUCTION_IMPORT_ALLOWED = true`
only after explicit owner authorization.

---

### R5 — M2 production import

**Status: DONE (2026-10-10).** `TDR_FULL_2569-09_v3_M7.0.zip` (sha256 `c558d2d4cc3ed667f8b30ea028dbb66c4030cdce4e7daabe735df870cb94677d`) is live and independently reconciled. Details and evidence: `docs/WORK_STATE.md` "R5 production import".

For the explicitly approved final package:

1. replace the repo's package-import AI/SOP files from `สำหรับ_AI/` as required by the package contract;
2. run TDR outer validation;
3. run the package's shipped validator;
4. stage all panels;
5. execute replace-whole-set import atomically;
6. run post-import reconciliation:
   - `reg_province = reg_trend`;
   - `reg_powertrain` reconciles to `reg_trend` within contract tolerance;
7. persist package/panel metadata and import history;
8. record `master_version`;
9. notify Ice of the accepted import.

Exit condition: one real final package is live and independently reconciled. **Met.**

Not closed by R5 (carried forward, none blocks R6): step 1 (replace the repo's package-import AI/SOP files from `สำหรับ_AI/`) was deliberately not applied -- the package's `CLAUDE.md`/`AGENTS.md` would overwrite repo-specific sections, so it needs an owner decision; the importer's `data/packages/` version log was not written; step 9 (notify Ice) is an owner action.

---

### R6 — M3 production crosswalk

**Status: NEXT, not started (R5 is done; waits for the owner's explicit go -- `PRODUCTION_CROSSWALK_ALLOWED` stays false until then).**

Order:

1. process `id_changes.csv` first when present;
2. run the real matcher against imported Ice data;
3. generate review output;
4. AUTO rows may follow the existing acceptance rules;
5. PROPOSED/STRUCTURE rows require owner review;
6. do not silently infer merge/split redirects;
7. approve only after review.

At this gate update:
- `PRODUCTION_CROSSWALK_ALLOWED = true` only after R5;
- crosswalk approval still remains an explicit reviewed action.

Exit condition: production crosswalk is reviewed, redirects are recorded, unmatched groups are explicit.

---

### R7 — M4 real-data acceptance

**Status: BLOCKED by R6**

Run the read-only acceptance harness against live imported Ice data and reviewed crosswalk.

Required:
- brand/model totals reconcile to Ice totals;
- no units are dropped by mapping;
- segment/body “ไม่ระบุ” is counted rather than hidden;
- powertrain certainty/ranges survive aggregation;
- wheel/tyre availability uses real persisted `period_from`;
- wheel/tyre coverage is exposed;
- redirect resolver is cycle-safe;
- serving-contract shapes remain compatible.

No page cutover yet.

Exit condition: acceptance is clean enough for owner-approved M5.

---

### R8 — M5 live cutover

**Status: BLOCKED by R7 + owner approval**

Switch live market/public/member consumers to the Ice-backed engine.

Rules:
- cut over behind the frozen serving contract;
- do not use legacy registration views as a fallback source for Ice numbers;
- keep legacy tables read-only during the transition;
- consume `ice_model_group_redirects` for retired market IDs/bookmarks/links;
- preserve access/free-scope behavior from package metadata.

At this gate update:
- `LIVE_CUTOVER_ALLOWED = true` only immediately before the approved cutover.

Exit condition: production pages/API use Ice market engine and acceptance remains green.

---

### R9 — Post-cutover observation and cleanup

Only after M5 is stable:
- monitor reconciliation/coverage;
- remove obsolete display-path dependencies deliberately;
- do not delete historical registration data needed for audit;
- document rollback/cutover result.

## Stop conditions

Claude/agents must stop rather than improvise when any of these occur:

- owner says the package is trial/draft/not final;
- required panel is missing;
- any declared hash/size fails;
- sign-offs are incomplete;
- changelog continuity fails;
- proposed/unreleased CHANGELOG state has unclear release meaning;
- model-group identity changed but redirect semantics are missing/ambiguous;
- shipped validator fails;
- TDR reconciliation fails;
- real matcher produces ambiguous structural proposals that have not been reviewed;
- requested work would skip the current gate.

## Local Claude Code protocol

Claude Code launched from the repo root automatically reads `CLAUDE.md`. For every Market Track task it must then read, in this order:

1. `CLAUDE.md`
2. `AGENTS.md`
3. `docs/WORK_STATE.md`
4. this file
5. `.claude/skills/tdr-package-import/SKILL.md` when a Full Package or panel is involved
6. the specific implementation contract (`VEHICLE_DB_V3.md`, `SERVING_CONTRACT.md`) only as needed

Before changing code it must state:

- **CURRENT GATE**
- **WHY this gate is current**
- **ALLOWED actions**
- **FORBIDDEN actions**
- **EXIT TESTS**

After completing a gate:
- run the required tests;
- update `docs/WORK_STATE.md` in the same session;
- update `CURRENT_GATE` and safety flags in this file only when the exit condition is actually met;
- stop at the next hard gate instead of starting work ahead.

Use the repo command `/market-next` in Claude Code to force this protocol explicitly.
