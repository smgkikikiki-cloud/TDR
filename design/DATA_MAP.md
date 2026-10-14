# Data Map — current source, target UI adapter and release state

**Repository snapshot:** main SHA c2715cbee494ae076b2582ef99f2bbc590b5dd99, 2026-10-14. This map separates code from source truth, schema deployment and released page wiring. Old design figures are not current facts. The route matrix covers P01–P27 and active routes.

> **Authority rule:** Vehicle Master owns canonical Brand, Model, Generation, Variant, MarketTrim, segment/body classification, specifications and Vehicle Master prices. TDR Vehicle Master's segment and body_type override Ice; preserve Ice values only as raw source evidence. Ice package registrations and class-scoped links are separate market evidence, not canonical model fields.

## Source/maturity labels

- MAIN_CODE: implementation exists in the pinned main tree.
- DRAFT_BRANCH: code/docs exist on an unmerged PR branch.
- SOURCE_REPORT_ONLY: owner/ticket reports a live read but this audit did not re-query it.
- SCHEMA_UNVERIFIED: repository SQL/object names exist; current applied ledger/ACL was not independently observed.
- GATED: source may exist but the applicable owner/domain gate is not approved.
- UNKNOWN: evidence unavailable; do not fill with a guess.

## Current and target source map

| UI data | Current main source and grain | Target adapter/source rule | Provenance, period, units, coverage | Auth/release state |
|---|---|---|---|---|
| Home catalog cards | app/page.tsx and lib/canonical-data.ts: Vehicle Master models/brands and current trim counts. | Same canonical read path. Declare lifecycle selection; never use mockup totals. | Vehicle Master freshness; entity counts are not registrations. | MAIN_CODE; deployed schema/runtime unverified; public. |
| Home/public market | lib/home-market.ts and lib/public-market.ts; public brand snapshot/time-series. /market calls getPublicMarket("brand"). | Existing route remains explicit legacy until approved. New Ice market UI only uses tdr.market-ui.v1. | Current route period/total/unmapped treatment comes from its legacy API; do not freeze a prior value in design. | MAIN_CODE; Production route status unverified. |
| Member market | /api/report/market, /api/report/registration, lib/registration-analytics.ts and access policy. | Replacement uses accepted Ice release and class-scoped link version; only Ice-supported dimensions/filters; no fallback. | Show source/package, period/window, unit, fixed denominator, linked/unmapped/excluded counts and class scope where provided. Unsupported values remain UNKNOWN/error. | Legacy path MAIN_CODE; Ice replacement DRAFT_BRANCH #246; R6/R7/R8 GATED. |
| Vehicle identity/classification | current_* reads through lib/canonical-data.ts and compare adapters. | Vehicle Master views own canonical identity, Segment and Body Type. | Preserve ID/model/generation/trim grain and fact source/observation/qualifier. | Main adapter exists; applied DB/ACL SCHEMA_UNVERIFIED. |
| Ice registration/crosswalk | Main Market Track/package tooling; Draft #246 adds scoped readers/resolver/artifacts. Issue #249 Oct 14 numbers are SOURCE_REPORT_ONLY. | Preserve raw source model/class labels and registration counts; link only at approved class scope; never create canonical segment/body from Ice. | Release/period/class/unit/denominator and scoped link status/version are mandatory; reconcile before display. | R6/R7/R8 gated. Pending/excluded is not approved mapping. |
| Compare | /api/compare/models, /api/compare/trims, /api/tools/compare; canonical trim IDs and qualified compare rows. | Keep lib/free-compare.ts, lib/compare-winners.ts and session/quota boundaries; redesign view only. | Vehicle Master facts/units/qualifiers; no market period unless a separate typed panel exists. | MAIN_CODE; public picker and protected/quota-accounted compare action. |
| Analysis/research | lib/research.ts, /research, /research/[slug], /api/research/read and Admin. | Adapt current public-preview/protected-read DTO when fields match; new report schema only after evidence of a gap. | Publication date, source, tier, preview and private content stay separate. | MAIN_CODE; storage/data deployment unverified. |
| Upcoming | Main /upcoming redirects; lib/upcoming/boundary.ts only bounds optional cards. Draft #220 has proposal/static preview, no live writer. | Strict published-only editorial DTO; canonical links reference existing Vehicle Master IDs and do not affect catalog/market counts. | Source visibility, last verified, launch-window precision, confidence and estimate stay distinct. | Route not implemented; #220 DRAFT_BRANCH; schema/deployment SCHEMA_UNVERIFIED. |
| Pricing/tier | lib/plans.ts, lib/access-policy.ts, lib/billing.ts, docs/PRODUCT_ACCESS.md and docs/BILLING.md. | Shared PLAN_CATALOG/access-policy; no page-local price/tier copy. | Distinguish THB/month from billed interval. Stripe IDs/billing period only from server/provider. | Stripe MAIN_CODE; live config unverified. |
| Auth/account | Supabase Auth/session, server access policy, customer/entitlement API, member pages. | Browser handles sign-in only; billing/registration source stays server-mediated. | Tier/usage from server entitlement/quota, not client claims. Phone verification is separate from member access and required for checkout activation per docs. | MAIN_CODE; OTP production provider/route unverified. |
| News/company | lib/data.ts, /news, /companies*, event/company records. | Preserve editorial grain and source URL/date when present. | Event date is not market period; source link alone is not canonical vehicle evidence. | MAIN_CODE. |
| Admin | Secure Admin route group and scoped actions/APIs. | New writers require separately governed server permissions/audit; UI visibility grants no access. | Keep private notes/private sources off public DTO and metadata. | Current code exists; deployed grants/RLS unverified. |

