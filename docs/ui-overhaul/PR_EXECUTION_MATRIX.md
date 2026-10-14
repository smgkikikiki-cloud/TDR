# UI/UX Overhaul — executable PR packets after Phase A

All packets derive from baseline SHA [`c2715cbee494ae076b2582ef99f2bbc590b5dd99`](PHASE_A_BASELINE.md). They are **handoffs, not authorizations**. Each future implementation task requires its own exact owner go, pinned source SHA and applicable domain gate. Roadmap v1.0 stays unchanged; `portfolio.plan.json` execution remains disabled.

## Dependency graph

```text
existing main shell/tokens/components
 ├─ PR 6 Models + PR 7 Brands/Search (adapt/finish)
 │   └─ PR 8 Compare full presentation (keep current compare service)
 ├─ PR 13 Analysis (map/reuse research runtime) ──┐
 ├─ PR 9 Pricing/Auth (Stripe, UI only)            ├─ PR 5 Home final integration (#173 last)
 ├─ PR 10 Static/editorial (owner copy gates)     ┘
 ├─ PR 11 Intelligence UI ── Ice adapter + R6/R7/R8 gates for live data
 ├─ PR 12 Upcoming UI ── source/rights/schema/Admin decisions + authorized migration allocation
 └─ PR 15 Ice panels/import/export ── panel contracts, access/rights, independent Ice gates
```

Compare, Pricing UI, static content shell and model/catalog visual work are not blocked by Ice cutover. A UI can be complete while an adapter is gated; no card is allowed to present invented values or legacy numbers as Ice.

## Work packets for Graft rows 0–15

