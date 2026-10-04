---
name: tdr-design-graft
description: Use for UI overhaul, page implementation and design-graft work governed by design/GRAFT_PLAN.md (a page-by-page migration onto the TDR design system), including the UI portion of feat/* rows such as Intelligence and Analysis. Routes the work to only the GRAFT_PLAN row, PAGES section and DATA_MAP section it needs, prefers existing shared components, and keeps it from spreading into unrelated audits or refactors. Not for backend, schema, data, payment or import work, even inside a feature row. It does not change any design requirement.
---

# TDR design graft — scoped workflow

Purpose: spend context on the one PR in front of you. This skill changes **how much you read and run, never what must be true**. Every requirement in `design/GRAFT_PLAN.md`, `design/DESIGN.md`, `design/PAGES.md`, `design/DATA_MAP.md`, `docs/MERGE_DECISIONS.md` and `AGENTS.md` still applies in full, and the owner's instructions for the PR win over this file. If this file and `design/GRAFT_PLAN.md` ever disagree, `GRAFT_PLAN.md` is the source of truth.

## Scope
- **Applies to:** UI overhaul, page implementation and design-graft work governed by `design/GRAFT_PLAN.md`, and the UI portion of `feat/*` rows (for example Intelligence, Analysis).
- **Does not apply to, and must not constrain:** the backend, schema, data, payment or import work a feature row requires (migrations, pipelines, admin CRUD, entitlements, checkout, data wiring and the like). Do that work under the row's own requirements and the repo's rules; §2 and §4 below do not limit it.
- **Dependencies are read normally.** When a feature row explicitly depends on `docs/vehicle-db/*` or any other source §2 would normally skip, read that dependency as the row requires.

Do not start a design PR from this skill alone: the owner's go for that row is required (`GRAFT_PLAN.md`). One PR per row, on `design/<name>` (features `feat/<name>`), from the latest `main`.

## 1. Route the PR (read only these)
1. Find the PR's row in `design/GRAFT_PLAN.md` (§A foundation, §B existing pages, §C features). Read **§0 (roadmap rules)** once, that row, the blockers that row names, and the migration-reservation notes only if the row has a migration.
2. Open `design/PAGES.md` §0 (rules for every page) and **only** the `P0x` sections the row lists.
3. Open `design/DATA_MAP.md` only for the heading that feeds those pages, plus "Facts to keep visible on every data page".
4. Open `design/DESIGN.md` for the topic you need (colour, type, breakpoints, §10.5 locked content) and always §11 (done-when).
5. `docs/MERGE_DECISIONS.md`: skim for entries about the pages in this row.
6. `docs/WORK_STATE.md` (and `AGENTS.md` rules): read before multi-step work, as `AGENTS.md` requires. Design PRs never touch the active repair batch.
7. `design/reference/`: open the one HTML section or screenshot for the page you are building (search by class or heading). Skip `ice-mockups/02–05` (removed).

## 2. Do not read
- Superseded or historical design material (older `tokens.ice-original.json`, retired roadmap text, earlier merged PR descriptions, `docs/RETAIL_LINEUP_*`, `docs/vehicle-db/*`) **unless the PR's task actually depends on it** (a feature row that names a dependency, see Scope). Say which file and why when you do.
- Pages, panels or rows other than this PR's, "for context".
- `automotive/vehicle_master/` (design PRs never touch it, per `AGENTS.md`).

## 3. Build with what exists
- Prefer the shared components in `components/design/` (Button, Chip, TierBadge, Flag, KpiCard, Card, PageHead, LockedBlock, StageBar, ConfidenceMeter, Table, Field, Skeleton, BodyIcon, …) and `design/components.css`. Reuse shared logic already merged (for example `lib/body-families.ts`, `lib/models/*`, `lib/brands/*`, `lib/search/catalog.ts`).
- Add a new shared component only if the page genuinely has no existing one, and add it once, in `components/design/`.
- Colours only through `var(--token)`; edit `design/tokens.json` then `npm run build:design-tokens`. List migrated files in `design/migrated.json`.
- Data comes through the typed contract the GRAFT_PLAN row describes; no data, permission or payment logic in design PRs; never invent figures or copy.

## 4. Stay in scope
- No repo-wide audits, sweeps, renames or refactors. If you find something unrelated, note it in the PR description and leave it.
- Touch only the files the row needs. A fix to a shared component is allowed only when this PR cannot meet its acceptance criteria without it, and it is called out in the PR.
- No silent scope additions; an unresolved decision goes to the owner, not into a guess.

## 5. Verify, then stop
Verification is exactly what the sources require, no more. This section adds no new requirement.
- **While implementing:** use focused checks (the touched file's script, `tsc`, `check:design`, the page itself) rather than the whole suite.
- **Final verification, once:** run `npm run check` once, when `GRAFT_PLAN.md` requires it (it does for design PRs), plus the page's own acceptance list: `DESIGN.md` §11, the page's section in `PAGES.md`, and the owner's PR instructions. Required screenshots, widths and light/dark themes are unchanged.
- **Production build:** only when the row, `PAGES.md`, `DESIGN.md` or the owner's acceptance requires it, or when it is needed to perform a required visual check. It is not a universal requirement.
- **Expand testing only when a required acceptance check fails**, and only enough to find that failure's cause. No exploratory sweeps up front.
- **Acceptance passes = STOP:** summarise, push, open the PR as the owner's rules say, report. Do not polish adjacent pages, re-audit approved/merged work, or begin the next row.
- Never trade a required check or deliverable for brevity: skipping a required acceptance check is a failure to meet the PR.
