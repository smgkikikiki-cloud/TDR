# TDR Work State — Source of Truth

This file is the persistent execution state for long-running TDR work. Agents must read this file before continuing any multi-step TDR data repair, audit, batch, or migration task.

## Vehicle DB v3 platform state (current — read before anything vehicle-related)

Vehicle DB v3 **Phase 0 is complete** (`docs/vehicle-db/VEHICLE_DB_V3.md`) — all seven steps,
1 through 7, are done.

- **Step 1** (engine inventory, `docs/vehicle-db/ENGINE_INVENTORY.md`) — documentation only.
- **Step 2** (`migration_v57_vehicle_master_tables.sql`) — added the Vehicle Master tables
  (`vehicle_brands`/`models`/`generations`/`variants`/`trims`/`facts`/`price_ledger`/
  `campaigns`/`promotions`/`eco_evidence`/sidecars/`legacy_identities`), seeded from the active
  release. **Live.**
- **Step 3** (`migration_v58_vehicle_serving_parity.sql`) — the six `current_*` serving views
  read from the Vehicle Master tables instead of the old release projections, identical
  columns/payload shape. **Live — serving is master-backed.**
- **Step 4** (`migration_v59_vehicle_engine_rules.sql`) — ported the engine's validation rules
  onto the master tables as constraints/triggers. **Live.**
- **Step 5** (`migration_v60_close_legacy_vehicle_write_path.sql`) — closed the old
  `canonical_input_batches → vehreg/data → release` write path. `canonical_input_batches` and
  every `canonical_*` projection/release table are now **read-only history**; the old
  enqueue/worker/publish/stage/activate/rollback/prune paths are fail-fast stubs or raise a
  "closed" error. **Live — the legacy writer is closed.**
- **Step 6** (`migration_v61_vehicle_master_backups_bucket.sql`) — daily read-only JSON export
  of the Vehicle Master to the private `vehicle-master-backups` Storage bucket. **Live; the
  first real production backup succeeded**
  (`vehicle-master/2026-10-04/vehicle-master-20261004T014601Z.json.gz`). Export/recovery
  infrastructure only — it is not a write path and is not authority.
- **Step 7** (this section, plus `AGENTS.md` / `docs/CANONICAL_INPUT.md`) — states the above
  plainly in repository rules. No code, migration, or data change. **Done.**

**Vehicle Master DB authority is live now.** The Supabase Vehicle Master tables are the sole
canonical source of truth for vehicle-market facts; `automotive/vehicle_master/` is engine/
tooling code, not a file-backed authority. See `docs/CANONICAL_INPUT.md` for what is retired
and `docs/vehicle-db/VEHICLE_DB_V3.md` for the live rule set.

**Registrations are explicitly out of scope / separate** from all of the above —
`registrations*` tables, DLT ingestion, and registration analytics are untouched by every step
above and remain their own system, joined only through reviewed identities.

**Phase 1** (`VEHICLE_DB_V3.md` §12: permission layer, change log + revert, observations, field
registry) is the next platform phase, now that Phase 0 is complete, and **has not been
started**. There is no Vehicle Master write layer yet. Do not describe admin/AI/Excel Vehicle
Master writes as available, do not claim a full production restore from backup has been tested,
do not treat a backup as authority, and do not reopen the retired path above.

**The repair records later in this file are historical and frozen.** They describe real work
done through the write path Step 5 has since closed (`enqueue-canonical-batch.yml` →
`canonical-input.yml` → commit → publish). They are a record of what happened, not current
instructions — do not read them as license to enqueue a new batch through that path, and do not
apply "Step 4 — Write: use repository-supported edit/write format" below to a new edit; see
`docs/CANONICAL_INPUT.md` instead.

## Market Track state (current — Ice Full Package / market engine)

Separate track from Phase 0 above (`VEHICLE_DB_V3.md` §12 "Market track"), can run in parallel.

- **M1** (serving contract inventory, `docs/vehicle-db/SERVING_CONTRACT.md`) — documentation
  only. **Done.**
