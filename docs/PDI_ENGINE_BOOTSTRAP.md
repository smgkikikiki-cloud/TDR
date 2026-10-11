# TDR PDI engine — bootstrap, internal only

Status: **implemented on isolated branch as an experimental engine. NOT APPROVED FOR PUBLISHING.**
Source specification: `TDR_PDI_PARAMETER_SPEC_v0.5_DRAFT.md` (2026-10-08), plus PDI/CTPDI Master Brief v0.7. The spec explicitly marks ratio-of-medians, equal-model-weight mean and full-coverage scoring as **proposed**. Implementing their deterministic interpretation for tests is **not** methodology approval.

## What is implemented

- `lib/pdi-engine.ts` — dependency-free pure calculation; accepts typed and *already evidence-qualified* MSRP and cash-bundle records. No DB writes.
- `scripts/check-pdi-engine.ts` — deterministic acceptance examples for price trigger, all-trim median, verified zero vs unknown, JP candidate, no finance/student/dealer contamination, no accidental discount stacking, expiry, conflicts, equal-model weighting and like-for-like movement.
- `scripts/pdi-readonly-audit.ts` — server-only, read-only adapter for **existing canonical Vehicle Master** tables. No alternative Thai-car identity or pricing authority. It audits missing metadata and returns non-publishable research results.
- `npm run check:pdi` and `npm run pdi:audit`; `npm run check` includes the new deterministic check.

## Evidence gates (non-negotiable)

1. **MSRP:** Must be a positive LIST_PRICE observation, in release, non-retracted, date-valid, carrying evidence ID + reference, and explicitly marked OFFICIAL/ADMIN. Legacy rows with `authority=NULL` are evidence *candidates*, not verified in the index.
2. **Discount:** `0` means a documented verified-zero observation, **not** the absence of a campaign. No currently defined `vehicle_promotions` row may become verified-zero by inference.
3. **Promotions:** The read-only adapter only accepts normalized rows with `type=DISCOUNT`, `scope=TRIM`, `status=ACTIVE`, explicit source, authority, validity and explicit owner-approved flags in `conditions` (`pdi_verified_general_cash=true`, `retail_scope=NATIONWIDE`). Finance, profession, student, trade-in, vague "up to", dealer-only, expired, assumed-valid-to and untyped legacy options are withheld.
4. **Stacking:** Only pre-adjudicated cash bundles with explicit proof of composability can sum components. Never sum separate ads simply because both are currently displayed.
5. **Eligibility:** CN HEV/PHEV/REEV/BEV or explicitly approved JP ICE/HEV/BEV model; strict <2,000,000 THB MSRP entry at the **model** level; then all current-retail canonical trims, including expensive trims. The current code **does not infer or approve any Japanese whitelist**; all JP audit rows are `CANDIDATE`.
6. **Coverage:** Score the model only if **every** included current retail trim has verified MSRP and verified cash discount or verified zero. Partial trims stay visible. Eligible model aggregation is equal-model weight; the draft output unit is **percentage**, and movements are **percentage points**. `MEDIAN_NET_OFFER_PRICE` derives from paired trim-level MSRP minus discount, never from difference of unpaired medians.
7. **Publication:** The report exposes `researchMeanPdiPct` only. `publishableHeadlinePdiPct` stays NULL unless explicit owner publication approval and approved minimum completeness percentage are supplied. The audit does not provide either gate; it can **never publish a headline**.
8. **Frozen history:** Every calculation carries `sourceSnapshot` and `universeVersion` as reproducibility identifiers. This initial branch does **not** create durable snapshot history nor historical 2021+ price backfill. Those are next milestones.

## Real TDR data audit (2026-10-11, read-only Supabase inspection)

Connected Vehicle Master sample has approximately 323 models, 1,569 trims, 320 LIST_PRICE ledger rows, 40 CAMPAIGN_PRICE rows and 48 promotion records. All 48 promotion records presently have NULL typed `type`, `scope` and `status`. The sampled LIST_PRICE rows also have `authority=NULL` although some have source URLs.

**Consequence:** Do not display a live national PDI now. The engine is executable against sufficiently adjudicated inputs, but a fully verified live market headline cannot responsibly be generated from today's available source qualification metadata. The adapter reports exactly where it stops. Do not backfill zeros or guess eligibility.

## How to run

```bash
npm ci
npm run check:pdi
# With an authorized server-side Supabase secret and the repo's environment:
npm run pdi:audit > /tmp/tdr-pdi-evidence-audit.json
```

The audit output includes calculation counts, incomplete candidates and source release provenance. It makes no DB writes and never exports a public endpoint. The JSON is internal and may contain proprietary model IDs.

## Next chunks, *not* implemented

A. Human/admin evidence normalization queue for existing campaign/price rows; official MSRP verification/review; explicitly verified zero-discount checks; separate MSRP-cut action ledger (never a cash numerator).

B. Owner-approved Japanese admission rules (review and versioning), scope conflicts, monthly discovery plus snapshot freeze, 2021–present historical evidence backfill linked only to canonical Vehicle Master identities.

C. Versioned output storage and publication gate once freshness/coverage thresholds and draft formula are approved; compute daily/weekly/monthly histories, peer groups, breadth/velocity/price actions. Then integrate with Competitive Pressure Layer 3. CTPDI consumes approved PDI signals later; don't conflate two indices.

**Do not:** merge/deploy without review, mutate the Vehicle Master in this branch, make new authoritative MSRP tables, generate unverified promotions with an LLM, write customer-facing APIs, or treat trial calculation outputs as commercially publishable.

## Update — October 11 operational pilot and publication guard

The branch now includes `lib/pdi-universe-policy.ts`, `data/pdi/pilot-2026-10-{e07,s07}.json`, `scripts/pdi-oem-pilot.ts`, the delegated Japanese allowlist, and exact October official-source model values. See [PDI_WORKING_PILOT_2026_10.md](./PDI_WORKING_PILOT_2026_10.md).

A research basket with 100% observed selected-model coverage is **not** complete-market coverage. `calculatePdi()` therefore refuses a publishable headline until **all** of the following are true: `publicationApproved`, `methodologyApproved`, `completeUniverseAttested`, approved minimum completeness threshold, and no unresolved `CANDIDATE`/`SCOPE_CONFLICT`. The live audit never supplies those attestations and has no public-facing publication path. The pilot is intended only for internal validation.

Run `npm run pdi:pilot` for reproducible official OEM model scores and `npm run pdi:pilot:verify` for an optional server-only current Vehicle Master parity check.
