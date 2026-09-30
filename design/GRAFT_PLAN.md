# GRAFT_PLAN.md — order of work (nothing is grafted until the owner says go)

One PR per row, branch `design/<name>` (features: `feat/<name>`), never commit to main. Each PR: `npm run check` passes, files added to `design/migrated.json`, 8 screenshots (1440/1024/834/390 × light/dark), acceptance list from DESIGN §11 + the page's section in PAGES.md. Owner reviews before merge.

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
| 5 | design/home | P01 | DATA_MAP §Home |
| 6 | design/models | P02, P03, P04 | canonical funcs only |
| 7 | design/brands-search | P05, P06, P07 | — |
| 8 | design/compare | P08 | keep quota rules |
| 9 | design/pricing-auth | P18, P19, P21 (UI only; no payment logic) | `lib/plans.ts` price change is its own PR |
| 10 | design/static | P22–P26 | copy `[COPY]` needs owner text |

## C. Features
| # | PR | Scope | Depends |
|---|---|---|---|
| 11 | feat/intelligence-hub | P09 hub + P10 Panel 5 (ex-/market) + the `/market` family redirects, tier rules from DATA_MAP (re-verify against the new market engine first, blocker 11) | 4, blocker 1–2 |
| 12 | feat/upcoming | migration per SCHEMA_PLAN, admin CRUD (P27), P16, P17, tests | 4 |
| 13 | feat/analysis | migration + buckets + upload/processing pipeline + P14, P15, `check-analysis-privacy`, unlock concurrency test | 4 |
| 14 | feat/omise | Checkout P20, `tdr_entitlements`, renewal reminders (7 days) | Omise 3DS answer |
| 15 | feat/ice-import | Ice Panels 1–4, Info builder, CSV (P11, P13) | separate go |

Rows 12 and 13 can run in parallel after 4. Migrations: repo is at v52 → Upcoming = **v53**, Analysis = **v54** (fixed).

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
11. **Market analysis engine replacement (owner, noted 30 ก.ย., lands within days).** `lib/registration-market.ts` / `lib/public-market.ts` and the `getPublicMarket()` / `compareMarketSliceRows()` data functions named in DATA_MAP may change or disappear. Until the new engine ships and DATA_MAP §Home / §Intelligence is re-verified against it: do not wire market numbers in PR 5 (home), do not start PR 11 (P09/P10 Panel 5), and do not re-derive tier rules for Panel 5. Blockers 1–2 (market total definition, Aug 2569 coverage) may be resolved by the new engine. PRs 0–4, 6–10, 12, 13 do not depend on it.

PR 4 acceptance additions: map and legend swatches use `--border-strong`; check `--diverge-4` in dark mode (2.9:1); report TierBadge uses `tdr-tier--member` for MEMBER tier.

## E. Automatic checks to have before feature PRs
`check:design` (tokens, no hex, no car logos in strict files), `check-analysis-privacy` (no original/display URL in HTML/JSON/OG/sitemap for non-entitled), upcoming constraint tests, unlock concurrency test, overflow test at 6 widths.
