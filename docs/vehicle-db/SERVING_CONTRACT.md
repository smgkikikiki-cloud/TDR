# Serving Contract — vehicle & market data (M1)

Market track step **M1** of `VEHICLE_DB_V3.md` (§12, §15.1). **Document only — no code changes.**
This lists every function, HTTP endpoint and DB view that a public or member page uses to get vehicle or market data, with its return shape and the pages that use it. Engine PRs (Phase 0, M4) may change only what sits *behind* these entries, following the rules in §15.2.

Verified against the code on `main` @ `73e3aaab4` and the live schema of Supabase project `ltvwzkffmpudpjfjomrg` (`information_schema`, 2 Oct 2026).

---

## 0. How to read this

- **Contract surface** = the entries in §1–§4. A page or component may depend on them. Their names, parameters and return shapes are frozen. New data needs = new optional fields only, never renamed or removed ones (§15.2).
- **Behind the contract** = the tables and helper functions each entry reads. Engine PRs may replace these freely, provided the contract output stays the same (vehicle side: parity; market side: acceptance tests, §15.2).
- "Pages" lists the route files that call each entry directly. Admin surfaces are listed separately (§5) because §15 governs the public UI; they are still consumers that a Phase 0 switch must not break.
- Shapes are written TypeScript-style. Most of these functions are untyped in code (`any`); the shape below is what the code actually builds, so it is the de-facto contract.

### Layer map

```
pages (app/**/page.tsx, client components)
  │
  ├─ server functions ── lib/canonical-data.ts          (vehicle: catalogue, model, trim)
  │                     lib/compare-canonical-data.ts  (vehicle: compare picker + rich trims)
  │                     lib/public-market.ts / home-market.ts (market: public aggregate)
  │
  ├─ HTTP endpoints ──── /api/search/suggest, /api/compare/*, /api/tools/compare        (vehicle)
  │                     /api/report/market, /api/report/registration, /api/tools/sales-dashboard (market)
  │
  └─ shared pure code ── lib/registration-market.ts (types, windows, slicing, movement)
                        lib/member-market.ts       (coverage / provisional period helpers)
                               │
                               ▼
         market engine: lib/registration-analytics.ts, lib/historical-model-state.ts,
                        lib/market-price-state.ts
                               │
                               ▼
         DB serving layer: current_* views, registration_* views, vehicle_media_*
```

---

## 1. Vehicle side — server functions (`lib/canonical-data.ts`)

All read via `publicDb()` (anon key). If the DB is not configured they return `[]` / `null`. Supabase errors are thrown.

### 1.1 Shared row shapes

**`CanonicalBrand`** — built inline in `getCanonicalBrands`:
```ts
{
  ...current_vehicle_brands.payload,       // spread first; includes oem_group, brand_origin, …
  id: string                               // = canonical_id
  canonical_id: string
  editorial_id: string | null              // = tdr_brand_id (legacy uuid)
  slug: string
  name_en: string
  name_th: string | null
  country_origin: string | null            // = origin_country
  logo_url: string | null                  // from legacy `brands.logo_url` via tdr_brand_id; fail-open → null
}
```

**`CanonicalModel`** — `modelRow()` (private) + media overlay in `getCanonicalModels`:
```ts
{
  ...current_vehicle_models.payload,       // spread first; includes brand_id, powertrains[], production_type,
                                           // production_country, market_scope, market_position, seats, cab_type,
                                           // launch_year, launch_quarter, length_mm, …
  id: string                               // = canonical_id
  canonical_id: string
  editorial_id: string | null              // = tdr_model_id (legacy uuid)
  slug: string
  name_en: string
  name_th: string | null
  generation_id: string | null             // column, else payload.generation_id
  generation: string | null                // payload.generation, else last segment of generation_id
  segment: string | null
  body_type: string | null                 // normalized through BODY map (HATCHBACK, SEDAN, …, OTHER)
  status: string                           // CURRENT | HISTORICAL | UNVERIFIED | …
  retail_price_min: number | null          // column (engine-computed)
  retail_price_max: number | null
  brands: { id, slug, name_en, name_th, logo_url: null }   // from payload.brand; logo always null here
  // added by getCanonicalModels only:
  image_url: string | null                 // primary exterior (hero | front_3q) via media bindings
  hero_image_url: string | null            // same value
  image_type: string | null
  image_source_url: string | null
  image_source_type: string | null
}
```