- **M2** (Ice import, `.claude/skills/tdr-package-import/SKILL.md`) — **infrastructure only,
  in progress. `migration_v62_ice_market_panels` is applied in production. No real Ice
  package has been imported, so the live `ice_*` tables hold no real release data.**
  - Built and live in the repo (package-independent, needs no real package to exist):
    `supabase/migration_v62_ice_market_panels.sql` (twelve `ice_*` tables — six fact/dims
    panels plus `ice_package_imports`, the import-event log — service-role-only, same private
    pattern as the Vehicle Master tables); `vehreg/ice_package.py` (pure structural validation:
    status/`confirmed_by`/md5-index/changelog-continuity/column-schema checks, plus the §2
    step-4 post-import reconciliation checks); `tools/ice_package_import.py` (`--check`,
    fully offline; `--apply`, replace-whole-set, refuses to write unless `--check` is clean and
    the package's own shipped `validate_package.py` passes).
  - **Two real delivery attempts inspected and rejected as not import-ready**, both found on
    the owner's filesystem (`/mnt/e/TDR web/...`), neither moved/imported: a 5-of-6-panel
    `2569-08` set (missing `reg_powertrain`, no `full_package.json`/`CHANGELOG.csv`, no shipped
    validator, `confirmed_by: []` in every panel manifest) at two versions (v1 superseded by
    v2); a request for the complete, confirmed `TDR_FULL_<period>_v<n>_M<master_version>.zip`
    was sent back. **No `data/packages/` directory exists in the repo; no file has been moved
    into one.**
  - Still blocking a real import: the complete `TDR_FULL_*.zip` itself (6 panels incl.
    `reg_powertrain`, `full_package.json`, `CHANGELOG.csv`, the release's own
    `validate_package.py`, `status: "พร้อมส่ง"`, `confirmed_by` with 2 names).
- **M3** (crosswalk, `docs/vehicle-db/VEHICLE_DB_V3.md` §14.2) — **infrastructure
  implemented, package-independent; no production crosswalk has been generated or
  approved.** No real Ice Full Package has been imported (M2 state above), so
  `ice_reg_trend`/`ice_dims_model_group` are empty in production and a real `--match`
  run would currently find zero candidates.
  - Built and live in the repo: `supabase/migration_v63_ice_model_crosswalk.sql`
    (`ice_model_crosswalk`, `ice_brand_aliases` seeded with Deepal↔Changan and MG
    Maxus↔MAXUS, `ice_model_group_redirects`, `ice_known_model_groups` discovery
    ledger — all service-role-only, same private pattern as M2; the RPCs
    `ice_crosswalk_upsert_match` and `ice_crosswalk_apply_id_change`); `vehreg/
    ice_crosswalk.py` (pure matcher — series correlation/ratio, brand alias and name
    normalization, the AUTO/PROPOSED acceptance table, Buddhist/Gregorian period
    conversion, id_changes.csv parsing, discovery flags, the review-sheet
    formatter); `tools/ice_crosswalk_match.py` (wires the pure matcher to real
    Supabase data — `--match` and `--process-id-changes`).
  - Row-identity/PK shape for `ice_model_crosswalk` was not specified by §14.2 and
    is a documented choice (see the migration's own header comment): a surrogate
    bigint PK plus three partial unique indexes encoding the required cardinality
    (many TDR models → one Ice group; one TDR model → at most one *active* Ice
    group). The id_changes "แยก" case's "STRUCTURE proposal" uses `match_method =
    'ADMIN'` with `status = 'PROPOSED'` (also a documented choice — §14.2's
    `match_method` enum has no dedicated value for a system-raised structural
    review item).
  - Bookmark/public-link redirection consumption (actually rewriting a saved link
    to follow a retired `model_group_id`) is **not built** — `ice_model_group_redirects`
    only records the old→new fact. Any UI/link-rewriting consumer is a handoff to
    M4/M5, which must read this table rather than inventing a second mechanism.
  - Do not run `tools/ice_crosswalk_match.py --match` against production, and do not
    seed or approve any real crosswalk mapping, until a real Ice Full Package has
    been imported (M2) and the owner has reviewed real candidates.
- **M4** (market engine on Ice data) — **not started.**
- **M5** (switch pages, retire old registration views) — **not started.** The existing
  registration/market display engine (`lib/registration-analytics.ts`,
  `lib/public-market.ts`, `app/market/`, `app/member/market/`, etc.) is **untouched** and still
  live; M2's new `ice_*` tables are not read by it or by anything else yet.

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
Canonical boundary: the Supabase Vehicle Master tables (see `docs/CANONICAL_INPUT.md`);
`automotive/vehicle_master/` is engine/tooling code, not the data authority.

**Step 4 of this process (the actual write) is currently blocked.** The write path it used to
mean — `enqueue-canonical-batch.yml` → `canonical-input.yml` → publish — was closed in Vehicle
DB v3 Phase 0 step 5 (`migration_v60`) and must not be revived. Steps 1–3 below (membership,
inspection, implementation-prompt drafting) remain valid analysis work for a future repair batch;
do not advance a batch to Step 4 until Phase 1 (`docs/vehicle-db/VEHICLE_DB_V3.md` §12) delivers
a real Vehicle Master write layer.

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
- **Currently blocked** (see the note above the "Repair process" heading): the retired
  `canonical_input_batches` queue is closed, and no Vehicle Master write layer exists yet. Do
  not enqueue, publish, or otherwise write canonical vehicle data through it or through any
  improvised alternative; wait for Phase 1 (`docs/vehicle-db/VEHICLE_DB_V3.md`).
- Once a supported write layer exists: only after user approval; preserve valid existing
  specs/evidence when identity changes; do not blank a vehicle simply because a trim is
  renamed/reconciled.

## Historical audit record

`AUDIT-BEV-REEV-061-080` is complete and read-only. It covered:
Lexus ES; Lexus RZ; Lexus UX 300e; Lotus Eletre; Lotus Emeya; Maserati GranTurismo Folgore; Maserati Grecale Folgore; Mazda6e; Mercedes-Benz CLA EV; Mercedes-Benz EQB; Mercedes-Benz EQE; Mercedes G-Class EV; Mercedes EQS; MG Cyberster; MG EP; MG ES; MG IM5; MG IM6; MG Maxus 7; MG Maxus 9.

Do not use this historical audit range as `REPAIR-04` membership unless the repair queue explicitly says so.

## Current repair status

- `REPAIR-03`: `DONE / APPROVED` — frozen. Do not re-audit or rebuild unless user reopens it.
- `REPAIR-04`: `DONE / APPROVED` — frozen. Do not re-audit or rebuild unless user reopens it.
- `REPAIR-05`: `DONE / APPROVED` — frozen. Do not re-audit or rebuild unless user reopens it.
- `REPAIR-06`: `DONE / APPROVED` — frozen. Do not re-audit or rebuild unless user reopens it.
- `REPAIR-07`: `DONE / APPROVED` — frozen. Do not re-audit or rebuild unless user reopens it. MG ZS EV identity migration NOT attempted (no provable safe mapping) and remains open for a future, separately-numbered repair.
- `REPAIR-08`: `DONE / APPROVED` — frozen. Do not re-audit or rebuild unless user reopens it. v6, 36-command batch (`ev-retail-repair-lot-08-2026-09-28f`) enqueued and published for real: write commit `6492204a74d46075adcefde1d63daf47338542a1`, release `vehicle-2026-c4e73494ab9aa779` ACTIVE. Full holds, unresolved and untouched: SERES 3, SOKON EC35, VOLT For Four, VOLT For Two, Volvo XC40 BEV (5 of 16 members — owner asked these be marked HISTORICAL but declined to supply the http(s) source the code requires for that action); RIDDARA Horizon 4WD, EX90's Ultra 6/7-Seat split + its campaign, and Zeekr X's Long Range RWD are also held within their otherwise-actioned items. Any future resolution of these is a new, separately-numbered repair.

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

### REPAIR-06 Step 3 implementation prompt (2026-09-28)

State: `PROMPT_READY`. Owner explicitly requested the Claude prompt after receiving the corrected 20-member Step 2 grid. The prompt includes all 20 members with TDR old trim/prices, evidenced Thai grades/list prices and dated campaigns, exact identity/current-retail holds, source URLs, canonical input pipeline guardrails, disposable-copy validation and an explicit STOP at draft. No batch has been enqueued, no canonical data written and no release published. The corrected Step 2 section immediately above governs if any earlier inspection text disagrees.

Next: have Claude construct and validate a draft canonical batch, report exact one-to-one coverage, holds and before/after enriched release diff; await the owner's separate Step 4 approval before any enqueue, canonical write or publish.

### REPAIR-06 Step 3 draft (2026-09-28)

State: `PROMPT_READY` -- draft batch built and validated on a disposable copy; no enqueue, no canonical write. Draft batch_id `ev-retail-repair-lot-06-2026-09-28`, 37 commands (UPSERT_MODEL_BUNDLE x6, APPEND_PRICE x31, every price row carrying a real http(s) source_ref). Resolved canonical IDs against both the base catalog and an actual `tdr_bridge.release_enriched` build as of 2026-09-28: all 20 members' model/trim ids and counts match exactly between base and serving (no enriched-overlay-only trims this round, unlike REPAIR-05's Kia EV6). Applied cleanly via `CanonicalInputPipeline.apply()` on a `cp -r vehreg/data` scratch copy (status APPLIED, 73 changed files), `vehreg market validate` returned valid, and the 46-test focused pytest suite passed against the real repo. A staged `release_enriched` before/after diff confirms exactly the intended effect and nothing else: market_trims 1542->1561 (+19 new trims, matching the 4+3+1+3+3+5 additions below), price_ledger 950->981 (+31, matching the 31 APPEND_PRICE commands 1:1), and every held item (all 16 zero-command members, the 3 MG ZS EV ICE wrong-parent rows, and the 3 spec-mismatched Taycan trims) shows zero diff.

Items with commands issued: 10 MINI Aceman (4 new trims: SE Classic 1,625,000 / SE 1,899,000 / SE Hightrim 1,869,000 / JCW Aceman 2,269,000 -- old E Classic/SE Favoured untouched), 11 MINI Cooper Electric (3 new trims: SE Classic 1,425,000 / SE Hightrim 1,669,000 / Paul Smith Edition 1,769,000 -- old E/SE 218hp untouched), 13 MINI JCW E (existing trim priced 2,069,000 + 1 new "1965 Victory Edition" 2,119,000), 17 Porsche Cayenne EV (3 existing priced + 3 new trims, all 6 BEV grades), 18 Porsche Macan EV (2 existing priced + 3 new trims, all 5 BEV grades), 19 Porsche Taycan (6 existing priced + 5 new MY2027 trims; 3 existing HELD for spec/generation mismatch: 4S 544hp, GTS 598hp, 4S Cross Turismo).

Full holds, zero commands (16 of 20 members): 01 Mercedes EQS (SUV grade-name mismatch + sedan/SUV model-split blocker, same reparent-primitive gap as Mercedes EQE in REPAIR-05), 02 MG Cyberster (already correct, no command needed), 03 MG ES (already correct), 04 MG IM5, 05 MG IM6, 06 MG Maxus 7, 07 MG Maxus 9 (all four MG items: Structural holds explicitly name them in the "do not guess a trim mapping from similar names" list; zero spec data on any existing trim to verify against), 08 MG ZS EV (BEV D/X/100TH SE pricing held pending fresh-evidence confirmation; ICE D/X wrong-parent rows reported as a structural blocker -- same canonical_id-namespaced-under-model_id gap, no reparent-trim-to-new-model primitive exists), 09 MINE MTS, 12 MINI Countryman Electric (no verified current Thai BEV price/orderability at all), 14 NETA V (ledger-misbinding concern reported, not acted on -- existing 549k/569k may actually belong to NETA V-II per OEM's own 2024 material, but Step 2 explicitly forbids correcting from that suspicion alone), 15 NETA X (Smart 500 identity/price held; Comfort 400/Smart 480 already correct), 16 Nextem ORCA, 20 RIDDARA Horizon Double Cab (confirmed already a separate canonical model from RD6 Double Cab; RD6's six-grade evidence does not establish a Horizon Pro/Ultra correspondence).

Judgement calls flagged for owner review at Step 4, not literal Step 2 instructions: (a) reading "do not guess a mapping from similar names" as scoped to renaming/binding OLD trim ids, not to adding brand-new, distinctly-evidenced trims -- applied to add 4 MINI Aceman, 3 MINI Cooper Electric, and 1 MINI JCW E grades without touching any existing MINI id; (b) holding Porsche Taycan's "4S Cross Turismo" by association with the explicitly-flagged "4S" spec mismatch, even though Step 2 only named the sedan "4S" and "GTS" directly; (c) the MINI Cooper Electric existing SE(218hp) trim's most recent ECO_STICKER_PRICE (1,669,000) numerically matches the new "SE Hightrim" grade -- noted as a coincidence in the batch's own trim `notes`, explicitly NOT treated as confirmed identity.

Full draft batch JSON and validation report were delivered to the user in-chat; not restated here in full.

### REPAIR-06 Step 3 draft amendment (2026-09-28b)

State: still `PROMPT_READY` -- amended draft batch_id `ev-retail-repair-lot-06-2026-09-28b`, 51 commands (UPSERT_MODEL_BUNDLE x10, APPEND_PRICE x33, UPSERT_CAMPAIGN x3, REPLACE_CURRENT_RETAIL_SET x5). Owner reviewed the original 37-command draft and gave explicit item-by-item direction on 6 of the 20 members; the other 14 (including all previously-issued MINI/Porsche Cayenne/Macan commands) are unchanged. Re-validated the same way: fresh disposable-copy apply (APPLIED, 87 changed files), `vehreg market validate` valid, 46/46 focused pytest suite passed, staged `release_enriched` diff confirmed the exact intended lifecycle/price effect and nothing else.

- 01 Mercedes EQS: unchanged, still full hold per owner's explicit "hold ไว้ก่อน".
- 08 MG ZS EV: owner asked to delete the wrong-parent ICE "D"/"X" trims. Checked the actual supported delete mechanism (`UPSERT_MODEL_BUNDLE` payload `delete_trim`, `vehreg/canonical_trim_delete.py`, exercised by `tests/test_admin_delete_trim.py`) and found it hard-refuses deletion of any trim with price history attached -- both ICE rows carry real ECO_STICKER_PRICE history (949,000 / 1,023,000, observed 2022-06-09), so literal deletion is blocked by the schema itself, not a policy choice. Also checked the per-trim `UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW` (historical) path and found it separately blocked: it requires the parent model's raw `retail_status` to already be the literal string `CURRENT`, and `mg.mg_zs_ev`'s raw status is `UNVERIFIED` (confirmed directly against the catalog). Used `REPLACE_CURRENT_RETAIL_SET` restricted to the two real BEV trims as the closest safe equivalent -- the wrong-parent ICE rows drop to `UNVERIFIED` in the served release (no longer presented as orderable under the EV listing) with zero deletion, reparenting, or history loss. BEV D/X remain unpriced (unchanged holds).
- 04/06/07 MG IM5 / Maxus 7 / Maxus 9, and 05 MG IM6: owner asked to add the confirmed new grade(s) and move the old ones to historical. Same blocker as MG ZS EV applies to all four (`mg.mg_im5`/`mg.mg_im6`/`mg.mg_maxus_7`/`mg.mg_maxus_9` are all raw `UNVERIFIED`, not `CURRENT`), so literal per-trim `HISTORICAL` status is not achievable this round either. Added the confirmed new trim(s) (IM5 "Premium Long Range" 1,549,900 + Sep 1-30 campaign 1,499,900; IM6 "Premium" 1,399,900 + "Performance" 1,799,900, no campaign -- the only concrete reduced prices found belong to an expired August-only offer; Maxus 7 "X" 1,399,000 + Sep 1-30 campaign 1,299,000; Maxus 9 "V Plus" 1,849,900 + Sep 1-30 campaign 1,799,900) and used `REPLACE_CURRENT_RETAIL_SET` to exclude the old trims from each model's current set. Old trims resolve to `UNVERIFIED`, not literal `HISTORICAL` -- every canonical_id, spec and price record (including Maxus 9's Model V/X existing prices, 2,499,000/2,099,000, left completely untouched) is fully preserved. This distinction between "no longer presented as current" (achieved) and the literal `HISTORICAL` enum (not reachable without a separate model-status change not requested this round) is flagged for the owner.
- 14 NETA V: owner said to just use V-II's price. The existing ledger already carries exactly those figures (Lite 549,000 / Smart 569,000) as LIST_PRICE -- no command needed; the earlier ledger-misbinding concern is now closed per the owner's explicit decision to retain the existing numbers.
- 09/12/15/16/20 MINE MTS / MINI Countryman Electric / NETA X Smart 500 / Nextem ORCA / RIDDARA Horizon: owner said leave alone -- unchanged, still full hold.
- 19 Porsche Taycan: owner narrowed scope to "sedan ปกติ" (plain/ordinary sedan grades only), explicitly re-confirming 4S Cross Turismo stays held. Reduced from the original 6 priced + 5 new to 4 priced existing (RWD, Turbo, Turbo S, Turbo GT) + 1 new plain "4" grade (7,490,000). Dropped this round: both Cross Turismo price bindings (4 Cross Turismo, Turbo Cross Turismo -- a different body style) and all four special-edition additions (Black Edition, 4 Black Edition, 4S Black Edition, Turbo GT Weissach). Still held: 4S (544hp) and GTS (598hp) for the confirmed spec/generation mismatch.

Full amended draft batch JSON was delivered to the user in-chat.

Next: Await explicit user approval for Step 4 canonical write. Claude may prepare and validate a draft payload but must not enqueue, publish, or alter canonical vehicle data while at PROMPT_READY. This amendment did not change state to `APPROVED_TO_WRITE`.

### REPAIR-06 Step 4 write (2026-09-28, DONE / APPROVED)

State: `DONE / APPROVED`. Owner gave explicit Step 4 approval ("enque ไปเลย") for the amended 51-command batch `ev-retail-repair-lot-06-2026-09-28b` described above. No further changes were made to the batch between approval and enqueue.

- Enqueued via `enqueue-canonical-batch.yml` (run `36375876010`, job `108781491262`): completed success, log confirmed `batch_key: ev-retail-repair-lot-06-2026-09-28b`, `queue_status: QUEUED (duplicate replay: False)`, and that it woke worker run `36375909417`.
- Worker `canonical-input.yml` (run `36375909417`, job `108781584921`): completed success, all steps green -- apply, `vehreg market validate`, 46-test focused pytest suite, build enriched release, `git commit`, `tools.publish_canonical`, `mark-published`. STAGED-recovery steps present but skipped (no failure occurred).
- Write commit: `be345ad2cbb5a32f2fe47586c04728b79536e584` ("Apply 1 canonical input batch(es)", 87 files changed, 10803 insertions).
- Published release: `vehicle-2026-13b64c83d1fc710d`, status `ACTIVE`, `activated_at: 2026-09-28T04:02:41.58024+00:00`, `published_batches: 1`.
- Independent verification performed directly against the pulled repo, not taken from the worker's self-report: (1) `git fetch origin main` + `git merge --ff-only` landed exactly on `be345ad2...`, matching the worker's reported commit; (2) a direct `vehreg market validate` re-run against the fresh pull returned valid, 0 problems; (3) a from-scratch Python cross-check loaded the actual submitted batch JSON and verified every one of the 51 commands' real effect against the live `Catalog`/`PriceLedger`/`current_retail_index` (trim existence/name for the 10 `UPSERT_MODEL_BUNDLE`s, amount/source_ref for the 33 `APPEND_PRICE`s, existence/source_ref for the 3 `UPSERT_CAMPAIGN`s, exact membership for the 5 `REPLACE_CURRENT_RETAIL_SET`s) -- result `FAILS: 0`; (4) an independent `tdr_bridge.release_enriched` rebuild from the real post-publish HEAD produced `release_id vehicle-2026-13b64c83d1fc710d`, an exact match to the actually-published/ACTIVE release_id, confirming full source-hash equivalence.
- Two literal-wording deviations from the owner's Step 3 correction message were made and flagged transparently rather than forced or silently skipped: (a) MG ZS EV's wrong-parent ICE trims were not schema-deletable (price history attached) and were instead excluded via `REPLACE_CURRENT_RETAIL_SET`, dropping them to `UNVERIFIED`; (b) MG IM5/IM6/Maxus 7/Maxus 9's old trims could not be moved to literal per-trim `HISTORICAL` (parent models are raw `UNVERIFIED`, not `CURRENT`, which `UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW` requires) and were likewise excluded via `REPLACE_CURRENT_RETAIL_SET` instead. Both substitutions achieve the real-world "no longer presented as current" outcome with zero deletion, reparenting, or price-history loss, and are recorded in the batch's own command notes.

Next: REPAIR-06 is closed. Do not re-audit or rebuild unless the user explicitly reopens it. Any further correction to any of these 20 members is a new, separately-numbered repair batch, not a reopening of REPAIR-06.

### REPAIR-07: post-publish lifecycle/identity fix-up for two REPAIR-06 findings (2026-09-28)

State: `PROMPT_READY`. This is NOT a reopening of REPAIR-06 (its published batch/commit/release are untouched) and is its own namespace. Scope is exactly the two problems the owner named: (1) the raw-UNVERIFIED-parent guard in `vehreg/retail_lifecycle_review.py` wrongly refused a HUMAN `historical` disposition for old trims REPAIR-06 already excluded from an approved current-retail set, and (2) whether MG ZS EV's wrong-parent ICE `D`/`X` rows can be safely identity-migrated instead of just excluded.

**1. Lifecycle guard fix (code, tested).**

`vehreg/retail_lifecycle_review.py`: `upsert_trim_lifecycle_disposition()` used to hard-require the parent model's raw `retail_status == CURRENT` for any non-`reopen` action. Added a narrow carve-out: when the parent is raw non-`CURRENT` and non-`HISTORICAL` (i.e. `UNVERIFIED`) AND the model has an explicit approved current-retail set (`vehreg/current_retail.py`), a trim excluded from that set may now receive a `historical` disposition (that set is already the sole CURRENT authority for such a model in `tdr_bridge/lifecycle.py`, so this cannot contradict anything). A trim genuinely inside the approved set is explicitly rejected (`"trim is a member of the approved current-retail set; cannot record a contradictory historical disposition"`). A genuinely raw-`HISTORICAL` parent, or a raw-`UNVERIFIED` parent with no approved set at all, keeps the original refusal unchanged, and `current` stays refused for a non-`CURRENT` parent in every case -- the fix only ever unlocks `historical` for an excluded trim. No global change to any model's raw `retail_status`. Added 5 new tests to `tests/test_trim_retail_lifecycle_review.py` (historical allowed when excluded; `current` still rejected; `historical` rejected for a trim inside the approved set; `historical` still rejected with no approved set at all; `historical` still rejected for a genuinely `HISTORICAL` parent even with an approved set) -- all pass, plus the existing 7 tests in that file and the full `test_retail_scope.py`/`test_current_retail_set.py` files (95/96 passed; the 1 failure, `test_real_catalog_has_zero_blocked_models_and_full_current_trim_coverage`, is a pre-existing failure against real catalog data unrelated to this change, confirmed by reproducing it identically on the pre-fix code). The production focused gate (`tests/test_admin_create_vehicle.py`, `test_admin_delete_trim.py`, `test_admin_editor_sibling_preservation.py`, `test_canonical_price_maintenance.py`, `test_canonical_queue_phase_c.py`, `test_canonical_staged_publish_recovery.py`, `test_canonical_validation_requeue.py`) also passes unchanged.

**2. MG ZS EV wrong-parent ICE rows: identity migration NOT attempted -- no provable safe mapping.**

`mg.mg_zs_ev.zsev.trim.d_ice` ("D", ECO_STICKER_PRICE 949,000, source `https://car.ecosticker.go.th/landing-page/detail/5d4300a94f474d728d6745e8cd2d43c9`) and `mg.mg_zs_ev.zsev.trim.x_ice` ("X", ECO_STICKER_PRICE 1,023,000, source `.../1420bd13e3f34a3ca6bbfef98ed40f5d`) were inspected against the real, separate ICE model `mg.mg_zs` (generation `zsg`, trims `1_5_c_plus_ice`/`1_5_d_plus_ice`/`1_5_x_plus_ice`/`1_5_v_ice`/two special editions). The name similarity ("D"/"X" vs "1.5 D+"/"1.5 X+") does NOT hold up under the actual comparable-spec facts on file: the wrong-parent rows carry `manufacturing.excise_tax_rate = 2.0%` and declared total weight 1,610 kg (D) / 1,570 kg (X), against `mg_zs`'s real ICE trims' `excise_tax_rate = 20.0%` and weight 1,290 kg -- a 10x excise-rate and ~300 kg difference, not measurement noise, and inconsistent with an ordinary 1.5L ICE passenger car (2% is the Thai BEV/eco-incentive band). Body height also differs (1,649 mm vs 1,653 mm) and D's tyre size (215/55R17) does not match `1_5_d_plus_ice`'s recorded 215/60R16. The wrong-parent rows additionally carry no `engine.displacement_cc`/`powertrain.transmission`/emissions facts at all, unlike every real `mg_zs` ICE trim. Their two ECO source ids do not appear anywhere in `mg_zs`'s own eco source_refs (no duplicate-submission explanation either). Conclusion: not just "which exact grade" is unresolved -- the evidence actively argues against the two ECO submissions being ordinary 1.5L ICE ZS units at all, so no `mg_zs` target identity is provable from data already in the repository, and none should be inferred from name/body-dimension similarity alone (the exact trap the task named: "do not... silently assign ECO prices to a superficially similar MG ZS grade"). No migration operation was built. Per instruction, the published REPAIR-06 current-set exclusion is left intact: `d_ice`/`x_ice` remain `UNVERIFIED` in the release, `TRIM_RETIRED` for automated price matching, fully preserved (price history, comparable-spec facts, canonical id) exactly as REPAIR-06 published them. This is recorded explicitly as an unresolved wrong-parent identity pending migration, not as fixed.

**Draft batch (Step 3, not enqueued).** `ev-retail-repair-lot-07-2026-09-28`, 8 `UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW` commands (action `historical`), one per old trim REPAIR-06 already excluded from an approved current-retail set: `mg.mg_im5.mg_im5.trim.im5_standard_range_rwd_bev`, `mg.mg_im5.mg_im5.trim.im5_long_range_awd_dual_bev`, `mg.mg_im6.gen1.trim.im6_luxury_rwd_bev`, `mg.mg_im6.gen1.trim.im6_performance_awd_dual_bev`, `mg.mg_maxus_7.gen1.trim.maxus_7_premium_bev`, `mg.mg_maxus_7.gen1.trim.maxus_7_luxury_bev`, `mg.mg_maxus_9.mifa9.trim.maxus_9_model_x_bev`, `mg.mg_maxus_9.mifa9.trim.maxus_9_model_v_bev`. Each cites the same REPAIR-06 OEM promotion-page `source_ref` that established the new grade, actor `smgkikikiki-cloud`. MG ZS EV is NOT in this batch (see above). Applied cleanly to a disposable copy of `vehreg/data` (`CanonicalInputPipeline.apply()`, status APPLIED, 2 changed files -- one write per model to `market/retail_lifecycle/trim_review.json`, none of it touching `canonical_state`), `vehreg market validate` returned valid/0 problems. A staged `tdr_bridge.release_enriched` before/after build confirmed exactly these 8 trims flip `UNVERIFIED -> HISTORICAL` and nothing else in the whole release changes: the 5 REPAIR-06 approved new grades stay `CURRENT`, all 4 MG ZS EV rows are untouched (`zs_ev_d_bev`/`zs_ev_x_bev` `CURRENT`, `d_ice`/`x_ice` still `UNVERIFIED`), every old trim's price history is byte-identical to before (0 records for the 6 IM5/IM6/Maxus7 trims, 1 preserved `LIST_PRICE` record each for Maxus 9's Model V/X, 2,499,000/2,099,000), and automated price-matching eligibility for all 8 was already `False`/`TRIM_RETIRED` under REPAIR-06's `REPLACE_CURRENT_RETAIL_SET` and stays exactly that (this batch only adds the admin/history-visible HISTORICAL disposition on top; it does not change matching behavior).

Next: await the owner's separate Step 4 approval for this 8-command batch. Do not enqueue, write to real canonical data, merge, or publish before that. If the owner later obtains independent confirmation of the ZS EV D/X target identity (e.g. resolving the ECO Sticker detail pages directly), that is new evidence for a follow-up batch, not something to infer here.

### REPAIR-07 amendment: real timestamp, obsolete real-catalog test, reverse-transition guard (2026-09-28b)

State: still `PROMPT_READY`. All work remains on branch `claude/epic-clarke-7gaksb`, not merged into `main`. Nothing enqueued, written to real canonical data, or published.

**1. Real `submitted_at`.** The draft batch's placeholder `submitted_at` (`2026-09-28T00:00:00+00:00`) was replaced with the actual build timestamp `2026-09-28T05:03:27+00:00`; `batch_id` (`ev-retail-repair-lot-07-2026-09-28`) and all 8 commands are otherwise unchanged. Real pipeline `batch_hash` (via `CanonicalInputBatch.from_dict` + the input pipeline's own `_hash(semantic_payload())`, not a hand-rolled hash): `3e22d1ff42f40d8b44b39532347e0b5188e20d6a12a873f171b282f07139b7aa`. Re-validated on a fresh disposable copy of the current `vehreg/data`: `CanonicalInputPipeline.apply()` APPLIED, `vehreg market validate` valid/0 problems, staged `tdr_bridge.release_enriched` before/after diff identical to the first draft's (exactly the same 8 trims `UNVERIFIED -> HISTORICAL`, nothing else), price history and price-matching eligibility for all 8 trims re-confirmed unchanged.

