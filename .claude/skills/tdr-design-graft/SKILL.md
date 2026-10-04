---
name: tdr-design-graft
description: Use for any task in the TDR design graft (a PR from a row of design/GRAFT_PLAN.md — a page-by-page UI migration onto the TDR design system). Routes the PR to only the GRAFT_PLAN row, PAGES section and DATA_MAP section it needs, prefers existing shared components, and keeps the work from spreading into unrelated audits or refactors. It does not change any design requirement.
---

# TDR design graft — scoped workflow

Purpose: spend context on the one PR in front of you. This skill changes **how much you read and run, never what must be true**. Every requirement in `design/GRAFT_PLAN.md`, `design/DESIGN.md`, `design/PAGES.md`, `design/DATA_MAP.md`, `docs/MERGE_DECISIONS.md` and `AGENTS.md` still applies in full, and the owner's instructions for the PR win over this file. If this file and `design/GRAFT_PLAN.md` ever disagree, `GRAFT_PLAN.md` is the source of truth.

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
- Superseded or historical design material (older `tokens.ice-original.json`, retired roadmap text, earlier merged PR descriptions, `docs/RETAIL_LINEUP_*`, `docs/vehicle-db/*`) **unless the PR's task actually depends on it**. Say which file and why when you do.
- Pages, panels or rows other than this PR's, "for context".
- `automotive/vehicle_master/` (not touched by design PRs).

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
- Run the checks the PR requires and nothing wider first: `npm run check` (includes tsc and `check:design`), the production build, and the page's own acceptance list (`DESIGN.md` §11 + the page's section in `PAGES.md` + the owner's PR instructions: widths, light/dark, states, screenshots).
- **Expand testing only when a required acceptance check fails**, and only enough to find that failure's cause. Do not add exploratory sweeps up front.
- **Stop when the PR's acceptance criteria pass**: summarise, push, open the PR as the owner's rules say, report. Do not polish adjacent pages, re-audit approved/merged work, or begin the next row.
- Never trade a required check or deliverable for brevity. Skipping an acceptance check is not saving context; it is a failure to meet the PR.