**`CanonicalTrim`** — `trimRow()` (private):
```ts
{
  ...current_market_trims.payload.specs,   // spread first; flat spec keys (engine_cc, battery_kwh, seats, …)
  id: string                               // = canonical_id
  canonical_id: string
  name: string
  model_id: string
  generation_id: string | null
  variant_id: string | null
  status: string                           // default "current" if null
  powertrain: string | null                // column, else specs.powertrain
  price_baht: number | null                // current_list_price.amount_thb
  current_list_price: object | null        // column, else payload.current_list_price
  campaign_quote: object                   // column or {}; pages read campaign_quote.campaign_options[]
  price_history: array                     // column or []
  source_refs: object                      // column or {}
  comparable_specs: array | null           // payload.comparable_specs (SpecLedger.resolved())
  trim_powertrains: [{ powertrain_id: "canonical-pt:<canonical_id>" }]
  _powertrain: { id, label, powertrain_type, engine_code, displacement_cc,
                 battery_capacity_kwh, transmission, drivetrain }   // stripped in getCanonicalModelBundle
}
```

### 1.2 Functions

| Function | Signature | Reads | Returns | Pages / callers |
|---|---|---|---|---|
| `getCanonicalBrands` | `(limit = 150)` | `current_vehicle_brands` (order name_en), legacy `brands.logo_url` | `CanonicalBrand[]` | `app/page.tsx`, `app/brands/page.tsx`, `app/models/page.tsx`, `app/member/market/page.tsx`, `app/reports/page.tsx`, `/api/search/suggest` |
| `getCanonicalBrand` | `(slug)` | via `getCanonicalBrands(250)` | `CanonicalBrand \| null` | `app/brands/[slug]/page.tsx` |
| `getCanonicalModels` | `(limit = 600)` | `current_vehicle_models` (order name_en) + `getCanonicalPrimaryMediaIndex()` | `CanonicalModel[]` (all statuses — callers filter) | `app/page.tsx`, `app/brands/page.tsx`, `app/models/page.tsx`, `app/search/page.tsx`, `app/reports/page.tsx`, `app/member/market/page.tsx`, `/api/search/suggest` |
| `getCanonicalModelsByBrand` | `(brandId)` | via `getCanonicalModels(600)`, filter `brand_id` | `CanonicalModel[]` | `app/brands/[slug]/page.tsx` |
| `getCurrentTrimCountsByModel` | `()` | `current_market_trims` (`model_id,status`, CURRENT, paged 1000) | `Map<model_id, number>` | `app/models/page.tsx`, `app/brands/[slug]/page.tsx` |
| `getCanonicalHistoricalTrims` | `(modelCanonicalId)` | `current_market_trims` (status HISTORICAL) | `{ id, name, powertrain }[]` | `app/models/[slug]/page.tsx` (collapsed "เลิกจำหน่ายแล้ว" list) |
| `getCanonicalModelBundle` | `(slug)` | `current_vehicle_models` by slug; `current_market_trims` (CURRENT); `getCanonicalVehicleMedia`; `getCanonicalModelHeadOverride` | `null` or `CanonicalModel` (without `image_type`) + `{ media: MediaRow[], powertrains_detail: _powertrain[], trims: CanonicalTrim[] }`; fills model `length_mm/width_mm/wheelbase_mm/seats` from trims when all trims agree | `app/models/[slug]/page.tsx`, `app/models/[slug]/[trim]/page.tsx` |
| `getCanonicalRelatedModels` | `(model, limit = 8)` | via `getCanonicalModels(600)`, same `brand_id`, excluding self | `CanonicalModel[]` | `app/models/[slug]/page.tsx` |
| `searchCanonicalCatalog` | `(query, limits?)` | via `getCanonicalBrands(250)` + `getCanonicalModels(600)` → `lib/search/catalog.ts` | `{ brands, models }` | `app/search/page.tsx` |
| `getCanonicalVehicleMedia` | `(entityId)` | `vehicle_media_bindings`, `vehicle_media_assets` | `MediaRow[]` sorted by type priority then confidence | internal (bundle) |
| `getCanonicalModelHeadOverride` | `(modelId)` | same | `MediaRow[] \| null` (`null` = no override, `[]` = intentionally blank) | internal (bundle) |
| `getCanonicalPrimaryMediaIndex` | private | same | `Map<entity_id, MediaRow \| null>` | internal (`getCanonicalModels`) |
| `trimRow` / `modelRow` | private | — | shapes in §1.1 | internal; their **output** is the contract |
| `getCanonicalCompareTrims` | `(limit?)` | `current_market_trims` + `getCanonicalModels(1000)` | `CanonicalTrim` + compare fields | **no caller** (see §7) |
| `getModelMarketTeasers` | `(canonicalModelId, limit = 4)` | `public_model_market_teaser` | raw rows | **no caller** (see §7) |

