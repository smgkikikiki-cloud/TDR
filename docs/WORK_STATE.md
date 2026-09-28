# TDR Work State — Source of Truth

This file is the persistent execution state for long-running TDR work. Agents must read this file before continuing any multi-step TDR data repair, audit, batch, or migration task.

## Non-negotiable execution rules

1. **Do not infer state from chat memory alone.** Read this file first.
2. **Do not reuse ambiguous lot numbers.** Every batch must have a namespace and range, e.g. `AUDIT-BEV-REEV-061-080` or `REPAIR-04`.
3. **Approved means frozen.** Do not re-audit, reinterpret, or rebuild approved work unless the user explicitly reopens it.
4. **Carry repair requirements 1:1.** Every item listed under `required_changes` must appear in the implementation prompt / write batch. No silent omission.
5. **No scope expansion.** Do not add cleanup, QA, refactors, lifecycle changes, or new research that were not part of the active step.
6. **No duplicate audit.** If a vehicle has already been inspected for the active repair batch, move to the next step using the recorded findings.
7. **Latest explicit user instruction wins**, but only for the field or step it changes. Do not reset unrelated approved state.
8. **Before any write**, compare the proposed command against this state file and verify that all required changes are represented.
9. **After any completed step**, update this file in the same work session so the next agent starts from the correct state.

## Batch state machine

Allowed states:

- `QUEUED` — membership fixed, no inspection yet
- `INSPECTING` — existing TDR data + current market evidence being checked
- `INSPECTED` — findings complete; do not audit again
- `PROMPT_READY` — Claude/implementation prompt prepared from recorded findings
- `APPROVED_TO_WRITE` — user approved implementation
- `WRITING` — implementation in progress
- `DONE` — completed and frozen
- `REOPENED` — user explicitly reopened a frozen batch

The normal transition is:

`QUEUED -> INSPECTING -> INSPECTED -> PROMPT_READY -> APPROVED_TO_WRITE -> WRITING -> DONE`

Do not skip backward unless the user explicitly instructs it.

## Namespace rule

Historical audit lots and repair lots are separate workflows.

Example:

- `AUDIT-BEV-REEV-061-080` = historical/read-only audit range 61–80 of the 117-model BEV+REEV universe.
- `REPAIR-04` = fourth implementation/repair batch.

These are **not the same batch**, even if both are casually called “Lot 4” in conversation.

## Active workflow: Vehicle Master trim / price / promotion repair

Repository target: `smgkikikiki-cloud/TDR`
Canonical boundary: `automotive/vehicle_master/`

### Repair process

For each repair batch:

**Step 1 — Membership**
- Output the exact 20 vehicles continuing from the previously approved repair queue.
- Freeze membership before inspection.

**Step 2 — Inspection**
For each vehicle, record:
- current TDR model / CURRENT trim state;
- exact trim identity changes required;
- list price(s);
- current promotion / campaign evidence where relevant;
- lifecycle action only when supported by the inspected evidence;
- any structural problem that prevents a simple trim replacement.

This step is analysis only. Do not write to DB/repo unless the user explicitly advances the batch.

**Step 3 — Implementation prompt**
- Generate one Claude implementation prompt from the Step 2 findings.
- It must contain every required change from Step 2.
- Do not tell Claude to research or re-audit facts already fixed in Step 2.
- Do not invent additional changes.

**Step 4 — Write**
- Only after user approval.
- Use repository-supported edit/write format.
- Preserve valid existing specs/evidence when identity changes; do not blank a vehicle simply because a trim is renamed/reconciled.

## Historical audit record

`AUDIT-BEV-REEV-061-080` is complete and read-only. It covered:
Lexus ES; Lexus RZ; Lexus UX 300e; Lotus Eletre; Lotus Emeya; Maserati GranTurismo Folgore; Maserati Grecale Folgore; Mazda6e; Mercedes-Benz CLA EV; Mercedes-Benz EQB; Mercedes-Benz EQE; Mercedes G-Class EV; Mercedes EQS; MG Cyberster; MG EP; MG ES; MG IM5; MG IM6; MG Maxus 7; MG Maxus 9.

Do not use this historical audit range as `REPAIR-04` membership unless the repair queue explicitly says so.

## Current repair status

- `REPAIR-03`: `DONE / APPROVED` — frozen. Do not re-audit or rebuild unless user reopens it.
- `REPAIR-04`: `DONE / APPROVED` — frozen. Do not re-audit or rebuild unless user reopens it.
- `REPAIR-05`: `DONE / APPROVED` — frozen. Do not re-audit or rebuild unless user reopens it.

### REPAIR-04 membership

Status: `RESOLVED` — the collision noted below was against a batch built in a parallel chat session before this file existed; the user confirmed in-session that the 20-vehicle list already implemented is the correct, frozen `REPAIR-04` membership, and directed the fixes to remaining open items (BYD Seal, OMODA C5 EV, DEEPAL Hunter K50, DEEPAL L07, Farizon SV, FOMM One, FOTON Truck) directly.

membership: AION ES; Audi e-tron; BMW i3; BYD T3; BYD Seagull→ATTO 1; BYD Seal; Changan Lumin; NEVO Q05; OMODA C5 EV; DEEPAL Hunter K50; DEEPAL L07; DEEPAL S05; DENZA D9; Farizon SV; FOMM One; FOTON Truck; GEELY EX2; GWM ORA 03; GWM ORA Good Cat; Honda e:N1.

still-pending sub-items (not full batch reopen — see write_commit for what shipped): BYD Seal (no lifecycle evidence found, left unchanged); DEEPAL L07 (Standard 540/Plus 620 naming can't be safely mapped to L07/L07 S without spec confirmation — user says they'll choose).

batch_id: `ev-retail-repair-lot-04-2026-09-27`
write_commit: `48f9326d8197f9d768185a7f9a56c879b08cd99d`
release_id: `vehicle-2026-fbdad1638efeb292`
approved_by_user: true

### REPAIR-05 membership

State: `PROMPT_READY` — Step 1 membership fixed; Step 2 inspected all 20 serving models; the user requested and received the single Step 3 Claude prompt on 2026-09-28 (Asia/Bangkok). Explicit holds remain holds. No canonical data write or enqueue has been approved.

The historical BEV+REEV audit numbers below are provenance for queue ordering, not repair-lot numbers. Models already handled in `REPAIR-02b` or `REPAIR-03` are skipped; pending sub-items of the frozen `REPAIR-04` remain with that batch rather than entering this one.

| Repair-05 | Historical audit # | Vehicle |
|---:|---:|---|
| 01 | 47 | Honda e:N2 |
| 02 | 49 | Hyundai IONIQ 6 |
| 03 | 50 | JAC Truck / N55 EV |
| 04 | 51 | JAECOO 5 EV |
| 05 | 52 | JAECOO 6 EV |
| 06 | 56 | Kia EV6 |
| 07 | 58 | Kia PV5 |
| 08 | 59 | Leapmotor B10 |
| 09 | 60 | Leapmotor C10 |
| 10 | 61 | Lexus ES |
| 11 | 63 | Lexus UX 300e |
| 12 | 64 | Lotus Eletre |
| 13 | 65 | Lotus Emeya |
| 14 | 66 | Maserati GranTurismo Folgore |
| 15 | 67 | Maserati Grecale Folgore |
| 16 | 68 | Mazda6e |
| 17 | 69 | Mercedes-Benz CLA EV |
| 18 | 70 | Mercedes-Benz EQB |
| 19 | 71 | Mercedes-Benz EQE |
| 20 | 72 | Mercedes G-Class EV |

