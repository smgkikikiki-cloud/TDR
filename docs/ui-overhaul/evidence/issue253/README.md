# Issue #253 — P02–P07 acceptance evidence

The UI was audited from latest `main` (`c6a4a09877cbdcb7759584e59ce5f9df9f854023`). The only confirmed presentation gaps were the mobile brand alphabet hit area and the missing retry block when the P06 canonical brand read fails. They are fixed on `design/p02-p07-vehicle-ui-20261015`; the tested application commit is `a546a5af019a1010b75e98f756685b6dd450e04f`. The evidence-pack commit adds screenshots and this report only.

The full screenshot/hash inventory, viewport measurements, canonical source samples, interactions and validation outcomes are in [qa-manifest.json](qa-manifest.json). All normal page screenshots use the live public Vehicle Master `current_*` serving reads through the application. Only the search-suggestion 500 error example is locally simulated; it does not supply vehicle content. No production writes or catalog data changes were made.

## Route acceptance

| Page | Result | Evidence and remaining gate |
|---|---|---|
| P02 `/models` | PASS | Current-only model KPIs and filters, URL filter/sort/page preservation, 12-at-a-time pagination, back navigation, CompareTray and max-four behavior. Upcoming remains an honest empty state under its actual owner gate. |
| P03 `/models/[slug]` | PASS / GATED | Canonical identity/media/credit, current price and specification evidence, exact current trims, related models, and historical trim separation. The registration panel has no market values; Ice/R6–R8 remain gated. |
| P04 `/models/[slug]/[trim]` | PASS | Exact canonical trim identity, known registry facts, grouped specifications, unit/source rows, sibling route and Compare. Unknown trim specs are omitted. Invalid trim renders the framework not-found page and `noindex`. |
| P05 `/brands` | PASS | Logo-free canonical brand rows/counts/prices, filtering and keyboard A–Z navigation. The verified 40px mobile letters were raised to 44px and locked by a regression check. |
| P06 `/brands/[slug]` | PASS / GATED | Canonical brand KPIs and model grid; a serving-read failure now returns a retryable `BlockError`, while an absent brand remains a 404. Upcoming cards stay gated by the approved editorial source. |
| P07 `/search` + overlay | PASS | `?q=` results and live suggestions share ordering and current-only lifecycle rules. Dialog focus, keyboard loop, Escape/return, direct links, empty state and retryable error state were checked. |

## Screenshot matrix

Each cell links to the light and dark full-page screenshots at that width. These are the 48 required captures from Chromium 154.0.8037.57 at device scale 1.

| Page | 1440px | 1024px | 834px | 390px |
|---|---|---|---|---|
| P02 `/models` | [light](screenshots/p02-models-1440-light.png) · [dark](screenshots/p02-models-1440-dark.png) | [light](screenshots/p02-models-1024-light.png) · [dark](screenshots/p02-models-1024-dark.png) | [light](screenshots/p02-models-834-light.png) · [dark](screenshots/p02-models-834-dark.png) | [light](screenshots/p02-models-390-light.png) · [dark](screenshots/p02-models-390-dark.png) |
| P03 `/models/aion-aion-y-plus` | [light](screenshots/p03-model-detail-1440-light.png) · [dark](screenshots/p03-model-detail-1440-dark.png) | [light](screenshots/p03-model-detail-1024-light.png) · [dark](screenshots/p03-model-detail-1024-dark.png) | [light](screenshots/p03-model-detail-834-light.png) · [dark](screenshots/p03-model-detail-834-dark.png) | [light](screenshots/p03-model-detail-390-light.png) · [dark](screenshots/p03-model-detail-390-dark.png) |
| P04 `/models/byd-atto2/extended_range_premium_45_1_kwh_bev` | [light](screenshots/p04-trim-specifications-1440-light.png) · [dark](screenshots/p04-trim-specifications-1440-dark.png) | [light](screenshots/p04-trim-specifications-1024-light.png) · [dark](screenshots/p04-trim-specifications-1024-dark.png) | [light](screenshots/p04-trim-specifications-834-light.png) · [dark](screenshots/p04-trim-specifications-834-dark.png) | [light](screenshots/p04-trim-specifications-390-light.png) · [dark](screenshots/p04-trim-specifications-390-dark.png) |
| P05 `/brands` | [light](screenshots/p05-brands-1440-light.png) · [dark](screenshots/p05-brands-1440-dark.png) | [light](screenshots/p05-brands-1024-light.png) · [dark](screenshots/p05-brands-1024-dark.png) | [light](screenshots/p05-brands-834-light.png) · [dark](screenshots/p05-brands-834-dark.png) | [light](screenshots/p05-brands-390-light.png) · [dark](screenshots/p05-brands-390-dark.png) |
| P06 `/brands/byd` | [light](screenshots/p06-brand-detail-1440-light.png) · [dark](screenshots/p06-brand-detail-1440-dark.png) | [light](screenshots/p06-brand-detail-1024-light.png) · [dark](screenshots/p06-brand-detail-1024-dark.png) | [light](screenshots/p06-brand-detail-834-light.png) · [dark](screenshots/p06-brand-detail-834-dark.png) | [light](screenshots/p06-brand-detail-390-light.png) · [dark](screenshots/p06-brand-detail-390-dark.png) |
| P07 `/search?q=atto2` | [light](screenshots/p07-search-1440-light.png) · [dark](screenshots/p07-search-1440-dark.png) | [light](screenshots/p07-search-1024-light.png) · [dark](screenshots/p07-search-1024-dark.png) | [light](screenshots/p07-search-834-light.png) · [dark](screenshots/p07-search-834-dark.png) | [light](screenshots/p07-search-390-light.png) · [dark](screenshots/p07-search-390-dark.png) |