`MediaRow = { vehicle_id, visual_key, public_url, image_type, confidence, width, height, source_url, source_type }`.

Status rule used by every public vehicle function: only lifecycle-`CURRENT` trims are shown (`lib/canonical-trim-status.ts`: `isCurrentLifecycleStatus`, `filterToCurrentTrims`). The model list functions return all statuses and the pages filter (`row.status === "CURRENT"`).

---

## 2. Vehicle side — compare (`lib/compare-canonical-data.ts`) and vehicle endpoints

| Function | Signature | Reads | Returns | Callers |
|---|---|---|---|---|
| `getCanonicalCompareModelOptions` | `()` | `current_vehicle_models` (`canonical_id,name_en,name_th,status,payload`, paged) | `{ id, brand, model }[]` (CURRENT only, sorted th) | `/api/compare/models` |
| `getCanonicalCompareTrimOptionsForModel` | `(modelId)` | `current_market_trims` (picker columns, CURRENT) + model row | `{ id, model_id, brand_name, model_name, name, powertrain, price_baht }[]` | `/api/compare/trims?model_id=` |
| `getCanonicalCompareTrimOptionsByIds` | `(ids[] ≤ 4)` | same | same shape, request order | `/api/compare/trims?ids=` |
| `getCanonicalCompareTrimsByIds` | `(ids[] ≤ 4)` | `current_market_trims` (incl. payload, campaign_quote), `current_vehicle_models`, media tables (targeted) | rich trim: `CanonicalTrim` fields (no `price_history`, `source_refs`, `_powertrain`) + `model_slug, brand_name, model_name, image_url, segment, body_type, production_type, production_country, model_seats, cab_type, retail_status, launch_year, launch_quarter` | `/api/tools/compare` |

### HTTP endpoints (client pages depend on these JSON bodies)

| Endpoint | Auth | Response body | Used by |
|---|---|---|---|
| `GET /api/search/suggest?q=` | public | brand/model suggestions from `getCanonicalBrands(250)` + `getCanonicalModels(600)` via `searchCatalog` | `components/search/SearchOverlay.tsx` |
| `GET /api/compare/models` | public, `max-age=300` | `{ models: { id, brand, model }[] }` | `app/compare/page.tsx` |
| `GET /api/compare/trims?model_id= \| ids=` | public, `max-age=300` | `{ trims: TrimOption[] }`; 400 without a parameter | `app/compare/page.tsx` |
| `GET/POST /api/tools/compare` | member, Free quota | comparison built from `getCanonicalCompareTrimsByIds` + `lib/free-compare.ts` | `app/compare/page.tsx` |

---

## 3. Market side — server functions and shared types

### 3.1 Public aggregate (`lib/public-market.ts`, `lib/home-market.ts`)

| Function | Signature | Reads | Returns | Pages |
|---|---|---|---|---|
| `getPublicMarket` | `(dimension: PublicDimension = "brand")` | `adminDb()` (service role): `registration_reporting_source` (latest period), then `periodTotal` × up to 12 months | `PublicMarket \| null` | `app/market/page.tsx` (+ `MarketCharts.tsx` uses the type) |
| `getHomeMarket` | `unstable_cache(() => getPublicMarket("brand"))`, key `tdr-home-market-brand-v1`, revalidate 1800 s | — | `PublicMarket \| null` | `app/page.tsx` (reads `totalRegistrations`, `period`, `brands[0..2]`, `trend`) |
| `periodTotal` | private `(db, period, dimension)` | `fetchRegistrationRows` → `canonicalizeRegistrationRows` → `sliceMarketFacts(limit 500)` | `{ rows: MarketSliceRow[], total }` | internal |

