# Engine rules on the Vehicle Master (Phase 0 step 4)

This is Phase 0 step 4 of [`VEHICLE_DB_V3.md`](VEHICLE_DB_V3.md): port the engine rules. It is a parity port of the rules in
[`ENGINE_INVENTORY.md`](ENGINE_INVENTORY.md) onto the v57 master tables. The goal is that the master stays valid once
the release engine is no longer what validates it. This is not v3 Phase 1: no authority tiers, observations, change log,
ABSENT/tombstones, same-tier conflict resolution or soft-delete redesign. Where a later v3 rule conflicts, the engine's
behaviour is kept and the conflict is listed in §5.

| Piece | Path |
|---|---|
| Migration | `supabase/migration_v59_vehicle_engine_rules.sql` (not applied to production) |
| TypeScript | `lib/vehicle-engine/{taxonomy,entities,pricing,specs,lifecycle,sidecars,eco,served}.ts` |
| Parity corpus | `automotive/vehicle_master/tools/engine_rule_corpus.py` → `tests/fixtures/engine_rule_corpus.json` |
| Tests | `scripts/check-vehicle-engine-rules.ts` (TS vs corpus) · `tests/test_vehicle_engine_rules_migration_v59.py` (DB vs engine) · `tests/test_engine_rule_corpus.py` (corpus vs engine) |

## 1. Where a rule lives

Each rule has one new enforcement point. The Python engine stays the reference, and the tests compare against it.

- **CHECK constraint.** An invariant of one row, for example `Model.validate`, `PriceRecord.validate` or the slug shape of
  an id. Postgres validates every existing row when the constraint is added.
- **Trigger.** A rule across rows that must not be bypassable: a same-start conflict, append-only prices, immutable ids,
  base-catalog-only references, or the ECO cross-check. These are deferred to commit, because the engine validates a whole
  write. For example, a same-day price replacement retracts the old row and appends the new one.
  `vehicle_engine_rules_check()` reports the same rules over every row, and the migration refuses to apply unless that
  report is empty.
- **TypeScript.** A rule that needs:
  - the comparable-spec registry, which v3 §3 keeps in `lib/spec-field-registry.ts`;
  - the facet resolution chain;
  - raw-input parsing (aliases, string trimming);
  - write planning (live-row selection, supersede/retract/close, sidecar actions);
  - the §5 computations.

  These are pure functions with no I/O. They are the rules a server write layer runs before it writes.
- **Python only (deferred).** Deriving an id from a name (`slug`, `trim_identity`), and the rules of the old file write path.
  Each is in §3 with its reason.

The rule functions (`_vm_*`) are executable by `service_role` only. That is the role that writes the master; CHECK
expressions and trigger bodies run as the writing role. Browser roles still have no write privilege on any master table.

## 2. Rule-parity matrix

Statuses:
- **ported (DB):** a constraint or trigger in `migration_v59`.
- **ported (TS):** a function in `lib/vehicle-engine/`.
- **deferred:** with the reason given.

Reference tests:
- **`DB`:** `test_vehicle_engine_rules_migration_v59.py`. Each case's expected accept/reject is computed by calling the
  Python engine inside the test.
- **`TS`:** `check-vehicle-engine-rules.ts`. Each case's expected value or message comes from the corpus the engine
  generated.

### A. Identity / ids (§2, §3)

