# TDR PDI: First reproducible, official-evidence working numbers
## Internal market-intelligence experiment · 11 October 2026

**Status:** EXECUTABLE RESEARCH PILOT, **NOT** a published nationwide Thai market PDI. Methodology still v0.5 DRAFT, and all official discounts expire under the stated October campaign terms.

### 1. Delegated universe fields (v0.6 pilot)

- **Geography / channel:** Thailand, new retail passenger vehicles, generally accessible nationwide advertised unconditional cash offers only.
- **Brand origin**, *not vehicle production country*: China `CN` and Japan `JP`.
- **China powertrains:** HEV, PHEV, REEV, BEV; ICE excluded in v0.6 headline.
- **Japan powertrains:** ICE, HEV, BEV **only in explicit selected-model allowlist** in `lib/pdi-universe-policy.ts`; PHEV, REEV excluded in this index scope. Current pilot whitelist has **36 canonical Japanese models**.
- **Passenger body types:** SEDAN, HATCHBACK, WAGON, CROSSOVER, SUV, OFFROAD, PPV, MPV, COUPE. **PICKUP, VAN, TRUCK, BUS:** distinct future commercial series; do not dilute the passenger PDI. Unknown body type gets REVIEW_REQUIRED.
- **Model eligibility trigger:** at least one verified current retail MSRP *strictly below* ฿2,000,000; once admitted include **every current retail trim** of that model, including higher-priced ones. Source-reviewed retail trim membership is required for scoring.
- **Japanese brand market position:** explicit selected models labelled Mass (no accidental admission of Lexus premium/luxury models). Neither whitelist membership nor active model status overrides price threshold or verification.
- **Unit:** model PDI in percent; trim cash discount in THB; model median MSRP/cash bundles; market aggregation equal-model-weight only for fully scored models.
- **Never treat missing promotions as zero, or retail campaign reductions as permanent MSRP changes.** The model's discount must be verified at every current retail trim.

These are **architect's delegated operational scope rules** for the pilot, subject to formal publication methodology review. They do not revise the earlier locked China/Japan powertrain and MSRP rules.

### 2. Official OEM evidence, October 2026

Primary source: [CHANGAN/DEEPAL October 2026 campaign](https://www.changan.co.th/th/promotion/campaign-oct-2026-th/) (1–31 October 2026, general noncommercial retail). TDR's frozen Vehicle Master release `vehicle-2026-a8e647b7db765c78`, as-of 1 October 2026. Exact reviewed Current Retail Sets from the database:

| Canonical model | Current retail trim | Reference MSRP | OEM discount | Advertised net retail |
|---|---|---:|---:|---:|
| `deepal.deepal_e07` | `deepal.deepal_e07.gen1.trim.plus_bev` | 1,699,000 | 50,000 | 1,649,000 |
| `deepal.deepal_e07` | `deepal.deepal_e07.gen1.trim.performance_awd_bev` | 2,099,000 | 100,000 | 1,999,000 |
| `deepal.deepal_s07` | `deepal.deepal_s07.gen1.trim.new_bev` | 1,219,000 | 120,000 | 1,099,000 |

These MSRP values agree with TDR's `vehicle_price_ledger` list-price records and official OEM page. TDR's old price rows have no assigned typed authority/source URLs in places, so **the pilot's OEM source evidence is pinned separately instead of silently granting authority to all legacy records**. E07's two campaign-price rows exist in the ledger; S07's October offer is recovered from the OEM publication, **not present as a typed campaign row**.

**Computed and reproducible:**

| Model | Median MSRP | Median eligible cash offer | PDI = cash/MSRP | Median of paired exact net prices |
|---|---:|---:|---:|---:|
| DEEPAL E07 | ฿1,899,000 | ฿75,000 | **3.949447%** | ฿1,824,000 |
| DEEPAL New S07 | ฿1,219,000 | ฿120,000 | **9.844135%** | ฿1,099,000 |

**Selected two-model OEM pilot basket:** equal-model mean = **6.896790806957247% (≈ 6.90%)**. This is **not** a representative population sample, not national PDI, and must never be displayed as the latter. The basket is specifically chosen because official complete evidence is available. **Pilot coverage = 2/2 models, 3/3 reviewed trims ONLY inside this deliberately small source-backed set.**

### 3. Actual data foundation availability (read-only Supabase audit 11 October 2026)

Under this delegated passenger policy, the current Vehicle Master contains **68 Chinese** in-scope passenger model candidates and **36 Japanese** listed models. Of these, **36 CN** and **2 JP** have *reviewed current retail trim sets*. Unadjudicated list-price rows suggest at least **32 CN + 2 JP** reviewed models have a trim listed below the threshold. Of those, **30 CN + 2 JP** have a complete corresponding list-price set.

**Important:** these counts describe *potential price-trigger candidates using available list-price observations, not confirmed eligible and fully price/offer-verified scored universe members*. As of the audit, 48/48 legacy promotion options have NULL `type`, `scope`, `status`, and the tested list-price ledger examples have NULL `authority`. These omissions preclude a legitimate broad national index. A 100% coverage claim for the selected two-model experiment **must not** be transferred to the entire 104-model policy discovery list.

### 4. Running and defending the numbers

```bash
npm ci
npm run pdi:pilot
# With authorized server-only Supabase secret; does not write to DB
npm run pdi:pilot:verify
npm run pdi:audit
npm run check:pdi
```

`pdi:pilot` validates the pinned OEM offer records and calls the actual `calculatePdi()` core. `pdi:pilot:verify` **additionally** asserts the current live Vehicle Master release, reviewed retail-set memberships, trim status/powertrains and recorded official MSRP match the pinned provenance; it **fails closed** if the source release changes. `pdi:audit` audits all in-scope candidates from live Vehicle Master and never publishes a headline.

### 5. What needs to happen to grow beyond a selected pilot

1. Human-verified typed promotion metadata: source, validity, retail scope, target trim, conditionality, time observed, stackability. Do not automatically convert untyped legacy campaign prices.
2. Review remaining CN and Japan selected-model MSRP, current retail trim sets and mixed-powertrain model conflicts. Do not invent trim coverage.
3. Explicit **verified-zero** source checks for models with no promotions. Lack of a promotion found is `UNKNOWN`.
4. Create frozen source and index snapshot storage (read models, not alternative MSRP truth tables), then daily/weekly runs and true universe coverage thresholds.
5. After a real market audit plus methodology sign-off, approve nationwide publishable headline; only then wire it to Dealership Toolkit. No merge/deploy from this draft PR now.

**Ethical/evidence constraint:** the attached pilot evidences show **advertised** prices and qualifying discount amounts, not actual invoice/dealer realized transaction prices. The OEM offer may change before 31 October; the research snapshot belongs to 11 October 2026 only.