```ts
type PublicDimension = "brand" | "powertrain" | "body_type" | "segment" | "origin_country" | "oem_group";
PUBLIC_BRAND_LIMIT = 8; PUBLIC_TREND_MONTHS = 12;

type PublicMarket = {
  dimension: PublicDimension;
  period: string;                 // "YYYY-MM-01", latest period in registration_reporting_source
  previousPeriod: string | null;
  totalRegistrations: number;     // sum of slice rows (mapped units only — see §7)
  brands: { key; label; registrations; sharePct }[];   // top 8 (name kept for every dimension)
  others: { registrations; sharePct } | null;
  movers: { key; label; delta; sharePct }[];           // ≤ 10, from compareMarketSliceRows
  trend: { period; total: number | null }[];           // 12 months, oldest first; null = no data
};
```

### 3.2 Shared pure module (`lib/registration-market.ts`)

Imported directly by client code (`app/member/market/MarketWorkspace.tsx`), so it is part of the contract even though it has no I/O.

- Types: `MarketDimension` (12 values: `brand, model, segment, body_type, powertrain, oem_group, market_position, import_type, origin_country, brand_origin, registration_type, market_scope`), `MarketWindow` (`month | rolling3 | rolling6 | rolling12 | ytd`), `MarketComparison` (`previous | yoy`), `MarketPeriodWindow { from, to }`, `MarketSliceFilters` (12 optional string arrays), `CanonicalRegistrationFact`, `MarketSliceRow`, `MarketMovementRow`.
- Period helpers: `normalizeReportPeriod`, `shiftReportPeriod`, `resolveMarketWindow`, `previousMarketWindow`, `comparisonMarketWindow`, `reportPeriods`, `missingReportPeriods`, `isMarketDimension/Window/Comparison`.
- `sliceMarketFacts({ facts, dimension, filters?, includeUnmapped?, limit? }) → MarketSliceRow[]`
- `compareMarketSliceRows(previousRows, currentRows) → MarketMovementRow[]`

```ts
type MarketSliceRow = {
  entity_key; entity_label; registrations; market_total; market_share_pct; market_rank;
  window_raw_units; window_mapped_units; window_mapping_coverage_pct;   // number | string
};
type MarketMovementRow = {
  entity_key; entity_label; units_previous; units_current; units_change;
  share_previous_pct; share_current_pct; share_change_pp;
  rank_previous: number | null; rank_current: number | null; rank_change: number | null;
};
```

Labels produced today: missing values become `"UNKNOWN"`; model-level powertrain is one value from `payload.powertrains`, or `"MIXED"` when there are several (`canonicalPowertrain` in `registration-analytics.ts`).

### 3.3 Coverage helpers (`lib/member-market.ts`)

`periodKey`, `provisionalMarketPeriods(rows)` (period < 40 % of the 6-month baseline → provisional), `defaultMarketPeriod(rows)`, `coverageForPeriod(rows, period)`; `CoverageRowLike` matches `registration_analytics_coverage` rows. Used by `app/member/market/MarketWorkspace.tsx` and admin pages.

### 3.4 Engine entry points (`lib/registration-analytics.ts`) — behind the endpoints

| Function | Returns | Used by |
|---|---|---|
| `resolveRegistrationAccess(token)` | `AccessContext` | all member market endpoints |
| `getRegistrationAnalytics({ accessToken, dimension, period?, limit? })` | raw view rows (`select *`) | `/api/report/registration` |
| `getRegistrationDashboard(token)` | `RegistrationDashboard { tier, period, coverage, dimensions, quota }` | `/api/tools/sales-dashboard` |
| `getRegistrationAvailablePeriods(ctx)` | `string[]` | `/api/report/market` |
| `fetchRegistrationRows`, `canonicalizeRegistrationRows` | raw rows / `CanonicalRegistrationFact[]` | `getPublicMarket`, `loadRegistrationFactSpan` |
| `assertMarketSliceAllowed`, `loadRegistrationFactSpan`, `sliceLoadedFacts`, `getRegistrationMarketSlice`, `consumeMarketReportQuota` | gates / facts / `MarketSliceRow[]` / quota | `/api/report/market` |