| Rule (ENGINE_INVENTORY) | Python | New enforcement | Reference tests | Status |
|---|---|---|---|---|
| Brand id is one slug segment | `catalog._add_brand_payload_inplace`, `normalize.slug` | `vm_rule_brand_identity` (`_vm_slug_segment`) | DB `test_brand_ids_have_the_slug_shape`; `test_trim_identity_rule`, `test_vehicle_master_tables_migration_v57` | ported (DB) |
| Model `<brand>.<seg>`, generation `<model>.<seg>`, variant `<generation>.<seg>`, trim `<generation>.trim.<seg>` | `catalog._add_*`, `normalize.trim_identity` | `vm_rule_{model,generation,variant,trim}_identity` (`_vm_child_id`) | DB rehearsal on production copy; `test_trim_identity_rule` | ported (DB) |
| Variant and trim belong to the generation's model | catalog nesting | FKs `vm_rule_{variant,trim}_generation_model` → `(canonical_id, model_id)` | DB `test_structure_rules` | ported (DB) |
| Trim's `variant` resolves under the **same** generation | `Catalog._resolve_trim_variant_ref` | FK `vm_rule_trim_variant` → `vehicle_variants(canonical_id, generation_id)` | DB `test_structure_rules` | ported (DB) |
| Existing ids never change (incl. parent ids) | ids composed from the file path; v3 §2.2 | `vm_rule_freeze_ids` (`_vm_freeze_keys`) on every master table | DB `test_ids_never_change`, `test_facts_are_revised_in_place_never_deleted_or_renamed` | ported (DB) |
| Duplicate ids rejected | `CatalogError` on load | primary keys (v57) | v57 tests | ported (v57) |
| Overlay/fragment local id `^[a-z0-9][a-z0-9_]*$` | `trim_reconciliation._LOCAL_ID`, `trim_fragments._LOCAL_ID` | `vm_rule_trim_validate` → `_vm_overlay_trim_problems` | DB `test_overlay_trims_follow_the_overlay_rules`; `test_trim_reconciliation`, `test_trim_verified_fragments` | ported (DB) |
| Payload identity fields equal the row's columns | (one source in files) | `vm_rule_*_identity`, payload checks in `_vm_price_problems` / `_vm_fact_problems` / sidecar row checks | DB `test_ledger_is_append_only` ("columns and payload must move together") | ported (DB) |
| **Deriving** a segment from a name: `slug`, `trim_local_id`, `trim_identity`, `slug(local_id) == local_id` | `vehreg/normalize.py`, `product.import_trims` | stays in Python. The DB checks the **shape** only, see F3 | `test_trim_identity_rule`, DB `test_slug_shape_is_a_superset_of_slug_output` | **deferred.** One implementation (ENGINE_INVENTORY §2; `lib/canonical-vehicle-create.ts`). A second one in TS or SQL would drift on Thai marks and corporate noise words. A Phase 1 writer must call the Python rule. |
| Public URL slugs (`_slug`, crosswalk) | `tdr_bridge/release.py` | stored as served (`vehicle_*.slug`), immutable via the id-freeze trigger on keys | §4 | deferred: release-time crosswalk, frozen (§9.2, §9.3) |
| `duplicate_body_warnings` (same brand + `slug(name_en)` + body + cab) | `Catalog.duplicate_body_warnings` | — | `test_catalog_no_shadow_nameplates` | **deferred:** needs `slug(name_en)` (see above) |

### B. Taxonomy and entities (§4.1–§4.4)

