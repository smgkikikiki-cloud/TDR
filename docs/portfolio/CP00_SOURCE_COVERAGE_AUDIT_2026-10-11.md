# CP-00 — Source Coverage Read-Only Audit, Evidence Round 1

**Observation date:** 2026-10-11  
**Source:** live Supabase `ltvwzkffmpudpjfjomrg` identified by `docs/WORK_STATE.md` as TDR project, plus current `main` GitHub code.  
**Access:** SQL `SELECT` only over `information_schema.columns` and aggregate counts/grouping. No UPDATE/INSERT/DELETE/DDL; no migration, service changes, R6 matching run, publication or write-path operations.  
**Status:** **EVIDENCE COLLECTED / CP-00 PARTIALLY COMPLETE** (real raw coverage and schema observed; field-level offer semantics, effective validity, time-aligned observations, historical source coverage and source licenses NOT certified).  
**This is an audit observation, not a product/roadmap approval.**

## Executive verdict

**TDR is NOT yet ready to publish a reliable whole-market PDI, a 2021-present official retail-discount chronology or a calibrated Model-level Competitive Pressure Score.** The main blocker isn't index arithmetic: it is **sparse, nonhomogeneous and incompletely normalized official list-price/offer history** on the present DB, current retail-universe uncertainty, and unresolved model-level market mapping.

However, TDR has useful canonical model/trim tables, real market history and a partial contemporary list-price cohort. **A restricted source-audited Pressure evidence pilot is plausible**, after independent verification of a small cohort, substitution mapping and market authorization. Do not equate this to full launch readiness.

## A. Inventory (actual SQL aggregation)

| Table / measurement | Rows / observed result | Meaning and limitations |
| --- | ---: | --- |
| `vehicle_models` | **323** | includes all model statuses |
| `vehicle_trims` | **1,569** | status: 1,431 CURRENT; 102 UNVERIFIED; 36 HISTORICAL |
| current model IDs (at least one CURRENT trim) | **318** | *CURRENT is a DB lifecycle flag; not evidence that all trims are owner-confirmed retail* |
| `vehicle_price_ledger` | **1,004** | price types and dates differ substantially |
| `vehicle_promotions` | **48** | campaign options, not confirmed national general-cash offers |
| `vehicle_campaigns` | **44** | 30 with start and 30 with end; 29 with source_ref |
| `ice_package_imports` | **1** | latest master version 7.0, accepted 2026-10-10 |
| `ice_dims_model_group` | **1,200** | external Ice identities |
| `ice_reg_trend` | **262,985** | model-group-period-province-regtype registration rows |
| `ice_model_crosswalk` | **490** | 82 AUTO, 408 PROPOSED, 0 APPROVED; 489 distinct group IDs |
| `ice_model_group_redirects` | **50** | needs review of semantics / authorization |

### Observed price-ledger distribution

| Price type | Ledger rows | Distinct trim IDs | Year of coalesced effective/observed date | Source refs | Important constraints |
| --- | ---: | ---: | --- | ---: | --- |
| `ECO_STICKER_PRICE` | **643** | 615 | **2019–2026** | 643 | **Must not automatically convert to Retail MSRP** |
| `LIST_PRICE` | **320** | 304 | **2026 only** | 250 | only 13 have effective_from; 307 missing; all observed_at present |
| `CAMPAIGN_PRICE` | **40** | 38 | **2026** | 12 | cannot assume valid unqualified cash discounts |
| `ESTIMATED_PRICE` | **1** | 1 | 2026 | 1 | not official MSRP |

Ledger year detail: `ECO_STICKER_PRICE` 2019=3, 2020=43, **2021=30**, 2022=87, 2023=81, 2024=116, 2025=144, 2026=139. No 2021–2025 `LIST_PRICE` rows were found by `coalesce(effective_from, observed_at)` **in this ledger**. This does **not** prove that no externally recoverable published MSRP existed in those years.

`LIST_PRICE` `source` labels: `owner_pricing_directory` 161 rows (all `source_ref` present), `admin` 150 (80 refs), `official_oem` 5 (5 refs), `autolifethailand` 4 (4 refs). These are **raw source labels**, not an independent verification that every row meets official list-price licensing and effective-date rules. All 320 `LIST_PRICE` ledger rows have null `authority` and `vat_included` fields; applying a method requiring source authority or consistent VAT needs provenance validation and potential field mapping, not automatic default values.

### Current-retail price coverage: biggest immediate defect

Universe for this diagnostic only: 1,431 `vehicle_trims` where status=CURRENT and not deleted, across 318 models. Match `LIST_PRICE` by exact `trim_id` irrespective of current validity date.

| Diagnostic | Observed |
| --- | ---: |
| CURRENT trim IDs | **1,431** |
| CURRENT trim IDs with any nonretracted historical `LIST_PRICE` | **273** (**19.1%**) |
| CURRENT trim IDs with served `current_list_price.amount_thb` | **273** |
| CURRENT models with at least one such Trim | **140 / 318** |
| CURRENT models with **all** CURRENT Trim IDs having at least one such LIST_PRICE | **74 / 318** |
| CURRENT models with **no** matching LIST_PRICE | **178 / 318** |