`RegistrationDimension` → view: `coverage → registration_analytics_coverage`, `brand → registration_brand_share`, `model → registration_model_share`, `mom → registration_model_mom`, `segment → registration_monthly_segment`, `powertrain → registration_monthly_powertrain`, `chinese-bev → registration_chinese_bev_rank`.

Supporting engine state (not called by pages): `getActiveHistoricalModelState(db)` (`lib/historical-model-state.ts`), `getActiveMarketPriceState(db)` (`lib/market-price-state.ts`).

### 3.5 Market HTTP endpoints

| Endpoint | Auth | Response body | Used by |
|---|---|---|---|
| `GET /api/report/market` | member bearer; quota once per request | `{ plan: { tier, model_grain, windows, comparisons, filters, history_from }, dimension, period, window, period_from, period_to, filters, price_band, price_coverage, include_unmapped, rows: MarketSliceRow[], comparison: { mode, window, rows, movement: MarketMovementRow[], price_coverage } \| null, trend: { period, total }[], quota }`. Errors: `{ error, upgrade_required? , missing_periods?, window?, comparison_window?, price_coverage? }` | `app/member/market/MarketWorkspace.tsx` |
| `GET /api/report/registration?dimension=&period=&limit=` | member bearer; quota unless `coverage` | `{ dimension, period, rows }` (rows = view columns, §4.2) | `MarketWorkspace.tsx` (coverage, limit 120) |
| `GET /api/tools/sales-dashboard` | member bearer; one quota unit | `RegistrationDashboard` | `app/member/page.tsx` (reads `coverage.total_registrations`, `coverage.mapped_unit_pct`, `coverage.mapped_registrations`, `dimensions.brand/model/mom/segment/powertrain`) |

Query parameters of `/api/report/market`: `dimension, period, window, compare, price_band, limit (≤500), include_unmapped, trend_months (0–12)`, filters `registration_type, brand, model, segment, body_type, powertrain, oem_group, market_position, import_type, origin_country, brand_origin, market_scope` (comma or repeated).

`app/member/market/page.tsx` also builds its brand/model pickers from `getCanonicalBrands(200)` / `getCanonicalModels(700)`, reading `status, segment, body_type, powertrains, production_type, production_country, market_scope, brands.id` and brand `oem_group, brand_origin`.

---

## 4. DB serving layer (live columns, 2 Oct 2026)

### 4.1 Vehicle views (Phase 0 parity targets)

| View | Columns | Read by (non-admin) |
|---|---|---|
| `current_vehicle_brands` | `release_id, canonical_id, tdr_brand_id uuid, slug, name_en, name_th, origin_country, payload jsonb` | `canonical-data`, `registration-analytics` |
| `current_vehicle_models` | `release_id, canonical_id, tdr_model_id uuid, brand_id, slug, name_en, name_th, generation_id, status, segment, body_type, retail_price_min numeric, retail_price_max numeric, payload jsonb` | `canonical-data`, `compare-canonical-data`, `registration-analytics`, `/api/report/market` (count) |
| `current_vehicle_generations` | `release_id, canonical_id, model_id, code, segment, launched date, ended date, payload jsonb` | `market-price-state` |
| `current_market_trims` | `release_id, canonical_id, model_id, generation_id, variant_id, name, powertrain, status, payload jsonb, current_list_price jsonb, campaign_quote jsonb, price_history jsonb, source_refs jsonb` | `canonical-data`, `compare-canonical-data`, `market-price-state` |
| `current_spec_facts` | `release_id, fact_id, trim_id, field_key, verification_status, payload jsonb` | admin only (`canonical-editor`) |
| `current_price_ledger` | `release_id, record_id, trim_id, amount_thb bigint, price_type, effective_from, effective_to, observed_at, campaign_id, option_id, source, source_ref, payload jsonb` | **no reader** |
| `vehicle_media_bindings`, `vehicle_media_assets` (tables) | see schema | `canonical-data`, `compare-canonical-data` |