| Rule | Python | New enforcement | Reference tests | Status |
|---|---|---|---|---|
| Facet parsing: member name, then value, then aliases (incl. the Drivetrain `4X4`/`FOUR_WD` KeyError, F1) | `taxonomy.Facet.parse`, `FACET_ALIASES` | `taxonomy.ts parseFacet` | TS taxonomy: 3,157 cases (every name, value, alias, case/spacing variant and junk input × 11 facets); `test_vehreg` | ported (TS) |
| Stored facet values are closed vocabularies | enums | `_vm_model_problems`, `_vm_variant_problems`, `_vm_market_trim_problems`, `vm_rule_*_segment` | DB model/variant/trim cases | ported (DB) |
| `check_registration`, pickup⇔cab, `retail_status CURRENT` needs source + date | `Model.validate` | `vm_rule_model_validate` (`_vm_model_problems`) | DB `test_models_are_accepted_exactly_when_the_engine_accepts_them` (10 cases); `test_vehreg` | ported (DB) |
| Complete model: body ≠ OTHER; at least 1 variant; every model has at least 1 generation | `Catalog.validate`, `Catalog._add_model` | `_vm_model_problems`; `_vm_structure_problems` (`model_has_variant`, `model_has_generation`) | DB model cases, `test_structure_rules` | ported (DB) |
| Powertrain rule (skipped for incomplete variant), origin rule, LOCKED_AT_MODEL, price min/max order, same band, price within range; skipped for incomplete **models** | `Variant.validate`, `Catalog.validate` | `_vm_variant_problems` via deferred trigger (`variant_validate` needs the model's `incomplete` flag) | DB `test_variants_are_accepted_exactly_when_the_engine_accepts_them` (14 cases); `test_powertrain_rules`, `test_powertrain_catalog_fixes` | ported (DB) |
| MarketTrim: exact powertrain, positive integer dimensions/seats/engine, positive battery, legacy price ≥ 0, wheelbase < length, BEV without engine | `MarketTrim.validate`, loader | `vm_rule_trim_validate` → `_vm_market_trim_problems` (over `catalog_payload`) | DB `test_catalog_trims_…` (10 cases), `test_bev_trim_cannot_carry_an_engine`; `test_catalog_structural_integrity` | ported (DB) |
| Trim powertrain equals its variant's (unless either is UNKNOWN) | `Catalog.validate` | `_vm_structure_problems` (`trim_variant_powertrain`) | DB `test_structure_rules` | ported (DB) |
| Resolution chain + `cross_check` (body/segment F, powertrain, origin, registration on merged facets) | `entities.resolve`, `cross_check` | `entities.ts resolve`, `crossCheck`, `validateCatalogResolution` | TS resolution: the full 2026 repository catalog (0 problems, as Python) + 15 synthetic catalogs; `test_vehreg` | ported (TS). It needs the merged four-layer view, which a row constraint cannot see. Note: the cross-facet checks also exist per row in the DB functions. Those are two placements of one rule, for two scopes (the row vs the resolved chain). |
| Catalog file loading (brand payload parse, defaults, `source_refs` cleaning, staged brand merge) | `vehreg/catalog.py` | — | `test_vehreg` | **deferred:** this is the input format of the old file write path (closed in step 5). The master holds the parsed rows. |
| `incomplete_models()` gap report | `Catalog.incomplete_models` | — | `test_catalog_stubs` | deferred: a report, not a rule |

### C. Price ledger and campaigns (§4.6)

| Rule | Python | New enforcement | Reference tests | Status |
|---|---|---|---|---|
| Row parse: unknown fields, digit-only amounts, `PriceType.parse`, string stripping, ISO dates | `PriceLedger.add_payload` | `pricing.ts parsePriceRow` | TS price_parse (31 of 32 cases; 1 known gap, F2); `test_price_ledger` | ported (TS) |
| `PriceRecord.validate`: positive amount, type, document id, positive reference price, campaign/option pairing, retraction reason, LIST needs a start, `from ≤ to` | `PriceRecord.validate` | `vm_rule_price_validate` → `_vm_price_problems` | DB `test_price_rows_are_accepted_exactly_when_the_engine_accepts_them` (22 cases) | ported (DB) |
| Trim exists **in the base catalog**; campaign exists; option exists in it | `PriceLedger.add_payload`/`validate` | FK `vehicle_trims`; `price_on_catalog_trim`; FKs `vm_rule_price_campaign`, `vm_rule_price_option` | DB price cases (unknown campaign / option / trim), overlay test | ported (DB) |
| Same-start conflict (LIST; CAMPAIGN/FINANCE per campaign + option) | `PriceLedger.validate` → `current_price_for_scope` | deferred trigger `vm_rule_price_conflicts` (`_vm_price_conflicts`) | DB price cases (7 conflict cases), `test_same_day_replacement_commits_as_one_write`; `test_price_time_semantics` | ported (DB) |
| Served ⇔ not retracted | §5.2 | `in_release = (retracted_at is null)` in `_vm_price_problems` | DB `test_ledger_is_append_only` | ported (DB) |
| Append-only: only `effective_to`, `retracted_at`, `retraction_reason`, `reviewed_by`, `notes` change; no un-retract; no delete | `product.correct_price` / `close_price` (the only mutations) | trigger `vm_rule_price_append_only` | DB `test_ledger_is_append_only` (8 cases), `test_service_role_cannot_bypass_the_rules` | ported (DB) |
| `correct_price` (exactly one live row; supersede/retract; same amount no-op; start ordering), `close_price` | `vehreg/product.py` | `pricing.ts planCorrectPrice`, `planClosePrice` | TS price_planners (12 scenarios run through the real functions on data trees); `test_price_editing`, `test_canonical_price_maintenance` | ported (TS) |
| APPEND_PRICE same-day rule (no-op / retract-and-replace / append) | `canonical_write._append_price` | `pricing.ts planAppendPrice` | TS append_price (4 scenarios through the real `CanonicalWritePipeline`) | ported (TS) |
| Campaign parse (unknown fields, options array, statuses, quota digits, conditions) | `_parse_campaign`, `_parse_conditions` | `pricing.ts parseCampaign` | TS campaign_parse (21 cases) | ported (TS) |
| `Campaign.validate` (+ option and condition rules, quota restated) | `Campaign.validate` | `vm_rule_campaign_validate` → `_vm_campaign_problems`; `vm_rule_promotion_option`; `campaign_options` structure rule | DB `test_campaigns_…` (12 cases), `test_campaign_options_and_promotions_stay_one_set` | ported (DB) |
| `append_prices` requires `source`, `source_ref`, `observed_at` | `product.append_prices` | — | `test_price_editing` | **deferred.** It is a rule of one bulk import path, not of the ledger (APPEND_PRICE does not apply it). Which write paths exist after step 5 is Phase 1's decision. |
| Price-intelligence feed (tiers, matching, promotion, writer precedence) | `vehreg/pricefeed*`, `price_*` | — | `test_pricefeed*`, `test_price_*` | **deferred / out of scope.** Not master rules. The feed writes through APPEND_PRICE / CORRECT_PRICE, whose rules are ported. |

### D. Comparable-spec facts (§4.7)

| Rule | Python | New enforcement | Reference tests | Status |
|---|---|---|---|---|
| Registry: key shape, unique, no price words, labels, NUMBER unit, precision, enums, allowed keys, profiles | `SpecRegistry.load` / `validate` | `specs.ts validateSpecRegistry` | TS registry (13 cases incl. the repository registry) | ported (TS): the registry lives in `lib/spec-field-registry.ts`'s data file (v3 §3) |
| Field registered; value fits `value_type`/`canonical_unit`; qualifiers ⊆ `comparison_qualifiers`; field applies to the trim's powertrain | `SpecFieldDefinition.validate_value`, `SpecLedger._validate_fact` | `specs.ts validateFactAgainstRegistry` | TS facts (71 cases over every value type) | ported (TS): needs the registry |
| Required ids; non-KNOWN ⇒ null value; KNOWN ⇒ value; `observed_at`; admin/non-admin source rules; `from ≤ to`; qualifiers are strings; price-word guard | `_validate_fact`, `add_payload` | `vm_rule_fact_validate` → `_vm_fact_problems` | DB `test_facts_are_accepted_exactly_when_the_engine_accepts_them` (17 cases) | ported (DB) |
| Same (trim, field, qualifier context, start) with different (state, value) | `SpecLedger.validate` | deferred trigger `vm_rule_fact_conflicts` (`_vm_fact_conflicts`; `value::text` keeps `5` ≠ `5.0`, as `json.dumps`) | DB fact cases ("conflicts", "agrees", "5.0 is not 5", "another start") | ported (DB) |
| Facts only on base-catalog trims | `_validate_fact` (`trim does not exist`) | `fact_on_catalog_trim` | DB "unknown trim" | ported (DB) |
| `fact_id` immutable; APPEND_SPEC revises a fact in place; facts never deleted | `add_payload` / `_append_spec` | `vm_rule_freeze_ids` (fact_id), `vm_rule_fact_no_delete`; UPDATE allowed | DB `test_facts_are_revised_in_place_never_deleted_or_renamed` | ported (DB), keeps §9.8 |
| Verification states VERIFIED / PROVISIONAL; value states incl. UNKNOWN, NOT_AVAILABLE | enums | v57 CHECKs | DB fact cases | kept as is (§9.9 is not resolved here) |
| `SpecLedger.resolved` | §5.5 | `specs.ts resolvedFacts` | §4 | ported (TS) |
| APPEND_SPEC `trim_ref` resolution, default `admin:<trim>:<field>` | `_append_spec` | — | `test_canonical_write_phase_c` | **deferred:** `trim_ref` needs `trim_identity` (Python only) |
| ECO candidate store, cohorts, battle cards | `ECOCandidateSpecStore`, `ComparableCohort` | — | `test_comparable_specs_phase4` | deferred: preview tooling, not master state |

### E. ECO evidence (§4.8)

| Rule | Python | New enforcement | Reference tests | Status |
|---|---|---|---|---|
| Parse (powertrain aliases, stripping) | `ECOStickerSpecStore.add_payload` | `eco.ts parseEcoSpec` | covered by taxonomy cases | ported (TS) |
| No price keys; `trim_id`/`source_ref` required; exact powertrain; positive seats/voltage/weight/range | `add_payload`, `ECOStickerSpec.validate` | `vm_rule_eco_validate` → `_vm_eco_problems` | DB `test_eco_evidence_…` (9 cases) | ported (DB) |
| Base-catalog trim; `source_ref` attached to the trim; powertrain, seats and tyre agree | `validate_against_catalog` | `eco_on_catalog_trim`, `eco_cross_check` (deferred trigger) | DB ECO cases | ported (DB) |
| ECO → trim promotion, review sidecar | `ecosticker_promote`, `eco_review_write` | — | `test_ecosticker_*`, `test_eco_*` | deferred: staging workflow, not in the master |

### F. Current-retail sets and lifecycle (§4.9)

| Rule | Python | New enforcement | Reference tests | Status |
|---|---|---|---|---|
| Named HUMAN reviewer; `source_ref` empty or http(s); non-blank unique ids; payload equals columns | `_validated_reviewer`, `_validated_source_ref`, `validate_current_retail_sets` | `vm_rule_current_retail_row`, `vm_rule_trim_lifecycle_row`, `vm_rule_model_operational_row` | DB set/decision cases | ported (DB) |
| Approved ids are base-catalog trims of the model | `validate_current_retail_sets` | `current_retail_member` | DB `test_current_retail_sets_…` (6 cases), `test_a_member_trim_cannot_be_deleted` | ported (DB) |
| A set may not include a trim with an unreopened HISTORICAL decision | `replace_current_retail_set` | deferred trigger `vm_rule_retail_decisions` | DB set case "a HISTORICAL-decided trim", `test_reopen_then_approve_in_one_write` | ported (DB) |
| HISTORICAL decision for an approved member is refused **when the parent model is not CURRENT** (F4) | `retail_lifecycle_review._upsert` | `vm_rule_retail_decisions` | DB `test_member_historical_decision_follows_the_engine` | ported (DB) |
| Actions (`current`/`historical`/`reopen`, bootstrap path, required evidence on the ordinary path, parent must be CURRENT, approved-set carve-out); dates per `date.fromisoformat` | `_upsert`, `upsert_bootstrap_…` | `sidecars.ts planTrimLifecycleReview` | TS sidecars (18 lifecycle scenarios through the real functions) | ported (TS): depends on the action |
| `replace_current_retail_set` normalization; `under_maintenance`/`normal` | `current_retail.py`, `model_operational_state.py` | `sidecars.ts planCurrentRetailSet`, `planModelOperationalState` | TS sidecars (10 scenarios) | ported (TS) |
| Price-coverage review, ECO review sidecars | `price_coverage_review.py`, `eco_review_write.py` | — | `test_price_coverage_*` | deferred: not migrated to the master (MASTER_TABLES.md) |

### Old write path (§4.10, §4.12)

| Rule | Status |
|---|---|
| Batch envelope, source kinds, command ids, idempotency by `revisions.jsonl`, staged-copy apply | **deferred.** This is the old write path that step 5 closes. The change log is Phase 1 (v3 §3, `canonical_write_revisions`). |
| UPSERT_MODEL_BUNDLE (shallow merge, child id prefixes, id derivation), WITHDRAW_MODEL, UPSERT_CAMPAIGN identical-payload error, `delete_trim` guard | **deferred** to the Phase 1 write layer. The invariants these commands protect are ported: id composition, immutable ids, structure rules, campaign validity, and FK and trigger guards on deleting a referenced trim. The orchestration itself (§9.11 shallow merge, §9.7 hard delete) is Phase 1 semantics. |
| Release publish RPCs (`v15`/`v44`/`v48`) | unchanged. Activation is blocked by the v58 guard. |

## 3. Deferred, in one list

1. **Id derivation** (`slug`, `trim_identity`, `slug(x) == x`, `duplicate_body_warnings`, APPEND_SPEC `trim_ref`). There is
   one implementation, in Python. A second one would silently disagree on Thai marks and corporate noise words. The DB
   checks the shape of every stored id.
2. **Old file write path** (catalog JSON parsing, batch envelope, revision log, command orchestration). Step 5 closes
   it, and Phase 1 replaces it.
3. **Workflow staging that is not master state:** overlay merge and reconciliation, source dispositions, ECO candidates,
   promotion, review sidecars, and price-coverage review.
4. **`append_prices` provenance requirement** (one bulk path) and the **price-intelligence feed** rules. These are not
   ledger rules.
5. **The §5 recompute itself, on write.** The rules are ported and proven (§4). Phase 0 has no master write path to run them.

## 4. Computed values (§5): what Phase 0 does with each

The master stores every computed value exactly as served on `served_as_of` (2026-10-01). Nothing recomputes on read,
so no value changes at midnight. Step 4 ports the rules that compute these values and proves them against production's
stored values. When a later write path changes an input, it must recompute the affected values with these functions and
the pinned `as_of`.

| Value | Inputs | Phase 0 decision | Ported rule | Proof |
|---|---|---|---|---|
| model `generation_id`, `segment` | generations | stored; recompute on write | `lifecycle.ts currentGeneration` | production: 323/323 equal |
| model `status` | `payload.retail_status` | stored; recompute on write | `modelServedStatus` | production: 323/323 |
| model `retail_price_min`/`max` | prices, generations, sidecars, maintenance | stored; recompute on write | `priceEligibleTrims` + `retailPriceBand` | production: 323/323 (140 with a band) |
| model `payload.powertrains`, `production_type`, `production_country`, `seats`, `generation`, `launch_year` | variants, generations | stored; recompute on write; editorial fallbacks stay stored | `modelDerivedPayload` | production: 323/323 |
| model `payload` editorial (`image_url`, `consumer_description`, `featured`, `launch_quarter`, `market_position`, `brand.slug`), `tdr_*_id`, `slug` | release-time crosswalk to legacy rows | **stored, frozen.** The crosswalk inputs are not master state. | — | — |
| trim `status` | model status, generation end, approved sets, decisions | stored; recompute on write | `trimServedStatus` | production: 1,569/1,569 (1,431 CURRENT, 36 HISTORICAL, 102 UNVERIFIED) |
| trim `current_list_price`, `price_history` | prices | stored; recompute on write | `currentListPrice`, `recordsFor` | production: 1,569/1,569 (304 with a list price) |
| trim `campaign_quote` | prices, campaigns | stored; recompute on write | `campaignQuote` | production: 1,569/1,569 (16 with live options) |
| trim `payload.comparable_specs`; which facts are `served_in_release` | facts, registry | stored; recompute on write | `resolvedFacts` | production: 1,569/1,569 (730 with specs) |
| trim `payload.ecosticker_evidence` | ECO evidence | stored; recompute on write | `served.ts` | production: equal |
| trim `payload.specs` | the trim's own spec record (with overlay merges) | **stored: this is master state**, not a computed value | — | — |
| price ledger rows served | prices | direct: `in_release = not retracted` (CHECK) | — | DB |
| release envelope (`counts`, `source_hash`, `historical_model_state`, `trim_reconciliation`) | release build | not master state. `historical_model_state` stays on releases (SERVING_CONTRACT §7.2) | — | — |

The production check is local and read-only. It ran the TS recompute at `as_of = 2026-10-01` over a read-only export of
the production master (2 Oct 2026) and found 0 differences in every column listed above. With `as_of = 2026-06-01`,
2,013 values differ, which shows the comparison is sensitive. The committed equivalent is the corpus's `served` section:
the engine's own release build on five data trees.

## 5. Findings (not resolved here)

- **F1. Drivetrain aliases `4X4` and `FOUR_WD` raise `KeyError`.** `FACET_ALIASES` maps them to `"4WD"`, the member's
  value, but `Facet.parse` looks aliases up by member *name* (`FOURWD`). The port keeps the rejection. Fixing it would be
  an engine change.
- **F2. JSON integral floats.** Python rejects `amount_thb: 899000.0` (a float), but after `JSON.parse` JavaScript sees
  `899000`. The TS parser cannot reproduce that one rejection. The DB stores `bigint`, so the stored value is the same.
  The corpus marks the case, and the TS check lists it instead of counting it.
- **F3. Id shape vs slug output.** The DB accepts any slug-shaped segment, so `dual_motor` is accepted even though
  `slug("dual_motor") == "dual"`. Only Python can derive a segment (§3, item 1).
- **F4. ENGINE_INVENTORY §4.9 simplifies the HISTORICAL-for-member rule.** The table says "never `historical` for a
  member". The code refuses it only when the parent model is not CURRENT. With a CURRENT parent the decision is
  recorded, and the approved set keeps the trim CURRENT. The port follows the code.
- **F5. Seeding a fresh database.** The v57 seed writes the release stage and the supplemental stage in separate
  transactions, and v59 rightly rejects the state in between (e.g. trims whose variants are not seeded yet). On a new
  database, apply through v58, seed, then apply v59. Production is already seeded.
- **F6. Two date parsers.** The price, spec and campaign rules require `YYYY-MM-DD`. The sidecar writers call
  `date.fromisoformat` directly, so they also accept `20260927` and ISO week dates (`2026-W39-7`) and normalize them.
  Both are ported as they are.
- Kept unchanged on purpose:
  - **§9.7** trim hard delete. Allowed only when nothing references the trim, as in the engine.
  - **§9.8** in-place fact revision.
  - **§9.9** UNKNOWN / NOT_AVAILABLE.
  - **§9.10** a conflict refuses the write.
  - **§9.13** brand origin is not normalized.
- None of the §9 items is resolved by this step.