**Even the 74 fully populated models are not yet PDI-ready**: this test does not require synchronized effective validity, verified genuine retail lineups, source authority, offer completeness or a qualifying mainstream cash discount. Conversely a given model can support a sourced descriptive price event even when the *whole-model* index is not scorable.

The preexisting `lib/market-price-state.ts` explicitly caps its three serving queries at 1,000 rows; do not treat that reader as a complete index/time-history API. A new full-coverage read contract or audit-safe pagination is required before backfill or time-series scoring.

### Promotions: source-present is not numerical cash-offer-ready

- 48 promotion options linked to **all 48** valid `vehicle_campaigns` records (44 distinct campaign IDs; 14 parent brands). This is a **campaign relationship**, NOT a Trim-specific price association.
- **0/48** rows have `trim_id`, `model_id`, `scope`, `type`, `amount_thb`, or `promo_price_thb` set in normalized columns. Raw `conditions` and `payload` JSON are present; fields `booking_from`, `booking_to`, `delivery_by`, `finance_required`, `quota_units`, `text` in `conditions` exist in every row (may contain nulls). **No direct cash discount quantity or mapped Trim can be inferred without a separate schema-aware source investigation.**
- **34/48** have top-level source + both `valid_from`/`valid_to`; 14 lack that complete date/source basis. `conditions.finance_required` = false for 46 and true for 2, but a false value alone does not establish an unconditional general-retail cash incentive.
- Source parent campaign metadata can be used to start a documentary review, not blindly converted to a cash discount or inferred zero.

**Readiness consequence:** first build a source-preserving **Promo Offer Classification & Linkage Audit** (which Model/Trim or eligible offer does each option apply to? How do nested descriptions map to cash/finance/gift, if at all?). Until that passes, net-price comparisons and national PDI based on these promotions must be `NOT_SCORABLE` for any unverified model.

### Ice Registration: actual historical breadth but not customer-sales causality

- `ice_reg_trend` spans Buddhist `2564-01` through `2569-09`, exactly **69 distinct months**, all 77 provinces represented in each year aggregation; years have 12/12/12/12/12/9 distinct months respectively (2021→2026 Sep).
- 2021: 43,840 rows / 552 distinct Ice groups; 2022: 45,285 / 502; 2023: 45,475 / 520; 2024: 43,653 / 515; 2025: 46,317 / 521; 2026 Jan–Sep: 38,415 / 506.
- Ice model data remain `model_group_id` grain. 82 AUTO linked groups; 0 APPROVED; many-to-many/partial evidence can forbid canonical model allocation. Do not take arbitrary display `canonical_model_id` from a `primaryLinkedModel` and assign the group's units to that model.
- The original Market Track `docs/WORK_STATE.md` claims R6 not started/empty crosswalk; **live read on 2026-10-11 empirically confirms 490 rows / 50 redirects** as reported by draft PR #200. C01 **execution state discrepancy is verified**; owner authorization and exact gate disposition remain unverified. This read is NOT permission to advance R6, R7 or R8.
- Counts by year only establish source table coverage, **not** every group complete for 69 months, no errors in allocation, or dealership transactions.

### Retail verification and additional limits

- `vehicle_trim_lifecycle_decisions` contains 15 rows (12 HISTORICAL, 3 CURRENT) and `vehicle_model_operational_states` query returned zero rows. `retail_lineup_plans` row count is zero. **Do not infer the absence of all approved retail lineups from these three tables alone**; owner-approved current sets may be represented in another layer, which needs an explicit authority/read-path audit.
- Current lifecycle count is an **upper bound candidate source universe**, not a verified `SOLD_NOW` registry.
- Read-only connected Supabase project is the one recorded in `WORK_STATE.md`; this audit did not validate the active Vercel deployment environment nor compare against `TDR ASIA`.

## B. Commercial readiness verdict (not all blockers are global)

| Engine/product | Verdict from this snapshot | Can progress now | Must not publish yet |
| --- | --- | --- | --- |
| PR200 / Ice Market ID | **UNRESOLVED AUTHORITY** | read-only row/run provenance, owner label decisions | re-run R6, auto-approved model units, R7/R8 |
| PR201 / Novel identity | **OFFLINE ONLY** | draft shadow and false-CREATE QA | canonical CREATE |
| PR203 / Current Catalog | **OFFLINE/QA** | source/retail eligibility audit, gap replay | writes or structural AUTO changes |
| PDI | **NO FULL-MARKET NUMERIC READINESS** | historical source inventory, promo classification, constrained synthetic pure functions | 2021-current index, discounts=0 for missing, unsourced national ranking |
| CTPDI | **CROSSWALK+CN SOURCE NOT AUDITED IN CP-00** | manual pairing/evidence and FX methodology design | ratio without locked CN pair, source, comparable basis |
| Competitive Pressure | **CANDIDATE LIMITED PILOT**, no score | reviewed substitute candidates, sourced MSRP move, null-safe market context on fixtures | national scored ranking and claimed registration-caused price loss |
| Dealer Geography / Watch | **OUTSIDE CP-00 SOURCE AUDIT** | dealer evidence inventory and verification contract | branch sales and auto-confirmed closure |
| Layer 3 | **UX CONTRACT ONLY** | org access/typed UI against known unavailable statuses | paid live pressure claims without verified input+method+entitlement |