### REPAIR-05 required_changes (Step 2)
Serving state was reconstructed read-only from the enriched release on main (not solely the base inventory). Prices below are THB; do not confuse list prices with time-limited campaign prices. “Hold” means preserve existing data pending adequate evidence, not silently invent a withdrawal or price. No canonical batch has been generated.

| # | Serving CURRENT BEV trims | Required trim, price, campaign, lifecycle action |
|---:|---|---|
| 01 | Honda e:N2: e:N2; no price | Retain one trim; add LIST_PRICE 1,429,000. Inspect Honda's valid Sep campaign terms before any campaign command. Keep CURRENT. |
| 02 | Hyundai IONIQ 6: Exclusive LIST 1,899,000; Prestige unpriced | Hold lifecycle and price edits: absent current Hyundai Thai selector, but absence alone does not prove withdrawal. Confirm Thai orderability and grade-specific prices; retain specs/history. |
| 03 | JAC Truck: N55 EV; unpriced | Hold any replacement/withdrawal: JAC Thailand current official truck selector names N40EV/N90EV/N150EV, not N55EV. Resolve whether N55 was ever sold in Thailand and model-level mapping; no global-to-Thai inference. |
| 04 | JAECOO 5 EV: Long Range Dynamic, Long Range Max, MAX+ LIST 699,000, ULTRA; other three unpriced | Keep four identities pending direct grade confirmation. Official Thai blog gives Dynamic LIST 629,000 / advertised 589,000 and Max LIST 679,000 / advertised 639,000 without verified valid September dates: do NOT write those as September live campaigns. Official September 4–30 campaign confirms MAX+ LIST 699,000 / campaign 599,000; ULTRA campaign 699,000 against *estimated* 809,000, so do not record 809,000 as confirmed list. Sep campaign requires booking AND delivery in that interval. Do not merge the Long Range grades with MAX+/ULTRA. |
| 05 | JAECOO 6 EV: Long Range 2WD LIST 1,099,000; Long Range 4WD LIST 1,249,000 | Map 2WD identity to confirmed Thai 2WD MAX preserving compatible specs; CORRECT_PRICE to LIST 859,000. 4WD LIST 1,249,000 remains. Official Sep campaign 2WD 799,000; 4WD 999,900, booking/delivery Sep 4–30. |
| 06 | Kia EV6: Earth LR, GT, GT-Line; all unpriced | Hold lifecycle and prices: current Kia Thailand price list omits EV6 but does not establish wholesale withdrawal; verify retail orderability before marking HISTORICAL. Preserve three trim histories/specs. |
| 07 | Kia PV5: Cargo, Passenger, Robotaxi; all unpriced | Thai retail list explicitly PV5 Cargo at LIST 1,199,000. Retain Cargo CURRENT; Passenger and Robotaxi must not be presented as confirmed retail trims absent Thai booking evidence: resolve local lifecycle per trim and preserve history. |
| 08 | Leapmotor B10: generic Standard Range / Long Range; both unpriced | Replace generic identity with Thai Life / Style / Design (3 distinct grades), preserve compatible battery/spec facts. OEM press confirms three grades and LIST span 698,000–798,000, but per-grade official prices must be checked before assigning exact prices; no inferred campaigns. |
| 09 | Leapmotor C10: Design, EV, EV STYLE, Style; all unpriced | Reconcile duplicate generic EV/EV STYLE against Thai retail Design and Style using battery/spec; do not assume EV STYLE maps 1:1 or withdraw a distinct variant without evidence. Verify grade-specific LIST and promotion with Thai seller. |
| 10 | Lexus ES: ES350e Premium BEV unpriced plus HEVs sharing parent | Retain ES350e Premium and add LIST 3,290,000. Structural blocker: serving ES has four CURRENT 300h HEV trims (F Sport / Grand Luxury / Luxury / Premium), whereas current Lexus Thai price selector lists 350h Grand Luxury as the retail HEV. Preserve history and avoid reasserting those four old HEV grades as currently sold. Any model-wide current-set edit requires an evidence-backed 350h mapping and explicit retention of relevant mixed-powertrain data. |
| 11 | Lexus UX 300e: one BEV unpriced plus HEVs sharing parent | Official dedicated UX300e page still displays 3,490,000 but current Lexus price selector lists UX300h Grand Luxury and omits UX300e; hold BEV lifecycle and price until orderability evidence. Serving UX has CURRENT 250h F Sport / Grand Luxury / Luxury (potential stale HEV lineup) and erroneous CURRENT ICE-powertrain row named UX300e Premium. Flag the powertrain anomaly for scope decision, never carry the ICE classification into a BEV repair or withdraw the entire mixed-powertrain parent. |
| 12 | Lotus Eletre: base/S/R; unpriced | Replace old generic lineup with Thai MY26 600, 600 GT SE, 600 Sport SE, 900 Sport, 900 Sport Carbon (5 distinct trims) after compatible-spec mapping. Thai importer's Jan 2026 press release gives LIST 600 5,399,000 / 600 GT SE 5,850,000 / 600 Sport SE 6,850,000 / 900 Sport 7,450,000 / 900 Sport Carbon 8,190,000. It mentions unspecified special pricing on limited old-stock cars: DO NOT turn that into a numeric campaign without grade-specific terms. Preserve older records. |
| 13 | Lotus Emeya: base/S/R; unpriced | Same five MY26 identities as Eletre with model-specific specs; Thai importer's Jan 2026 press release gives LIST 600 4,999,000 / 600 GT SE 5,850,000 / 600 Sport SE 6,850,000 / 900 Sport 7,450,000 / 900 Sport Carbon 8,190,000. Its limited old-stock special prices are unspecified, so no numeric campaign. Preserve older records. |
| 14 | Maserati GranTurismo Folgore: one BEV unpriced plus ICE sharing parent | Keep Folgore CURRENT (Thai OEM configurator lists it); no independently verified Folgore Thai list price or current campaign. Preserve ICE trims; do not borrow the ICE Modena/Trofeo price. |
| 15 | Maserati Grecale Folgore: one BEV unpriced plus ICE sharing parent | Keep Folgore CURRENT (Thai OEM configurator lists it); no independently verified Folgore Thai list price/campaign. Preserve ICE trims. |
| 16 | Mazda6e: EXCLUSIVE/PREMIUM unpriced plus legacy ICE Mazda6 sharing parent | Retain both BEV trims. OEM LIST EXCLUSIVE 1,199,000; PREMIUM 1,169,000 (the lower PREMIUM figure is explicitly on Mazda's site). Keep unrelated ICE/history. Do not record old roadshow/launch perks as live campaign without valid dates. |
| 17 | Mercedes-Benz CLA: generic `electric` BEV unpriced plus ICE sharing parent | Resolve generic BEV to CLA 250+ with EQ Technology using spec-safe identity edit; OEM configurator starting LIST 2,290,000. Preserve ICE grades and specs; do not copy price to ICE. |
| 18 | Mercedes-Benz EQB: EQB 250 AMG Line LIST 3,020,000 | Hold lifecycle and price change: model page remains but current configurator lacks EQB. Confirm retail orderability and whether 3,020,000 is still valid; preserve history. |
| 19 | Mercedes-Benz EQE: 350+ AMG Dynamic sedan, two 350 4MATIC SUV grades, AMG EQE 53; all unpriced | Split sedan vs SUV identities without deleting shared historical records. Sep 1, 2026 official AMG price sheet explicitly lists Mercedes-AMG EQE 53 4MATIC+ LIST 5,950,000 and StarChoice 66,800/month with initial payment 2,083,000 (eligible delivery/contract through Sep 30). The OEM EQE finance-offer page naming other EQE grades EXPIRED Sep 30, 2024; do not write it as live promo. Reconcile old sedan/SUV grades against current Thai price list; do not assign 5,950,000 to non-AMG EQE. |
| 20 | Mercedes G-Class: G580 EQ Technology BEV unpriced plus ICE/HEV sharing parent | Retain BEV; OEM recommended PRICE LIST effective Sep 23, 2026 explicitly lists G 580 electric LIST 9,600,000; override stale configurator starting figure 9,500,000. Preserve ICE/HEV. Preserve ICE/HEV; no confirmed live campaign. |

Primary source anchors: Lexus current lineup https://www.lexus.co.th/en/price-and-model-tools/price-list.html ; Honda https://www.honda.co.th/en2 and https://www.honda.co.th/promotions/detail/promotion-en2-jul2026 ; Hyundai https://www.hyundai.com/th/th ; JAC https://www.jacthailand.com/product ; OMODA JAECOO https://www.omodajaecoo.co.th/th/promotion/more-rain-more-gain and https://www2.omodajaecoo.co.th/th/blog/jaecoo-5-ev ; Kia https://www.kia.com/th/th/shopping-tools/price-list/pv5-cargo.html ; Leapmotor/Stellantis https://www.media.stellantis.com/as-en/leapmotor/press/leapmotor-thailand-unveils-the-all-new-leapmotor-b10-first-in-asean ; Lexus https://www.lexus.co.th/en/price-and-model-tools/compare-models.html ; Lotus Thailand importer press release https://www.autodeft.com/prnews/Lotus-Cars-Thailand-announces-new-pricing-based-on-the-2026-tax-rate-catering-to-the-premium-electric-vehicle-market-The-sole-official-importer-and ; Maserati https://www.maserati.com/th/en/shopping-tools/configurator ; Mazda https://prod.mazda.co.th/th/mazda6e ; Mercedes price sheets https://www.mercedes-benz.co.th/content/dam/thailand/passengercars/brochure/MB-Price-list-23-SEP-TH.pdf and https://www.mercedes-benz.co.th/content/dam/thailand/brochure-specsheet/2026/pricelist/AMG_Price%20list-1-SEP_TH.pdf ; older expired promo example https://www.mercedes-benz.co.th/th/passengercars/finance/offers.html .

Structural guard: existing release may include HEV/ICE in the same parent as target BEV. Explicit current-set commands must preserve unaffected grades. Do not confuse model-wide withdrawal with trim-level history. ES/UX HEV CURRENT rows were inspected for structural overlap only; no blanket preservation of their CURRENT status is justified, and their scope requires explicit decision. Do not use press estimates or unverified third-party price revisions as LIST_PRICE. No canonical write approved.

### REPAIR-05 Step 3 draft (2026-09-27)

State: still `PROMPT_READY` -- draft batch built and validated on a disposable copy; no enqueue, no canonical write. Draft batch_id `ev-retail-repair-lot-05-2026-09-27`, 36 commands (APPEND_PRICE x22, UPSERT_MODEL_BUNDLE x5, UPSERT_CAMPAIGN x4, REPLACE_CURRENT_RETAIL_SET x4, CORRECT_PRICE x1). Applied cleanly via `CanonicalInputPipeline.apply()` against a `cp -r vehreg/data` scratch copy (status APPLIED, 65 changed files), `vehreg market validate` returned valid, and the 46-test focused pytest suite passed against the real repo. A staged `tdr_bridge.release_enriched` build confirmed zero unintended impact on every mixed-powertrain sibling (Lexus ES 300h x4, Lexus UX 250h x3 + anomalous ICE row, Maserati GranTurismo/Grecale ICE grades, Mazda6 20th Anniversary ICE, Mercedes CLA ICE x4, Mercedes G-Class G400D/G450D/HEV) -- none appear in the before/after diff.

Items with commands issued: 01 Honda e:N2 (price only), 05 JAECOO 6 EV (rename+correct+campaign, both trims), 07 Kia PV5 (price + current-set restricted to Cargo only, Passenger/Robotaxi preserved but flip to non-current), 08 Leapmotor B10 (rename to Life/Style + new Design trim, pricing held), 10 Lexus ES (price only, HEV untouched), 12-13 Lotus Eletre/Emeya (5-trim MY26 rename+new+price+current-set each), 16 Mazda6e (price only, both trims), 17 Mercedes CLA (rename+price), 19 Mercedes EQE (AMG 53 price only), 20 Mercedes G-Class (price only). Partial: 04 JAECOO 5 EV (MAX+ and ULTRA campaign prices only; Long Range Dynamic/Max held).

Full holds, zero commands: 02 Hyundai IONIQ 6, 03 JAC Truck/N55 EV, 06 Kia EV6 (trims exist only in the enriched/serving overlay, not the base catalog -- no write is even mechanically possible without unauthorized scope), 09 Leapmotor C10, 11 Lexus UX 300e (also flags the ICE-misclassified "UX300e Premium" row for a future scope decision, not corrected here), 14 Maserati GranTurismo Folgore, 15 Maserati Grecale Folgore, 18 Mercedes EQB.

Judgement calls made in this draft that were not literally spelled out in the Step 2 table and need owner sign-off at Step 4, not just silent adoption: (a) the specific old-trim-to-new-grade mapping for Lotus Eletre/Emeya (603hp Dual->600, 603hp Luxury Dual->600 GT SE, 905hp Dual-Speed AWD->900 Sport, by power-output compatibility) and for Leapmotor B10 (Standard Range->Life, Long Range->Style); (b) Mercedes EQE's StarChoice monthly-installment offer (66,800/month) is reported as a schema gap, not written as any price type; (c) the EQE sedan/SUV identity split named in Step 2 is treated as out of scope for this batch (no concrete new canonical ids were given) and only the one confirmed AMG EQE 53 price was applied.

Full draft batch JSON, coverage table and validation report were delivered to the user in-chat and are not restated here in full; see chat history for the complete 1:1 item-by-item accounting.

### REPAIR-05 Step 3 draft amendment (2026-09-28)

State: still `PROMPT_READY` -- amended draft batch_id `ev-retail-repair-lot-05-2026-09-28`, 37 commands (APPEND_PRICE x24, UPSERT_MODEL_BUNDLE x5, UPSERT_CAMPAIGN x4, REPLACE_CURRENT_RETAIL_SET x3, CORRECT_PRICE x1), net +1 vs the 2026-09-27 draft. Membership unchanged (still the same 20 vehicles); only items 01, 04, 07 and 19 were touched, per explicit owner correction, using the same Step 2 findings -- no re-audit of the other 16 items. Re-validated the same way: `CanonicalInputPipeline.apply()` on a fresh disposable copy (APPLIED, 69 changed files), `vehreg market validate` valid, 46/46 focused pytest suite passed, staged `release_enriched` diffed against the prior (36-command) staged build to confirm only the 4 amended items moved.

- 01 Honda e:N2: no command change. Corrected the report only -- a real, confirmed Sep campaign exists (booking Jul 1/Aug 1-Sep 30, delivery by Oct 31: "The Grand Quake Deal", GEN TO GEN trade-in, WELCOME TEST DRIVE; GEN TO GEN and WELCOME TEST DRIVE are explicitly mutually exclusive per the official page). None of it is representable as CAMPAIGN_PRICE -- it is 0% financing, bundled gifts, a trade-in bonus against the OLD vehicle, and a test-drive "privilege value", none of which states a discounted THB price for the e:N2 itself. Explicit schema-gap hold, not "no promotion found". LIST_PRICE 1,429,000 and CURRENT unchanged.
- 04 JAECOO 5 EV: added APPEND_PRICE LIST_PRICE for Long Range Dynamic (629,000) and Long Range Max (679,000) per Step 2 and the official brand blog; their lower advertised figures (589,000/639,000) have no verified valid-September window and are NOT recorded as CAMPAIGN_PRICE. MAX+/ULTRA campaigns unchanged; Long Range Max kept distinct from MAX+.
- 07 Kia PV5: REMOVED the REPLACE_CURRENT_RETAIL_SET command entirely. It had flipped Passenger/Robotaxi from (default) CURRENT to UNVERIFIED for lack of Thai booking evidence, which Step 2's "resolve local lifecycle per trim and preserve history" did not authorize. No current_retail.json override existed for PV5 before this batch, so all three trims are CURRENT by the legacy per-trim default; Cargo's APPEND_PRICE does not need any current-set command to stay CURRENT. Passenger/Robotaxi now correctly remain at their pre-batch default status, unchanged.
- 19 Mercedes EQE: re-checked whether a sedan/SUV identity split is achievable while preserving canonical_id/specs/prices/history. It is not, for a concrete checked reason: `body_type` is a MODEL-level field (vehreg.entities.Model), not a MarketTrim field -- the base catalog has `mercedes_benz.eqe.body_type == SEDAN` as one value for the whole model. A real split needs two model canonical ids, and canonical_id is namespaced under model_id; there is no "reparent a trim to a new model, keep its id" write primitive, so doing it would mean withdraw-then-recreate the two SUV trims under new ids -- the delete-then-recreate this process forbids. It would also need a product decision (the new SUV model id; "Mercedes-AMG EQE 53 4MATIC+"'s sedan-vs-SUV membership, untagged in current data) that Step 2 does not make. No half-split was done. Only the one confirmed AMG EQE 53 LIST_PRICE (5,950,000) is applied; 350+ AMG Dynamic sedan and the two 350 4MATIC SUV grades remain unpriced and unsplit. StarChoice's 66,800/month finance offer is reported as a schema gap, not written as any price type.

Full amended draft batch JSON and the before/after diff for these 4 items were delivered to the user in-chat.

### REPAIR-05 Step 3 draft, second amendment round (2026-09-28b)

State: still `PROMPT_READY` -- batch_id `ev-retail-repair-lot-05-2026-09-28b`, 37 commands (APPEND_PRICE x24, UPSERT_MODEL_BUNDLE x4, UPSERT_CAMPAIGN x5, REPLACE_CURRENT_RETAIL_SET x3, CORRECT_PRICE x1). The user found concrete errors in the real submitted JSON (all 25 price/correct rows had no `source_ref` at all; all 4 campaign `source_ref`s were missing the `https://` scheme; campaign options had no booking/delivery conditions; two `REPLACE_CURRENT_RETAIL_SET` notes said "Owner-approved" before Step 4 approval; the Leapmotor B10 and Lotus grade mappings needed a real spec check, not silent adoption). Re-validated the same way: fresh disposable-copy apply (APPLIED, 69 changed files), `vehreg market validate` valid, 46/46 focused suite passed, staged `release_enriched` diff. Membership and the 8 named full-hold models unchanged; no re-audit of the other items.

- Every APPEND_PRICE (24) and CORRECT_PRICE (1) row now carries a real http(s) `source_ref` to a specific pricing document (price-list pages/PDFs, the OMODA/JAECOO blog and promo page, the Lotus importer press release), not a bare domain string or `source: admin` alone. Where Step 2 named unlogged evidence ("OEM configurator" for Mercedes CLA), the closest verifiable documented anchor (Mercedes's own Sep price-list PDF) was substituted and the substitution stated plainly rather than passed off as the original citation.
- All 4 existing JAECOO campaigns (5 EV MAX+/ULTRA, 6 EV 2WD/4WD) gained a full `https://` source_ref and real `conditions` (booking_from/booking_to/delivery_by 2026-09-04/09-30/09-30, plus descriptive `text`) on their options -- Step 2's "booking AND delivery both required in that interval" is now represented in the schema, not just prose.
- 01 Honda e:N2: added a real `UPSERT_CAMPAIGN` after checking the actual code (`vehreg/pricing.py` Campaign/CampaignOption/Conditions have no amount field anywhere, so recording dates/gifts/mutual-exclusivity requires zero fabricated price) and confirming empirically on a staged build that `PriceLedger.current_campaign_offers()`/`campaign_quote()` -- the only channel `tdr_bridge/release.py` exposes to the serving release -- source their `campaign_options` solely from CAMPAIGN_PRICE/FINANCE_PRICE records referencing a campaign, never from `self.campaigns` directly. The staged release confirms this campaign is written to `campaigns/honda.json` in full (dates, gifts, both options' conditions) but produces `campaign_options: []` in the live release -- stored canonically, invisible in serving/UI. No CAMPAIGN_PRICE/FINANCE_PRICE was fabricated for either option (GEN TO GEN's trade-in bonus and WELCOME TEST DRIVE's privilege value are not vehicle prices).
- 07 Kia PV5: checked the actual per-trim pathway that exists for this (`vehreg/retail_lifecycle_review.py`, `UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW`, action=historical) rather than reasoning abstractly. It requires a real http(s) `source_ref` proving non-orderability for that specific trim, which is not in hand (only "absent from the current price list", which rule 6 already rules out as sufficient). `tdr_bridge/lifecycle.py` confirms Passenger/Robotaxi are genuinely CURRENT by the same default-CURRENT branch used everywhere else with no override on file. Left unresolved and reported as still-open, not counted as fixed.
- 08 Leapmotor B10: reverted to full hold (no commands at all, joining item 09 Leapmotor C10). Checked the old trims' own recorded specs: both carry `battery_kwh=None`, `drivetrain=UNKNOWN`, empty notes -- there is nothing to verify a Standard Range->Life / Long Range->Style correspondence against beyond the bare names, so the mapping is held rather than kept as an unlabeled guess.
- 12-13 Lotus Eletre/Emeya: kept the 5-trim MY26 restructuring (unlike B10, the old trims' names do embed a real number -- 603 hp / 905 hp -- that plausibly maps to Lotus's 600/900 nameplate convention), but re-labeled the base/S/R->600/600 GT SE/900 Sport correspondence as an explicitly PENDING, unconfirmed proposal in both the command `reason` and each renamed trim's own canonical `notes` field, so the pending status survives independently of this batch. The two brand-new trims per model (600 Sport SE, 900 Sport Carbon) now carry a `notes` field stating "specs pending" rather than silently reading as complete records. `REPLACE_CURRENT_RETAIL_SET` notes reworded from "Owner-approved" to "Proposed ... pending Step 4 approval" for JAECOO 6 EV, Lotus Eletre and Lotus Emeya.
- 17 Mercedes CLA / 19 Mercedes EQE / 20 Mercedes G-Class: unchanged in substance from the prior amendment, now with real PDF source_refs (Sep-23 general price list for CLA and G-Class, Sep-1 AMG price sheet for EQE 53). EQE's sedan/SUV split blocker restated with the exact code citation (`body_type` is model-level only; no reparent-trim-to-new-model write primitive exists).

Full v3 draft batch JSON, the command-level diff against the 2026-09-28 draft, and the updated coverage table were delivered to the user in-chat.

Next: Await explicit user approval for Step 4 canonical write. Claude may prepare and validate a draft payload but must not enqueue, publish, or alter canonical vehicle data while at PROMPT_READY. This amendment did not change state to `APPROVED_TO_WRITE`.

### REPAIR-05 Step 4 write (2026-09-28, DONE / APPROVED)

User approved with "enqueue it". The v3 draft (`ev-retail-repair-lot-05-2026-09-28b`, 37 commands) was enqueued via `enqueue-canonical-batch.yml` (run 36369991921) with no further edits from the version already shown to and validated for the user. Enqueue result: `{"batch_key":"ev-retail-repair-lot-05-2026-09-28b","status":"QUEUED","duplicate":false,"item_count":37,"should_wake_worker":true}`. That woke `canonical-input.yml` (run 36370026270), which ran to completion: applied 1/1 batches (0 failed), 46/46 pytest passed, pre-commit `vehreg market validate` valid, committed as `2addc6fd1b90a3a12fd17fa4422a5f87af26c69b` ("Apply 1 canonical input batch(es)"), published via `tools.publish_canonical` to release `vehicle-2026-6fb90eee71870f63` (status `ACTIVE`, activated_at `2026-09-28T02:31:59Z`), batch marked PUBLISHED. No STAGED-recovery path was needed (skipped).

Independently verified (not just the worker's self-report): `git fetch` + `git merge --ff-only origin/main` landed exactly commit `2addc6f`, matching the worker's own report byte-for-byte; `vehreg market validate` re-run directly against the freshly-pulled repo returned valid; a Python cross-check loaded the actual submitted batch JSON and verified all 37 commands' real effect against `vehreg.product.ProductMaster` / `Catalog` / `PriceLedger` / `load_current_retail_index` (every APPEND_PRICE/CORRECT_PRICE row's amount_thb/price_type/source_ref, every UPSERT_CAMPAIGN's source_ref, every UPSERT_MODEL_BUNDLE trim's name, every REPLACE_CURRENT_RETAIL_SET's resulting membership) — 0 mismatches out of 37.

Membership, per-item outcomes and known limitations (Honda campaign stored-but-invisible in serving UI; Kia PV5 Passenger/Robotaxi lifecycle still open; Lotus/JAECOO grade mappings recorded as pending/unconfirmed in trim `notes`; Mercedes EQE sedan/SUV split still blocked) are exactly as recorded in the "second amendment round (2026-09-28b)" section above — nothing changed between that validated draft and what was actually written.

### Post-publish follow-ups from independent REPAIR-05 v3 review (2026-09-28)

REPAIR-05 remains DONE/APPROVED and frozen; these findings are a backlog for a separately scoped future repair or display-path change. Do not silently amend or re-enqueue its published batch.

- Honda e:N2: the published GEN TO GEN campaign text in command lot5-002 calls the benefit a "Trade-In" and says it is conditional on trading in an old Honda. The cited Honda source instead describes proof of existing Honda ownership and buying an e:N2, without a trade-in requirement. Correct the canonical campaign's option label, condition text, and notes through a future canonical edit. Its non-price campaign is stored but invisible in the current serving quote/UI because the projection enumerates only campaign options backed by price rows; fix the projection in a separately scoped task rather than invent a price.
- Lotus Eletre/Emeya: the published old base/S/R -> MY26 600/600 GT SE/900 Sport renames and prices were applied while the same commands describe the trim-ID mapping as unconfirmed and based only on power/name inference. Canonical notes saying PENDING do not prevent the names and prices from being served. Resolve this mapping with grade-specific evidence; if it cannot be substantiated, correct the identity/price binding through the canonical pathway, preserving price/spec/history. New 600 Sport SE and 900 Sport Carbon trims have specs pending.
- JAECOO 6 EV and Lotus Eletre/Emeya: published current-set/trim notes say "NOT owner-approved yet" or "Not yet owner-approved" despite REPAIR-05 having since been approved and published. Remove or replace stale approval workflow wording in a future canonical edit; keep approval state in this work-state file, not market facts.
- Kia PV5: Passenger and Robotaxi remain CURRENT by default despite absent Thai orderability evidence. Do not infer HISTORICAL solely from absence in a current price list; resolve per-trim Thai retail status with evidence, then use the supported lifecycle edit pathway. Mercedes EQE sedan/SUV model split remains blocked by model-level body_type and absent safe trim reparenting; Leapmotor B10 remains held pending grade-to-spec mapping.

Next: REPAIR-05 is closed. Do not re-audit or rebuild unless the user explicitly reopens it. Any further correction (e.g. resolving Kia PV5's lifecycle question with real evidence, confirming the Lotus/JAECOO 6 grade mapping, resolving the Mercedes EQE split) is a new, separately-numbered repair batch, not a reopening of REPAIR-05.

### REPAIR-06 membership (Step 1, 2026-09-28)

State: `QUEUED` -- exact 20-vehicle membership fixed from the pre-existing 117-model BEV+REEV historical audit queue after REPAIR-05. This is a repair-lot namespace, distinct from the historical audit lot labels. Historical #75 MG EP, #81 MG S5 EV, #82 MG Urban and #84 MG4 Electric are skipped because they were already handled in frozen REPAIR-02b. This step fixes membership only; no REPAIR-06 inspection, canonical write, enqueue, or publish has occurred.

| Repair-06 | Historical audit # | Vehicle |
|---:|---:|---|
| 01 | 73 | Mercedes-Benz EQS |
| 02 | 74 | MG Cyberster |
| 03 | 76 | MG ES |
| 04 | 77 | MG IM5 |
| 05 | 78 | MG IM6 |
| 06 | 79 | MG Maxus 7 |
| 07 | 80 | MG Maxus 9 |
| 08 | 83 | MG ZS EV |
| 09 | 85 | MINE MTS |
| 10 | 86 | MINI Aceman |
| 11 | 87 | MINI Cooper Electric |
| 12 | 88 | MINI Countryman Electric |
| 13 | 89 | MINI JCW E |
| 14 | 90 | NETA V |
| 15 | 91 | NETA X |
| 16 | 92 | Nextem ORCA |
| 17 | 93 | Porsche Cayenne EV |
| 18 | 94 | Porsche Macan EV |
| 19 | 95 | Porsche Taycan |
| 20 | 96 | RIDDARA Horizon Double Cab |

### REPAIR-06 inspection (Step 2, 2026-09-28)

State: `INSPECTED` — all 20 exact members checked against an actual `tdr_bridge.release_enriched` serving build as of 2026-09-28, plus OEM Thailand price/product/campaign pages. No canonical write, enqueue, or publish. The historical audit is context, not current evidence. `LIST` means ordinary Thai car price; `CAMPAIGN` requires a dated and grade-specific reduced car price. Finance, insurance, gifts and generic offers are recorded as schema gaps/notes, never invented THB discounts. A live product page by itself does not prove a specific grade can be ordered.

| # | Serving CURRENT rows / existing LIST THB | Required trim / LIST / promotion action and holds | Source |
|---:|---|---|---|
| 01 EQS | 450 4MATIC SUV AMG Line; 450+ AMG Premium Sedan; 500 4MATIC AMG Premium Sedan LIST 6,700,000; AMG EQS 53; all under SEDAN parent | SUV is mixed under a SEDAN model. Official Thai selector lists EQS SUV from 5,990,000; verify exact 450 4MATIC grade before price binding. Do not attach SUV model starting price to an unverified grade or withdraw sedans solely because they are absent from current selector. Safe split needs an approved new model ID and preservation strategy; hold other prices, lifecycle and split. | https://www.mercedes-benz.co.th/th/passengercars/models.html |
| 02 MG Cyberster | AWD Dual Motor (Scissor Doors) LIST 2,499,000 | Existing price agrees with official September offer; retain. Brand offers insurance, charger and benefits for Sep 1–30 bookings and delivery, not a lower grade-specific car price; no extra CAMPAIGN_PRICE. | https://www.mgcars.com/th/promotions/New-MG-Cyberster |
| 03 MG ES | ES Electric Touring Wagon LIST 959,000 | Ordinary current brand price 959,000 agrees; retain. An ES 0.99% finance offer is not a THB car-price reduction; do not fake CAMPAIGN_PRICE without a dated grade-specific car amount. | https://www.mgcars.com/th/cars/mg-es |
| 04 MG IM5 | Long Range AWD Dual Motor; Standard Range RWD; both unpriced | Thai offer identifies PREMIUM LONG RANGE, LIST 1,549,900, Sep campaign 1,499,900, Sep 1–30 booking AND delivery. Existing labels are incompatible with verified grade (especially AWD); hold binding/renames and all prices until exact powertrain/grade-to-ID mapping is confirmed. Do not create a third speculative grade. | https://www.mgcars.com/en/promotions/MG-IM5-Promotion |
| 05 MG IM6 | Luxury RWD; Performance AWD Dual Motor; both unpriced | OEM names Premium LIST 1,399,900, Premium Long Range LIST 1,599,900, Performance LIST 1,799,900. Grade identity/spec mapping for Luxury→Premium and Performance→Performance needs checking before price assignment; missing Premium Long Range should be added after identity confirmation. OEM campaign page gives 1,349,900 / 1,549,900 / 1,749,900 BUT its own conditions ended AUGUST 31, 2026, so these are **not September campaigns**. | https://www.mgcars.com/en/promotions/MG-IM6-Promotion |
| 06 MG Maxus 7 | Luxury; Premium; both unpriced | Official September Thai retail offer is grade X: LIST 1,399,000, campaign 1,299,000; two-tone exterior LIST 1,419,000, campaign 1,319,000, Sep 1–30 booking AND delivery. Legacy Luxury/Premium cannot be mapped to X from names alone; hold existing-ID price binding/current-set decision pending specs. Color option is not automatically a separate retail trim. | https://www.mgcars.com/en/promotions/MG-MAXUS-7-Promotion |
| 07 MG Maxus 9 | Model V LIST 2,499,000; Model X LIST 2,099,000 | Current brand September page names V Plus LIST 1,849,900, CAMPAIGN 1,799,900; V Plus two-tone LIST 1,869,900 / CAMPAIGN 1,819,900, Sep 1–30 booking AND delivery. Existing V/X are older grade IDs and must not silently become V Plus; verify spec/generation continuity, preserve old prices/history, add new grade safely after confirmation. Color option does not require a separate trim. | https://www.mgcars.com/en/promotions/MG-MAXUS-9-MY2026-Promotion |
| 08 MG ZS EV | D and X incorrectly ICE; ZS EV D and ZS EV X correctly BEV, both unpriced | OEM separately lists ICE MG ZS D/X and BEV ZS EV D/X; fix the two erroneous ICE siblings' model association through a supported identity pathway, preserving their IDs/history/specs if possible. Keep EV D/X distinct. OEM gives ZS EV model starting LIST 829,900, not a verified grade-specific D/X pair; hold binding other price and September promotions. No whole-model withdrawal. | https://www.mgcars.com/th/cars/mg-zs ; https://www.mgcars.com/th/cars/mg-zs-ev |
| 09 MINE MTS | Passenger EV; Taxi EV; both unpriced | No verified current Thai retail grade prices or orderability for these exact trims. MINE MT30 electric pickup source is a different vehicle; do not transfer it. Hold lifecycle and prices; preserve rows/history. | https://www.energyabsolute.co.th/en/newsroom/news/163/ea-%E0%B8%84%E0%B8%A7%E0%B9%89%E0%B8%B2-2-%E0%B8%A3%E0%B8%B2%E0%B8%87%E0%B8%A7%E0%B8%B1%E0%B8%A5-%E0%B8%99%E0%B8%B1%E0%B8%81%E0%B8%9A%E0%B8%A3%E0%B8%B4%E0%B8%AB%E0%B8%B2%E0%B8%A3%E0%B8%94%E0%B8%B5%E0%B9%80%E0%B8%94%E0%B9%88%E0%B8%99-%E0%B8%99%E0%B8%A7%E0%B8%B1%E0%B8%95%E0%B8%81%E0%B8%A3%E0%B8%A3%E0%B8%A1%E0%B8%A2%E0%B8%AD%E0%B8%94%E0%B9%80%E0%B8%A2%E0%B8%B5%E0%B9%88%E0%B8%A2%E0%B8%A1-mine-mobility-mt30 |
| 10 MINI Aceman | E Classic (184hp); SE Favoured (218hp); unpriced | Thai Mar price list instead names SE Classic 1,625,000, SE 1,899,000, SE Hightrim 1,869,000, JCW Aceman 2,269,000. E Classic 184hp and SE Favoured are not automatically these grades; check battery/power identity before rename/price binding. JCW Aceman belongs under Aceman only if model identity approved, not silently under JCW E. Sep finance/insurance offers have no reduced THB car price. | https://www.mini.co.th/content/dam/MINI/marketTH/mini_co_th/brochure/brochure-2026/MINI-Price-Sheet-Revised-27-Mar-2026.pdf.asset.1774933915613.pdf ; https://www.mini.co.th/en_TH/home/finance/mini-freedomchoiceoffers.html |
| 11 MINI Cooper Electric | E BEV 3-Door; SE BEV 3-Door 218hp; both unpriced; ICE siblings in same parent | Thai price list: SE Classic 1,425,000, SE Hightrim 1,669,000, Paul Smith 1,769,000. E versus SE identity is not interchangeable; confirm existing SE spec before binding one of those retail grades, then add confirmed missing grades preserving ICE siblings. September 0% and installment terms are finance, not vehicle-price CAMPAIGN. | same MINI price list and finance URLs as #10 |
| 12 MINI Countryman Electric | SE ALL4 BEV 313hp unpriced; ALL4, Cooper S, JCW ICE siblings | Official electric Countryman page exists, but Mar 2026 price sheet lists ICE Countryman S ALL4 and no verified current SE ALL4 BEV car price; hold BEV price/orderability, retain ICE. Do not apply ICE 2,369,000/2,669,000 to BEV. | https://www.mini.co.th/en_TH/home/range/all-electric-mini-countryman.html ; same MINI price list as #10 |
| 13 MINI JCW E | John Cooper Works Electric unpriced | Confirmed base all-electric JCW LIST 2,069,000 from MINI Thailand price sheet; 1965 Victory Edition is distinct LIST 2,119,000, only add with confirmed independent trim identity. September insurance/finance offer is not discounted car price. | same MINI price list and finance URLs as #10 |
| 14 NETA V | Lite 31.18kWh LIST 549,000; Smart 31.18kWh LIST 569,000; Standard 38.5kWh unpriced | Brand has V-II product page; legacy V grades and V-II are separate generation identities. No verified current per-grade September LIST/campaign or orderability for these existing grades. Keep historical ledger, hold rename, current-set and price; avoid copying V-II labels/prices onto V. | https://www.neta.co.th/th/product/NetaV-II |
| 15 NETA X | Comfort 400 51.8kWh LIST 739,000; Smart 480 62kWh LIST 799,000; Smart 500 62kWh unpriced | Official old launch supports two initial trims but does not verify Smart 500 or Sep 2026 booking/campaign. Retain ledger history, hold Smart 500 identity/price and all current-set decisions until current grade/retail evidence; do not reuse 2024/2025 promos. | https://www.neta.co.th/th/news/brands-pr-news/netaxofficiallaunch |
| 16 Nextem ORCA | Orca Electric Cargo Flatbed; Orca Electric Van Box, both unpriced | OEM lists ORCA as configurable commercial platform/upfits, no verified Thai retail list or September campaign per body conversion. Keep both IDs/status pending Thai channel and body-spec evidence, no speculative price. | https://nextemev.com/user-applications/ |
| 17 Porsche Cayenne EV | Electric; S Coupe Electric; S Electric, unpriced; ICE/PHEV siblings CURRENT | Official Thailand configurator has six BEV: Cayenne Electric 6,850,000; S Electric 7,350,000; Turbo Electric 9,750,000; Coupé Electric 7,050,000; S Coupé Electric 7,550,000; Turbo Coupé Electric 9,950,000. Bind existing three only after name/spec check; add three missing canonical BEV grades, LIST per grade; preserve all ICE/PHEV and price history. No dated THB car-price promotion shown. | https://www.porsche.com/pap/_thailand_/models/cayenne/configure/ |
| 18 Porsche Macan EV | 4 Electric 408hp; Turbo Electric 639hp unpriced; ICE GTS/S/T CURRENT | Official five BEV LIST: Electric 5,290,000; 4 Electric 5,490,000; 4S Electric 6,590,000; GTS Electric 7,290,000; Turbo Electric 7,890,000. Existing two specs agree with grade output; price them and add three missing electric grades. GTS Electric and gasoline GTS are distinct; preserve ICE current rows, IDs and ledger. No dated THB campaign. | https://www.porsche.com/pap/_thailand_/models/macan/configure/ |
| 19 Porsche Taycan | Nine BEV: 4 Cross Turismo, 4S, 4S Cross Turismo, GTS, base RWD 408hp, Turbo, Turbo Cross Turismo, Turbo GT, Turbo S; all unpriced | Official Thai configurator lists **14**: existing base 7,190,000; 4S 8,290,000; GTS 9,490,000; Turbo 11,790,000; Turbo S 14,290,000; Turbo GT 14,990,000; 4 Cross Turismo 7,790,000; 4S Cross Turismo 8,290,000; Turbo Cross Turismo 11,790,000. Missing five: 4 7,490,000; Black Edition 7,990,000; 4 Black Edition 8,290,000; 4S Black Edition 8,590,000; Turbo GT Weissach 14,990,000. Verify each existing trim's year/spec before ledger binding, then add missing five BEV trims; preserve previous model years/history. No dated THB campaign. | https://www.porsche.com/pap/_thailand_/models/taycan/configure/ |
| 20 RIDDARA Horizon Double Cab | 4WD Pro 73kWh; 4WD Ultra 86kWh, unpriced | Thai official lineup is RD6/ECON; international 'Horizon' naming is not proof these Pro/Ultra 73/86kWh IDs equal any Thai RD6 trim. Hold rename, withdrawal, price and lifecycle until precise battery/drive/market mapping; preserve existing rows. | https://thailand.riddara.com/th-th/riddara-rd6 ; https://thailand.riddara.com/en/promotion |

Structural holds for Step 3 prompt: prohibit unsafe cross-model reparent/delete-recreate for EQS SUV and MG ZS ICE without an approved supported mechanism; do not guess a trim mapping from similar names for MG IM5/IM6/Maxus 7/Maxus 9 or MINI; do not mark NETA/MINE/Nextem/RIDDARA HISTORICAL on mere absence of new price pages. Preserve ICE/PHEV siblings on MINI Cooper/Countryman and Porsche Cayenne/Macan. Use the repo's canonical batch/edit pipeline for every writable price/trim/campaign/current-set action; validate the enriched serving result before proposing enqueue. No batch or implementation prompt has yet been generated.

Next: Step 3, a single Claude implementation prompt reflecting every row and explicit holds 1:1. Do not revisit this inspection unless the owner supplies new evidence or a concrete correction.

### REPAIR-06 Step 2 correction — full Thai grade check (2026-09-28)

Owner challenged whether Step 2 captured **all** currently evidenced Thai grades. Rechecked OEM Thai configurators, technical/spec downloads, purchase/quotation selector and dated campaign pages. This section supersedes narrower counts or premature "current" assertions in the first Step 2 table. State remains `INSPECTED`; implementation prompt not yet produced; no data write.

- 01 Mercedes EQS: Thai official model selector lists EQS SUV, not EQS Saloon. SUV finance specifies `EQS 450 4MATIC SUV AMG Dynamic` at 5,990,000 THB, whereas TDR calls SUV `AMG Line`. Treat as grade-name/spec mismatch; don't bind 5,990,000 to AMG Line without compatible identity. https://www.mercedes-benz.co.th/th/passengercars/models/suv/eqs/finance.html
- 04 MG IM5: current September offer and MG quotation selector explicitly identify `Premium Long Range`, LIST 1,549,900, September reduced price 1,499,900. Promotion headline `EXCLUSIVE EDITION` alone is not proof of a second independently priced grade; do not create one. TDR AWD/RWD pair still lacks a safe spec map. https://www.mgcars.com/en/promotions/MG-IM5-Promotion ; https://ex-prod.mgcars.com/en/RequestQuotation
- 05 MG IM6: quotation selector currently lists `Premium` 1,399,900 and `Performance` 1,799,900; additionally a `MG IM6 LONG RANGE` entry exists separately but is shown with **0 baht**, not an assignable list price. An August offer named `Premium Long Range`, 1,599,900 ordinary and 1,549,900 reduced, but booking/delivery terms end Aug 31. Therefore do not assert there are exactly three orderable September grades or a live third-grade LIST 1,599,900 without a current-dated grade quote. Keep it as an evidenced former/separate listing with present price/orderability unresolved. https://ex-prod.mgcars.com/en/Calculator ; https://www.mgcars.com/en/promotions/MG-IM6-Promotion
- 08 MG ZS EV: OEM current product spec table names **three BEV grades**, `D`, `X`, **`100TH SE`** (third omitted in the first inspection). OEM product's displayed `MODEL D` car price is 829,900; independent MG authorized dealer page lists D 829,900 and X/100TH SE 899,900, but its price currency/date and current stock for 100TH SE require a direct fresh price/booking confirmation before current price bindings. Preserve D/X ICE siblings' history while resolving wrong-parent rows. https://www.mgcars.com/th/cars/mg-zs-ev ; https://mg.ablemotors.com/mg-zs-ev/
- 10 MINI Aceman: OEM March price PDF names SE Classic 1,625,000, SE 1,899,000, SE Hightrim 1,869,000, and distinct JCW Aceman 2,269,000; its live Thai spec-sheet index ALSO lists SE Multitone Collection, SE Shadow Collection, and SE JCW Collection, omitted in first inspection. The last three have Thailand-specific spec PDFs (June 2026) but no confirmed live ordinary car prices or orderability in the March price PDF; distinguish **evidenced Thai spec identity** from **verified current retail grade**. Do not equate SE JCW Collection to JCW Aceman drivetrain. https://www.mini.co.th/en_TH/home/brochure.html ; https://www.mini.co.th/content/dam/MINI/marketTH/mini_co_th/brochure/brochure-2026/MINI-Price-Sheet-Revised-27-Mar-2026.pdf.asset.1774933915613.pdf
- 11/12/13 MINI: Thai spec-sheet index lists Cooper SE Classic, SE Hightrim, Paul Smith Edition; separate all-electric JCW, JCW Aceman and 1965 Victory Edition. Thai localized electric Countryman generic product page exists, but current Thai spec/price index lists Countryman S ALL4 ICE only; do not infer electric Countryman E + SE ALL4 from a generic page using EUR offers as currently Thai-retailable grades. Same sources as #10.
- 14 NETA V: NETA's official 2024 Thai release explicitly places `Lite 549,000` and `Smart 569,000` on **NETA V-II**, not proof these TDR amounts belong to the existing **NETA V** IDs. TDR 549k/569k assignment must be investigated as a potential misbinding; do not rename/price-correct from old launch evidence or repeat those numbers as verified V pricing. V-II Lite/Smart are verified historically Thai grades; September 2026 orderability remains unproven. https://www.neta.co.th/th/news/brands-pr-news/netav-llready ; https://www.neta.co.th/th/product/NetaV-II
- 15 NETA X: Thai OEM identifies just `Comfort 401` 51.8kWh 739,000 and `Smart 480` 62kWh 799,000 at launch, not `Smart 500`; do not assert September status from old launch page. https://www.neta.co.th/th/news/brands-pr-news/netaxofficiallaunch
- 18 Porsche Macan: configurator groups **five BEV**: Electric, 4 Electric, 4S Electric, `GTS` (electro 571 PS; labeled simply GTS in configurator), Turbo Electric. A *second* `GTS` (gasoline 440 PS) appears separately. Distinguish BEV/ICE by fuel+spec, not name alone. https://www.porsche.com/pap/_thailand_/models/macan/configure/
- 19 Porsche Taycan: configurator has 14 **MY2027** versions. TDR existing 4S says 544hp while configured 4S says 598 PS; TDR GTS 598hp vs configured 700 PS; this is a model-year/spec mismatch, not license to simply append current price to old trim IDs. Grade/version mapping must be proven individually, preserve history; five missing versions as in first table. https://www.porsche.com/pap/_thailand_/models/taycan/configure/
- 20 RIDDARA: Thai OEM 2025 press lists **six RD6 grades** after range additions: 2WD 63kWh 899,000; 2WD 73.9kWh 999,000; 4WD 73.9kWh 1,149,000; 4WD 86kWh 1,299,000; 2WD 86kWh 1,159,000; 4WD 86kWh Sunroof 1,335,000. This is evidence RD6 contains both 4WD 73.9 and 4WD 86, **not** proof TDR's `Horizon Pro/Ultra` names are exact Thai grade identities, nor proof all six remain orderable Sep 2026. Current Thai brand site shows RD6/ECON, not Horizon. https://thailand.riddara.com/newsroom/20250325 ; https://thailand.riddara.com/en/riddara-rd6
- Other members (#02 Cyberster, #03 ES, #06 Maxus 7, #07 Maxus 9, #09 MINE MTS, #16 Nextem ORCA, #17 Cayenne EV) were checked against OEM offer/grade pages: no newly verified omitted currently priced Thai grade beyond what the first table reports. Maxus 7/9 exterior two-tone is an option, not proved separate mechanical grade. The absence of further OEM pages is not proof no additional fleet/private trims exist. Porsche Cayenne six electric grades remain as stated.

Next: present a corrected 20-item owner-facing Thai market grid separating TDR grades+old prices, official evidenced grade/version, current price/dated promotion and grade-orderability holds; only then compose Step 3 prompt on owner direction.

## Per-batch recording template

```yaml
batch_id: REPAIR-XX
state: QUEUED
membership:
  - 01: Brand Model
required_changes:
  Brand Model:
    tdr_current: ""
    trim_action: ""
    list_price: ""
    promotion: ""
    lifecycle_action: ""
    preserve: ""
    source_notes: ""
approved_by_user: false
implementation_prompt_commit: null
write_commit: null
```

## Agent handoff format

Before continuing a batch, report only:

- `ACTIVE:` batch id + state
- `DONE:` frozen prior step
- `NEXT:` exactly one next action

Then execute that next action. Do not restart the workflow from the beginning.
