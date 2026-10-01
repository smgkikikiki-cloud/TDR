# GRAFT_PLAN.md — order of work (nothing is grafted until the owner says go)

> **Owner roadmap decision, 1 Oct 2569 — this graft IS the overhaul.** See §0 before reading any row below. Anything elsewhere in `design/` or the code that says a page, panel or Home section is "left for a later overhaul" is cancelled.

One PR per row, branch `design/<name>` (features: `feat/<name>`), never commit to main. Each PR: `npm run check` passes, files added to `design/migrated.json`, 8 screenshots (1440/1024/834/390 × light/dark), acceptance list from DESIGN §11 + the page's section in PAGES.md. Owner reviews before merge.

## 0. Roadmap decision (owner, 1 Oct 2569): this graft is the overhaul
Supersedes every earlier "Market / Compare / Analysis / the matching Home sections stay largely as-is until a later overhaul" assumption.

**Rules for every agent**
1. **Do not preserve an old page, panel or UX (or leave a temporary old version in place) merely because a deeper overhaul was once scheduled for later.** Market / Intelligence, Compare, Analysis and their Home integrations are all part of this overhaul cycle.
2. **UI overhaul is independent of the data-engine migration.** Page structure, filter model, dimension tabs, comparison controls, KPI containers, ranking/table layouts, donut/trend layouts, component architecture, responsive behaviour, tier presentation and the loading / empty / locked / error states are built to their FINAL design now.
3. **Clean data boundary.** Where a data source is not ready, the UI consumes one explicit, typed contract (types + an adapter interface owned by the PR that builds the UI), never the source directly. The real source then plugs into that adapter without redesigning the UI. A page must not import the not-ready source "temporarily".
4. **Compatibility means data contracts and valid incoming URLs/selections, not the old presentation.** Keep canonical trim identity, quota enforcement, comparison data, `lib/compare-winners.ts` and its evidence-safe winner semantics correct; do not keep an old layout for compatibility's sake.
5. **Placeholders are not an acceptance state.** A state that exists only because a dependency had not landed (e.g. `MarketUpdating`, an empty Analysis block on Home) is temporary integration scaffolding. It must be removed before the PR that carries it merges.
6. **Blocker 11 (below) is unchanged for data:** nothing reconnects Home or Intelligence to the old market engine, no market figure is invented or re-derived, and final production wiring uses the replacement engine. It no longer delays any UI work.
7. Vehicle Master (`automotive/vehicle_master/`) is not touched by any of this.

**Execution order.** The numeric order of the tables below is NOT sacred; dependency constraints decide. Preferred sequence:

`PR 6 Models → PR 7 Brands/Search → PR 8 Compare (full overhaul) → Analysis (PR 13, moved forward) → PR 9 Pricing/Auth → PR 10 Static → PR 11 Market/Intelligence (full overhaul; production data once the replacement engine contract is available) → finalize and rebase PR 5 Home on the finished Analysis and Market contracts`

Upcoming (PR 12) and the other feature PRs stay independent and may run in parallel unless their dependencies change. Each still needs the owner's go before it starts.