## C. Precise next tasks after this read-only CP-00 round

### CP-00a — Source classification/canonical time readiness (read-only audit)

- Determine which `owner_pricing_directory` rows have independently verifiable official list-price provenance/observed/effective dates and whether their tax basis is consistent.
- Identify the **actual retail-approved lineups** with source and effective dates (avoid inferring from CURRENT flag).
- Reconcile `vehicle_promotions.conditions/payload` with `vehicle_campaigns` and any `campaign_quote` serving shapes using a schema-aware parser in a fixture/read-only audit; no writes or reclassification yet.
- For a small reviewed Model cohort, produce `LIST_PRICE`, `CASH_NET_OFFER`, `UNKNOWN_OFFER`, `NOT_CURRENT_RETAIL`, `CONFLICT` separately, **never zero-fill**.

### CP-00b — Historical MSRP & offer-source recovery **plan** (no harvesting yet)

- 2021–2025 source rights/archives, documented OEM price lists, period validity, link to generations/market trims **and selection-bias audit**.
- Explicitly distinguish historical full-lineup reconstruction from today's Model/Trim membership. An ECO sticker price may be retained as tax-document evidence, not promoted to a verified MSRP without independent validation.
- Report progress as `verified_model_months / eligible_model_months` *only if* denominator can be reconstructed honestly; otherwise `DENOMINATOR_UNKNOWN`.

### CP-00c — Ice identity report/market context

- Independent read-only R6 workflow/state/run provenance check, 490 row categories and whether a newer approved set exists; never infer owner approval from `AUTO`.
- For chosen pilot competitors, document coverage of the same registration class, time window, period completeness and exact reviewed link(s); no fanout/double count.

### CP-01..05 after domain-specific owner approvals

Pure substitution model/graph; separate MSRP and verified cash lanes; registration adapter; evidence-ranked Pressure assessment; org-scoped product UI/report and security. Existing PR #200/201/203 keep their own scoped roadmaps/gates, and no writer/main/deploy/paid API is enabled.

## D. Reproducibility queries (SELECT-only; aggregate output)

Executed in connected Supabase `ltvwzkffmpudpjfjomrg`, October 11 2026. Each independent query uses only aggregates over canonical tables. Parent/child source amounts and raw text were not copied into this PR.

```sql
-- Price types and official historical date-bucket sanity check
SELECT price_type, extract(year FROM coalesce(effective_from,observed_at))::int yr,
       count(*) records, count(distinct trim_id) trims
FROM public.vehicle_price_ledger
GROUP BY 1,2 ORDER BY 1,2;

-- Exact current-trim-to-LIST_PRICE diagnostic; does not claim source validity
WITH a AS (
 SELECT canonical_id,model_id
 FROM public.vehicle_trims
 WHERE upper(coalesce(status,''))='CURRENT' AND deleted_at IS NULL
),
lp AS (
 SELECT DISTINCT trim_id FROM public.vehicle_price_ledger
 WHERE price_type='LIST_PRICE' AND retracted_at IS NULL
),
m AS (
 SELECT a.model_id,count(*) n_trims,count(lp.trim_id) n_list
 FROM a LEFT JOIN lp ON lp.trim_id=a.canonical_id GROUP BY a.model_id
)
SELECT count(*) models,
       count(*) FILTER (WHERE n_list=0) models_without_list,
       count(*) FILTER (WHERE n_list=n_trims) models_with_all_list,
       sum(n_trims) current_trims,
       sum(n_list) current_trims_with_list
FROM m;

-- Crosswalk status and observed Ice group coverage; no approval inference
SELECT status,count(*) n FROM public.ice_model_crosswalk GROUP BY status;
SELECT left(period,4) be_year,count(distinct period) months,
       count(*) records,count(distinct model_group_id) groups
FROM public.ice_reg_trend GROUP BY 1 ORDER BY 1;
```

## E. Engineering acceptance for the next data adapter

- `PAGINATED_READ`: no implicit 1,000 cap or silent truncated response; stable full extraction with declared as-of.
- `SOURCE_BASIS`: list/ECO/campaign/estimated distinguished; MSRP and cash-net lanes never merged.
- `DATE_BASIS`: as-known vs effective dates separately handled; null effective date doesn't mean price action on observed date.
- `STATUS_BASIS`: `CURRENT` != owner retail approval, missing/expired != verified zero, pending crosswalk != accepted model link.
- `REPRODUCIBLE`: row counts, versions, input hashes, source coverage and expected nulls independently checked from both working directories.
- `PERMISSIONS`: read-only SQL for audits; no GraphQL/Data API new entitlements, migrations, work_state overrides, R6/R7/R8 changes.
- `OWNER_GATE`: owner reviews results and approves a **bounded offline** pure-data computation task separately; the portfolio's `execution.enabled` remains false.

**Conclusion:** The pricing *data layer* is now a first-class Roadmap dependency, not a minor subtask of UI or an index formula.
