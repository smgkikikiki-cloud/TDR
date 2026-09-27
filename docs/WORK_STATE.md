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

### REPAIR-04 membership

Status: `RESOLVED` — the collision noted below was against a batch built in a parallel chat session before this file existed; the user confirmed in-session that the 20-vehicle list already implemented is the correct, frozen `REPAIR-04` membership, and directed the fixes to remaining open items (BYD Seal, OMODA C5 EV, DEEPAL Hunter K50, DEEPAL L07, Farizon SV, FOMM One, FOTON Truck) directly.

membership: AION ES; Audi e-tron; BMW i3; BYD T3; BYD Seagull→ATTO 1; BYD Seal; Changan Lumin; NEVO Q05; OMODA C5 EV; DEEPAL Hunter K50; DEEPAL L07; DEEPAL S05; DENZA D9; Farizon SV; FOMM One; FOTON Truck; GEELY EX2; GWM ORA 03; GWM ORA Good Cat; Honda e:N1.

still-pending sub-items (not full batch reopen — see write_commit for what shipped): BYD Seal (no lifecycle evidence found, left unchanged); DEEPAL L07 (Standard 540/Plus 620 naming can't be safely mapped to L07/L07 S without spec confirmation — user says they'll choose).

batch_id: `ev-retail-repair-lot-04-2026-09-27`
write_commit: `48f9326d8197f9d768185a7f9a56c879b08cd99d`
release_id: `vehicle-2026-fbdad1638efeb292`
approved_by_user: true

### REPAIR-05 membership

