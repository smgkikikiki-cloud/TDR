# TDR registration analytics

Registration facts are a paid intelligence dataset and remain separate from Vehicle Master / MarketTrim.

## Source precedence

1. Canonical DLT API export (`data/raw/dlt_YYYY-MM.csv`) when available.
2. Long-form DLT workbook snapshot (`data/raw_pivot/long_YYYY-MM.csv`) when no API export exists. It retains registration class.
3. Pivot snapshot (`data/raw_pivot/pivot_YYYY-MM.csv`) only when neither stronger source exists. It has `registration_type=*` and therefore must not guess class-dependent model splits.

For 2026 the currently loaded source chain is January API export, February-July long-form snapshots, and August pivot.

## Mapping rule

Raw DLT brand/model strings are always retained. `model_id` is populated only through `registration_brand_aliases` / `registration_model_aliases`. Ambiguous identities remain NULL. Pickup nameplates use reviewed class-specific aliases when class is available (for example RY1 double cab and RY3 cab); the classless pivot month deliberately leaves those nameplates unmapped.

The mapping tables are registration-only crosswalks. They are not MarketTrim records and must not be used to mutate the free catalogue.

## Private serving views

- `registration_analytics_coverage`: mapping quality by month.
- `registration_brand_share`: brand registrations, share, rank.
- `registration_model_share`: model registrations, share, rank.
- `registration_model_mom`: model month-on-month movement.
- `registration_monthly_segment`: segment mix with classified-market coverage.
- `registration_monthly_powertrain`: powertrain mix for single-powertrain canonical models only, with coverage.
- `registration_chinese_bev_rank`: Chinese-origin, single-powertrain BEV model ranking.

All views are service-role only. Browser clients must use the entitlement-aware server endpoint instead of querying Supabase directly.

## Member endpoint

`GET /api/report/registration`

Requires a Supabase member access token in `Authorization: Bearer <token>` and an active `registration_full` row in `tdr_entitlements` (`ACTIVE`, `TRIALING`, or `GRACE`, and not past `valid_until`).

Parameters:

- `dimension=coverage|brand|model|mom|segment|powertrain|chinese-bev`
- `period=YYYY-MM` or `YYYY-MM-DD` (optional)
- `limit=1..500` (optional)

Responses are `private, no-store`. The server uses `SUPABASE_SECRET_KEY` (preferred) or the legacy `SUPABASE_SERVICE_ROLE_KEY`; neither is sent to the browser.

## 2026 load quality at implementation time

January-July canonical-model mapping is approximately 98-99% of registration units. August is lower because the available pivot lacks registration class; ambiguous pickup splits are intentionally left raw rather than fabricated. Dashboard dimensions that rely on canonical metadata expose their own coverage denominator.
