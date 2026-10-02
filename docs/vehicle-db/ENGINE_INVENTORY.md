# Vehicle Master engine inventory (Phase 0 step 1)

Source of truth for this document: `automotive/vehicle_master/` at `main` (`73e3aaab4`), plus the
Supabase release migrations that receive its output (`supabase/migration_v15_*`, `v27_*`, `v48_*`).
Purpose: list every validation rule, every computed value, the ID format and slug generation, so
that Phase 0 steps 2–4 of [`VEHICLE_DB_V3.md`](VEHICLE_DB_V3.md) can port them without loss.
Nothing here changes behaviour. Where the code disagrees with itself or with v3, it is listed in §9
rather than resolved.

File references are relative to `automotive/vehicle_master/`.

---

## 1. Pipeline today

```
JSON files under vehreg/data/<year>/            (the current master)
  models/<brand>.json                            brand → models → generations → variants / trims
  market/prices/*.json                           PriceLedger rows
  market/campaigns/<brand>.json                  campaigns + options
  market/trims/canonical.json, canonical_*.json  retail MarketTrim overlay + verified fragments
  market/trims/reconciliation*.json              source-evidence coverage state
  market/trims/source_dispositions_*.json        dispositions for source rows
  market/trims/current_retail.json               owner-approved CURRENT sets
  market/retail_lifecycle/trim_review.json       HUMAN trim CURRENT/HISTORICAL decisions
  market/operational_state/model_state.json      HUMAN UNDER_MAINTENANCE flags
  product/comparable_specs/{registry,profiles}.json + facts/*.json
  product/ecosticker/...                         ECO homologation evidence
        │
        │  writes: Supabase canonical_input_batches → tools/canonical_input_worker.py
        │          → vehreg/input_pipeline.py (staged copy) → vehreg/canonical_write.py
        │          → git commit (.github/workflows/canonical-input.yml)
        ▼
python -m tdr_bridge.release_enriched                       (.github/workflows/vehicle-release.yml)
   --inventory integration_data/tdr_2026-09-09.json         (legacy TDR brands/models for crosswalk)
   --overrides integration_data/crosswalk_overrides.json
   --as-of $(date -u +%F)
   = tdr_bridge/release.py ReleaseBuilder.build()
     → trim_reconciliation.apply_canonical_trim_overlay
     → trim_fragments.apply_verified_trim_fragments
     → lifecycle.apply_retail_lifecycle
     → historical_state.build_historical_model_state
     → source_dispositions.release_reconciliation_report_with_dispositions (blockers fail the build)
     → source_hash / release_id
        ▼
python -m tdr_bridge.publish  → RPCs begin_vehicle_release / stage_vehicle_release_chunk (500 rows)
                                 / finalize  (migration_v48)
        ▼
canonical_{brand,model,generation,market_trim,price,spec}_projection  keyed (release_id, …)
current_* views = projection JOIN canonical_vehicle_state(scope='vehicle_catalog').active_release_id
```

Every value in the `current_*` views is computed **once, at release build time, with
`as_of` = the UTC build date**. Nothing in SQL recomputes them. This matters for parity (§9.1).

---

## 2. ID format

All canonical IDs are dot-joined slugs composed from the file path; no file repeats a parent key.
Composition lives in `vehreg/catalog.py` (`_add_*`) and `vehreg/normalize.py` (`trim_identity`).

| Entity | Format | Local segment comes from | Example |
|---|---|---|---|
| Brand | `<brand>` | `slug(brand.id or brand.name_en)` | `toyota` |
| Model | `<brand>.<model>` | `slug(model.id or model.name_en)` | `toyota.yaris_ativ` |
| Generation | `<model_id>.<gen>` | `slug(code or id or "gen1")` | `toyota.yaris_ativ.mxpa10` |
| Variant (analytical) | `<generation_id>.<variant>` | `slug(variant.id or variant.name)` | `toyota.yaris_ativ.mxpa10.smart` |
| MarketTrim | `<generation_id>.trim.<local>` | `trim_local_id(id, name, powertrain)` | `toyota.alphard.ah40.trim.z_premier` |
| Spec fact (admin) | `admin:<trim_id>:<field_key>` | set by `APPEND_SPEC` when `fact_id` blank | |
| Spec fact (other) | any non-empty string, immutable | caller | |
| Price row (serving) | `record_id` = first 24 hex of `sha256(canonical JSON of the row)` | `tdr_bridge/release.py::_price_row` | |
| Revision | first 24 hex of `sha256("<year>:<command_id>:<hash(before)>:<hash(after)>")` | `canonical_write.py` | |
| Release | `vehicle-<year>-<first 16 hex of source_hash>` | `release_enriched.py` | `vehicle-2026-3fa1…` |
| Batch / command id | `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$`; command defaults to `<batch_id>:<n>` | `input_pipeline.py`, `canonical_write.py` | |

Rules:

- **MarketTrim local id** (`normalize.trim_local_id`): explicit `id` if given, else
  `slug(f"{name} {powertrain}")`. Powertrain is part of the generated id so "Premium BEV" and
  "Premium PHEV" cannot collide. An explicit id, once written, never changes on rename.
- Overlay / fragment trims (`market/trims/canonical*.json`) must supply an explicit local id matching
  `^[a-z0-9][a-z0-9_]*$` (`trim_reconciliation._LOCAL_ID`, `trim_fragments._LOCAL_ID`).
- `product.import_trims` requires `slug(local_id) == local_id` (id already canonical).
- `APPEND_SPEC` can address a trim created earlier in the same batch with
  `trim_ref = {generation_id, id|name, powertrain}`; it is resolved with the same `trim_identity`.
- The id is **not predictable outside Python** (Thai mark folding, corporate-word stripping — §3).
  The admin editor asks Python for it; any TS port must reuse one implementation.
- `Generation` with no `code` and no `id` gets `gen1`. `brand_payload()` writes the local
  generation id back so a blank-code generation does not reload as `gen1`.
- Duplicate ids at any level → `CatalogError` at load (brand, model, generation, variant, trim).

## 3. Slug generation

There are **two different slug functions**, used for different things.

### 3.1 `vehreg.normalize.slug` — canonical id segments