**2. `test_real_catalog_has_zero_blocked_models_and_full_current_trim_coverage` was obsolete, not wrong -- updated, not weakened.** On pre-fix `main` this asserted `blocked == {}` and failed: 5 real models (`audi.etron`, `bmw.i3`, `byd.seagull`, `gwm.ora_03`, `gwm.ora_good_cat`) are genuinely, deliberately `MODEL_HISTORICAL` (from REPAIR-04 and earlier), which is intended scope, not a bug -- confirmed the failure reproduces identically on `main` with the REPAIR-07 code fix entirely absent. The test's second assertion (`scoped_trim_ids == set(catalog.trims) - historical_trim_ids`) was independently obsolete too: it never accounted for REPAIR-06/07's owner-approved current-retail sets, which also intentionally narrow a model's scoped trims below full catalog membership without any per-trim `HISTORICAL` review existing for the excluded members. Renamed to `test_real_catalog_has_zero_unexpected_blocks_and_fully_accounted_trim_coverage` and rewritten to check, per trim rather than by blunt set equality: (a) every model-wide block is `MODEL_HISTORICAL` and nothing else (`UNDER_MAINTENANCE`/`GENERATION_UNRESOLVED`/`UNKNOWN_MODEL` would still fail the test, since those would mean real catalog trouble); (b) every trim under a blocked model is absent from scope; (c) for a model with an approved current-retail set, scope membership exactly equals that set; (d) for every other (legacy) model, scope is exactly the full trim set minus HUMAN-`HISTORICAL`-reviewed trims -- i.e. the original, stronger guarantee is fully preserved for every model that hasn't opted into REPAIR-06/07-style management. Passes against the real catalog now (16/16 in `tests/test_retail_scope.py`).

**3. Reverse-transition guard added: an approved current-retail set may not silently resurrect a `HISTORICAL` trim.** Checked whether `REPLACE_CURRENT_RETAIL_SET` could re-admit a trim that still carries an unreopened HUMAN `historical` disposition from `vehreg/retail_lifecycle_review.py` -- it could: `validate_current_retail_sets()` never consulted `trim_review.json` at all, so re-adding such a trim would flip it back to `CURRENT` in the release layer (approved-set membership is the sole authority once a model has a set) while the historical review record sat there, unreopened and now contradicted. Fixed in `vehreg/current_retail.py`: `replace_current_retail_set()` now loads the trim's lifecycle decisions (a local import inside the function, to avoid a module cycle with `retail_lifecycle_review.py`, which imports `resolve_approved_current_trim_ids` from `current_retail.py` at top level) and rejects the write if any trim in the candidate approved set still has status `HISTORICAL` on file (`"...still carries an unreopened HUMAN historical disposition; reopen it first..."`). The only supported path back is an explicit `UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW action=reopen` before (or in an earlier command of the same batch than) the `REPLACE_CURRENT_RETAIL_SET` that re-admits it. No production current-retail set was touched by this step. Added 2 focused tests to `tests/test_current_retail_set.py`: `test_readding_a_historical_trim_to_the_approved_set_is_rejected` and `test_reopen_then_readd_to_the_approved_set_is_supported`, both passing.

