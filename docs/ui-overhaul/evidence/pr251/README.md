# Compare UI browser evidence for PR #251

These artifacts cover the P08 Compare Specs page on branch `design/compare-full-overhaul-20261014`. Browser assertions ran against the optimized local Next.js production build, using Chromium 154.0.8037.57 and the real `/api/compare/trims` and `/api/tools/compare` endpoints. The selected trims and returned comparison snapshot are recorded in [browser-qa.json](./browser-qa.json), including the response SHA-256.

The four canonical trims were BYD Atto 3, BYD Dolphin, Tesla Model 3, and Toyota Yaris Cross. The real endpoint returned 17 groups, three rows with policy-approved winner marks, 76 unknown values, and anonymous remaining allowance of 9/10 after the comparison. Missing values remained visible as unknown; the page did not recalculate winner decisions.

## Viewport and theme captures

Each link opens a full-page PNG captured at the listed viewport width and height. The responsive assertions in `browser-qa.json` were measured at those actual viewport dimensions before capture.

| Viewport | Light | Dark |
| --- | --- | --- |
| 1440 × 1000 | [PNG](./compare-1440-light.png) | [PNG](./compare-1440-dark.png) |
| 1024 × 1000 | [PNG](./compare-1024-light.png) | [PNG](./compare-1024-dark.png) |
| 834 × 900 | [PNG](./compare-834-light.png) | [PNG](./compare-834-dark.png) |
| 390 × 844 | [PNG](./compare-390-light.png) | [PNG](./compare-390-dark.png) |

## Browser checks

- No document-level horizontal overflow at any of the four widths.
- Four selected vehicle columns render on desktop and tablet; the phone viewport shows two columns at once with horizontal table scrolling.
- The table header remains sticky; the phone row-label column remains pinned while swiping horizontally.
- No interactive target below 44 CSS pixels was detected in the audited controls.
- Broken vehicle image URLs render an explicit unavailable-image state.
- Playwright smoke checks pass for a real deep-link comparison, canonical share IDs, stale-result clearing after filter changes, keyboard picker focus/Escape, unavailable-selection recovery, and the existing 401 signup and 429 quota paths.
- Exact screenshot byte counts and SHA-256 values, selection IDs, and per-viewport measurements are in `browser-qa.json`.

The 834px table's 16px vertical scrollbar gutter is included in its row-label offset metric. It does not cause page overflow or unpin the row labels.

## Validation run

- `npm run check`
- `npm run build`
- `npm run check:design`
- `npx tsx scripts/check-free-compare.ts`
- `npx tsx scripts/check-compare-winners.ts`
- `npx tsx scripts/check-compare-quota-order.ts`

These checks cover the UI contract and existing comparison service behavior. Hosted GitHub CI and the Vercel Preview are separate checks and are not represented by this local browser evidence.