```
slug(text) = re.sub("_+", "_", fold(text, split_digits=False).replace(" ", "_")).strip("_") or "unnamed"

fold(text, split_digits):
  1. NFKC normalize, strip, lowercase
  2. replace every run of chars outside [0-9a-z฀-๿] with " "      (Thai block kept)
  3. (split_digits=True only — matching, not slugs) split letter/digit boundaries
  4. remove whole-word corporate noise:
     motor motors automobile automotive auto company co ltd limited thailand manufacturing
     corporation corp inc group sales บริษัท จำกัด มหาชน ประเทศไทย ยานยนต์ มอเตอร์
  5. remove Thai combining marks [ัิ-ฺ็-๎]
  6. collapse whitespace
```

Consequences a port must reproduce exactly: Thai base letters survive in ids; "Dual Motor" →
`dual`; a trim named "Auto" → `unnamed`; "1.5" → `1_5` (the `.` is a non-alnum char).

### 3.2 `tdr_bridge.release._slug` — public URL slugs

```
_slug(value) = "-".join(re.findall("[a-z0-9]+", NFKD(value).lower())) or "vehicle"
```

Thai characters are dropped entirely.

| Serving column | Value |
|---|---|
| `current_vehicle_brands.slug` | crosswalked legacy TDR brand `slug` if matched, else `_slug(brand.id)` |
| `current_vehicle_models.slug` | crosswalked legacy TDR model `slug` if matched, else `_slug(f"{brand.id}-{model.name_en}")` |
| `models.payload.brand.slug` | crosswalked brand slug, else `_slug(brand.id)` |

So public slugs depend on the release-time crosswalk (§5.1). A model whose crosswalk changes gets a
different slug in the next release.

### 3.3 Other normalizers (identity-adjacent)

- `normalize.base_nameplate(name)`: strips a trailing split suffix
  (`single cab|double cab|smart cab|club cab|king cab|open cab|freestyle cab|giant cab|cab4|spark|sedan|hatchback|coupe|cab|` + Thai equivalents).
  Used as the default `Model.nameplate`.
- `release._norm(value)`: NFKD casefold, keep only alnum — the crosswalk comparison key.
- `pricefeed.grade_tokens(name, model_name)`: `fold(name)` tokens minus the model's own name tokens
  minus `{l, cc, litre, liter, รุ่น, ใหม่}` — used to match price claims to trims.
- `Facet.parse(raw)`: `upper()`, `-`/space → `_`, then enum name, enum value, then `FACET_ALIASES`
  (§4.1).

---

## 4. Validation rules

Rules are grouped by where they fire. "Load" = raised while reading files (whole load fails);
"validate" = collected into a problem list that blocks writes and release builds.

### 4.1 Vocabularies (`vehreg/taxonomy.py`)

| Facet | Values | Input aliases (parse only) |
|---|---|---|
| `Segment` | A B C D E F UNKNOWN (F = pickup, owner scheme) | — |
| `BodyType` | HATCHBACK SEDAN CROSSOVER PPV OFFROAD COUPE MPV PICKUP WAGON VAN TRUCK OTHER | SUV/MONOCOQUE_SUV/UNIBODY_SUV→CROSSOVER; PPV_SUV/PICKUP_DERIVED_SUV→PPV; SUV_BOF/BODY_ON_FRAME_SUV/LADDER_FRAME_SUV/OFFROAD_SUV/OFFROAD_LADDER_FRAME→OFFROAD; MINIVAN→MPV; CONVERTIBLE/CABRIOLET→COUPE; ESTATE→WAGON; PICK_UP→PICKUP |
| `CabType` | DOUBLE_CAB SINGLE_SMART SMART_CAB SINGLE_CAB NOT_APPLICABLE | CAB4/4_DOOR/CREW_CAB→DOUBLE_CAB; SPACE_CAB/EXTENDED_CAB/HALF_CAB/OPEN_CAB→SMART_CAB; STANDARD_CAB/CHASSIS→SINGLE_CAB; SINGLE_SMART_CAB/CAB/RY3_CAB→SINGLE_SMART; NA/NONE→NOT_APPLICABLE |
| `Powertrain` | ICE HEV PHEV REEV BEV FCEV UNKNOWN (no MHEV) | EV/ELECTRIC→BEV; HYBRID/FULL_HYBRID→HEV; MHEV/MILD_HYBRID/MILD_HEV/EQ_BOOST/48V/GASOLINE/PETROL/DIESEL→ICE; PLUG_IN_HYBRID/PLUGIN→PHEV; EREV→REEV; HYDROGEN→FCEV. Generic "range extender" deliberately **not** REEV |
| `Drivetrain` | FWD RWD AWD 4WD UNKNOWN | 2WD/FF→FWD; FR/4X2→RWD; 4X4/FOUR_WD→4WD |
| `ImportType` | CBU SKD CKD UNKNOWN | IMPORTED→CBU; LOCAL/ASSEMBLED→CKD |
| `RegistrationType` | RY1 RY2 RY3 RY12 OTHER | RY_1/1/รย.1 etc. |
| `MarketScope` | CORE NICHE GREY COMMERCIAL UNKNOWN | MAIN/OFFICIAL→CORE; EXOTIC/SUPERCAR→NICHE; IMPORT→GREY … |
| `RetailStatus` | CURRENT HISTORICAL UNVERIFIED | — |
| `BrandSegment` | BUDGET MASS PREMIUM_TECH PERFORMANCE PREMIUM_LUXURY UNKNOWN | — |
| `MarketPosition` (derived) | ENTRY <500k · VOLUME <1M · UPPER <1.8M · LUXURY ≥1.8M · UNKNOWN | — |

Cross-facet rules:

- **Registration** (`check_registration`): expected = PICKUP+DOUBLE_CAB→RY1, other PICKUP→RY3,
  TRUCK→RY3, else RY1. RY2 always allowed (owner's call for >7 seats). VAN/TRUCK exempt (data decides).
  Otherwise declared ≠ expected is a problem.
- **Body/segment** (`check_body_segment`): PICKUP needs a cab_type; cab_type only valid for PICKUP;
  every PICKUP is segment F; segment F only for PICKUP.
- **Powertrain** (`check_powertrain`, analytical Variant / resolved row): BEV must not have
  `engine_cc`; ICE must not have `battery_kwh`; PHEV/REEV need `engine_cc`; BEV/PHEV/REEV need
  `battery_kwh`.
- **Origin** (`check_origin`): SKD/CKD require `origin_country == "TH"`.

### 4.2 Entities (`vehreg/entities.py`)

- **Model.validate**: registration rule; PICKUP must name a cab_type; non-PICKUP must not;
  `retail_status = CURRENT` requires both `retail_source` and `retail_checked_at`.
- **Variant.validate**: powertrain rule (skipped if `incomplete`); origin rule; must not override
  `body_type`/`cab_type` (`LOCKED_AT_MODEL`); `price_min_thb ≤ price_max_thb`; min and max must be in
  the same `MarketPosition` band; `price_thb` must lie within min..max.
- **MarketTrim.validate**: powertrain is exact (not UNKNOWN); `engine_cc, seats, length_mm, width_mm,
  height_mm, wheelbase_mm` positive finite **int**; `battery_kwh` positive finite number;
  `price_thb` (legacy) finite ≥ 0; `wheelbase_mm < length_mm`; BEV has no `engine_cc` and no
  `engine_code`.
- `_is_set`: `None`, `""`, `"UNKNOWN"` and enum UNKNOWN count as "not asserted" during resolve.

### 4.3 Catalog loader (`vehreg/catalog.py`) — load-time, atomic per brand file

- Year folder must contain ≥1 brand file; JSON must parse.
- Brand payload needs `brand`; brand id unique across files.
- Model needs `name_en`; model needs ≥1 generation.
- Variant needs `name`.
- Trim needs `name`; trim powertrain must be exact (UNKNOWN rejected at load).
- Trim `variant_id`/`variant` reference must resolve to a variant in the **same generation**
  (by full id, `<gen>.<slug(ref)>`, or `slug(variant.name)`), else load fails.
- `source_refs`: keys/values stripped, empty dropped, duplicates removed (order kept).
- Defaults: `body_type` OTHER, `cab_type` NOT_APPLICABLE, `registration_type` from body+cab,
  `market_scope` CORE, `retail_status` UNVERIFIED, `nameplate` = `base_nameplate(name_en)`.
- A brand file is staged in an isolated Catalog and merged only if every nested object parsed.

### 4.4 Catalog.validate (`vehreg/catalog.py`)

- Every Model.validate.
- Non-`incomplete` model: `body_type` ≠ OTHER; has ≥1 variant.
- Every Variant.validate except variants of `incomplete` models.
- Every MarketTrim.validate; if trim has `variant_id`, trim powertrain must equal the variant's
  (unless either is UNKNOWN).
- `duplicate_body_warnings`: two models with same `(brand, slug(name_en), body_type, cab_type)`.
- `cross_check` on every resolved Variant (skip incomplete model / incomplete variant):
  body/segment, powertrain, origin, registration rules on the merged facets.
- Reported separately, not as problems: `incomplete_models()` gaps
  (`price`, `battery_kwh` for electrified, `engine_cc` for combustion, `powertrain` UNKNOWN).

### 4.5 Retail trim overlay and fragments (release build)

`trim_reconciliation.apply_canonical_trim_overlay` (`market/trims/canonical.json`) and
`trim_fragments.apply_verified_trim_fragments` (`canonical_*.json`, `schema_version` 1):

- Row is an object; local id matches `^[a-z0-9][a-z0-9_]*$`; `model_id` exists; `generation_id` is
  under that model; `name` non-empty; powertrain parses and is not UNKNOWN; `variant_id` **must be
  empty**; `source_refs` non-empty object of non-empty string lists; `aliases` list of strings;
  `specs` object.
- Release must not already contain duplicate MarketTrim ids.
- If the id already exists → **merge** (`merge_market_trim_evidence`):
  - identity fields (`canonical_id, model_id, generation_id, powertrain`, and `specs.id/generation_id/powertrain`)
    may be filled when missing but never changed — a difference fails the build;
  - a different display name becomes an alias;
  - `source_refs` are unioned;
  - incoming specs fill only missing/`UNKNOWN`/empty values; two different populated values fail
    the build; specs may not set reserved keys (`id, generation_id, name, powertrain, variant_id, aliases, source_refs`).
- New rows get `status = "UNVERIFIED"` (later overwritten by lifecycle, §5.3), empty prices and
  `comparable_specs = []`.

Reconciliation state (`reconciliation.json` + `reconciliation_*.json` overrides):

- Per model row: `model_id` known and unique; `status` ∈ `READY | AMBIGUOUS_POWERTRAIN | NON_MARKET | HISTORICAL_ONLY | RESEARCH_UNRESOLVED`;
  `source_refs` non-empty strings; `source_trim_count` int ≥ 0; `reason` non-empty.
- Override rows must reference an already tracked model and carry `supersedes: true`.
- Source dispositions: `model_id, source_ref, source_name` required; disposition ∈
  `SUPERSEDED_BY_VERIFIED_LINEUP | AGGREGATE_SOURCE_ROW | NON_MARKET_SOURCE_ROW | DUPLICATE_SOURCE_ROW`;
  `reason` and non-empty `evidence_refs` required; `source_ref` must be a known owner source; no duplicates.
- **Release blocker**: a reconciliation row whose model is not in the release
  (`SOURCE_EVIDENCE_MODEL_NOT_IN_RELEASE`) → `enrich_release` raises; nothing publishes.
  READY-but-unpromoted rows are research debt only, not a blocker.

Candidate powertrain resolution (`resolve_candidate_powertrain`, used by research tooling):
exact single hint in trim name → READY; multiple → AMBIGUOUS; else single hint in source model text;
else the generation's single analytical powertrain; else AMBIGUOUS / RESEARCH_UNRESOLVED.
Hint regexes: REEV/EREV/RANGE-EXTENDER, PHEV/PLUG-IN/DM-I, HEV/FULL-HYBRID/E-POWER, BEV/EV/PURE-ELECTRIC,
FCEV/FUEL-CELL, ICE/PETROL/GASOLINE/DIESEL/TFSI/TDI (word-bounded).

### 4.6 Price ledger (`vehreg/pricing.py`)

PriceRecord fields: `trim_id, amount_thb, price_type, effective_from, effective_to, observed_at,
source, source_ref, source_document_id, notes, campaign_id, option_id, reference_price_thb,
retracted_at, retraction_reason, reviewed_by`. Unknown fields rejected.

- `trim_id` required and (with catalog) must exist.
- `amount_thb` positive integer, digits only (`^[0-9]+$`, bool rejected).
- `price_type` ∈ `LIST_PRICE INTRODUCTORY_PRICE CAMPAIGN_PRICE FINANCE_PRICE ESTIMATED_PRICE DEALER_PRICE ECO_STICKER_PRICE UNKNOWN`.
- `source_document_id` empty or `^sha256:[0-9a-f]{64}$`.
- `reference_price_thb` positive integer if present.
- CAMPAIGN_PRICE / FINANCE_PRICE require `campaign_id`; `option_id` requires `campaign_id`;
  `campaign_id` only on CAMPAIGN/FINANCE.
- All dates `YYYY-MM-DD` and real dates.
- `retracted_at` requires `retraction_reason`.
- LIST_PRICE requires `effective_from` or `observed_at`.
- `effective_from ≤ effective_to`.
- Campaign referenced must exist; option referenced must exist in that campaign.
- **Conflict rule**: for every LIST_PRICE start date (and every CAMPAIGN/FINANCE start within one
  campaign+option scope), resolving on that date must not find two active rows with the same start
  and different amounts → "conflicting LIST_PRICE at <date>; review required".
- Exact duplicate rows are de-duplicated on load; a bad row rejects the whole file.
- `append_prices` (and every new observation) requires `source`, `source_ref`, `observed_at`.

Campaigns:

- Campaign: `id` and `brand_id` required (brand must exist on `save_campaign`); `quota_units`
  positive int; `starts ≤ ends`; ≥1 option; option ids unique; an option may not restate a
  campaign-level quota.
- Option: `id` required; dates valid; `starts ≤ ends`; status ∈ `ACTIVE SOLD_OUT WITHDRAWN SUPERSEDED`;
  non-ACTIVE requires `closed_at`; `closed_at` requires non-ACTIVE.
- Conditions: only `booking_from, booking_to, delivery_by, quota_units, finance_required, text`;
  `booking_from ≤ booking_to`; `quota_units` positive int; `finance_required` boolean.

Manual maintenance (`product.correct_price`, `close_price`):

- Both require a non-empty `reason` and `reviewer`.
- Exactly one live row must match `(trim, price_type[, campaign, option])` on `as_of`; zero or
  several is an error.
- `supersede`: same amount → no-op; old row's start must be before the new `effective_from`; old row
  gets `effective_to = new_start − 1 day`; new row appended with `observed_at = today`.
- `retract`: old row gets `retracted_at = today`, `retraction_reason`; new row appended.
- `close`: `ends` must be on/after the live row's start; sets `effective_to = ends`.
- Every write re-validates the full ProductMaster.

### 4.7 Comparable specs (`vehreg/comparable_specs.py`)

Registry (`product/comparable_specs/registry.json`, 96 fields today, groups: safety, chassis,
powertrain, battery, efficiency, dimensions, charging, comfort, technology, identity, utility,
performance, manufacturing):

- `schema_version` 1; only keys `key, group, label_th, label_en, value_type, comparison_rule,
  canonical_unit, applicable_powertrains, comparison_qualifiers, display_precision`.
- `key` matches `^[a-z][a-z0-9_.]*$`, unique.
- **No price fields**: key or unit containing `price, msrp, thb, baht, cost, ราคา` rejected.
- `group`, `label_th`, `label_en` required; NUMBER requires `canonical_unit`;
  `display_precision` int ≥ 0.
- `value_type` ∈ `NUMBER BOOLEAN ENUM TEXT SET`; `comparison_rule` ∈
  `HIGHER_BETTER LOWER_BETTER PRESENCE SET_DIFFERENCE INFORMATION_ONLY`.
- Profiles reference only known fields, no duplicates.

SpecFact (`fact_id, trim_id, field_key, value_state, value, unit, qualifiers, effective_from,
effective_to, observed_at, claim_ids, verification_status, source, source_ref, source_locator`):

- `fact_id, trim_id, field_key` required; `field_key` registered; trim exists.
- `value_state` ∈ `KNOWN UNKNOWN NOT_AVAILABLE NOT_APPLICABLE`. Non-KNOWN → value must be null.
- KNOWN: NUMBER finite, ≥ 0, `unit == canonical_unit`; non-NUMBER must have empty unit;
  BOOLEAN is bool; ENUM/TEXT non-empty string; SET non-empty list of non-empty strings.
- Qualifiers only from the field's `comparison_qualifiers`.
- Field with `applicable_powertrains` rejects trims of other powertrains.
- `observed_at` required.
- Source: `admin:*` facts need `source` and `source_ref` both present or both absent; all other
  facts need both.
- `effective_from ≤ effective_to`.
- **Immutable by fact_id**: re-adding the same id with different content is rejected.
- **Conflict**: same `(trim, field, qualifier values, start)` with different `(value_state, value)` → problem.
- `verification_status` ∈ `VERIFIED PROVISIONAL` (default VERIFIED).
- Price-word guard also applied per fact row on load.

### 4.8 ECO homologation evidence (`vehreg/homologation.py`)

- `trim_id`, `source_ref` required; powertrain exact; `seats`, `battery_voltage_v`,
  `declared_total_weight_kg`, `rated_range_km` > 0 when present; no key containing `price`;
  duplicate `trim_id` rejected; trim must exist.
- Cross-check against the catalog: trim exists; `source_ref` listed in the trim's
  `source_refs.ecosticker`; powertrain equal; seats equal when both set; tyre size (spaces removed,
  upper) equal to `tire_front` / `tire_rear` when those are set.
- ECO candidate store (`ECOCandidateSpecStore`, cohort preview): candidate values must pass the
  registry; cohort representatives must exist in the snapshot. ECO price is always
  `ECO_STICKER_PRICE`, never MSRP.
- ECO → trim promotion (`ecosticker_promote`): action ∈ `create_market_trim | reject | defer`; a
  human must name the trim; emits `UPSERT_MODEL_BUNDLE` only; never carries ECO price, tyres, wheels,
  dimensions or battery into the trim.

### 4.9 Workflow sidecars (HUMAN-only)

Common: reviewer/actor non-empty and not `system | agent | agent-proposed`; dates `YYYY-MM-DD`;
`schema_version` 1; unknown fields rejected; duplicates per key rejected; atomic file replace.

| Store | Rules |
|---|---|
| `current_retail.json` (`vehreg/current_retail.py`) | per model: model exists, once only; `trim_ids` non-empty, unique; every trim exists **in the base Catalog** (not overlay-only) and belongs to that model; `source_ref` empty or http(s); `REPLACE_CURRENT_RETAIL_SET` replaces the whole set; refuses to add a trim that still has an unreopened HUMAN HISTORICAL decision |
| `trim_review.json` (`retail_lifecycle_review.py`) | action ∈ `current, historical, reopen`; stored status CURRENT/HISTORICAL; trim exists; ordinary path requires http(s) `source_ref` (bootstrap path: historical/reopen only, empty source allowed); parent model must be canonical CURRENT, except: a model with an approved set may record `historical` for a **non-member**; never `historical` for a member |
| `model_state.json` (`model_operational_state.py`) | action ∈ `under_maintenance, normal`; model exists; absence = NORMAL |
| price coverage review (`price_coverage_review.py`) | action ∈ `defer, reopen`; reason ∈ `AWAITING_FINAL_LIST_PRICE, OFFICIAL_EVIDENCE_CONFLICT, NO_RELIABLE_EVIDENCE`; never enters PriceLedger or serving |
| ECO review (`eco_review_write.py`) | action ∈ `reject, defer, reopen`; staging metadata only |

### 4.10 Input batches (`vehreg/input_pipeline.py`) and commands (`vehreg/canonical_write.py`)

Batch:

- Only fields `schema_version, batch_id, year, source, actor, reason, submitted_at, commands`;
  `schema_version` 1.
- `batch_id` safe token; `year` int in 2000–2100.
- `source.kind` ∈ `ADMIN ECO OEM MEDIA PRICE_HARVEST MIGRATION API`; `DLT`/`REGISTRATION` explicitly rejected.
- 1–500 commands; `submitted_at` ISO-8601 **with timezone** (deterministic retries).
- `command_id` unique in batch; all commands use the batch year.
- Special ops and their required source kind: `UPSERT_ECO_REVIEW` (ECO);
  `UPSERT_PRICE_COVERAGE_REVIEW`, `UPSERT_TRIM_RETAIL_LIFECYCLE_REVIEW`,
  `UPSERT_MODEL_OPERATIONAL_STATE`, `REPLACE_CURRENT_RETAIL_SET` (ADMIN); all need a HUMAN actor.
- The whole batch is applied to a staged copy of the data tree; files are copied back and the commit
  marker written last.

Command (`CanonicalWriteCommand`): only `command_id, operation, year, actor, reason, canonical_id,
payload, submitted_at`; operation ∈
`UPSERT_MODEL_BUNDLE WITHDRAW_MODEL APPEND_PRICE CORRECT_PRICE CLOSE_PRICE UPSERT_CAMPAIGN APPEND_SPEC`;
payload is an object. **Idempotent**: a `command_id` already in `revisions.jsonl` returns the
recorded revision without re-applying.

| Operation | Rules / effects |
|---|---|
| `UPSERT_MODEL_BUNDLE` | needs `brand`, `model`, `generation` objects; canonical id from command, `model.canonical_id`, or `slug(brand) . slug(model)`; id must look like `<brand>.<model>`; brand slug must agree; `brand.name_en` required; new model requires `name_en`; `generation.code` required; variants need `name`, trims need `name`; child `canonical_id` must start with the right parent prefix; variants upserted by `slug(id or name)`, trims by `trim_local_id`; whole catalog re-validated before writing. Patches **merge** keys (shallow), never remove existing keys |
| `UPSERT_MODEL_BUNDLE` + `payload.delete_trim` (`canonical_trim_delete.py`) | parent model id required; trim must exist and belong to that model; refused if any price row (incl. retracted), any spec fact, or any campaign file mentions it; must appear exactly once in source JSON; catalog re-validated; hard delete of the JSON row. Registration references are checked by the TS admin action before queueing |
| `WITHDRAW_MODEL` | model exists; sets `retail_status = HISTORICAL`; with `ended`, fills `ended` on every generation that has none |
| `APPEND_PRICE` | trim exists; same `(trim, type, campaign, option)` live row with the same start date: same amount → no-op, different amount → **retract-and-replace** (`correct_price mode=retract`); else append to `market/prices/canonical_<command_id>.json`; LIST_PRICE is resolved on its start date to catch conflicts |
| `CORRECT_PRICE` | trim exists; `reason` required; `mode` supersede/retract (§4.6); no-change is an error |
| `CLOSE_PRICE` | trim exists; `reason` and `ends` required (§4.6) |
| `UPSERT_CAMPAIGN` | campaign object with id; identical payload is an error; whole campaign replaced in `market/campaigns/<brand>.json` |
| `APPEND_SPEC` | trim from `canonical_id`/`trim_id` or `trim_ref` (must not contradict); `field_key` required; default `fact_id = admin:<trim>:<field>`; file named from `fact_id` (`canonical_<safe>_<sha12>.json`) so re-stating a fact **replaces it in place**; a file holding another fact is an error; only this trim's facts are validated |

Every applied command appends a revision (`before`, `after`, hashes, actor, reason, changed files) to
`canonical_state/revisions.jsonl`, an event to `outbox.jsonl`, and a shadow file.

### 4.11 Price-intelligence feed (writes through `APPEND_PRICE` / `CORRECT_PRICE`)

Not part of serving, but its rules decide which prices reach the ledger:

- Source tiers: A manufacturer (enough alone); B named media (needs **2 independent** groups, and not
  all republishers); C discovery only; D alert only. Independence: same source, or document
  body-sketch overlap ≥ 0.55 (5-word shingles, 96-hash sketch) = same voice.
- Review reasons: no/ambiguous trim match, trim not in catalog, amount outside 150,000–60,000,000 THB,
  UNKNOWN price type, campaign without conditions, low tier only, single tier B, closed-campaign
  contradiction/echo, campaign with unknown date. Conflicts are never resolved by highest/lowest/newest.
- Trim match: exact grade-token set equality (name or alias) → unique wins, tie → none; else subset
  match covering ≥ half the claim's tokens, highest token count, tie → none.
- Lifecycle (P0/P5): no end date = open-ended; absence or age never expires a price; a replacement
  must be observed again ≥ 24 h after first seen; campaign/finance replacement requires explicit
  campaign+option scope; price types never supersede each other.
- Promotion (P6): HUMAN approval required; only SAFE_CANDIDATE, CONFIRMED_REPLACEMENT,
  HISTORICAL_ONLY promotable; append + supersede; unstated effective date → confirmation date;
  `source_document_id` mandatory.
- Writer precedence (`pricefeed_writer.plan_offers`): same amount → nothing; empty scope → append;
  newer start → supersede; same-day-or-older vs a non-feed (owner) row → ignored; older than a
  feed row → stale; two feed rows same start → exception.
- Price-eligibility scope for automation (`retail_scope.py`): model not UNDER_MAINTENANCE, not
  HISTORICAL, has an active generation on `as_of`; trim in an active generation; if the model has an
  approved current set, only members; else not HUMAN-HISTORICAL.

### 4.12 Release build and publish

- `ReleaseBuilder.__init__`: `ProductMaster.validate()` (catalog + prices + ECO cross-check + spec
  registry + spec facts) must be empty, else no release.
- Overlay/fragment/merge rules (§4.5); reconciliation blockers (§4.5).
- Publish RPCs (`migration_v15`, `v44`, `v48`): `release_id` matches `^vehicle-[0-9]{4}-[a-f0-9]{16}$`;
  `schema_version` 1; `source_hash` and `canonical_revision` present; staged section counts must equal
  `release.counts`; sections staged in FK order brands → models → generations → market_trims →
  price_ledger → spec_facts; activation refuses a release whose `revision_ordinal` is older than the
  active one (v44); 30 s per stage RPC, 45 s for single-shot publish.
- DB constraints (`v27`): `canonical_model_projection.status` and
  `canonical_market_trim_projection.status` ∈ `CURRENT HISTORICAL UNVERIFIED`; trim status default
  `UNVERIFIED`.

---

## 5. Computed values

### 5.1 Release-time crosswalk to legacy TDR rows (`tdr_bridge/release.py`)

Input: `integration_data/tdr_2026-09-09.json` (legacy `brands`/`models` with uuid ids) and
`integration_data/crosswalk_overrides.json` (`brands`, `models`, `source_aliases`).

- **Brand**: forced override → that row (missing row = `BROKEN_OVERRIDE`). Else match `_norm` of
  brand id / name_en / name_th against legacy slug / name_en / name_th; exactly one → mapped; else
  retry adding brand aliases; exactly one → mapped; else review `AMBIGUOUS` / `UNMATCHED`.
- **Model**, in order: overrides (each legacy id claimed once); legacy rows whose `notes` contain
  `source=<canonical_id>` (after `source_aliases`); then surface match — canonical surfaces
  `{id, id without brand, name_en, name_th, nameplate, aliases}` vs legacy `{slug, name_en, name_th,
  slug minus brand slug prefix}`, restricted to the mapped brand, unclaimed rows only; exactly one →
  mapped. Unmapped canonical and unclaimed legacy rows are written to `crosswalk.review`.
- Output: `tdr_brand_id`, `tdr_model_id`, slugs (§3.2), and editorial fields copied into model
  payload (below).

### 5.2 Per-section fields

**brands** (`current_vehicle_brands`)

| Column | Value |
|---|---|
| `canonical_id` | brand id |
| `tdr_brand_id` | crosswalk |
| `slug` | §3.2 |
| `name_en`, `name_th` | brand |
| `origin_country` | `brand.brand_origin` (raw, not normalized) |
| `payload` | `asdict(Brand)` with enums flattened |

**models** (`current_vehicle_models`)

| Column | Value |
|---|---|
| `generation_id` | **current generation**: newest (by `launched` desc, then id desc) among generations active on `as_of` (launched ≤ as_of or null, and ended > as_of or null); if none active, newest of all |
| `status` | first `editorial.status or retail_status`, then **overwritten by lifecycle** → `HISTORICAL` if `retail_status == HISTORICAL`, else `CURRENT` (models are never published as UNVERIFIED) |
| `segment` | current generation's segment, else `UNKNOWN` |
| `body_type` | model body_type |
| `retail_price_min` / `retail_price_max` | min / max of `current_list_amount(trim, as_of)` over **price-eligible** trims of the model (§4.11 scope: active generations, approved set, not HUMAN-HISTORICAL, model not maintenance/historical); null if none |
| `payload` | `asdict(Model)` plus: `brand {id, slug, name_en, name_th}`; `generation` = current gen code; `seats` = current gen seats; `powertrains` = sorted distinct non-UNKNOWN **Variant** powertrains across all generations; `market_position` = editorial value else `brand_segment.title()`; `image_url`, `consumer_description`, `featured`, `launch_quarter` = editorial; `production_type` = single distinct variant import_type, `MIXED` if several, else editorial; `production_country` = same rule over origin_country; `launch_year` = current gen `launched[:4]` else editorial |

**generations** (`current_vehicle_generations`): all generations of the model, sorted newest first;
`canonical_id, model_id, code, segment, launched, ended, payload = asdict(Generation)`.

**market_trims** (`current_market_trims`)

| Column | Value |
|---|---|
| `canonical_id, model_id, generation_id, variant_id, name, powertrain` | trim identity |
| `status` | §5.3 |
| `payload` | `ProductMaster.detail(trim, as_of)` (below) — or the overlay shape for overlay-only trims (§4.5) |
| `current_list_price` | `detail.current_list_price` |
| `campaign_quote` | `PriceLedger.campaign_quote(trim, as_of)` (§5.4); `{}` for overlay-only trims |
| `price_history` | `detail.price_history` |
| `source_refs` | trim source refs (unioned with overlay/fragment refs on merge) |

`detail(trim, as_of)`:

```
catalog_year, price_as_of = as_of,
model_id, model (name_en), brand (name_en),
specs = asdict(MarketTrim) without price_thb,     (overlay merges add aliases/source_refs/spec keys here)
current_list_price = PriceRecord as dict | null,
price_history = records_for(trim) — non-retracted rows, all types, sorted by
                (effective_from or observed_at, observed_at, amount_thb),
ecosticker_evidence = ECOStickerSpec as dict | null,
comparable_specs = SpecLedger.resolved(trim, as_of) as dicts (VERIFIED only)
```

**price_ledger** (`current_price_ledger`): one row per `records_for(trim)` for every catalog trim —
**retracted rows excluded**, all price types — each `{record_id, **PriceRecord}`; SQL columns
`trim_id, amount_thb, price_type, effective_from, effective_to, observed_at, campaign_id, option_id,
source, source_ref`, `payload` = the whole row.

**spec_facts** (`current_spec_facts`): for every catalog trim, each resolved fact
`{trim_id, **SpecFact}`; SQL columns `fact_id, trim_id, field_key, verification_status`, `payload` =
the whole row. Only resolved VERIFIED facts are published, not the full fact history.

### 5.3 Trim status (`tdr_bridge/lifecycle.py`)

`release.py` first writes `discontinued` (generation ended ≤ as_of) or `current`; overlay rows write
`UNVERIFIED`. Then `apply_retail_lifecycle` overwrites every trim, first match wins:

1. Model status HISTORICAL, or generation `ended ≤ as_of` → `HISTORICAL`.
2. Model has an approved current set: member → `CURRENT`; non-member with HUMAN HISTORICAL
   decision → `HISTORICAL` (+ `retail_lifecycle_review` block); other non-member → `UNVERIFIED`.
3. HUMAN decision exists → its status (`CURRENT`/`HISTORICAL`) + review block.
4. Otherwise → `CURRENT`.

So `UNVERIFIED` trims exist only in models with an approved current set.

### 5.4 Price resolution

- `current_price_for_scope(trim, type, as_of, campaign, option)`: rows of that type (CAMPAIGN/FINANCE
  also filtered to the exact campaign+option; missing scope → none), non-retracted, with start
  (`effective_from or observed_at`) ≤ as_of; take the **latest start**; keep rows with that start
  that are active on as_of (`effective_to` null or ≥ as_of); different amounts → `PricingError`
  (fails the build); return the last.
- `current_list_price` = that for LIST_PRICE. `current_list_amount` = its `amount_thb`.
- `discount_thb` = `reference_price_thb − amount_thb` (derived, never stored).
- `current_campaign_offers`: every (type, campaign, option) scope seen on the trim; resolve each;
  drop if campaign not live on as_of (`starts ≤ as_of ≤ ends`) or option not open
  (`open_on`: `closed_at` not reached, status ACTIVE or has closed_at, within option `starts..ends`,
  within `booking_from..booking_to`).
- `status_on(as_of)`: option status as it was on as_of — `ACTIVE` before `closed_at`, recorded
  status on/after.
- `campaign_quote` shape (served unchanged per v3 §7):

```
{ trim_id, as_of, list_price_thb,
  campaign_options: [ { amount_thb, price_type, reference_price_thb, discount_thb,
                        campaign_id, campaign_name, gifts, campaign_starts, campaign_ends,
                        option_id, option_label, status_as_of, current_status, closed_at,
                        conditions (non-empty keys only), quota_units (option, else campaign),
                        quota_scope ("OPTION" | "CAMPAIGN" | null), valid_to (row effective_to),
                        source, source_ref, source_document_id } ] }
```

### 5.5 Spec resolution (`SpecLedger.resolved`)

For one trim and `as_of`: candidate facts = VERIFIED, start (`effective_from or observed_at`) ≤ as_of
or no start; group by `(field_key, qualifier values)`; within a group take the latest start; keep
those active on as_of; differing `(value_state, value)` → `ComparableSpecError` (fails the build);
pick the highest `fact_id`; output sorted by `(field_key, qualifiers)`.

### 5.6 Release envelope

- `counts` per section (`market_trims` recomputed after overlays).
- `historical_model_state`: per catalog year, model baselines + monthly production-state changes
  from `data/research/monthly_production_state.csv` (with `source_aliases`); errors fail the build.
  Stored in the release manifest payload; read by `lib/historical-model-state.ts`.
- `trim_reconciliation`: per tracked model `source_trim_count, canonical_trim_count,
  canonical_source_trim_count` (canonical trims whose refs intersect the row's refs),
  `unresolved_source_trim_count = max(source − promoted, 0)`, `status = CANONICAL` if unresolved = 0
  else declared, after source dispositions; plus counts and blockers. Not published to a view.
- `source_hash` = sha256 of canonical JSON (sorted keys, compact) of `SEMANTIC_KEYS` (`schema_version,
  year, canonical_revision, as_of, brands, models, generations, market_trims, price_ledger,
  spec_facts, historical_model_state, trim_reconciliation`). `release_id` from it (§2).
  `created_at` is wall-clock and outside the hash. `revision_ordinal` = commit count (optional).
- Publish manifest (`begin_vehicle_release`) contains only `schema_version, release_id,
  canonical_revision, source_hash, year, as_of, counts, historical_model_state, revision_ordinal`.

### 5.7 Analytical-only computed values (not served by `current_*`)

`entities.resolve()` walks variant → generation → model → brand (first asserted value wins,
`body_type`/`cab_type` only from model) and derives `powertrain_group`, `market_powertrain`,
`is_electrified` (HEV/PHEV/REEV/BEV/FCEV), `is_plug_in` (PHEV/REEV/BEV), `market_position` (from
variant `price_thb`), `is_locally_assembled` (SKD/CKD, or CBU from TH). Used by registration
analytics (`cube`, `iter_resolved`), not by the vehicle views. `price_taxonomy` (UNDER_1M /
1M_TO_2M / 2M_PLUS) and `serving_projection.py` (Phase-E legacy `models`/`trims` projection with
`_BODY_TO_TDR` labels and consensus rules) are separate consumers.

---

## 6. Write-path inputs that are not identity

| Path | Feeds | Notes |
|---|---|---|
| Admin editor (TS) → `canonical_input_batches` → worker | all §4.10 ops | the only routine write path today |
| `tools/pricefeed_write.py`, `price_promote_batch.py` | `APPEND_PRICE`/`CORRECT_PRICE` | §4.11 |
| `tools/ecosticker_import.py`, `eco_trim_proposals.py` | ECO evidence, `UPSERT_MODEL_BUNDLE` | §4.8 |
| `vehreg/spec_excel.py` | `APPEND_SPEC` rows | identity column `canonical_trim_id`; headers must be registered field keys or core int fields (`seats, length_mm, width_mm, height_mm, wheelbase_mm, engine_cc`) / `battery_kwh`; booleans `1/true/yes/y`, `0/false/no/n`; tokens `UNKNOWN, NOT_AVAILABLE, NOT_APPLICABLE` |
| `retail_lineup_*` workers | current-retail sets / lifecycle via bootstrap | owner-authoritative; source_ref optional |
| `vehreg/authoring.py` (CSV), `tools/seed_catalog.py`, `tools/add_2026_models.py` | catalog JSON directly | legacy bulk authoring, bypasses the revision log |
| `tdr_bridge/external_identity_registry.py` | `integration_data/external_identity_registry.json` | legacy uuid ↔ canonical bindings; namespace `legacy_tdr`; states `active/retired`; authority `explicit_review` |

---

## 7. Test reference (for Phase 0 step 4)

Python tests under `tests/` that pin the rules above. Step 4 must reproduce these cases.

| Area | Tests |
|---|---|
| IDs, slug, trim identity | `test_trim_identity_rule`, `test_vehreg` (normalize/catalog sections), `test_catalog_structural_integrity`, `test_catalog_no_shadow_nameplates` |
| Taxonomy, entities, catalog validate | `test_vehreg`, `test_powertrain_rules`, `test_powertrain_catalog_fixes`, `test_catalog_corrections`, `test_catalog_stubs`, `test_product_master` |
| Price ledger, campaigns, maintenance | `test_price_ledger`, `test_price_editing`, `test_canonical_price_maintenance`, `test_fronx_corrections`, `test_price_time_semantics`, `test_price_time_integration` |
| Comparable specs | `test_comparable_specs_phase4`, `test_spec_excel`, `test_spec_excel_atomic_apply`, `test_spec_excel_source_free` |
| ECO | `test_ecosticker_*`, `test_eco_*`, `test_jaecoo_j5_*` |
| Write pipeline | `test_canonical_write_phase_c`, `test_input_pipeline`, `test_admin_delete_trim`, `test_admin_create_vehicle*`, `test_admin_editor_sibling_preservation`, `test_canonical_queue_phase_c`, `test_enqueue_canonical_batch` |
| Overlay, fragments, reconciliation | `test_trim_reconciliation`, `test_trim_reconciliation_data`, `test_trim_verified_fragments`, `test_trim_evidence_merge`, `test_source_dispositions` |
| Lifecycle, current retail, scope | `test_current_retail_set`, `test_trim_retail_lifecycle_review`, `test_retail_lifecycle_projection`, `test_retail_scope`, `test_model_operational_state`, `test_retail_lineup_*` |
| Release build / publish | `test_tdr_bridge`, `test_release_retail_price_band_scope`, `test_release_scoped_reads`, `test_release_retention`, `test_publish_canonical_verify_serving`, `test_staged_vehicle_release_migration_v48`, `test_release_activation_staleness_guard_migration_v44`, `test_tdr_historical_state` |
| Price intelligence | `test_pricefeed*`, `test_price_match_p4*`, `test_price_reconcile_p5*`, `test_price_promote_p6*`, `test_price_lifecycle_p0`, `test_price_bundle_lineage*`, `test_price_coverage_*` |
| Identity registry | `test_external_identity_registry`, `test_external_identity_sync` |

---

## 8. What a DB master must carry to keep parity

Minimum state the master tables (step 2) need so the existing views can be rebuilt (step 3):

- Brand/model/generation/variant/trim rows **with their composed ids** (never re-derived on read).
- Every Model field in `asdict(Model)` (payload is served as-is), incl. `incomplete`,
  `powertrain_checked`, `retail_status`, `retail_checked_at`, `retail_source`, `notes`, `overrides`.
- Variants (they still drive `payload.powertrains`, `production_type`, `production_country`).
- Overlay/fragment-only trims and their merged `specs` keys (they are not in `Catalog.trims`).
- Price rows including retracted ones and `reviewed_by` (retracted are hidden from serving but kept).
- Campaigns with options and conditions.
- Spec facts including PROVISIONAL and superseded ones (serving shows only resolved VERIFIED).
- ECO evidence rows (`ecosticker_evidence`).
- Sidecars: current-retail sets, trim lifecycle decisions, model operational state.
- Crosswalk inputs (legacy inventory, overrides) or the resolved `tdr_*_id` / slug values.
- `as_of` semantics: the values in §5 depend on the date (§9.1).

---

## 9. Findings to resolve in later steps (not changed here)

1. **Time-dependent values are frozen per release.** `retail_price_min/max`, `current_list_price`,
   `campaign_quote`, `comparable_specs`, model `generation_id`, trim `status` (generation ended) are
   computed with the build date. A live DB view would change at midnight; the current views change
   only on publish. The parity test must pin `as_of` to the active release's `as_of`.
2. **Two slug algorithms** (§3.1 ids keep Thai, §3.2 URL slugs drop it) and both have fallbacks
   (`unnamed`, `vehicle`). A Thai-only name produces `vehicle` as URL slug.
3. **Public slugs come from a name-based crosswalk recomputed every release**, so a newly matched
   legacy row can change a model's slug. v3 §3 wants ids that never change; slugs are not covered
   explicitly.
4. **Model status is never `UNVERIFIED` in serving** (lifecycle maps everything non-HISTORICAL to
   CURRENT), although the catalog default and the DB constraint allow it. v3 §6.A counts 102
   `UNVERIFIED` trims; at trim level those come only from approved-set non-members.
5. **Overlay/fragment trims are invisible to `Catalog`** — no prices, no spec facts, no price
   eligibility, cannot be in an approved current set until materialized via `UPSERT_MODEL_BUNDLE`.
   Their `campaign_quote` is `{}` while catalog trims always get the full shape.
6. **`price_ledger` and `spec_facts` sections include only base-catalog trims**; overlay trims never
   have rows.
7. **Trim deletion is a hard delete** of the JSON row (guarded by price/spec/campaign references).
   v3 §1.5 requires soft delete.
8. **Spec facts written by `APPEND_SPEC` replace the previous fact in place** (same `fact_id`
   file), while other paths treat `fact_id` as immutable. The history lives only in the revision log.
9. **`ValueState.UNKNOWN` and `NOT_AVAILABLE` exist** in the spec engine and in the Excel tokens; v3
   §3 drops UNKNOWN rows and introduces `ABSENT`. `NOT_AVAILABLE` has no v3 counterpart.
10. **Conflicts fail the whole release** (same-start LIST_PRICE with different amounts; same-start
    spec facts with different values; overlay spec conflicts). v3 resolves same-tier disagreement
    without failing.
11. **`UPSERT_MODEL_BUNDLE` patches are shallow merges**; a field cannot be cleared by omission.
12. **Legacy bulk tools** (`authoring.py`, `seed_catalog.py`, `add_2026_models.py`) write catalog JSON
    without revisions; they must be retired or routed through the master in step 5.
13. **`brand.origin_country`** is served from `brand_origin` unnormalized, while variant origins go
    through `normalize_country`.
