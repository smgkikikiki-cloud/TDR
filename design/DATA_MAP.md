# DATA_MAP.md — where every number/list on every page comes from

Verified against the code and the live Supabase project on 28–29 Sep 2569. ✅ exists · 🔧 small addition needed · ⏳ Ice data (not imported yet → show `soon`) · ⚠️ decision/caveat.
**Rule:** the owner's data must be wired live everywhere. **Never copy numbers from a mockup** (the mockups embed sample data; e.g. mockup said 1,570 trims, real = 1,432).
Definitions: "latest period" = `max(period)` of `registration_reporting_source`. Market total = units whose brand resolves canonically (repo definition; Aug 2569 = 61,805). Ice's package total (62,417) is a different definition — do not mix the two in one view (open item).

## Home (`reference/home_v7.html`)
| Block | Source | |
| --- | --- | --- |
| Period label, total, YoY %, YTD, YTD YoY | `getPublicMarket()` (`period`, `totalRegistrations`); YoY & YTD need `periodTotal()` for same month last year / Jan..latest (in `lib/public-market.ts`, not exported) | 🔧 |
| Headline "รถใหม่ X% เป็น EV แล้ว" | BEV share from `getPublicMarket("powertrain")` over model-resolved units; **computed, never hard-coded** | ✅ ⚠️ Aug 2569 model-resolution only 81% (pivot file has no registration class) → BEV share overstated, ICE drop looks −14.8pp; add coverage line under donut; consider hiding headline % when coverage <90% |
| BEV %, xEV % (BEV+HEV+PHEV+REEV) | same | ✅ |
| Province probe, Panel 1–4 cards' numbers, Top tyre, wheel/tyre rows | Ice packages `reg_province`, `rim_province`, `tyre_province`, `reg_trend` | ⏳ show `soon` |
| 12-month trend | `getPublicMarket().trend` | ✅ |
| Powertrain donut + pp | `getPublicMarket("powertrain")` current & previous month; groups ไฟฟ้าล้วน/หลายระบบในรุ่นเดียว/ไฮบริด/สันดาป/อื่นๆ(PHEV+REEV+UNKNOWN) | ✅ (pp needs previous-month slice → 🔧 export from `getPublicMarket`) |
| Brand share top 6 + pp | `getPublicMarket("brand")`; pp = `compareMarketSliceRows().share_change_pp` | 🔧 expose in return type |
| Top 5 models | dimension `model` of `lib/registration-market.ts` (latest period) — owner approved showing top 5 publicly (exception to "model level = Pro") | ✅ |
| Vehicle Database counts | models: `getCanonicalModels()` filtered `isCurrentLifecycleStatus` (318); trims: `current_market_trims` status CURRENT (1,432); brands: distinct brand of current models (62). **Live values, not 323/1,570** | ✅ |
| Body chips + counts | `body_type` grouped: รถเก๋ง=SEDAN+COUPE+WAGON · SUV=CROSSOVER+PPV+OFFROAD · แฮทช์แบ็ก · กระบะ=PICKUP · MPV · รถตู้=VAN (TRUCK not a chip) | ✅ |
| Brand chips | `getCanonicalBrands()` ordered by current-model count; text only | ✅ |
| Compare examples | top-2 by `modelScore()` in current `app/page.tsx`; price = min/max trim `current_list_price.amount_thb`; image = official media | ✅ |
| Analysis cards | `analysis_reports` latest 3 published | 🔧 new table (SCHEMA_PLAN) |
| Plans | `lib/plans.ts` must become Pro ฿1,099/mo · ฿11,490/yr, no quarterly, Enterprise no price | 🔧 (business-logic PR, not design PR) |
| Auth state / tier | Supabase Auth + `tdr_entitlements` → `resolveTierFromEntitlements` | ✅ |