Payload keys pages depend on (must survive Phase 0): model `payload.brand{id,slug,name_en,name_th}`, `generation_id`, `generation`, `powertrains[]`, `production_type`, `production_country`, `market_scope`, `market_position`, `seats`, `cab_type`, `launch_year`, `launch_quarter`, dimension keys; brand `payload.oem_group`, `brand_origin`; trim `payload.specs{…}`, `payload.comparable_specs[]`, `payload.brand`, `payload.model`, `payload.current_list_price`; `campaign_quote.campaign_options[].status_as_of`.

### 4.2 Market views (replaced by Ice data in M4)

| View | Columns |
|---|---|
| `registration_reporting_source` | `id, period date, registration_type, brand_name_raw, model_name_raw, model_id uuid, canonical_model_id, registrations int, source_id, mapping_method, created_at, fact_source` |
| `registration_analytics_coverage` | `period, raw_rows, total_registrations, mapped_rows, mapped_registrations, mapped_unit_pct` |
| `registration_brand_share` | `period, brand_key, brand_name, registrations, market_total, market_share_pct, market_rank` |
| `registration_model_share` | `period, entity_key, model_id, brand_key, brand_name, model_name, segment, body_type, powertrains[], registrations, source_rows, canonically_mapped, market_total, market_share_pct, market_rank` |
| `registration_model_mom` | as model_share minus share/rank, plus `previous_registrations, mom_delta, mom_pct` |
| `registration_monthly_segment` | `period, segment, registrations, classified_total, market_total, share_of_classified_pct, market_coverage_pct, segment_rank` |
| `registration_monthly_powertrain` | `period, powertrain, registrations, classified_total, market_total, share_of_classified_pct, market_coverage_pct, powertrain_rank` |
| `registration_chinese_bev_rank` | `period, model_id, brand_key, brand_name, model_name, registrations, bev_rank` |

Other inputs to the market engine: `registration_brand_aliases`, `canonical_vehicle_state`, `canonical_vehicle_releases.payload.historical_model_state`, `canonical_price_projection`.

---

## 5. Page → contract matrix

| Page | Vehicle contract | Market contract |
|---|---|---|
| `/` `app/page.tsx` | `getCanonicalBrands(150)`, `getCanonicalModels(600)` | `getHomeMarket()` |
| `/brands` | `getCanonicalBrands(250)`, `getCanonicalModels(600)` | — |
| `/brands/[slug]` | `getCanonicalBrand`, `getCanonicalModelsByBrand`, `getCurrentTrimCountsByModel` | — |
| `/models` | `getCanonicalBrands(150)`, `getCanonicalModels(600)`, `getCurrentTrimCountsByModel` | — |
| `/models/[slug]` | `getCanonicalModelBundle`, `getCanonicalRelatedModels(…, 6)`, `getCanonicalHistoricalTrims`; legacy `getProductionProgramsByModel(editorial_id)` | — |
| `/models/[slug]/[trim]` | `getCanonicalModelBundle` (trim picked from `trims`) | — |
| `/search` | `getCanonicalModels(600)`, `searchCanonicalCatalog` | — |
| `/compare` (client) | `/api/compare/models`, `/api/compare/trims`, `/api/tools/compare` | — |
| search overlay (client) | `/api/search/suggest` | — |
| `/reports` | `getCanonicalBrands(250)`, `getCanonicalModels(600)`; legacy `getEvents` | — |
| `/market` | — | `getPublicMarket("brand")`, `PUBLIC_BRAND_LIMIT`, `PublicMarket` |
| `/member` (client) | — | `/api/tools/sales-dashboard` |
| `/member/market` | `getCanonicalBrands(200)`, `getCanonicalModels(700)` (pickers) | `/api/report/market`, `/api/report/registration?dimension=coverage`, `registration-market` helpers, `member-market` helpers |