**PR 5 / Home (draft #173).** Stays a draft. Its `MarketUpdating` blocks and its Analysis empty state are temporary integration states, not the intended final Home. Before it merges: (a) the Market/Intelligence blocks are wired to the replacement engine through the PR 11 contract, (b) the Analysis section uses the final Analysis implementation and its Home-card contract, (c) every placeholder that exists only because dependent work had not landed is removed, (d) its local body-family copy is replaced by `lib/body-families.ts` (PR 6), and its plan block reads the shared plan source (blocker 4). Do not treat the current draft state as PR 5's acceptance state.

## A. Foundation
| # | PR | Scope | Depends |
|---|---|---|---|
| 0 | fix-main-check | Repair 2 failing asserts in `check-trim-retail-lifecycle-review.ts` (pre-existing). Separate PR, no design files | — |
| 1 | design/foundation | Add `design/**`, scripts, `check:design`, allow `design/*` previews in `vercel.json`, AGENTS.md design block | 0 |
| 2 | design/tokens | Wire `tokens.css` + 3 fonts via `next/font`; map existing `semantic-tokens.css` to new tokens | 1 |
| 3 | design/shell | Header, footer, bottom bar, theme toggle, logo plate, redirects whose targets already exist (PAGES §6; the `/market`, `/reports`, `/member`, `/member/market` → `/intelligence*` redirects move to PR 11) | 2 |
| 4 | design/components | Shared components per `reference/components.html` (Button, Chip, TierBadge (free · member · pro · enterprise), Flag, KPI, Delta, Card, PageHead, LockedBlock, StageBar, ConfidenceMeter, table, form) | 3 |

## B. Existing pages (data already live)
| # | PR | Pages | Data |
|---|---|---|---|
| 5 | design/home | P01 — draft #173; merges last (see §0): final Market blocks via PR 11, final Analysis cards via PR 13, no leftover placeholders | DATA_MAP §Home |
| 6 | design/models | P02, P03, P04 | canonical funcs only |
| 7 | design/brands-search | P05, P06, P07 | — |
| 8 | design/compare | P08 — **full Compare overhaul** (whole `/compare` experience, not a reskin). Keep quota enforcement, canonical trim identity, comparison data, `compare-winners` / evidence-safe winners, and valid incoming `?trims=` / `?models=` URLs; the old presentation is not preserved | `lib/free-compare.ts`, `lib/compare-winners.ts` |
| 9 | design/pricing-auth | P18, P19, P21 (UI only; no payment logic) | `lib/plans.ts` price change is its own PR |
| 10 | design/static | P22–P26 | copy `[COPY]` needs owner text |

## C. Features
| # | PR | Scope | Depends |
|---|---|---|---|
| 11 | feat/intelligence-hub | **Full Market / Intelligence overhaul**: P09 hub + P10 Panel 5 (ex-/market) + the `/market` family redirects. UI (structure, filters, dimension tabs, comparison controls, KPI containers, ranking/table, donut/trend layouts, tier presentation, all four states, responsive) is built now against an explicit market data contract; production wiring uses the replacement engine and re-verifies DATA_MAP §Intelligence tier rules first (blocker 11) | 4; wiring: blocker 11 |
| 12 | feat/upcoming | migration per SCHEMA_PLAN, admin CRUD (P27), P16, P17, tests | 4 |
| 13 | feat/analysis | **Moved earlier (see §0 order).** migration + buckets + upload/processing pipeline + P14, P15, `check-analysis-privacy`, unlock concurrency test, **and the Home-card data contract** (latest 3 published reports, DATA_MAP §Home "Analysis cards") that PR 5 consumes | 4 (blocker 3 still to confirm for list wiring) |
| 14 | feat/omise | Checkout P20, `tdr_entitlements`, renewal reminders (7 days) | Omise 3DS answer |
| 15 | feat/ice-import | Ice Panels 1–4, Info builder, CSV (P11, P13) | separate go |

Rows 12 and 13 can run in parallel after 4, and row 13 may run before rows 9–11. Migrations: repo is at v52 → Upcoming = **v53**, Analysis = **v54** (owner decision, 1 Oct 2569). These are feature reservations that prevent parallel-PR collisions, not a requirement that migrations merge in numeric order:
- If Analysis merges before Upcoming, v53 stays temporarily absent/reserved. Do NOT rename Analysis to v53 by merge order and do NOT create an empty/dummy v53 migration.
- When Upcoming merges it uses its reserved v53. v54 must stay independent of v53 and must not reference schema created by Upcoming.
- If Upcoming is cancelled, v53 may stay an unused gap permanently. Never renumber already-merged migrations.

## AGENTS.md design block must also say
Read `docs/WORK_STATE.md` before multi-step work. Design PRs never touch the active repair batch or `automotive/vehicle_master/`. Editorial tables (upcoming/analysis) may link canonical IDs but never redefine vehicle facts.

## D. Open blockers (owner or third party; do not guess)
1. Definition of total market (61,805 identified-model vs Ice 62,417) — affects headline + Panel 5.
2. Aug 2569 model resolution only ~81% → BEV share / ICE drop distorted; decide headline handling.
3. Research table missing in production — confirm before P14 list wiring.
4. Price change in `lib/plans.ts` (฿1,099 / ฿11,490) — owner go.
5. SMS/OTP provider for production.
6. Omise: do 3DS cards support Charge Schedules? (ask Omise)
7. ECO Sticker data licence.
8. Contact recipient email; `[COPY]` texts: About, Terms, Privacy, FAQ, method notes.
9. Vercel team scope for preview access (`kiki-ed8b`) — reconnect connector.
10. Preview deploy config (`vercel.json` disables non-main).
11. **Market analysis engine replacement (owner, noted 30 ก.ย., lands within days).** `lib/registration-market.ts` / `lib/public-market.ts` and the `getPublicMarket()` / `compareMarketSliceRows()` data functions named in DATA_MAP may change or disappear. **Scope after the 1 Oct 2569 roadmap decision (§0): this blocks DATA WIRING only, not UI.** Until the new engine ships and DATA_MAP §Home / §Intelligence is re-verified against it: do not wire Home or Intelligence market numbers through the old engine (or any equivalent), do not invent or re-derive figures, and do not re-derive tier rules for Panel 5 before re-verification. The PR 5 market blocks and PR 11 may be built to their final UI now behind the explicit market data contract; production wiring waits for the replacement engine. Blockers 1–2 (market total definition, Aug 2569 coverage) may be resolved by the new engine. PRs 0–4, 6–10, 12, 13 do not depend on it.

PR 4 acceptance additions: map and legend swatches use `--border-strong`; check `--diverge-4` in dark mode (2.9:1); report TierBadge uses `tdr-tier--member` for MEMBER tier.

## E. Automatic checks to have before feature PRs
`check:design` (tokens, no hex, no car logos in strict files), `check-analysis-privacy` (no original/display URL in HTML/JSON/OG/sitemap for non-entitled), upcoming constraint tests, unlock concurrency test, overflow test at 6 widths.