## /models list, brand pages, search
`getCanonicalModels(600)` (+ `payload`: powertrains, seats, production_type, market_position, launch_year; `retail_price_min/max`; 140/318 have price; many new models lack powertrains/seats → show "สเปกพื้นฐานยังไม่ครบ" / "ยังไม่ประกาศราคา"). Filters `matches()/facetHit()` in current page (keep). Trims per model: count of `current_market_trims` CURRENT (🔧 add to query). Images: `getCanonicalPrimaryMediaIndex()` (official media; owner confirmed acceptable, credit line required). Brand rail → brand list with counts from current models (no logos). Facet counts include values absent from current option lists (position "Budget", segment F/UNKNOWN) — hide zero/unknown options.

## Model / trim pages
Model: `getCanonicalModelBundle(slug)`, `getCanonicalRelatedModels(r,6)`, production programs `getProductionProgramsByModel`. Model-market block: dimension `model` for this `canonical_model_id` (12 months) — **Pro only**; non-Pro gets a static placeholder (no values in DOM). Trim: `trimRow()` + `comparable_specs` (≈32 facts, sources `ecosticker`/`official_*`, `verification_status`, `observed_at`); labels/order `lib/spec-field-registry.ts`; campaign: `campaign_quote.campaign_options` where `status_as_of = ACTIVE` (fields: option_label/campaign_name, amount_thb, conditions.text, valid_to, source_ref). ⚠️ ECO Sticker terms: Ice notes no licence found for paid services → owner accepted risk/checks; keep source badge.

## Intelligence
Panel 5 = existing engine. Tier rules (derived from approved decisions; owner may adjust): **Anonymous** — default brand snapshot of latest month, no interaction. **Freemium (30 days)** — latest month only, dimensions brand/powertrain/body/segment (choose 1 at first entry, locked), no model dimension, no filters, no compare, no export, watermark, copy disabled. **Free after 30 days** — same as anonymous. **Pro/Enterprise** — all windows (month, rolling 3/6/12, YTD), compare (previous, YoY), all dimensions incl. model, filters, Info. CSV Enterprise only once `export_columns` defined. Replaces old FREE quota (5 queries/day, 12-month history) and the "4 of 6 sales modules" picker.
Panels 1–4: Ice packages (`manifest.json`, `panel.json`, csv per panel; `confirmed_by` must list 2 people to import). Not imported → cards `soon`.

## Analysis Report
Tables `analysis_reports`, `analysis_report_images`, `analysis_report_unlocks` (SCHEMA_PLAN). Access:
| Viewer | Report tier MEMBER | PRO | ENTERPRISE |
| --- | --- | --- | --- |
| Anonymous / expired trial | teaser (list + summary + first takeaway only) | teaser | teaser |
| Freemium in trial | clear | teaser + unlock (2 total) | teaser |
| Pro | clear | clear | teaser |
| Enterprise | clear | clear | clear |
Owner-confirmed 30 ก.ย.: Pro sees ENTERPRISE reports as teaser only; anonymous sees list + summary only (even for MEMBER-tier reports — MEMBER means "any signed-in trial/paid member").
List/summary/first takeaway are always public. Unlock consumed only on explicit confirm; re-open of an unlocked report is free.

## Upcoming
Table `upcoming_vehicles` (SCHEMA_PLAN), editorial, public read of `status='published'` (`state` ACTIVE/DELAYED; CANCELLED visible 90 days on the detail page only). Optional links: `brand_canonical_id`, `predecessor_model_id`, `launched_model_id`. Never joined into registrations, compare, or catalogue counts.

## Account / commerce
`tdr_customers`, `tdr_entitlements`, `tdr_subscriptions`, `tdr_customer_profiles`, `tdr_usage_*`; new `free_trial` (started_at, ends_at, breakdown, phone unique) per Ice `02_tiers_matrix`. Payments: `PaymentProvider` interface (Omise; Stripe code to be retired). Prices from `lib/plans.ts`. Contact: `contact_messages` (new).

## Facts to keep visible on every data page
Source line "ที่มา: กรมการขนส่งทางบก (Open Data Common)" · Bangkok = place of registration note · estimate flag for wheel/tyre · coverage line where resolution <100%.