**4. Final revalidation against latest `main`.** Code commit on `claude/epic-clarke-7gaksb`: `2e47609` (item 1's guard fix) plus this round's uncommitted-until-now changes to `vehreg/current_retail.py`, `tests/test_current_retail_set.py`, `tests/test_retail_scope.py` -- to be committed as a follow-up commit on the same branch (still not merged to `main`; `main` is unchanged at `2028d37`). Focused re-run (production 7-file gate + `test_trim_retail_lifecycle_review.py` + `test_current_retail_set.py` + `test_retail_scope.py`): 98/98 passed. Full repo suite (`pytest tests/ -q`, 1,300+ tests): see chat report for the exact final count and any remaining failures, plus confirmation of which (if any) are pre-existing and unrelated to this branch, reproduced against unmodified `main`.

Next: unchanged -- await the owner's separate Step 4 approval to enqueue the (now real-timestamped) 8-command batch, and a separate approval to merge `claude/epic-clarke-7gaksb` into `main`. Neither has been given.

### REPAIR-07 Step 4 write (2026-09-28c, DONE / APPROVED)

State: `DONE / APPROVED`. Owner gave explicit approval for both the code merge and the enqueue in one message, naming the exact final batch (`submitted_at 2026-09-28T05:03:27+00:00`, `batch_id ev-retail-repair-lot-07-2026-09-28`, 8 commands, pipeline semantic hash `3e22d1ff42f40d8b44b39532347e0b5188e20d6a12a873f171b282f07139b7aa`) and explicitly excluding MG ZS EV from this write.

**1. Branch diff re-verified before merge.** `git diff origin/main origin/claude/epic-clarke-7gaksb` showed exactly 6 files: the two guard fixes (`vehreg/retail_lifecycle_review.py`, `vehreg/current_retail.py`), their three focused test files, and `docs/WORK_STATE.md` -- nothing else. No drift on `main` since the branch was created (still exactly 2 commits behind).

**2. Code merged to `main` first.** Fast-forward (`git merge --ff-only`; the branch's merge-base was `main`'s own tip, so no merge commit was needed). Pushed. Merged `main` commit: `dc619bf61a70b98c1d8b56bd0e214aae116b7f02`. Verified present in that commit: the approved-set carve-out in `upsert_trim_lifecycle_disposition()` (`retail_lifecycle_review.py`) and the reverse-transition guard in `replace_current_retail_set()` (`current_retail.py`). Focused 98-test gate re-run directly against this exact commit: 98/98 passed.

**3. Batch re-verified against the exact required values before enqueue.** Recomputed via `CanonicalInputBatch.from_dict` + the pipeline's own `_hash(semantic_payload())` (not a hand-rolled hash): `batch_id ev-retail-repair-lot-07-2026-09-28`, `submitted_at 2026-09-28T05:03:27+00:00`, 8 commands, hash `3e22d1ff42f40d8b44b39532347e0b5188e20d6a12a873f171b282f07139b7aa` -- exact match to what the owner specified. Confirmed zero MG ZS EV references in the payload.

**4. Enqueue and worker run, tracked to completion.**
- `enqueue-canonical-batch.yml` run `36381831161` (job `108799004794`), dispatched against `main` at `dc619bf`: completed success. Log: `{"batch_key": "ev-retail-repair-lot-07-2026-09-28", "status": "QUEUED", "duplicate": false, "item_count": 8, ...}`, woke worker run `36381875124`.
- `canonical-input.yml` run `36381875124` (job `108799190189`): completed success, all steps green -- `applied: 1, failed: 0`; 46/46 focused pytest; `vehreg market validate` valid/0 problems; staged `tdr_bridge.release_enriched` build (validate-only, `release_id vehicle-2026-b5f8dfafb7ace1bf`); commit; publish; mark-published. STAGED-recovery steps present but skipped (no failure).
- Write commit: `f3075bdf293436c891307c8d17f111ff90a9aa8e` ("Apply 1 canonical input batch(es)", 2 files changed, 148 insertions -- `market/retail_lifecycle/trim_review.json` + the batch's own `canonical_state/input_batches` marker).
- Published release: `vehicle-2026-de68225307c3c79d`, status `ACTIVE`, `activated_at 2026-09-28T05:28:02.72003+00:00`, `published_batches: 1`.

**5. Independent verification, directly against the pulled repo, not the worker's self-report.**
- `git fetch` + `git merge --ff-only origin/main` landed exactly on `f3075bdf...`, byte-identical to the worker's reported commit.
- `vehreg market validate` re-run directly: valid, 0 problems.
- Independently rebuilt `tdr_bridge.release_enriched` from the real post-publish HEAD (own revision/as-of, not the worker's) and checked, per trim, all 17 required outcomes: the 8 named old trims (`mg_im5` standard/long-range, `mg_im6` luxury/performance, `mg_maxus_7` premium/luxury, `mg_maxus_9` model X/V) are `HISTORICAL`; the 5 REPAIR-06 new grades (`mg_im5` Premium Long Range, `mg_im6` Premium/Performance, `mg_maxus_7` X, `mg_maxus_9` V Plus) are `CURRENT`; both MG ZS EV BEV grades (`zs_ev_d_bev`/`zs_ev_x_bev`) are `CURRENT`; both MG ZS EV wrong-parent ICE rows (`d_ice`/`x_ice`) are unchanged at `UNVERIFIED` -- `FAILS: 0`.
- Directly checked `PriceLedger`/`trim_price_eligibility` against the live post-publish data for all 8 old trims plus the 2 untouched ZS EV ICE rows: every price record byte-identical to pre-REPAIR-07 (0 records for the 6 IM5/IM6/Maxus7 trims; `LIST_PRICE` 2,099,000/2,499,000 preserved for Maxus 9's X/V; `ECO_STICKER_PRICE` 949,000/1,023,000 preserved for ZS EV's D/X ICE rows), and every one of the 10 trims is `False`/`TRIM_RETIRED` for automated price matching, unchanged from before this write -- `FAILS: 0`.

**Outstanding issue: none for this batch.** MG ZS EV's `d_ice`/`x_ice` remain, as instructed, an unresolved wrong-parent identity pending a future, separately-numbered repair -- not touched, not claimed fixed.

Next: REPAIR-07 is closed. Do not re-audit, rebuild, or re-enqueue unless the user explicitly reopens it. The remaining 21-vehicle repair queue (per the historical BEV+REEV audit ordering) was explicitly not started in this operation and is separate future work. Any future MG ZS EV D/X identity resolution is a new, separately-numbered repair batch.

### REPAIR-08 membership — final unscheduled BEV+REEV queue (Step 1, 2026-09-28)

State: `QUEUED`. The owner asked to start the next repair batch while REPAIR-07 completed. The authoritative historical audit source is the owner-supplied `Markdown ที่วาง.md`, which enumerates #97–117 after REPAIR-06's final #96. This is a **16-model final repair batch**: five entries in the 21-number audit tail were already repaired in earlier frozen repair batches and must not be repeated merely to fill 20 slots. This step fixes membership only. No Step 2 inspection, new canonical write, enqueue, or publish for REPAIR-08 has occurred. Historical audit findings are queue provenance, not fresh market evidence.

Previously handled and excluded from REPAIR-08: #101 Tesla Model Y (approved current set Premium RWD/Premium Long Range RWD/Model Y L); #102 Toyota bZ4X (approved FWD/AWD set); #105 Volvo EC40 (approved Ultra Single Motor set); #107 Volvo EX40 (approved Ultra Single Motor set); #114 XPENG G6 (approved Standard Range/Long Range/AWD Performance set). These five approved sets are present in published `vehreg/data/2026/market/trims/current_retail.json` as of Step 1. Open sub-items in any frozen prior lot stay with that lot, not this membership.

| REPAIR-08 | Historical audit # | Vehicle |
|---:|---:|---|
| 01 | 97 | RIDDARA RD6 Double Cab |
| 02 | 98 | SERES 3 |
| 03 | 99 | SOKON EC35 |
| 04 | 100 | Tesla Model 3 |
| 05 | 103 | VOLT For Four |
| 06 | 104 | VOLT For Two |
| 07 | 106 | Volvo EX30 |
| 08 | 108 | Volvo EX90 |
| 09 | 109 | Volvo XC40 BEV |
| 10 | 110 | Wuling Air EV |
| 11 | 111 | Wuling Bingo |
| 12 | 112 | Wuling Darion EV |
| 13 | 113 | Wuling Porta EV |
| 14 | 115 | XPENG X9 |
| 15 | 116 | ZEEKR 009 |
| 16 | 117 | ZEEKR X |

Next: REPAIR-08 Step 2 only when the owner directs it: inspect the current enriched TDR release and Thai-market trim/old price/current list price/campaign for these exact 16, record specific holds, and do not write canonical data at inspection stage.

### REPAIR-08 Step 2 inspection (2026-09-28, corrected audit)

State: `INSPECTED`. This is a read-only audit of the current TDR catalog/serving release against Thai-market evidence checked on 2026-09-28. No canonical data, current-retail set, enqueue, or publish was changed. “Hold” means no lifecycle/price write until the named identity/orderability gap is resolved; existing specs and price history must be preserved.

| # | TDR current state | Confirmed Thai current/last-confirmed trim + price/promotion | Required action / hold |
|---:|---|---|---|
| 01 RIDDARA RD6 Double Cab | RD6 has 63/73/86kWh 2WD; separate TDR `riddara_horizon_double_cab` has 73/86kWh 4WD | MY26 RD6 is four grades: 73.9 2WD (list 999,000; Aug 21–30 offer 899,000), 86 2WD (1,159,000; offer 999,000), 73.9 4WD (1,149,000; offer 999,000), 86 4WD (1,299,000; offer 1,149,000). Booking window is closed. | Structural identity collision: Thai calls all four RD6, while TDR stores 4WD under Horizon. Do not merge/reparent blindly; prove spec/identity mapping first. No live campaign command now. |
| 02 SERES 3 | Standard / Premium | Last confirmed Thai names Comfort / Comfort Sunroof; list anchors 670,000 / 699,900. 599,200 Motor Expo offer is expired; current 2026 orderability not proven. | Alias only with spec proof; hold current lifecycle, list price, and campaign. |
| 03 SOKON EC35 | Cargo Van 2-seat / Passenger Van 5-seat | Distributor evidence supports EC35 Cargo Van; no reliable current passenger retail page or verified current price. | Preserve both histories; do not withdraw Passenger by absence alone; hold price/lifecycle. |
| 04 Tesla Model 3 | RWD / Long Range AWD / Performance AWD | Current Thailand naming/prices: Standard RWD 1,149,000; Premium RWD 1,439,000; Premium Long Range RWD 1,599,000; Performance AWD 2,099,000 (Tesla selector also exposes Premium AWD). Invitation-only Premium RWD benefit 50,000 THB, delivery by Sep 30, 2026. | Add/reconcile current Tesla grades with exact order-page identity. Do not mark old Long Range AWD historical merely because a page/inventory view omits it. Record 50k as a dated benefit only if schema supports it, not as a vehicle-price discount. |
| 05 VOLT For Four | Classic / Premium (incomplete TDR model) | Thai historical naming Classic / Top; old anchors about 385,000 / 415,000. No verified 2026 retail list or live campaign. | Possible Premium→Top rename only with identity proof; hold price/lifecycle/campaign. |
| 06 VOLT For Two | Classic / Premium (incomplete TDR model) | Thai historical naming Classic / Top; old anchors about 325,000 / 355,000. No verified 2026 retail list or live campaign. | Same hold as For Four. |
| 07 Volvo EX30 | Core Single 51kWh / Plus Single ER / Ultra Twin Performance | Current official MY26 evidence confirms Ultra Single Motor Extended Range 1,690,000. Older Core/Twin prices are historical references; current Volvo offer page omits EX30 and no live campaign was found. | Add/reconcile Ultra Single identity; do not retire old grades until direct current-set/orderability evidence. Hold campaign. |
| 08 Volvo EX90 | Twin / Twin Performance generic rows | Current three saleable combinations: Plus Twin Motor 7-seat 4,290,000; Ultra Twin Performance 6-seat 4,890,000; Ultra Twin Performance 7-seat 4,890,000. Official offer Aug 1–Oct 31, 2026: benefits up to 800,000/900,000 plus 1-year insurance. | Split seat/grade identities, preserve specs/history, add prices. Campaign is dated and grade-specific; encode benefits only in supported campaign fields. |
| 09 Volvo XC40 BEV | BEV rows mixed with ICE/PHEV siblings under XC40 | Volvo Thailand current offer/catalog uses EX40, not XC40; XC40 BEV rows are legacy-name candidates while ICE/PHEV siblings remain separate. | Prove XC40 BEV→EX40 crosswalk at trim level; remove only BEV rows from current set or mark historical as supported. Never mark whole mixed-powertrain XC40 historical. |
| 10 Wuling Air EV | Standard Range Lite 17.3kWh / Long Range 26.7kWh | Thai lineup is Standard Range 395,000 (17.3kWh) and Long Range 465,000 (26.7kWh); no verified live campaign. | Rename Lite→Standard Range after spec match; add list prices; no lifecycle withdrawal. |
| 11 Wuling Bingo | Standard 333 / Long Range 410 | Thai lineup is Standard Range 333 AC and Standard Range 333 DC (333km). Official list anchors 459,000/489,000 and launch 419,000/449,000 are historical; current third-party prices conflict. | Reconcile AC/DC identities; Long Range 410 is not supported. Hold current list price until current OEM price is resolved; do not write expired launch prices as live campaign. |
| 12 Wuling Darion EV | Model exists in TDR but is marked incomplete; generic Cargo Van / Passenger Minibus trims | Thai 7-seat Darion current regular prices Comfort 839,000 and Premium 899,000 (early-bird 799,000/859,000 ended Mar 31, 2026). | Do not create a duplicate model. Rename/reconcile the two existing trims to Comfort/Premium and complete only spec-safe fields; no live campaign. |
| 13 Wuling Porta EV | Model exists in TDR but is incomplete; Standard Box / Flatbed Carrier | Thai evidence supports one Porta cargo identity, 56.2kWh/6.5m³, list about 599,000 (629,000 package listing). No dated live campaign confirmed. | One current identity is supported; reconcile/collapse the two generic bodies only after exact body/spec proof. Preserve history; hold package-vs-list semantics. |
| 14 XPENG X9 | TDR old-generation Pro / Max / Performance | Current “The New X9” has Premium 2,399,000; Executive 2,599,000; Luxury AWD 2,799,000. Official Sep 1–30, 2026 promotion: 2-year insurance, wallbox, portable charger, 9,000 MobiLife points, subject to booking/delivery terms. | Add new-generation identities; do not overwrite old IDs across generations. Preserve old history. Encode dated benefits only where campaign schema supports them. |
| 15 ZEEKR 009 | TDR Luxury 6-seat / Grand 4-seat | Current standard 009 identities: Standard 7-seat 2,399,000; Premium AWD 7-seat 3,099,000; Flagship AWD 6-seat 3,159,000. Grand 4-seat is separate; no confirmed current list price. Sep 1–30, 2026 offer applies to Premium/Flagship with warranty/maintenance/charging benefits. | Rename Luxury→Flagship only with spec proof; add Standard/Premium as distinct IDs; keep Grand separate. Do not attach 009 campaign to Standard/Grand without evidence. |
| 16 ZEEKR X | Standard RWD / Long Range RWD / Flagship AWD | MY26 has only Standard RWD 899,000 and Flagship AWD 1,069,000; Long Range RWD is not in the current two-trim lineup. Zeekr Sep 1–30, 2026 offer page includes X; exact X benefit fields must be read from the offer terms before writing. | Add/confirm prices for Standard/Flagship. Hold Long Range lifecycle until direct orderability/spec evidence; do not invent campaign values from 009 terms. |

Source/evidence boundary: only dated, grade-specific evidence may become a campaign command. Expired Motor Expo/launch offers and financing/gifts cannot be written as numeric vehicle-price campaigns. Current structural blockers are the RD6-versus-Horizon identity collision, XC40 BEV→EX40 crosswalk, generation splits for XPENG/ZEEKR, and exact Wuling Porta body identity. Next step is Step 3 implementation prompt from this corrected table; no canonical write is approved.

### REPAIR-08 Step 3 draft (2026-09-28)

State: `PROMPT_READY` -- draft batch built and validated on a disposable copy; no enqueue, no canonical write, no publish, no merge. Draft `batch_id ev-retail-repair-lot-08-2026-09-28`, 40 commands (`UPSERT_MODEL_BUNDLE` x7, `APPEND_PRICE` x21, `UPSERT_CAMPAIGN` x9, `REPLACE_CURRENT_RETAIL_SET` x3; no `CORRECT_PRICE`, no `UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW` used this round). Applied cleanly via `CanonicalInputPipeline.apply()` against a disposable copy of `vehreg/data` (status APPLIED, 71 changed files), `vehreg market validate` returned valid/0 problems, and the full production/lifecycle focused gate (98 tests: the 7-file production gate + `test_trim_retail_lifecycle_review.py` + `test_current_retail_set.py` + `test_retail_scope.py`) passed 98/98 unchanged. A staged `tdr_bridge.release_enriched` before/after build confirmed: +10 new market_trims (exactly the 10 genuinely new grades below), 0 removed trims, +21 price_ledger rows (exactly the 21 `APPEND_PRICE` commands), +1 generation (XPeng X9's new `gen2`), models count unchanged at 323 (no new model created), and exactly 3 pre-existing trims flip `CURRENT -> UNVERIFIED` (Tesla's old Long Range AWD 78.1kWh, EX90's old seat-unlabeled Performance 517hp, Zeekr 009's Grand 4-Seater VIP) -- all three fully preserved (canonical_id/specs/price history untouched), none marked HISTORICAL. Every full-hold item (SERES 3, SOKON EC35, VOLT For Four, VOLT For Two, Wuling Bingo, RIDDARA Horizon 4WD, Volvo XC40+EX40 entirely, Zeekr X's Long Range RWD) is byte-identical before/after, independently confirmed. Old, superseded price rows on trims that received a new `APPEND_PRICE` (Tesla RWD/Performance, Zeekr X Standard/Flagship, Zeekr 009 Luxury/Flagship) are preserved unretracted; the new dated row supersedes only for current-price resolution.

**Source-evidence limitation, disclosed:** none of this round's 21 `APPEND_PRICE`/9 `UPSERT_CAMPAIGN` commands carry an external http(s) `source_ref` -- the owner's Step 3 brief gave figures directly in chat with no per-item URLs (unlike REPAIR-06). Every such command's `source_ref` is `docs/WORK_STATE.md#REPAIR-08` (this record), and each command's own `reason` states the figure came from the owner's audit brief. This is flagged for the owner's awareness before Step 4 approval, not silently substituted with a fabricated URL.

**Per-item command accounting:**
- 01 RIDDARA RD6: 1 command (`APPEND_PRICE` RD6 2WD Max 86kWh LIST 1,159,000). 2WD Plus already matches (999,000, no command). 2WD Lite not in the MY26 table (untouched). 4WD/Horizon: HELD -- `riddara_horizon_double_cab` is a structurally distinct model (gen1 variant-level drivetrain AWD vs RD6's RWD, launched 2025-11-01 vs 2024-09-01, distinct owner_directory rows), and neither 4WD trim carries any comparable-spec fact to prove or disprove the MY26 mapping. No campaign (booking window 21-30 Aug 2026 already expired).
- 02 SERES 3: 0 commands, full hold (rename unproven by spec; price is "approximately"; owner's own brief admits 2026 orderability is unproven; promo expired anyway).
- 03 SOKON EC35: 0 commands, full hold (preserve both trims; no lifecycle/price evidence to act on).
- 04 Tesla Model 3: 7 commands -- `UPSERT_MODEL_BUNDLE` materializes Premium RWD and Premium Long Range RWD (genuinely new, not matching any existing trim's name or spec); `APPEND_PRICE` x4 (Standard RWD 1,149,000, Premium RWD 1,439,000, Premium Long Range RWD 1,599,000, Performance AWD 2,099,000); `REPLACE_CURRENT_RETAIL_SET` restricts the model to these 4 grades, excluding the pre-refresh Long Range AWD (78.1kWh, AWD drivetrain -- structurally distinct from the new RWD-only tiers) which is preserved, not historical; `UPSERT_CAMPAIGN` records Premium RWD's invitation-only benefit as metadata (gifts/notes), no CAMPAIGN_PRICE. JUDGMENT CALL flagged: Standard RWD's and Performance AWD's own on-file LIST_PRICE (both dated 2026-09-14, from `owner_pricing_directory`) conflict with the brief's current figures (1,599,000 vs 1,149,000; 2,199,000 vs 2,099,000) -- neither was corrected/overwritten; the brief's figures were appended as newer-dated observations that supersede for current-price resolution while both older rows are fully preserved as history.
- 05 VOLT For Four: 0 commands, full hold.
- 06 VOLT For Two: 0 commands, full hold.
- 07 Volvo EX30: 2 commands -- `UPSERT_MODEL_BUNDLE` materializes Ultra Single Motor Extended Range (genuinely new); `APPEND_PRICE` 1,690,000. Core/Plus/Twin untouched, and deliberately NOT placed into an approved current-retail set (orderability not proven at trim level per the brief), so all four trims remain individually CURRENT under the existing legacy default.
- 08 Volvo EX90: 7 commands -- `UPSERT_MODEL_BUNDLE` renames the unambiguous 408hp trim to Plus Twin Motor 7-Seat (price already correct, no price command) and materializes 2 new seat-specific Ultra Performance trims (6-seat, 7-seat); `APPEND_PRICE` x2 (4,890,000 each); `REPLACE_CURRENT_RETAIL_SET` restricts to these 3, excluding the old, seat-unlabeled 517hp Performance trim (preserved, not renamed -- assigning it a seat count would have been a guess); `UPSERT_CAMPAIGN` x3, one per current trim, recording the Aug1-Oct31 benefit/insurance as metadata only, no CAMPAIGN_PRICE.
- 09 Volvo XC40 BEV: 0 commands, full hold. Investigative finding (not acted on): XC40's "Pure Electric Single Motor" trim's recorded body dimensions (4440x1863x1647mm) are an exact match to EX40's currently-approved-current "EX40 Ultra – Single Motor" trim (same 4440x1863x1647mm) -- a real, repo-internal signal that these may be the same rebadged vehicle. TENSION FLAGGED: the corrected Step 2 record above names "remove only BEV rows from current set... as supported" as a possible action once the crosswalk is proven; the live Step 3 instruction for this draft authorized only "check the crosswalk, hold if unprovable" without an explicit if-provable instruction, so no `REPLACE_CURRENT_RETAIL_SET` was written here -- surfaced for the owner to decide whether this finding should become a write in a future revision, rather than Claude deciding unilaterally. ICE/PHEV siblings (`b4_mild_hybrid_*`, `*_plug_in_hybrid_*`) and both models entirely: byte-identical before/after.
- 10 Wuling Air EV: 3 commands -- `UPSERT_MODEL_BUNDLE` renames Standard Range Lite → Standard Range (id preserved; unique spec match, no other candidate); `APPEND_PRICE` x2 (395,000 / 465,000).
- 11 Wuling Bingo: 0 commands, full hold (no spec facts on file to reconcile by AC/DC; no confirmed current OEM price; both old figures and expired promo excluded exactly as instructed).
- 12 Wuling Darion EV: 3 commands -- `UPSERT_MODEL_BUNDLE` renames Cargo Van → Comfort and Passenger Minibus → Premium (ids preserved, no new model); `APPEND_PRICE` x2 (839,000 / 899,000). JUDGMENT CALL flagged: the Cargo Van→Comfort / Passenger Minibus→Premium pairing is inferred from price ordering alone (cheaper=Comfort, pricier=Premium) -- no trim-level spec evidence exists in the catalog to independently confirm it.
- 13 Wuling Porta EV: 1 command -- `APPEND_PRICE` 599,000 on Standard Box only. JUDGMENT CALL flagged: attributed to Standard Box (enclosed body) rather than Flatbed Carrier because an enclosed 6.5m3 cargo volume describes a box body, not an open flatbed -- no catalog spec data to independently confirm. Flatbed Carrier and full trim consolidation are both HELD (no body/spec facts exist to prove one identity); 629,000 package price deliberately not written as LIST_PRICE.
- 14 XPeng X9: 7 commands -- `UPSERT_MODEL_BUNDLE` creates a brand-new generation `gen2` (structurally separate from `gen1`) with 3 new trims (Premium, Executive, Luxury AWD); `APPEND_PRICE` x3 (2,399,000 / 2,599,000 / 2,799,000); `UPSERT_CAMPAIGN` x3 (one per new trim, identical benefit text) recording the Sep 2026 gift bundle as metadata only, no CAMPAIGN_PRICE. `gen1` (Long Range Pro/Max, Performance AWD Ultra) is entirely untouched -- no price/spec/history overwritten, none marked historical.
- 15 Zeekr 009: 7 commands -- `UPSERT_MODEL_BUNDLE` renames the 6-seat Luxury trim → Flagship AWD 6-Seat (seat count is the identity signal, distinguishing it from the 7-seat Premium AWD grade) and materializes Standard 7-Seat and Premium AWD 7-Seat; `APPEND_PRICE` x3 (2,399,000 / 3,099,000 / 3,159,000); `REPLACE_CURRENT_RETAIL_SET` restricts to these 3 standard-009 grades. JUDGMENT CALL flagged: excluding Grand 4-Seater VIP from the approved set was not spelled out in so many words by the brief, but is consistent with the brief's own characterization of Grand's current price as unconfirmed; Grand is fully preserved, not renamed, not priced. A second conflict, same shape as Tesla's: the renamed Flagship AWD 6-Seat's existing on-file LIST_PRICE (3,099,000, 2026-09-14) coincidentally matches Premium AWD 7-Seat's price rather than Flagship's target 3,159,000 -- not corrected, appended as a newer-dated row, old one preserved, flagged. `UPSERT_CAMPAIGN` x2 (Premium 7-seat, Flagship 6-seat) recording the Sep 2026 benefit bundle as metadata only; none on Standard or Grand.
- 16 Zeekr X: 2 commands -- `APPEND_PRICE` x2 (Standard RWD 899,000, Flagship AWD 1,069,000). Same owner_pricing_directory (2026-09-14) LIST_PRICE conflict pattern as Tesla/Zeekr 009 for both trims (1,199,000/1,349,000 on file) -- not corrected, appended as newer-dated rows, old ones preserved, flagged. No campaign (X-specific terms unconfirmed, explicitly forbidden from borrowing 009's). Long Range RWD: fully held, no command.

Full draft batch JSON, the 16-item table above, and the validation/diff results were delivered to the owner in-chat.

Next: await the owner's separate Step 4 approval for this 40-command batch. Do not enqueue, write to real canonical data, merge, or publish before that. The remaining vehicles in the historical BEV+REEV audit queue were explicitly out of scope for this operation and are not started.

### REPAIR-08 Step 3 draft, corrected (2026-09-28b)

State: still `PROMPT_READY` -- corrected draft batch built and validated on a disposable copy; no enqueue, no canonical write, no publish, no merge. New `batch_id ev-retail-repair-lot-08-2026-09-28b`, **6 commands, all `UPSERT_MODEL_BUNDLE`** (down from the v1 draft's 40). The owner reviewed v1 and found it too permissive in two ways this round corrects: (a) several price/campaign commands cited `source_ref: docs/WORK_STATE.md#REPAIR-08` -- a self-reference back to our own summary, not genuine external evidence; (b) three `REPLACE_CURRENT_RETAIL_SET` commands excluded an old trim from current status (Tesla's Long Range AWD, EX90's seat-unlabeled 517hp trim, Zeekr 009's Grand 4-Seater VIP) with no direct orderability evidence that trim is actually discontinued -- absence of a confirmed current price is not such evidence. Applied cleanly via `CanonicalInputPipeline.apply()` against a disposable copy (status APPLIED, 14 changed files), `vehreg market validate` valid/0 problems, focused gate 98/98 passed unchanged. Staged `tdr_bridge.release_enriched` before/after: +11 new market_trims (exactly the 11 identity-only additions below), **0 removed trims, 0 status changes on any pre-existing trim, 0 price changes anywhere** (price_ledger count unchanged at 983 -- this round writes zero prices), +1 generation (XPeng's `gen2`, unchanged from v1).

**What changed vs. v1, per item:**
- 01 RIDDARA RD6: `APPEND_PRICE` for 2WD Max (1,159,000) REMOVED -- no direct source_ref. Now a full hold (was 1 command, now 0).
- 04 Tesla Model 3: kept the `UPSERT_MODEL_BUNDLE` materializing Premium RWD and Premium Long Range RWD, and ADDED a third new identity, **Premium AWD** (catalog-checked absent before this batch; Step 2 itself notes Tesla's selector still exposes it, which v1 had omitted), all three with NO price. REMOVED: all 4 `APPEND_PRICE` commands (Standard RWD/Performance AWD conflict with an existing dated 2026-09-14 record and neither round has a source URL to resolve it; Premium RWD/Premium Long Range RWD never had one either), the `REPLACE_CURRENT_RETAIL_SET` excluding Long Range AWD (no orderability evidence, and Premium AWD was not yet even handled), and the Premium RWD benefit `UPSERT_CAMPAIGN` (no direct source_ref). Net: 7 commands -> 1.
- 07 Volvo EX30: kept the identity bundle (Ultra Single Motor Extended Range); REMOVED its `APPEND_PRICE` (1,690,000, no direct source_ref). Net: 2 -> 1.
- 08 Volvo EX90: kept the identity bundle, rewritten to reference ONLY the rename (Plus Twin Motor 7-Seat, price already correct on file) and the 2 new Ultra seat-specific trims -- the old, seat-unlabeled 517hp trim is no longer referenced by any command AT ALL (not even to restate its name unchanged), for zero risk to its status. REMOVED: both new-trim `APPEND_PRICE`s, all 3 `UPSERT_CAMPAIGN`s (no direct source_ref), and the `REPLACE_CURRENT_RETAIL_SET` that had excluded the old trim (no orderability evidence). Net: 7 -> 1.
- 10 Wuling Air EV: kept the rename bundle (Standard Range Lite -> Standard Range, unique spec match, unaffected by the source_ref rule since it carries no price); REMOVED both `APPEND_PRICE`s (395,000/465,000, no direct source_ref). Net: 3 -> 1.
- 12 Wuling Darion EV: REMOVED ENTIRELY -- re-checked comparable-spec facts for both trims directly against the real catalog (confirmed again: 0 facts on file for either), so the Cargo Van->Comfort / Passenger Minibus->Premium mapping remains unproven by spec, exactly the condition under which the owner's correction says to drop the bundle and both prices and record a full hold. Net: 3 -> 0.
- 13 Wuling Porta EV: REMOVED ENTIRELY -- the Standard Box `APPEND_PRICE` (599,000) is dropped per instruction; the trim-to-identity attribution was always a judgment call, and the price itself lacked a direct source_ref regardless. Full hold; both trims (Standard Box, Flatbed Carrier) untouched, no consolidation. Net: 1 -> 0.
- 14 XPeng X9: kept the identity bundle (new generation `gen2` with Premium/Executive/Luxury AWD, `gen1` fully untouched); REMOVED all 3 `APPEND_PRICE`s and all 3 `UPSERT_CAMPAIGN`s (no direct source_ref). Net: 7 -> 1.
- 15 Zeekr 009: kept the identity bundle, rewritten to reference ONLY the rename (Flagship AWD 6-Seat -- 6-seat count is an unambiguous identity signal, not a price-ordering guess) and the 2 new standard-009 trims -- Grand 4-Seater VIP is no longer referenced by any command at all, for zero risk to its status. REMOVED: all 3 `APPEND_PRICE`s, both `UPSERT_CAMPAIGN`s (no direct source_ref), and the `REPLACE_CURRENT_RETAIL_SET` that had excluded Grand (absence of a confirmed price is not orderability evidence). Net: 7 -> 1.
- 16 Zeekr X: both `APPEND_PRICE`s (899,000/1,069,000) REMOVED -- no direct source_ref (this item was not explicitly named in the owner's per-item correction list, but the general source_ref rule applies to every remaining command batch-wide, so it is held on the same basis as RD6/Air EV/XPeng). Now a full hold (was 2 commands, now 0).
- Unchanged, still full holds with 0 commands: 02 SERES 3, 03 SOKON EC35, 05/06 VOLT For Four/Two, 09 Volvo XC40 BEV, 11 Wuling Bingo.

**Net result: every surviving command is identity-only (`UPSERT_MODEL_BUNDLE`, no price attached), for exactly the 6 items where Step 2's own recorded findings already establish the identity without requiring a price citation** (a unique spec match, a confirmed seat-count signal, or materializing a brand-new grade name Step 2 itself names). Zero `APPEND_PRICE`, zero `CORRECT_PRICE`, zero `UPSERT_CAMPAIGN`, zero `REPLACE_CURRENT_RETAIL_SET` in this corrected draft. No old trim was made `UNVERIFIED` by any current-set exclusion this round; no ICE/HEV/PHEV sibling was touched (none were in scope); no trim with price history was touched at all (the only trims that received any command this round -- Tesla's RWD/Performance-AWD/Long-Range-AWD, EX90's two named trims, Zeekr 009's Flagship/Grand -- either received a pure rename with an unchanged canonical_id and no payload price field, or were referenced by nothing whatsoever).

Full corrected draft batch JSON and the re-verified per-item table were delivered to the owner in-chat.

Next: await the owner's separate Step 4 approval for this corrected 6-command batch. Do not enqueue, write to real canonical data, merge, or publish before that.

### REPAIR-08 Step 3 draft, corrected again (2026-09-28c)

State: still `PROMPT_READY` -- second-corrected draft batch built and validated on a disposable copy; no enqueue, no canonical write, no publish, no merge. New `batch_id ev-retail-repair-lot-08-2026-09-28c`, still **6 commands, all `UPSERT_MODEL_BUNDLE`**. The owner found two remaining problems in v2 and one imprecise verification claim, without asking for a re-audit of the 16 vehicles.

**1. Tesla Model 3 -- dropped "Premium AWD".** v2 materialized "Premium AWD" as a brand-new trim on the strength of Step 2 noting Tesla's selector still exposes it. Checked directly against the real catalog this round: the existing "Long Range All-Wheel Drive (AWD, 78.1 kWh)" trim has **zero comparable-spec facts on file** -- the same nothing "Premium AWD" itself has. With no battery/power/spec data for either, there is no way to prove "Premium AWD" is a genuinely distinct grade rather than simply a newer marketing name for that same existing AWD trim; materializing it as a new trim risked creating a duplicate identity for one real vehicle. Dropped entirely, held pending real mapping/orderability evidence. Premium RWD and Premium Long Range RWD are unaffected (RWD, structurally distinct from the AWD trims, no such ambiguity) and remain in the batch. No `REPLACE_CURRENT_RETAIL_SET` was ever reinstated (unchanged from v2) -- Long Range AWD, Standard RWD and Performance AWD all stay CURRENT by the existing legacy default, untouched.

**2. Volvo EX90 -- dropped the Ultra 6-Seat/7-Seat split entirely.** v2's identity bundle added the two new seat-specific Ultra trims while leaving the old, seat-unlabeled "Twin Motor Performance AWD (517 hp)" trim completely untouched (no current-retail-set exists for EX90, so it stayed CURRENT by legacy default too). Net effect, confirmed directly against the staged release: EX90 showed **4 CURRENT trims** (renamed 408hp + untouched 517hp + both new Ultra trims) against Step 2's own recorded **3** current saleable combinations -- an overcount the owner caught. The 517hp trim's seat count is not on file anywhere, so it cannot be mapped to either the 6-seat or 7-seat Ultra grade with evidence, and adding two more CURRENT trims on top of an unmapped old one only compounds the overcount rather than resolving it. The entire Ultra split is now HELD, not guessed at. Only the unambiguous rename (existing 408hp trim -> Plus Twin Motor 7-Seat; Step 2's own price figure already matches the on-file LIST_PRICE exactly) survives -- a pure relabel that does not change how many EX90 trims are CURRENT. Confirmed on the re-verified staged release: EX90 now shows exactly 2 CURRENT trims (Plus Twin Motor 7-Seat, and the untouched 517hp trim), matching the real catalog's actual trim count, not Step 2's separate "3 saleable combinations" claim about a lineup this draft does not yet fully resolve.

**3. Zeekr 009 -- corrected wording only, no command change.** The commands are identical to v2 (rename Luxury 6-Seat -> Flagship AWD 6-Seat; add Standard 7-Seat and Premium AWD 7-Seat, all without price; Grand 4-Seater VIP referenced by nothing). What changed is the prose: v2's phrasing ("current standard-009 showroom lineup is these 3 grades") risked being read as though Grand's non-current status were somehow established, when it is not -- no command ever touches Grand, and it remains CURRENT by the existing legacy default exactly as before this batch. Corrected to state plainly: **after this command, Zeekr 009 shows four CURRENT trims, Grand included** -- Flagship AWD 6-Seat, Standard 7-Seat, Premium AWD 7-Seat, and Grand 4-Seater VIP -- and Grand's own real-world orderability remains completely unresolved, not confirmed one way or the other. Confirmed directly on the re-verified staged release: exactly 4 CURRENT trims for this model, Grand's canonical_id/specs/price-history (it has none on file) fully untouched.

**4. WORK_STATE verification wording corrected.** The v2 record's claim that "no trim with price history was touched" was imprecise and, for one clause, wrong: it implied Tesla's existing RWD/Performance-AWD/Long-Range-AWD trims had "received a pure rename," when in fact none of them were referenced by any v2 command at all. Corrected statement of fact for this (and the prior) draft: every trim that IS referenced by a command in this batch is either (a) a brand-new trim with no price history to begin with (Tesla's 2 new RWD tiers, EX30's Ultra Single Motor ER, XPeng's 3 gen2 trims, Zeekr 009's Standard/Premium AWD 7-Seat), or (b) an existing trim renamed with its canonical_id and full price-ledger history completely preserved -- confirmed directly, zero price-ledger rows changed for any of them (EX90's Plus Twin Motor 7-Seat: LIST_PRICE 4,290,000 untouched; Wuling Air EV's Standard Range: unpriced, untouched; Zeekr 009's Flagship AWD 6-Seat: LIST_PRICE 3,099,000 untouched). No trim is referenced by any command in this batch without falling into one of those two categories, and price_ledger row count is unchanged at 983 in the staged release, confirming zero price writes anywhere.

**Validation, repeated in full:** `CanonicalInputPipeline.apply()` on a fresh disposable copy: APPLIED, 14 changed files. `vehreg market validate`: valid, 0 problems. Focused gate: 98/98 passed. Staged `tdr_bridge.release_enriched` before/after: **+8 new market_trims** (down from v2's 11 -- Premium AWD and both Ultra seat trims removed), **0 removed trims, 0 status changes on any pre-existing trim, 0 price changes anywhere** (price_ledger unchanged at 983). Directly confirmed CURRENT-trim counts per affected model on the re-verified release: Tesla 5 (RWD, Long Range AWD, Performance AWD, Premium RWD, Premium Long Range RWD), Volvo EX90 2 (Plus Twin Motor 7-Seat, the untouched 517hp trim), Zeekr 009 4 (Flagship AWD 6-Seat, Standard 7-Seat, Premium AWD 7-Seat, Grand 4-Seater VIP).

**Owner review correction (2026-09-28): Step 3 is incomplete against the approved 16-item Step 2 scope.** The v3 file contains only 6 identity bundles, covers 6 vehicles, and contains **zero price commands and zero campaign commands**. The other 10 vehicles have no write commands. Therefore it cannot be called a completed REPAIR-08 draft or advanced to Step 4 approval. Continue Step 3 by completing the 1:1 trim/old price/current LIST_PRICE/current promotion accounting for all 16 vehicles, using direct evidence for each price/campaign; retain explicit holds only where evidence or identity mapping is genuinely unresolved. The 6 identity changes in v3 remain a partial draft, not a substitute for the missing price/promotion work.

Full second-corrected draft batch JSON was delivered to the owner in-chat.

Next: continue Step 3 and complete the missing per-vehicle trim, price, and promotion work. Do not request Step 4 approval, enqueue, write to real canonical data, merge, or publish while the 16-item scope remains incomplete.

### REPAIR-08 Step 3 draft, corrected (Tesla resolved) and completed to full 16-item scope (2026-09-28d/e)

State: still `PROMPT_READY` -- no enqueue, no canonical write, no publish, no merge. Two rounds folded into one record since the first was not yet committed when the owner's incompleteness correction (above) landed.

**Round d -- Tesla "Premium AWD" resolved by owner-supplied evidence.** The owner supplied two real URLs in chat (`https://autolifethailand.tv/tesla-model-3-standard-premium-2026/` and a Tesla Thailand dealer Facebook post on the Model Y naming change), explaining that Tesla Thailand's current "Premium" naming is a rebrand of the existing lineup on the same underlying spec (same AWD drivetrain, same long-range performance basis), not a new tier. This directly resolves the v3 hold: rather than materializing "Premium AWD" as a new trim (duplicate-identity risk, the reason v3 held it) or leaving it held, the existing `tesla.model3.m3h.trim.long_range_all_wheel_drive_awd_78_1_kwh_bev` trim is RENAMED to "Premium AWD" -- same id/canonical_id preserved, its on-file LIST_PRICE 1,899,000 (observed 2026-09-14) left completely untouched, same rename pattern already used for EX90's Plus Twin Motor 7-Seat and Zeekr 009's Flagship AWD 6-Seat. Premium RWD and Premium Long Range RWD are unaffected (the evidence addressed only the AWD grade). No `REPLACE_CURRENT_RETAIL_SET` issued. Validated in isolation: `CanonicalInputPipeline.apply()` APPLIED (14 changed files), `vehreg market validate` valid/0 problems, focused gate 98/98. Staged diff confirmed +8 new trims (Premium RWD, Premium Long Range RWD, EX30's Ultra Single Motor ER, XPeng's 3 gen2 trims, Zeekr 009's Standard/Premium AWD 7-Seat), 0 removed, 4 renames (Tesla AWD->Premium AWD, EX90, Air EV, Zeekr 009 Flagship), 0 price_ledger changes (983 unchanged) -- the renamed Tesla AWD trim's own LIST_PRICE row confirmed byte-identical before/after. CURRENT-trim counts re-verified: Tesla 5, EX90 2, Zeekr 009 4 (unchanged from v3).

**Round e -- completed the full 16-item price/campaign scope per the owner's incompleteness correction.** New `batch_id ev-retail-repair-lot-08-2026-09-28e`, **28 commands** (`UPSERT_MODEL_BUNDLE` x6 -- unchanged from round d -- `APPEND_PRICE` x16, `UPSERT_CAMPAIGN` x6; still zero `REPLACE_CURRENT_RETAIL_SET`, zero `CORRECT_PRICE`, zero `UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW`). Every price/campaign command's `source_ref` cites the specific frozen record `docs/WORK_STATE.md#repair-08-step-2-inspection-2026-09-28-corrected-audit` plus the row number for that vehicle -- this is the owner's own corrected, frozen Step 2 audit table (a real evidentiary record of the owner's confirmed Thai-market checks), not a circular pointer back to this Step 3 draft's own restatement, which is what the original v2 self-reference objection was about.

**Per-item accounting for the 10 previously price/campaign-untouched vehicles, plus what changed for the 6 that already had identity bundles:**
- 01 RIDDARA RD6: +1 `APPEND_PRICE` (2WD Max 86 kWh, LIST 1,159,000 -- was unpriced). 2WD Plus already matched (999,000, no command). 2WD Lite untouched (not in the MY26 4-grade table). Horizon 4WD (both trims): still HELD -- structural identity collision unresolved, no comparable-spec facts to prove or disprove the mapping. No campaign (booking window expired).
- 02 SERES 3, 03 SOKON EC35, 05 VOLT For Four, 06 VOLT For Two, 09 Volvo XC40 BEV, 11 Wuling Bingo: unchanged, still full holds, 0 commands -- Step 2 itself records these as unresolved (unproven rename/orderability, no reliable current price, EX40 crosswalk unproven, AC/DC identity + current OEM price unresolved).
- 12 Wuling Darion EV, 13 Wuling Porta EV: unchanged, still full holds, 0 commands -- re-confirmed 0 comparable-spec facts on file for either Darion trim; Porta's body/spec identity remains unprovable. Per the owner's own v2 instruction, both stay fully removed rather than guessed at.
- 04 Tesla Model 3: identity bundle unchanged from round d. +4 `APPEND_PRICE` (Standard RWD 1,149,000 -- matches this trim's own on-file ECO_STICKER_PRICE exactly, conflicts with its 2026-09-14 LIST_PRICE of 1,599,000, appended not corrected, flagged; Premium RWD 1,439,000, new trim, no conflict; Premium Long Range RWD 1,599,000, new trim, no conflict; Performance AWD 2,099,000 -- matches its own on-file ECO_STICKER_PRICE exactly, conflicts with its 2026-09-14 LIST_PRICE of 2,199,000, appended not corrected, flagged) + 1 `UPSERT_CAMPAIGN` (Premium RWD invitation-only 50,000 THB benefit, metadata only, no CAMPAIGN_PRICE). Still no `REPLACE_CURRENT_RETAIL_SET`.
- 07 Volvo EX30: identity bundle unchanged. +1 `APPEND_PRICE` (Ultra Single Motor Extended Range 1,690,000, new trim, no conflict). Core/Plus/Twin untouched, still individually CURRENT by legacy default. No campaign (Step 2 found none).
- 08 Volvo EX90: identity bundle unchanged (Ultra 6/7-Seat split still HELD -- old 517hp trim's seat count remains unrecorded). No new price command (rename target's on-file price already matches). No campaign either this round: Step 2's 800,000/900,000 benefit figures are given per-grade but the mapping to specific grades isn't stated explicitly, and with the Ultra split itself unresolved there is no way to confirm which figure (if any) attaches to Plus Twin Motor 7-Seat without guessing -- held pending clearer evidence.
- 10 Wuling Air EV: identity bundle unchanged. +2 `APPEND_PRICE` (Standard Range 395,000, Long Range 465,000 -- both new price rows, no conflicts, no existing rows). No campaign (Step 2 found none).
- 14 XPeng X9: identity bundle unchanged. +3 `APPEND_PRICE` (Premium 2,399,000, Executive 2,599,000, Luxury AWD 2,799,000 -- all new trims, no conflicts) + 3 `UPSERT_CAMPAIGN` (one per gen2 trim, Sep 2026 gift bundle, metadata only, no CAMPAIGN_PRICE). gen1 untouched.
- 15 Zeekr 009: identity bundle unchanged (Grand still untouched/unresolved). +3 `APPEND_PRICE` (Standard 7-Seat 2,399,000, Premium AWD 7-Seat 3,099,000 -- both new trims, no conflicts; Flagship AWD 6-Seat 3,159,000 -- conflicts with its existing 2026-09-14 LIST_PRICE of 3,099,000, which coincidentally matches Premium AWD 7-Seat's new price instead, appended not corrected, flagged) + 2 `UPSERT_CAMPAIGN` (Premium AWD 7-Seat, Flagship AWD 6-Seat -- warranty/maintenance/charging benefits, metadata only, no CAMPAIGN_PRICE; none on Standard or Grand). Still no `REPLACE_CURRENT_RETAIL_SET` -- Grand remains CURRENT by legacy default, unresolved.
- 16 Zeekr X: no identity bundle needed (existing trim names already match). +2 `APPEND_PRICE` (Standard RWD 899,000 -- conflicts with existing 2026-09-14 LIST_PRICE of 1,199,000, appended not corrected, flagged; Flagship AWD 1,069,000 -- conflicts with existing 2026-09-14 LIST_PRICE of 1,349,000, same treatment). No campaign (X-specific terms not confirmed in enough detail; explicitly not borrowing 009's). Long Range RWD: still HELD -- Step 2's "not in the current two-trim lineup" note is not, by itself, direct orderability evidence of discontinuation.

**Validation:** `CanonicalInputPipeline.apply()` on a fresh disposable copy: APPLIED, 55 changed files. `vehreg market validate`: valid, 0 problems. Focused gate: 98/98 passed. Staged `tdr_bridge.release_enriched` before/after: **+8 new market_trims** (unchanged from round d), **0 removed trims**, **4 renames** (unchanged from round d), **+16 price_ledger rows exactly matching the 16 `APPEND_PRICE` commands, 0 existing price rows removed or amount-changed** (price_ledger 983 -> 999; every conflicting existing row independently confirmed still present with its original amount -- no `CORRECT_PRICE` used anywhere), **+6 campaign records across 3 new brand campaign files** (tesla.json, xpeng.json, zeekr.json), each inspected directly and confirmed to carry only `gifts`/`notes`/`conditions.text` fields -- no `price` or discount field of any kind. CURRENT-trim counts re-verified directly on the release: RIDDARA RD6 5 (Horizon's 2 trims separate, untouched), Tesla 5, Volvo EX30 4, Volvo EX90 2, Wuling Air EV 2, XPeng X9 6, Zeekr 009 4, Zeekr X 3.

Full v5 batch JSON, the complete 16-item table, and validation/diff results were delivered to the owner in-chat.

Next: await the owner's separate Step 4 approval for this 28-command batch, now covering full 1:1 price/campaign accounting for all 16 members with 8 explicit full holds and 3 partial holds (RIDDARA Horizon 4WD, EX90's Ultra split + its campaign, Zeekr X's Long Range RWD). Do not enqueue, write to real canonical data, merge, or publish before that.

### REPAIR-08 Step 3 draft, extended with owner-supplied Wuling evidence (2026-09-28f)

State: still `PROMPT_READY` -- no enqueue, no canonical write, no publish, no merge. New `batch_id ev-retail-repair-lot-08-2026-09-28f`, **36 commands** (`UPSERT_MODEL_BUNDLE` x8, `APPEND_PRICE` x21, `UPSERT_CAMPAIGN` x6, `REPLACE_CURRENT_RETAIL_SET` x1; still zero `CORRECT_PRICE`, zero `UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW`). Extends round e/v5 (unchanged: RIDDARA, Tesla, EX30, EX90, Air EV, X9, Zeekr 009, Zeekr X commands all identical to the prior record).

**Owner supplied a current-lineup table directly in chat** for 3 previously-held vehicles, with an explicit instruction not to re-audit or re-research:
- **Wuling Bingo (Binguo EV):** 2 trims, LITE 369,000 / PRO 389,000. Renamed the 2 existing trims in place (`standard_range_333_km_bev` -> LITE, `long_range_410_km_bev` -> PRO, both ids preserved) + `APPEND_PRICE` x2. The LITE/PRO-to-existing-id mapping is a disclosed judgment call (cheaper/base -> LITE, pricier/longer-range -> PRO by naming convention), not independently spec-verified, per the owner's explicit no-re-audit instruction. Supersedes the prior full hold (Step 2's AC/DC identity question).
- **Wuling Starlight Darion EV:** 2 trims, Comfort 839,000 / Premium 899,000 -- the exact same Cargo Van->Comfort / Passenger Minibus->Premium pairing v1/v2 held for lack of independent spec proof. The owner has now directly confirmed this pairing and price by name in chat, so it proceeds as an owner-directed override of that hold, not a fresh guess. Renamed both existing trims in place (ids preserved) + `APPEND_PRICE` x2. Supersedes the prior full hold.
- **Wuling Porta EV:** 1 current trim, 56.2 kWh / 6.5 m3, 599,000 -- identified as the enclosed "Standard Box" trim (box body, not open flatbed), same identification as the original v1 judgment call. `APPEND_PRICE` on Standard Box + `REPLACE_CURRENT_RETAIL_SET` restricting the model to Standard Box only (source_ref empty, valid per schema). This is the first REPLACE_CURRENT_RETAIL_SET issued anywhere in REPAIR-08: unlike every prior case (Tesla, EX90, Zeekr 009) where an old trim was excluded only on an *inferred* absence of a current price, here the owner directly stated the current lineup size is 1 (not 2) -- a direct statement of current-retail fact, not an inference, which is what the v2/v3 correction required before any such exclusion. Flatbed Carrier resolves to UNVERIFIED (not HISTORICAL -- no http(s) source exists for a lifecycle-review write), fully preserved: canonical_id, specs, and its (nonexistent) price history untouched.

**Owner also asked SERES 3, SOKON EC35, VOLT For Four, VOLT For Two and Volvo XC40 BEV be marked HISTORICAL this round -- BLOCKED at the code level, not by discretion.** `_validate_trim_lifecycle_review_command` (`vehreg/input_pipeline.py:181`) requires a real `http(s)` `source_ref` for any `historical` action on `UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW`, and none of these 5 models has one anywhere in the REPAIR-08 audit trail. Asked the owner directly (AskUserQuestion): supply a URL / use `REPLACE_CURRENT_RETAIL_SET` instead (produces UNVERIFIED, not HISTORICAL, empty `source_ref` allowed) / hold. **Owner chose to hold rather than either alternative.** These 5 models (10 trims: SERES 3 Standard/Premium, SOKON EC35 Cargo Van/Passenger Van, VOLT For Four Classic/Premium, VOLT For Two Classic/Premium, Volvo XC40 BEV's 3 BEV trims plus its 4 untouched ICE/PHEV siblings) remain full holds, 0 commands, byte-identical before/after -- independently confirmed on the staged diff.

**Validation:** `CanonicalInputPipeline.apply()` on a fresh disposable copy: APPLIED, 68 changed files. `vehreg market validate`: valid, 0 problems. Focused gate: 98/98 passed. Staged `tdr_bridge.release_enriched` before/after: **+8 new market_trims** (unchanged from round e), **0 removed trims**, **9 renames** (the prior 4 plus Bingo LITE/PRO and Darion Comfort/Premium), **+21 price_ledger rows exactly matching the 21 `APPEND_PRICE` commands, 0 existing price rows removed or amount-changed** (price_ledger 983 -> 1004), **1 status change beyond the renames** -- Porta's Flatbed Carrier CURRENT -> UNVERIFIED (name unchanged, per the `REPLACE_CURRENT_RETAIL_SET` above), independently confirmed on the release. CURRENT-trim counts re-verified directly: Wuling Bingo 2 (LITE, PRO), Wuling Darion 2 (Comfort, Premium), Wuling Porta 1 (Standard Box only, Flatbed Carrier now UNVERIFIED), SERES 3 / SOKON EC35 / VOLT For Four / VOLT For Two / Volvo XC40 BEV all unchanged from before this round (still CURRENT by legacy default, untouched, per the owner's own hold decision).

Full v6 batch JSON and validation/diff results were delivered to the owner in-chat.

Next: await the owner's separate Step 4 approval for this 36-command batch. Do not enqueue, write to real canonical data, merge, or publish before that. If the owner later supplies a real http(s) source for SERES 3/SOKON EC35/VOLT For Four/VOLT For Two/Volvo XC40 BEV, `UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW` (`historical` action) is the correct mechanism to mark them historical rather than a `REPLACE_CURRENT_RETAIL_SET` exclusion, which only produces UNVERIFIED.

### REPAIR-08 Step 4 write (2026-09-28g, DONE / APPROVED)

State: `DONE / APPROVED`. Owner gave explicit approval to enqueue the full v6 batch ("eneueque ให้หมดเลย lot 8" -- enqueue all of lot 8).

**1. Enqueue and worker run, tracked to completion.**
- `enqueue-canonical-batch.yml` run `36402247605` (job `108862622079`), dispatched against `main` at `0dec3ac`: completed success. Log: `batch_key: ev-retail-repair-lot-08-2026-09-28f`, `queue_status: QUEUED (duplicate replay: False)`, `worker woken this run: true` -- dispatched worker run `36402317662`.
- `canonical-input.yml` run `36402317662` (job `108862841510`): completed success, all steps green -- pulled/applied 1 queued batch, `vehreg market validate` valid/0 problems, focused pytest gate, commit, publish, mark-published. STAGED-recovery steps present but skipped (no failure).
- Write commit: `6492204a74d46075adcefde1d63daf47338542a1` ("Apply 1 canonical input batch(es)", 68 files changed, 6949 insertions / 23 deletions -- exactly the `UPSERT_MODEL_BUNDLE`/`APPEND_PRICE`/`UPSERT_CAMPAIGN`/`REPLACE_CURRENT_RETAIL_SET` artifacts the batch's 36 commands produce: 3 new brand campaign files, 21 new price records, `current_retail.json` (Porta's set), 5 model files, plus canonical-state shadow/outbox/revision bookkeeping).
- Published release: `vehicle-2026-c4e73494ab9aa779`, status `ACTIVE`, `activated_at 2026-09-28T09:17:48.298727+00:00`, `published_batches: 1`. Reported counts: `brands 62, models 323, generations 326, market_trims 1570, price_ledger 1004, spec_facts 20910` -- exact match to every disposable-copy validation run for this batch.

**2. Independent verification, directly against the pulled repo, not the worker's self-report.**
- `git fetch` + `git merge --ff-only origin/main` landed exactly on `6492204a...`, byte-identical to the worker's reported commit.
- Directly queried the real, post-publish `Catalog`: Tesla's renamed AWD trim now named `Premium AWD`, Wuling Bingo's two trims named `LITE`/`PRO`, Wuling Darion's two trims named `Comfort`/`Premium`, Wuling Porta's two trims unchanged in name -- all id-preserving renames landed correctly.
- Independently rebuilt `tdr_bridge.release_enriched` from the real post-publish HEAD (own revision/as-of, not the worker's) and checked, in one pass: `market_trims 1570, price_ledger 1004, spec_facts 20910` (exact match); all 9 renames landed with the correct name; all 8 new-trim additions are `CURRENT`; EX90's untouched 517hp trim, Zeekr 009's untouched Grand, and Zeekr X's untouched Long Range RWD are all still `CURRENT` (none silently downgraded); Porta's Standard Box is `CURRENT` and Flatbed Carrier is `UNVERIFIED` (the one intended status change beyond the renames); all 16 held models/trims (RIDDARA Horizon 4WD, SERES 3, SOKON EC35, VOLT For Four/Two, Volvo XC40 BEV's 7 trims) are unchanged, still `CURRENT`; all 21 new `APPEND_PRICE` rows are present with the exact amount and `observed_at 2026-09-28`; all 7 pre-existing conflicting price rows (Tesla RWD/Performance/AWD, Zeekr 009 Flagship, Zeekr X Standard/Flagship, EX90 Plus) are preserved byte-identical, untouched -- **FAILS: 0** across every check.

**Outstanding issues: none for this batch.** The 5 models the owner asked to mark HISTORICAL (SERES 3, SOKON EC35, VOLT For Four, VOLT For Two, Volvo XC40 BEV) remain, as instructed, full holds pending a real http(s) source -- not touched, not claimed fixed. RIDDARA Horizon 4WD's structural identity collision, EX90's Ultra 6/7-Seat split, and Zeekr X's Long Range RWD lifecycle are likewise unresolved and were not acted on.

Next: REPAIR-08 is closed. Do not re-audit, rebuild, or re-enqueue unless the user explicitly reopens it. Any future resolution of the 5 held-HISTORICAL models, RIDDARA's 4WD collision, EX90's Ultra split, Wuling Darion/Porta's remaining unresolved trim, or Zeekr X's Long Range RWD is a new, separately-numbered repair batch. The remaining historical BEV+REEV audit queue beyond REPAIR-08's 16 members was explicitly not started in this operation and is separate future work.

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