**Admin consumers** (outside §15's UI rule, but they read the same views and must keep working through Phase 0): `app/admin/(secure)/{page, market, registrations, data-quality, prices, eco-trims, retail-lifecycle, vehicle-input, models/[id]/edit}`, `app/admin/*-actions.ts`, `/api/admin/market/export`, `lib/admin-registration-market.ts`, `lib/canonical-editor.ts`, `lib/price-coverage-worklist.ts`. They read `current_vehicle_brands/models/generations`, `current_market_trims`, `current_spec_facts` and `registration_analytics_coverage` directly.

---

## 6. Expected visible differences after M4/M5 (market side, from §15.2 — not parity failures)

Per `VEHICLE_DB_V3.md` §14.3 / §15.2, these change on purpose and must be listed in the M4/M5 PRs:
- Market total = Ice total (e.g. 2569-08: 61,805 → 62,417).
- `powertrain` labels: BEV / HEV / PHEV / เบนซิน / ดีเซล / LPG from Ice `reg_powertrain`, replacing ICE / MIXED / REEV / UNKNOWN (today computed from `payload.powertrains` in `canonicalPowertrain`).
- Coverage line text (today `window_mapping_coverage_pct` / `mapped_unit_pct` = canonical mapping coverage) → crosswalk coverage + "ไม่ระบุ" for segment/body_type.
- Index names ("TDR Powertrain Index", "TDR Wheel & Tyre Index").
- Ice models without a TDR page: shown unlinked (today `entity_key = raw-model:…`).

Shape stays the same: `PublicMarket`, `MarketSliceRow`, `MarketMovementRow`, the `/api/report/market` body and `RegistrationDashboard` keep their fields.

---

## 7. Findings for later steps (not acted on in M1)

Facts found while checking the §15.1 starting list against the code. None needs a code change in M1; each is input for the step named.

1. **`current_price_ledger` has no reader.** The price engine (`lib/market-price-state.ts`) reads the projection table `canonical_price_projection` filtered by `release_id`, not the `current_price_ledger` view. → **Phase 0 step 3:** this must be repointed to the master (or to `current_price_ledger`) together with the views, or price-band market cuts silently keep reading the old projection.
2. **Market engine reads release-only state.** `getActiveHistoricalModelState` reads `canonical_vehicle_releases.payload.historical_model_state`, and both state loaders key their caches on `canonical_vehicle_state.active_release_id`. → **Phase 0 steps 3/5:** once releases stop being a write path, these need a source in the master, or must be retired in M4 (Ice brings its own history).
3. **`public_model_market_teaser` / `getModelMarketTeasers` have no caller.** The table exists, but no page reads it. → **M4/M5:** either wire it to Ice data or remove it; it is not a live contract today.
4. **`getCanonicalCompareTrims` has no caller.** It was superseded by `lib/compare-canonical-data.ts`. → Engine PRs do not need to keep its parity. A cleanup PR can remove it.
5. **Media selection is duplicated** in `canonical-data.ts` (`getCanonicalPrimaryMediaIndex`) and `compare-canonical-data.ts` (`targetedCompareModels`). The two must stay behaviourally identical (model binding with no asset = blank override that blocks generation fallback).
6. **A route reads a view directly.** `/api/report/market` counts `current_vehicle_models` for `price_coverage.total_models`. This counts every status, not only CURRENT. → **M4:** move it behind the engine.
7. **The public total only counts mapped units.** `getPublicMarket.totalRegistrations` sums slice rows, which drop units without a canonical brand (brand grain) or model. So today's figure is below the DLT total. M4 aligns it with the Ice total (§6).
8. **Legacy uuid dependencies on public pages.** `/models/[slug]` calls `getProductionProgramsByModel(editorial_id)` (legacy `production_programs` keyed by `tdr_model_id`). `getCanonicalBrands` reads `logo_url` from legacy `brands` via `tdr_brand_id`. → **Phase 0 step 2:** `tdr_model_id` / `tdr_brand_id` must stay populated in the master views (V3 §2 keeps every ID unchanged; these uuids are part of that).
9. **`modelRow` hard-codes `brands.logo_url = null`.** Pages that need a logo join `getCanonicalBrands()` themselves. This is existing behaviour and is part of the contract.
10. **Not in the starting list, but part of the contract:** `getCanonicalBrand`, `getCanonicalModelsByBrand`, `getCurrentTrimCountsByModel`, `getCanonicalHistoricalTrims`, `searchCanonicalCatalog`, all of `compare-canonical-data.ts`, `getHomeMarket`, `lib/member-market.ts`, and the market and compare HTTP endpoints. All of these are listed above.