Supplementary screenshots cover Upcoming-gated empty, empty-query suggestions, no-result search, live search overlay, simulated search error/retry, and invalid-trim not-found pages in both themes. They are listed with dimensions and SHA-256 hashes in the manifest.

## Real Vehicle Master data checks

The live `/models` page returned 318 current models, 1,431 current trims, 62 current brands, 135 CKD/SKD models and 142 CBU models. Those are values from the route's filtered canonical serving reads, not the count of every identity row in `vehicle_models`. The live BYD page returned 12 current models, 27 current trims and a stored current price range of ฿429,900–฿1,499,000.

The verified model and trim IDs are `byd.atto2` and `byd.atto2.atto2.trim.extended_range_premium_45_1_kwh_bev`. Search for `atto2` returned `/models/byd-atto2` first in both `/search` and `/api/search/suggest`. Aion Y Plus (`aion.aion_y_plus`) provided a real lifecycle check: 490 Premium is CURRENT; 410 Premium and 490 Elite are HISTORICAL. The two historical rows remain collapsed, display “เลิกจำหน่ายแล้ว,” and have no order/spec links.

## Browser and accessibility results

- 48/48 required screenshots loaded with HTTP 200; all six routes had one H1, no horizontal overflow, no unnamed visible controls and no missing image alt text.
- No undersized measured controls remained in the matrix. Source badges use an expanded 44px pseudo-element hit area; comparison uses the 44px label target. P05 alphabet links are 44×44px at phone width.
- All 24 additional overflow probes passed at 1366px and 1280px across six pages and both themes.
- Search dialog keyboard flow passed (focus enters, Shift+Tab wraps to final action, Tab wraps back, Escape closes and restores focus). The tablet filter sheet also closes and restores focus with Escape.
- P02 filter/sort/page URL state survived pagination (`page=1` → `page=2`) and browser Back restored the original filter/sort/page. P05 keyboard filtering followed by Enter on the T jump link reached `#brand-T`.
- The invalid canonical trim has a Next.js streamed not-found body and `noindex`; under the existing `loading.tsx` boundary Next sends HTTP 200 for that streamed response. An unknown brand without that streaming boundary returns HTTP 404.

## Validation and scope

`npm run check`, `npm run check:design`, `npm run build`, the focused `scripts/check-brands-search.ts`, and `git diff --check` passed on the implementation commit. The build reports a non-blocking existing Autoprefixer warning in `app/pricing/pricing.module.css:41`; pricing is outside this task. Hosted Actions and Vercel Preview are pending Draft PR creation and will be recorded in the PR handoff.

The app changes are limited to `app/brands/brands.css`, `app/brands/[slug]/page.tsx`, and the scoped guard `scripts/check-brands-search.ts`. There are no Vehicle Master writers, API/data-source changes, Ice cutover, billing, Engine, Price Fetcher, schema or migration changes. The final screenshot/evidence commit is documentation-only; `validatedCodeSha` in the manifest pins the application SHA used for the read-only browser session.