| Row / intended PR | Disposition and readiness | Exact outcome and contract | Suggested allowlist / denylist | Dependencies / tests / exit |
|---|---|---|---|---|
| 0 `fix-main-check` | Closed on this snapshot; `npm run check` passes. Reopen only on regression. | No code outcome is needed now. | No file changes absent a new reproducer. Deny unrelated design/data files. | Exact check result is in acceptance. |
| 1–4 foundation, tokens, shell, shared components | `CONTRACT_READY_BUT_GATED` per design owner go. Much already exists. | Keep accepted design identity and current components; complete accessible, responsive shell/tokens only where checklist shows a real gap. | `app/*token/shell/layout*`, `components/Header*`, nav, design components/CSS, `design/migrated.json`, scoped tests. Deny market, billing, DB, engines, Vehicle Master. | `npm run check:design`; semantic token/contrast/component checks; keyboard/screen-reader and route checks; eight screenshots for changed surface. Exit with updated strict-file list and visual evidence. |
| 5 `design/home` P01 (#173) | `CONTRACT_READY_BUT_GATED`; #173 remains Draft/merge-last. | Consume `tdr.home-ui.v1`; real catalog, Ice market and research cards plus shared plans; independent card states; remove `MarketUpdating` and empty Analysis placeholders. | Home components/styles, home tests, migrated list. Deny engine changes, duplicated taxonomy/plans, fabricated card data, route cutover. | PR 6 body-family; PR 11 market contract; PR 13 research mapping; 8 screenshot matrix, responsive/keyboard/card failure tests, no placeholder audit. Main UI can land only after owner go and integration contract. Production waits for data gates. |
| 6 `design/models` P02–P04 | `READY` for bounded UI adaptation after owner go; canonical source exists. | Finish accepted list/model/trim UX over Vehicle Master read DTO. | `app/models/**`, `components/models/**`, `lib/models/list.ts` only if contract-compatible, scoped tests/screenshots. Deny DB writers, canonical IDs/data, registration joins. | Canonical fixtures including UNKNOWN and historical trim; preserved filter query; 8 screenshots; `npm run check`, `check:design`. Exit with no hidden inferred specs. |
| 7 `design/brands-search` P05–P07 | `READY` for bounded UI adaptation after owner go. | Finish consistent brand/search routes using canonical read adapters. | `app/brands/**`, `app/search/**`, brand/search components and tests. Deny brand catalog writes and unsupported logo fetches. | Search deep-links, suggestion endpoint, keyboard facets, empty/error, source data, 8 screenshots. |
| 8 `design/compare` P08 | `READY` for UI work after owner go; existing engine is retained. | Complete full presentation via `tdr.compare-ui.v1`; canonical trim IDs, evidence-safe winner output, quota and valid legacy URLs. | `app/compare/**`, compare components/styles, tests, `design/migrated.json`. Deny `lib/free-compare.ts`, `lib/compare-winners.ts`, API/auth/quota unless an independently authorized defect. | Existing winner/quota suite, 2–4 trim/qualifier/UNKNOWN/tie cases, malformed IDs, URL round-trip, 8 screenshots, a11y/overflow and 401/429. |
| 9 `design/pricing-auth` P18–P21 | `READY` for UI-only work after owner go. | Use `tdr.pricing-ui.v1`, actual Stripe-backed shared catalog and existing auth/account APIs. | `/pricing`, current member auth/profile/billing surfaces, scoped components/tests. Deny `lib/billing.ts`, Stripe provider config, entitlement/tier/price edits, new payment methods. | Assert three plan prices/interval totals from `PLAN_CATALOG`; missing Stripe Price ID and signed-out states; server status/webhook authority; deep-link and auth/private-data tests; 8 screenshots. |
| 10 `design/static` P22–P26 | `CONTRACT_READY_BUT_GATED` by copy/recipient/legal owner. | Implement only routes with approved copy; preserve `/news`, `/companies`, detail; define system/error UI from server states. | New/changed static pages and tests. Deny invented legal, about, FAQ or contact claims; no data schema changes. | Owner supplies About/Terms/Privacy/Contact copy and recipient; test spam/rate limit if form contract approved; 8 screenshots per changed route family. |
| 11 `feat/intelligence-hub` P09–P12 | `CONTRACT_READY_BUT_GATED` for UI shell; live Ice results are domain-gated. | UI consumes `tdr.market-ui.v1`, `tdr.panel-ui.v1` (to be adopted with evidence) and current access policy; no fallback. | New intelligence route/components and isolated adapter interface/fixtures only. Deny old market imports in new UI, Ice schema writes, crosswalk edits, R6/R7/R8, unsupported dims. | Ice package/release/coverage fixtures; unsupported filter tests; locked/empty/partial/error; tier/quota negative tests; no legacy fallback; 8 screenshots. Live integration needs independent R6/R7/R8 acceptance and explicit R8 go. |
| 12 `feat/upcoming` P16–P17 + P27 subsection | `OWNER_DECISION_NEEDED` before DB/Admin work; UI shell can be fixture-only after owner go. | Apply `tdr.upcoming-ui.v1`, not PR #220 placeholder/schema assumptions. Strict public DTO; canonical links are references. | Upcoming page/components/contract tests. Deny DDL/writer/Admin mutation until source/rights/history/status/migration gates close. | Resolve PR #220 owner decisions; get authorized readback and fresh migration allocation; test draft/public/private-source isolation, date/window, launch redirect, rights, all states; 8 screenshots. |
| 13 `feat/analysis` P14–P15 + Home cards | `CONTRACT_READY_BUT_GATED`; main research runtime exists. | Adapt `research` runtime behind `tdr.analysis-ui.v1`; create new schema only for proven missing data and separate approval. | `/research`/future `/analysis` presentation and privacy tests; current API remains stable. Deny new DDL, upload pipeline, entitlement changes and report-claim invention. | Verify actual schema/shapes/fixtures; test teaser/full text, private media/metadata leakage, unlock concurrency/reopen, tiers and URLs; 8 screenshots. Home contract can then consume real preview. |
| 14 `feat/omise` P20 provider | `REMOVE` as a provider workstream; current provider is Stripe. | Fold payment UI into row 9; keep `lib/plans.ts`/`lib/billing.ts` authority unchanged. | None for Omise. | No Omise implementation or pricing change. Any future replacement is a new separately authorized security/business task. |
| 15 Ice package import / Panels 1–4 / Info/CSV P11/P13 | `OWNER_DECISION_NEEDED`; do not equate with PR #246. | Separate import, access and export contracts; only read a signed/accepted package and expose evidenced fields. | Future panel adapter/import UI only after contract; deny Price Fetcher changes, production importer, crosswalk/RPC and export until gates. | Approved package schema/rights/two-person import role/access+quota/export columns; independent tests for provenance/coverage/privacy; R6/R7/R8 as applicable; 8 screenshots. |

## Current open Draft PR classifications

| PR | Classification | Scoped blocker |
|---|---|---|
| #173 Home P01 | `CONTRACT_READY_BUT_GATED` | Must consume final Home/Market/Analysis contracts, remove placeholder states and pass visual/accessibility acceptance before merge. |
| #220 Upcoming R0 | `OWNER_DECISION_NEEDED` | Source/right, state/history, image, Admin and migration-authority decisions precede live schema or writer work; current PR is documentation/static preview. |
| #246 Ice scoped market/crosswalk | `CONTRACT_READY_BUT_GATED` | Independent PR/security/data QA and exact source/migration/ACL readback; R6/R7/R8 authorization remains distinct and is not advanced by Phase A. |

## Common implementation packet template

Every future PR starts from a fresh exact SHA and states: roadmap v1.0; owner go for that bounded task; page IDs/URLs; source/API owner; contract version; allowlist and denylist; auth/tier/quota; provenance/period/coverage; backward-compatible query/redirect behavior; failure/partial/locked states; test fixtures; independent acceptance criteria; applicable release gate. Do not dispatch automatically from this matrix.

For each visual UI change, capture **8 screenshots**: viewport widths 1440, 1024, 834 and 390 px, each in light and dark mode, at the same fixture data and state. Include page-specific loading/empty/locked/error screenshots where they materially change layout; those state captures supplement the 8 required baseline captures. Run keyboard focus, contrast, mobile overflow, URL, quota and private-data checks.

## Stage definitions

- `UI_COMPLETE`: final presentation, all states and screenshot/a11y acceptance are complete on fixture/adapter contract.
- `CONTRACT_READY`: typed request/response, provenance, tier, period, coverage, failure and fixtures are accepted by the source owner.
- `INTEGRATED`: the page uses the accepted real adapter and independently verified source data; no fallback or mock.
- `PREVIEW_QA`: an authorized preview is deployed and independently reviewed at target widths/themes.
- `PRODUCTION_RELEASED`: separate owner/domain gate, reviewed migration/config and deployment evidence are satisfied.

Never promote one stage's evidence into another stage's status. R6/R7/R8 blocks live Ice integration/cutover, not unrelated UI work.