## Legacy market and Ice target

Main public route is a legacy brand-grain snapshot; main member route uses legacy registration endpoints. This is an observed code fact, not the source for the new Graft UI. PR #246 adds a Draft Ice reader/crosswalk/report path but is unmerged. Issue #249 reports a current scoped-table count; this audit did not make an authorized readback, so those counts are not fresh UI totals or acceptance proof.

Future Ice responses must expose, directly or through a paired coverage object: release/source reference; period/window; supported dimensions/filters; raw unit and registration-class scope; fixed denominator; linked, unmapped and excluded registration units; identity-link version/status; and server access/tier/quota result. If the accepted source does not provide an item, keep it UNKNOWN and block that display/filter. Never mix legacy canonical-registration units with Ice package units.

Issue #249's owner-reported observation (439 vehicle_models, 616 APPROVED, 64 EXCLUDED, named functions) is in the Phase A baseline as a source report, not a value to render. No independent Production query or Vercel read was made in this documentation task.

## Home card map

| Card | Source | Grain/date | Display rule |
|---|---|---|---|
| Catalog counts | Vehicle Master canonical read adapter | Current canonical entities by approved lifecycle filter | Label entity count; never call it registration coverage. |
| Market snapshot/trend | Current getHomeMarket; future Ice only via accepted market adapter | Source period/window, units and denominator | Show each card's source/coverage. New Ice UI never falls back to legacy source. |
| Published analysis | getPublishedResearchArticles | One public item, publication date | Honest empty state; no private body/media in public metadata. |
| Plans | PLAN_CATALOG + lib/access-policy.ts | Billing interval and tier capability | ฿1,290 monthly; ฿990/month billed ฿2,970 quarterly; ฿790/month billed ฿9,480 annually; Enterprise contact-only. Live Stripe configuration is separate. |

## Model, trim, price and specifications

- Catalog/list/detail/compare use canonical Vehicle Master identities/serving views. Preserve model/generation/trim distinction, exact IDs and lifecycle.
- Segment/body is Vehicle Master-owned. Raw Ice segment/body text may remain provenance, not canonical filters or marketing labels.
- Missing Vehicle Master values are UNKNOWN; do not infer from sibling, price, name or Ice. Preserve field source, verification, units, qualifiers, observed/effective date where supplied.
- Retail/list/campaign facts use relevant Vehicle Master read contracts. ECO Sticker, MSRP, campaign price and estimate are not interchangeable. Price Fetcher is a separate OEM evidence pipeline.
- Compare winners come only from the existing evidence-safe library on matching field/qualifier contexts. Never rank unknown or incomparable rows.

## Plans, member access and quotas

Use [PRODUCT_ACCESS.md](../docs/PRODUCT_ACCESS.md), [BILLING.md](../docs/BILLING.md) and server code. Public catalog browsing is public; member analysis and paid checkout have separate guards. Session, entitlement and quota are server-validated; do not expose registration facts through browser DB clients or trust a browser tier claim. Stripe webhooks, not the Checkout success URL, change entitlements.

Old Graft/Data Map values about Omise, 30-day OTP trial, 5 queries/day/12-month windows, or ฿1,099/฿11,490 are not current code facts. Do not reintroduce without a new owner-reviewed decision.

## Source links

- Page/active-route matrix and v1 UI contracts: [PAGE_DATA_CONTRACT_MATRIX.md](../docs/ui-overhaul/PAGE_DATA_CONTRACT_MATRIX.md).
- Current code/graft dispositions: [UI_IMPLEMENTATION_AUDIT.md](../docs/ui-overhaul/UI_IMPLEMENTATION_AUDIT.md).
- Source states, PR heads, unverified environment: [PHASE_A_BASELINE.md](../docs/ui-overhaul/PHASE_A_BASELINE.md).
- Ice gates: [ROADMAP.md](../docs/market-track/ROADMAP.md).
- Vehicle authority/serving: [VEHICLE_DB_V3.md](../docs/vehicle-db/VEHICLE_DB_V3.md) and [SERVING_CONTRACT.md](../docs/vehicle-db/SERVING_CONTRACT.md).
- Access/billing: [PRODUCT_ACCESS.md](../docs/PRODUCT_ACCESS.md), [BILLING.md](../docs/BILLING.md), [lib/plans.ts](../lib/plans.ts), [lib/billing.ts](../lib/billing.ts), [lib/access-policy.ts](../lib/access-policy.ts).
- Draft Upcoming contract is on PR #220, not main: docs/portfolio/UPCOMING_CARS_R0_CONTRACT.md at that PR head.