State: `INSPECTED` — Step 1 membership fixed; Step 2 compared the serving enriched release to Thai-market primary sources on 2026-09-27. The unresolved evidence items below are explicit holds. Implementation prompt and canonical writes have not started.

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
| 04 | JAECOO 5 EV: Long Range Dynamic, Long Range Max, MAX+ LIST 699,000, ULTRA; other three unpriced | Keep four identities pending direct grade confirmation. Official Thai material gives Dynamic LIST 629,000 / campaign 589,000 and Max LIST 679,000 / campaign 639,000; current official September campaign gives MAX+ LIST 699,000 / campaign 599,000; ULTRA campaign 699,000 against *estimated* 809,000, so do not record 809,000 as confirmed list. Sep 4–30 booking/delivery conditions. Do not merge the Long Range grades with MAX+/ULTRA. |
| 05 | JAECOO 6 EV: Long Range 2WD LIST 1,099,000; Long Range 4WD LIST 1,249,000 | Map 2WD identity to confirmed Thai 2WD MAX preserving compatible specs; CORRECT_PRICE to LIST 859,000. 4WD LIST 1,249,000 remains. Official Sep campaign 2WD 799,000; 4WD 999,900, booking/delivery Sep 4–30. |
| 06 | Kia EV6: Earth LR, GT, GT-Line; all unpriced | Hold lifecycle and prices: current Kia Thailand price list omits EV6 but does not establish wholesale withdrawal; verify retail orderability before marking HISTORICAL. Preserve three trim histories/specs. |
| 07 | Kia PV5: Cargo, Passenger, Robotaxi; all unpriced | Thai retail list explicitly PV5 Cargo at LIST 1,199,000. Retain Cargo CURRENT; Passenger and Robotaxi must not be presented as confirmed retail trims absent Thai booking evidence: resolve local lifecycle per trim and preserve history. |
| 08 | Leapmotor B10: generic Standard Range / Long Range; both unpriced | Replace generic identity with Thai Life / Style / Design (3 distinct grades), preserve compatible battery/spec facts. OEM press confirms three grades and LIST span 698,000–798,000, but per-grade official prices must be checked before assigning exact prices; no inferred campaigns. |
| 09 | Leapmotor C10: Design, EV, EV STYLE, Style; all unpriced | Reconcile duplicate generic EV/EV STYLE against Thai retail Design and Style using battery/spec; do not assume EV STYLE maps 1:1 or withdraw a distinct variant without evidence. Verify grade-specific LIST and promotion with Thai seller. |
| 10 | Lexus ES: ES350e Premium BEV unpriced plus HEVs sharing parent | Retain ES350e Premium and add LIST 3,290,000; preserve every valid HEV/current trim under the same model. |
| 11 | Lexus UX 300e: one BEV unpriced plus HEVs sharing parent | Official dedicated 300e page persists but UX current selector emphasizes UX300h. Hold lifecycle until orderability evidence, retain BEV history and all HEV trims; confirm whether prior 3,490,000 is current list before writing. |
| 12 | Lotus Eletre: base/S/R; unpriced | Replace old generic lineup with Thai MY26 600, 600 GT SE, 600 Sport SE, 900 Sport, 900 Sport Carbon (5 distinct trims) after compatible-spec mapping. Jan 2026 reports revised prices; confirm directly against Thai distributor before writing LIST or campaign; preserve older records. |
| 13 | Lotus Emeya: base/S/R; unpriced | Same five MY26 identities as Eletre with model-specific specs; verify revised Thai distributor prices before writing; preserve older records. |
| 14 | Maserati GranTurismo Folgore: one BEV unpriced plus ICE sharing parent | Keep Folgore CURRENT (Thai OEM configurator lists it); no independently verified Folgore Thai list price or current campaign. Preserve ICE trims; do not borrow the ICE Modena/Trofeo price. |
| 15 | Maserati Grecale Folgore: one BEV unpriced plus ICE sharing parent | Keep Folgore CURRENT (Thai OEM configurator lists it); no independently verified Folgore Thai list price/campaign. Preserve ICE trims. |
| 16 | Mazda6e: EXCLUSIVE/PREMIUM unpriced plus legacy ICE Mazda6 sharing parent | Retain both BEV trims. OEM LIST EXCLUSIVE 1,199,000; PREMIUM 1,169,000 (the lower PREMIUM figure is explicitly on Mazda's site). Keep unrelated ICE/history. Do not record old roadshow/launch perks as live campaign without valid dates. |
| 17 | Mercedes-Benz CLA: generic `electric` BEV unpriced plus ICE sharing parent | Resolve generic BEV to CLA 250+ with EQ Technology using spec-safe identity edit; OEM configurator starting LIST 2,290,000. Preserve ICE grades and specs; do not copy price to ICE. |
| 18 | Mercedes-Benz EQB: EQB 250 AMG Line LIST 3,020,000 | Hold lifecycle and price change: model page remains but current configurator lacks EQB. Confirm retail orderability and whether 3,020,000 is still valid; preserve history. |
| 19 | Mercedes-Benz EQE: 350+ AMG Dynamic sedan, two 350 4MATIC SUV grades, AMG EQE 53; all unpriced | Split sedan vs SUV identities without deleting shared historical records. OEM configurator currently lists EQE Saloon from 5,950,000 (verify exact grade before assignment); OEM finance offers name EQE 300, 350 4MATIC SUV Electric Art/AMG Line/AMG Dynamic and AMG EQE53: reconcile old sedan/SUV/current grades against full Thai price list. Do not assign model starting price to wrong grade. |
| 20 | Mercedes G-Class: G580 EQ Technology BEV unpriced plus ICE/HEV sharing parent | Retain BEV; OEM electric G-Class configurator starts LIST 9,500,000, confirm G580 grade mapping before writing. Preserve ICE/HEV; no confirmed live campaign. |

Primary source anchors: Honda https://www.honda.co.th/en2 and https://www.honda.co.th/promotions/detail/promotion-en2-jul2026 ; Hyundai https://www.hyundai.com/th/th ; JAC https://www.jacthailand.com/product ; OMODA JAECOO https://www.omodajaecoo.co.th/th/promotion/more-rain-more-gain and https://www2.omodajaecoo.co.th/th/blog/jaecoo-5-ev ; Kia https://www.kia.com/th/th/shopping-tools/price-list/pv5-cargo.html ; Leapmotor/Stellantis https://www.media.stellantis.com/as-en/leapmotor/press/leapmotor-thailand-unveils-the-all-new-leapmotor-b10-first-in-asean ; Lexus https://www.lexus.co.th/en/price-and-model-tools/compare-models.html ; Maserati https://www.maserati.com/th/en/shopping-tools/configurator ; Mazda https://prod.mazda.co.th/th/mazda6e ; Mercedes https://www.mercedes-benz.co.th/th/passengercars/configurator.html and https://www.mercedes-benz.co.th/th/passengercars/finance/offers.html .

Structural guard: existing release may include HEV/ICE in the same parent as target BEV. Explicit current-set commands must preserve unaffected grades. Do not confuse model-wide withdrawal with trim-level history. Do not use press estimates or unverified third-party price revisions as LIST_PRICE. No canonical write approved.

Next: Step 3 create one Claude implementation prompt containing all 20 actions and explicit holds, following existing canonical editing pathway. Await user's instruction to advance; Step 4 remains gated by user approval.

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
