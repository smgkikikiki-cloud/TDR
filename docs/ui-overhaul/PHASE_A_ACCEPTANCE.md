# UI/UX Overhaul Phase A — acceptance and independent QA handoff

**Pinned source:** `main` `c2715cbee494ae076b2582ef99f2bbc590b5dd99`
**Roadmap:** approved v1.0; execution gate remains false.
**Task:** Issue #249 Phase A1–A7, documentation/read-only only.
**This file is not owner or independent QA sign-off.** Phase A is not accepted until a separate reviewer checks evidence and the owner explicitly accepts it.

## A1–A7 evidence matrix

| Criterion | Result | Evidence / remaining limit |
|---|---|---|
| A1 Architecture baseline pinned to actual `main` and related PR heads | **CONDITIONAL PASS** | [Baseline](PHASE_A_BASELINE.md) pins full SHAs and reports main vs Draft evidence. Production DB/ACL, Vercel preview/runtime and flags are not independently queried; Issue #249 live numbers remain owner-reported. |
| A2 Contradictions with authority, observed state, resolution, blocker and next evidence | **PASS, with owner gates open** | [Register](ARCHITECTURE_CONTRADICTIONS.md) records C-01–C-16. It does not close C01/C02, payment configuration or R6/R7/R8. |
| A3 P01–P27 plus additional active route families | **CONDITIONAL PASS** | [Matrix](PAGE_DATA_CONTRACT_MATRIX.md) has 27/27 P rows plus current non-P route families/APIs/Admin. Route inventory is main-code evidence, not a production route probe. |
| A4 Typed contracts for Compare, Pricing/Auth, Market, Analysis, Upcoming and Home | **CONDITIONAL PASS** | [Matrix](PAGE_DATA_CONTRACT_MATRIX.md) defines named v1 UI boundaries and source/security/state acceptance. Market/Upcoming/Analysis fields not proven by current source are explicit requirements/proposals, not deployed API claims. Panel 1–4/export contract awaits owner/source evidence. |
| A5 Graft rows 0–15 dispositioned against code/design/PR branches | **PASS** | [Audit](UI_IMPLEMENTATION_AUDIT.md) gives 16/16 `KEEP/ADAPT/REPLACE/REMOVE` dispositions with file and exit evidence. |
| A6 Executable revised roadmap and scoped future packets | **CONDITIONAL PASS** | [Execution matrix](PR_EXECUTION_MATRIX.md) covers all 16 rows, dependencies, path scope, tests, screenshots, and stage gates. Packets are not future-task authorization. Upcoming, static copy, Ice and Production integration still require exact owner/source/domain decisions. |
| A7 Checks, no-write statement, reviewer and owner acceptance | **PENDING CHECKS / NO SELF-APPROVAL** | This page contains reviewer checklist, owner yes/no card, and exact check slots below. Update after running checks; reviewer/owner must sign separately. |

## Deterministic completeness and repository checks

Commands to run from repository root and record exactly:

| Command | Expected evidence | Result |
|---|---|---|
| `npm run check` | Existing app/type/data/security/design check chain, including `check:design`. | **PASS, exit 0** on this worktree; full chained script completed. Node emitted non-fatal `MODULE_TYPELESS_PACKAGE_JSON` and npm update notices. |
| `npm run check:design` | Token generation parity, strict-file/token, contrast and component checks. | **PASS, exit 0**; 66 strict files, 0 guard failures; design contrast checker reported 0 failures. It printed 11 outlined swatches below 3:1 as informational output. |
| Internal Markdown link/reference check | Every new relative document link resolves; route/PR refs are cited. | **PASS, exit 0**; checked 8 edited Markdown files, all relative links resolve; 27/27 unique P pages and 16/16 Graft rows found. |
| `git diff --check` | No whitespace errors. | **PASS, exit 0** on the docs diff. |

`npm run check` is the repository's own complete check; `check:design` was also run separately to make the visual-token result clear. This docs-only PR does not claim browser screenshots, Vercel preview or hosted CI; no hosted CI run is attached to this local audit.

## Exact scope and safety confirmation

Changes for Issue #249 are limited to the eight requested documents: six new `docs/ui-overhaul/*.md` files plus revised `design/GRAFT_PLAN.md` and `design/DATA_MAP.md`. No app/component/engine/test/schema/migration/SQL writer/market crosswalk/feature flag/billing/production files are changed. No production/staging read or write is claimed unless separately cited in the baseline; **NO PROD WRITE / NO MERGE / NO DEPLOY / NO FLAG CHANGE / NO AUTONOMOUS EXECUTION ENABLEMENT** was performed by this task. `portfolio.plan.json` remains unchanged and `execution.enabled=false`.

The work stays in the original Website/Website Pro scope, not the Dealership Toolkit. The owner-approved v1.0 roadmap and existing R6/R7/R8, C01/C02, payment and migration gates remain unchanged. No new implementation PR is started by these documents; one documentation Draft PR for Issue #249 is the only requested PR.

## Independent reviewer checklist

Reviewer should use a clean checkout pinned to the branch SHA, then:

1. Verify the exact main SHA, PR #173/#220/#246 heads, states and base branch; confirm no extra source or data files changed.
2. Re-run `npm run check`, `npm run check:design`, link/reference validation and `git diff --check`; record exact output.
3. Sample all 27 page rows, all active route families and all 16 graft-row dispositions against code and contracts; flag any route/API or source mismatch.
4. Verify Stripe plan values against `lib/plans.ts` and tiers against `docs/PRODUCT_ACCESS.md`; verify Compare URLs/quota/winner reference and Market no-fallback rule.
5. Confirm Ice owner-reported Production counts are explicitly not independently verified, migrations are not treated as deployed proof, and R6/R7/R8 remain gated.
6. Confirm the `research` and Upcoming data contracts do not fabricate schema/runtime, and every private source/body/estimate policy is fail-closed.
7. Confirm no static-mock values, assumed coverage, guessed migration number, toolkit scope, or new owner decision became fact.
8. Decide whether A1–A7 are **ACCEPT / REQUEST CHANGES** with cited evidence. Reviewer cannot authorize owner gates.

## Owner acceptance card — no default answers

The owner may answer these after independent QA:

- [ ] Accept the Phase A architecture and route/data matrix as an implementation handoff.
- [ ] Accept each `READY` UI lane in the execution matrix for a separate bounded task packet.
- [ ] Request changes to specified evidence or contract rows.
- [ ] Keep all live Ice, migration, Stripe configuration, copy/legal and deployment gates as currently recorded until separately resolved.

No checkbox is preselected. Owner acceptance of this documentation does not authorize code implementation, source writes, crosswalk promotion, migration, merge, deployment or autonomous execution.

## Open dependencies by lane

- **Can be separately tasked after owner go:** Models, Brands/Search, Compare presentation, Stripe Pricing/Auth UI, design tokens/shell, and current research UI adaptation where existing contract suffices.
- **UI shell can be tasked but live integration gated:** Home and Intelligence; Ice data requires accepted release evidence and R6/R7/R8 sequence.
- **Owner/source decision needed before implementation:** Static legal/about/contact copy; Upcoming source rights/history/status and schema allocation; Panel 1–4/import/export fields and access policy; Analysis storage/media additions if existing research adapter proves insufficient.
- **Not verified:** hosted CI status, branch-protection rules, Vercel preview/Production routing/flags, deployed Supabase schema/ACL/migration ledger, Stripe live Price configuration.
