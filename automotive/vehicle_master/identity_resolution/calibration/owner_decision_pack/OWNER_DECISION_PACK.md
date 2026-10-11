# Owner Decision & Calibration Preparation Pack

> **Preparation only. Nothing here is decided, calibrated, approved or bound.** Pack `ir-owner-decision-pack/1`, branch `claude/wizardly-keller-0ixbhj`, PR #200 (draft), `adoption.binding = false`. Built from the accepted relation export (`ir-relation-export/1`, manifest sha256 `e9d74e05ce9c`) and four byte-pinned PR #201 artifacts @`30d2618a4`. No rule, policy value, export or sheet was changed. Every `owner_*` field in every file is blank; every column named `*_NON_AUTHORITATIVE` is a machine suggestion the owner may ignore.

Two kinds of verdict are kept apart (`verdict_crosswalk.csv`): the R6 sheet asks **is this Ice group this TDR model?** (a pair); PR #201's adjudication asks **should TDR have a model for this group at all?** (a group). A pair verdict never implies a group verdict or the reverse; `check_label_consistency()` only flags answers that cannot both be true.

## 1. The smallest first set

Nothing here requires all 560 R6 rows to be labelled. The first wave is **65 owner actions**: 4 rule/filing questions, 5 alias verdicts, 9 CREATE verdicts and 47 R6 pair verdicts (48 starter rows; 1 of them is answered together with an alias or CREATE verdict). It covers 80.7% of the lifetime units of all 69 AUTO pairs, every known suspicious-case family, every PART_OF / COMPOSED_OF and several-candidate row, and 93.1% of the lifetime units of the 82 CREATE candidates (15 rows). It is built to find a systematic failure early, not to certify a rate (see §7).

| item | kind | question | resolves | units |
|---|---|---|---|---|
| INIT-01 | CONTRACT | When the producer's brand relation to a TDR brand is RELATED (capped at PROPOSE), must a consumer take its candidate set from the producer instead of resolving the brand itself from catalog labels? | OD-B02 .. OD-B08 (7) | 15 |
| INIT-02 | CONTRACT | May a catalog brand `aliases` entry ever be a brand relation, and if so as which typed class (SAME / RELABEL / RELATED) and with which provenance? Decide the one label in the pack (JETOUR under Chery). | OD-B01 | 3 |
| INIT-03 | CATALOG | Where are Maxus-badged models filed: under the registration brand MG (as mg.mg_maxus_7 / mg.mg_maxus_9 are today) or under a Maxus brand? | OD-B09 .. OD-C11 (4) | 3032 |
| INIT-04 | CONTRACT | What does a TDR catalog model `aliases` entry assert: the same model, a registration-attribution label that may cover a broader family, or a lookup convenience? (The nine alias rows show all three readings occur.) | OD-A01 .. OD-A09 (9) | 26946 |
| INIT-OD-A01 | ALIAS_VERDICT | Jaecoo J5 (jaecoo-jaecoo-j5) vs catalog alias on jaecoo.jaecoo_5_ev: which alias class, and is the group that model? | OD-A01 | 24045 |
| INIT-OD-A02 | ALIAS_VERDICT | Binguo (wuling-binguo) vs catalog alias on wuling.wuling_bingo: which alias class, and is the group that model? | OD-A02 | 1285 |
| INIT-OD-A03 | ALIAS_VERDICT | Jaecoo J7 (jaecoo-jaecoo-j7) vs catalog alias on jaecoo.jaecoo_7: which alias class, and is the group that model? | OD-A03 | 1091 |
| INIT-OD-A04 | ALIAS_VERDICT | e6 (byd-e6) vs catalog alias on byd.byd_m6: which alias class, and is the group that model? | OD-A04 | 420 |
| INIT-OD-A05 | ALIAS_VERDICT | VW ID.Buzz (volkswagen-vw-idbuzz) vs catalog alias on volkswagen.caravelle: which alias class, and is the group that model? | OD-A05 | 51 |
| INIT-OD-C04 | CREATE_VERDICT | Should TDR have a canonical model for VOLT VOLT Volt (volt.volt)? | OD-C04 | 484 |
| INIT-OD-C06 | CREATE_VERDICT | Should TDR have a canonical model for JAECOO Jaecoo J6 (jaecoo.j6)? | OD-C06 | 8659 |
| INIT-OD-C07 | CREATE_VERDICT | Should TDR have a canonical model for ZEEKR Zeekr 7X (zeekr.7x)? | OD-C07 | 2892 |
| INIT-OD-C08 | CREATE_VERDICT | Should TDR have a canonical model for MAZDA Mazda6e (mazda.mazda6e)? | OD-C08 | 604 |
| INIT-OD-C10 | CREATE_VERDICT | Should TDR have a canonical model for PEUGEOT Peugeot 5008 (peugeot.5008)? | OD-C10 | 316 |
| INIT-OD-C19 | CREATE_VERDICT | Should TDR have a canonical model for TOYOTA Vios (toyota.vios)? | OD-C19 | 6647 |
| INIT-OD-C20 | CREATE_VERDICT | Should TDR have a canonical model for NISSAN Nissan March (nissan.march)? | OD-C20 | 4000 |
| INIT-OD-C21 | CREATE_VERDICT | Should TDR have a canonical model for NISSAN Nissan Note (nissan.note)? | OD-C21 | 3667 |
| INIT-OD-C22 | CREATE_VERDICT | Should TDR have a canonical model for TOYOTA Toyota Sienta (toyota.sienta)? | OD-C22 | 2645 |
| INIT-R6-S1 | R6_PAIR_VERDICTS | Pair verdicts for review ranks 1, 2, 6, 83, 86, 87, 88, 90, 92, 93, 94, 96, 99, 105, 114, 116, 126, 142 (v1 AUTO pairs that carry 80% of AUTO-pair units). | R6-1 .. R6-142 (18) | 1355944 |
| INIT-R6-S2 | R6_PAIR_VERDICTS | Pair verdicts for review ranks 3, 7, 8, 9, 10, 11, 20, 21, 23, 25, 29, 30, 46, 54, 56 (legacy AUTO rows that v1 does not AUTO (the units-heaviest 80%)). | R6-3 .. R6-56 (15) | 73927 |
| INIT-R6-S3 | R6_PAIR_VERDICTS | Pair verdicts for review ranks 84, 85, 93, 95, 98, 106, 184 (the largest row of each known-case family). | R6-84 .. R6-184 (7) | 1481061 |
| INIT-R6-S4 | R6_PAIR_VERDICTS | Pair verdicts for review ranks 508, 509, 510, 511, 512, 513, 514, 515, 516 (PART_OF / COMPOSED_OF and several-viable-candidate rows). | R6-508 .. R6-516 (9) | 66914 |

The full order, with later waves, is `decision_queue.csv`.

## 2. R6 owner sheet vs PR #201's 82 provisional CREATE candidates

- 47 of the 82 candidates appear in `r6_owner_review.csv` (47 sheet rows): 44 legacy-proposed pairs, 2 v1-only pairs, 1 without a candidate. The other 35 have only the missing-identity question.
- 4 of the first 176 prioritised rows are CREATE candidates (audi-audi-a8l, jaecoo-jaecoo-j7, wuling-binguo, zeekr-zeekr-7x): for them a pair verdict and a group verdict are two questions about one group. `r6_create_reconciliation.csv` lists every (candidate, sheet row) pair with the owner field each verdict goes into.
- Readings: a CORRECT_EQUIVALENT pair contradicts VALID_MISSING_CANONICAL; WRONG_TARGET leaves the group question open; NO_TDR_TARGET contradicts EXISTING_IDENTITY / VARIANT_TRIM_CODE; PART_OF / COMPOSED_OF with a new model is a REVIEW prompt, not a conflict.

| pair verdict \ group verdict | VALID_MISSING_CANONICAL | EXISTING_IDENTITY | VARIANT_TRIM_CODE | AMBIGUOUS |
|---|---|---|---|---|
| CORRECT_EQUIVALENT | CONFLICT | CONSISTENT_IF_SAME_TARGET | CONSISTENT_IF_SAME_TARGET | CONSISTENT |
| CORRECT_PART_OF | REVIEW | CONSISTENT | CONSISTENT | CONSISTENT |
| CORRECT_COMPOSED_OF | REVIEW | CONSISTENT | CONSISTENT | CONSISTENT |
| WRONG_TARGET | CONSISTENT | CONSISTENT_IF_DIFFERENT_TARGET | CONSISTENT | CONSISTENT |
| NO_TDR_TARGET | CONSISTENT | CONFLICT | CONFLICT | CONSISTENT |
| INSUFFICIENT_EVIDENCE | CONSISTENT | CONSISTENT | CONSISTENT | CONSISTENT |

## 3. Section A: nine TDR catalog-alias collisions (`catalog_alias_collisions.csv`)

A catalog model `aliases` entry equals the provider group's name. The machine class is not EQUAL by default: it is read from the registration series of the group and of the model's existing Ice claimants. A SEARCH_DISPLAY_SYNONYM is never suggested (the data cannot tell a lookup convenience from an identity claim); that distinction is the owner's.

| id | provider group (units) | alias -> catalog model | series | other EQUAL claimants | suggested class (non-auth.) | evidence |
|---|---|---|---|---|---|---|
| OD-A01 | jaecoo-jaecoo-j5 (24045) | j5/jaecoo j5 -> jaecoo.jaecoo_5_ev (Jaecoo 5 EV, CROSSOVER, aliases: 7) | STRONG 0.999999 / 12m |  | IDENTITY_EQUIVALENT | STRONG_PACK_EVIDENCE |
| OD-A02 | wuling-binguo (1285) | binguo -> wuling.wuling_bingo (Wuling Bingo, HATCHBACK, aliases: 3) | STRONG 1.0 / 24m |  | IDENTITY_EQUIVALENT | STRONG_PACK_EVIDENCE |
| OD-A03 | jaecoo-jaecoo-j7 (1091) | j7 -> jaecoo.jaecoo_7 (Jaecoo 7, CROSSOVER, aliases: 3) | STRONG 1.0 / 14m |  | IDENTITY_EQUIVALENT | STRONG_PACK_EVIDENCE |
| OD-A04 | byd-e6 (420) | e6 -> byd.byd_m6 (BYD M6, MPV, aliases: 2) | WEAK 0.364631 / 15m | byd-m6 | MISLEADING_ALIAS | STRONG_PACK_EVIDENCE |
| OD-A05 | volkswagen-vw-idbuzz (51) | id buzz -> volkswagen.caravelle (Caravelle, VAN, aliases: 3) | UNAVAILABLE None / 13m | volkswagen-volkswagen-caravelle | BROADER_MODEL_FAMILY | STRONG_PACK_EVIDENCE |
| OD-A06 | audi-audi-a8l (22) | A8L -> audi.a8 (A8, SEDAN, aliases: 2) | UNAVAILABLE None / 8m |  | UNRESOLVED | THIN |
| OD-A07 | audi-audi-s3 (20) | S3 -> audi.rs (RS, SEDAN, aliases: 5) | UNAVAILABLE None / 9m |  | MISLEADING_ALIAS | CONTEXT_ONLY |
| OD-A08 | isuzu-isuzu-cab4 (6) | cab4 -> isuzu.dmax_cab (D-Max Cab, PICKUP, aliases: 8) | UNAVAILABLE None / 2m |  | UNRESOLVED | THIN |
| OD-A09 | volkswagen-volkswagen-multivan (6) | multivan -> volkswagen.caravelle (Caravelle, VAN, aliases: 3) | UNAVAILABLE None / 2m | volkswagen-volkswagen-caravelle | UNRESOLVED | THIN |

- **OD-A01** Jaecoo J5 and jaecoo.jaecoo_5_ev register together (corr 0.999999, ratio 0.998341, 12 common months) and no other Ice group is EQUAL to jaecoo.jaecoo_5_ev: the registrations behind the catalog model are this group's. The alias reads as the same model.
- **OD-A02** Binguo and wuling.wuling_bingo register together (corr 1.0, ratio 1.0, 24 common months) and no other Ice group is EQUAL to wuling.wuling_bingo: the registrations behind the catalog model are this group's. The alias reads as the same model.
- **OD-A03** Jaecoo J7 and jaecoo.jaecoo_7 register together (corr 1.0, ratio 1.0, 14 common months) and no other Ice group is EQUAL to jaecoo.jaecoo_7: the registrations behind the catalog model are this group's. The alias reads as the same model.
- **OD-A04** byd.byd_m6's registrations are already explained by byd-m6 (STRONG corr=0.999234 ratio=1.005274 months=23); e6 does not match them (WEAK corr 0.364631) and the model sells about 2842.0 units to the group's 118.0 in the window. The group was registered from 2564-10 (catalog launch year of byd.byd_m6: 2024), so it reads as a misleading alias; whether it is a predecessor, a rename or a separate model is the owner's call (the pack holds no lineage evidence).
- **OD-A05** volkswagen.caravelle already has Ice claimant(s) volkswagen-volkswagen-caravelle; adding VW ID.Buzz moves their combined series toward volkswagen.caravelle (WEAK corr=0.958747 ratio=1.227723 months=22 -> STRONG corr=0.998387 ratio=1.012987 months=15). TDR files this group's registrations under volkswagen.caravelle while its body/segment differ (MPV / Full Size MPV vs VAN / E): a broader-family label, not a same-model alias.
- **OD-A06** No registration series decides this (UNAVAILABLE); 22 lifetime units. Left to the owner.
- **OD-A07** audi.rs has 7 finer or coarser Ice groups and a different body/segment (Hatchback vs SEDAN); the alias reads as a trim/variant label inside a larger family. No series (UNAVAILABLE).
- **OD-A08** No registration series decides this (UNAVAILABLE); 6 lifetime units. Left to the owner.
- **OD-A09** No registration series decides this (UNAVAILABLE); 6 lifetime units. Left to the owner.

Two further CREATE candidates have registrations that coincide with a catalog model although no alias matched: jaecoo-jaecoo-j6, volt-volt-volt (`create_candidates.csv`, tier P1). Full catalog records, token lists and source references are in the CSV.

## 4. Section B: brand resolution and the Maxus filing question (`brand_resolution_cases.csv`)

| id | group (units) | label | producer relation | catalog label lookup | disagreement |
|---|---|---|---|---|---|
| OD-B01 | JETOUR\|ไม่ระบุ (3) | JETOUR | none | chery via alias(jetour) | catalog alias resolves / producer has no brand relation |
| OD-B02 | MERCEDES AMG\|SL 43 (2) | MERCEDES AMG | mercedes_benz ALIAS_RELATED | none | producer admits related brand / catalog label lookup finds none |
| OD-B03 | MERCEDES AMG\|SL 55 4MATIC (1) | MERCEDES AMG | mercedes_benz ALIAS_RELATED | none | producer admits related brand / catalog label lookup finds none |
| OD-B04 | MERCEDESBENZ MAYBACH\|S680 4 M (2) | MERCEDESBENZ MAYBACH | mercedes_benz ALIAS_RELATED | none | producer admits related brand / catalog label lookup finds none |
| OD-B05 | RANGE ROVER\|AUTOBIOGRAPHY P400E LWB (2) | RANGE ROVER | land_rover ALIAS_RELATED | none | producer admits related brand / catalog label lookup finds none |
| OD-B06 | RANGE ROVER\|EVOQUE 2 2 SD4 DYNAMIC (1) | RANGE ROVER | land_rover ALIAS_RELATED | none | producer admits related brand / catalog label lookup finds none |
| OD-B07 | RANGE ROVER\|EVOQUE 2 2L SD4 (1) | RANGE ROVER | land_rover ALIAS_RELATED | none | producer admits related brand / catalog label lookup finds none |
| OD-B08 | maxus-maxus-epc1a (6) | MAXUS | mg ALIAS_RELATED | none | producer admits related brand / catalog label lookup finds none |
| OD-B09 | maxus-maxus-v80 (135) | MG | mg EXACT | mg via id(mg)\|mg via name_en(MG) | filing of a sub brand the catalog holds under another brand |
| OD-B10 | maxus-mifa-7 (934) | MG | mg EXACT | mg via id(mg)\|mg via name_en(MG) | filing of a sub brand the catalog holds under another brand |
| OD-B11 | maxus-mifa-9 (1963) | MG | mg EXACT | mg via id(mg)\|mg via name_en(MG) | filing of a sub brand the catalog holds under another brand |

The eight unresolved parity rows are one of two things. Seven (Mercedes AMG, Maybach, Range Rover, Maxus EPC1A) are brands the producer admits as **RELATED** (pool allowed, never AUTO) and no catalog brand record carries the label, so a consumer that looks the label up itself finds nothing. One (JETOUR) is the opposite: a catalog brand `aliases` entry (Chery: omoda, jetour) resolves it and the producer has no relation. Neither is a matching-rule defect; both are about **who decides a brand relation**. Contract-level options, none naming a brand or model:

1. **Relation-first** (recommended, INIT-01): the producer's typed relation is the one place a brand relation is decided; a consumer takes its pool from it and never reports BRAND_NOT_IN_TDR for a brand the producer relates.
2. **Catalog aliases are not brand relations until typed** (recommended, INIT-02): a catalog brand `aliases` entry is a registration-attribution label; the owner types it (SAME / RELABEL / RELATED) with a provenance before it counts. JETOUR is the one label to type now.
3. **Maxus filing** (INIT-03, a catalog decision): the catalog files Maxus models under brand `mg` (mg.mg_maxus_7, mg.mg_maxus_9) and has no Maxus brand; Ice registers V80 and Mifa 7/9 under MG; policy already types MAXUS/MG RELATED and MAXUS/'MG Maxus' RELABEL. The V80 CREATE (OD-C11, proposed `mg.maxus_v80`) and the two Mifa identity reviews follow that one decision.

## 5. Section C: R6 calibration cases, first 176 rows (`r6_priority_view.csv`)

The first 176 rows are tier 1 (82 legacy AUTO rows) and tier 2 (94 high-volume legacy PROPOSED rows). Risk categories in them: SERIES_MATERIAL_CHANGE 94, HIGH_VOLUME 63, LEGACY_AUTO_NOT_AUTO_IN_V1 62, V1_AUTO_PAIR_FALSE_AUTO_EXPOSURE 52, LEGACY_PROPOSED_AUTO_IN_V1 32, INTERACTS_WITH_OTHER_DECISION 4, SERIES_STRONG_NAME_CONTRADICTS 2.

- Of 82 legacy AUTO rows, **62** are not AUTO under the current contract ([('PROPOSE', 59), ('NO_CANDIDATE', 3)]); 49 legacy PROPOSED rows become AUTO. Which side is right is exactly what the labels decide, so S2 and S1 are the two ends of one question.
- Starter batch (`starter_batch` column): S1 18 v1-AUTO pairs (≥80% of AUTO-pair units); S2 15 legacy-AUTO rows that v1 does not AUTO (≥80% of their units); S3 7 known-family representatives; S4 9 structural rows; 48 distinct rows. Rows are assigned to 5 brand-separated folds over 62 brand families (rows per fold [112, 112, 112, 112, 112]).

## 6. Section D: all 82 CREATE candidates, grouped by risk (`create_candidates.csv`)

| tier | rows | units | evidence | suggested triage (non-auth.) |
|---|---|---|---|---|
| P1_CONTRADICTING_EVIDENCE | 18 | 40045 | needs a row review | SEE_ALIAS_DECISION 9, NEEDS_OWNER_JUDGEMENT 6, CHECK_EXISTING_IDENTITY 2, SEE_BRAND_DECISION 1 |
| P2_HIGH_IMPACT_OR_AMBIGUOUS | 20 | 19633 | needs a row review | LIKELY_VALID_MISSING_CANONICAL_CHECK_NAME 20 |
| P3_HISTORICAL_BULK | 44 | 1488 | spot-check 8, then confirm or escalate | LIKELY_VALID_MISSING_CANONICAL 44 |

P1 = contradicting evidence (alias, brand collision, coinciding series, strong legacy proposal). P2 = high volume, current market or a code-like name with no contradicting evidence. P3 = historical bulk. Age and volume never make a candidate false (PR #201's rule); they only order the work. The spot-check sample is the first 8 P3 rows by a fixed hash.

## 7. Calibration after labels exist (`calibration_procedure.json`)

- **Labels → ground truth**: pair labels give positives (per link type) and negatives; group labels make every pooled candidate of a VALID_MISSING_CANONICAL group a negative; AMBIGUOUS / INSUFFICIENT_EVIDENCE are excluded and counted. `check_label_consistency()` runs first.
- **Brand-separated evaluation**: 5 folds of brand families (`brand_folds.csv`); tune on four, evaluate once on the fifth, report pooled out-of-fold predictions. No threshold is tuned on a family it is evaluated on.
- **Metrics**: AUTO precision and false-AUTO count (Wilson interval; rule of three when zero), AUTO recall, PROPOSE precision, PROPOSE-or-better recall using the weighted negative sample for the pairs the contract missed; each also unit-weighted.
- **False-AUTO analysis**: each false-AUTO is listed with its codes and classified (series coincidence, granularity, lineage, brand relation, label noise); a root cause that a gate could express is a proposal for a later round, never applied in the same pass.
- **Pending thresholds**: each is re-run at its swept values on the labelled rows (`pending_threshold_sensitivity.csv`); an entry that moves no labelled row stays pending.

| requirement | value | meaning |
|---|---|---|
| ER-01 | 69 | the whole AUTO universe on the sheet; no bound on false-AUTO can be tighter than 3/n even if every one is labelled and correct |
| ER-02 | 0.043478 | the 95% upper bound on the false-AUTO rate if all AUTO pairs are labelled and none is wrong |
| ER-03 | 0.166667 | the starter batch labels 18 AUTO pairs (80.7% of AUTO-pair units): enough to find a systematic failure, not to certify a rate |
| ER-T10 | 30 | reachable from the AUTO universe |
| ER-T05 | 60 | reachable from the AUTO universe |
| ER-T02 | 150 | NOT reachable: only 69 AUTO pairs exist on the sheet; a tolerance this tight needs structural argument, more packages, or a wider AUTO set |
| ER-T01 | 300 | NOT reachable: only 69 AUTO pairs exist on the sheet; a tolerance this tight needs structural argument, more packages, or a wider AUTO set |
| ER-F1 | 62 | families are never split across folds |
| ER-F2 | 0\|1\|2\|3\|4 | folds that hold an S1 AUTO pair (a fold without one cannot report AUTO precision); the folds are 0..4 |
| ER-N1 | 24 | weights make the sample estimate the NO_CANDIDATE population |

The honest limit: only 69 AUTO pairs exist, so even a fully labelled, error-free set bounds false-AUTO at 4.3% (95%); the starter batch bounds it at 16.7%. A tolerance tighter than that cannot be shown from this sheet; it needs structural argument, more packages, or a different AUTO scope.

Pending calibration entries whose swept values move at least one group (the rest are not constrained by the sheet): `attributes_lifecycle` (10 groups, AUTO +7/−5); `candidates_bundle_bounds` (1 groups, AUTO +0/−0); `data_sufficiency_wrong_series` (1 groups, AUTO +0/−0); `lexical_fuzzy_min_length` (2 groups, AUTO +0/−0); `series_absent_row_gap` (32 groups, AUTO +32/−0); `series_minimums` (6 groups, AUTO +0/−6); `series_strong` (2 groups, AUTO +0/−1); `series_window` (40 groups, AUTO +21/−14).

## 8. Outstanding owner questions

- **Q1 (INIT-01)** Relation-first: may a consumer take its candidate set from the producer's RELATED brand relation instead of resolving the brand itself?
- **Q2 (INIT-02)** Are catalog brand `aliases` ever a brand relation? If so, which typed class for JETOUR (and the Chery `omoda` alias), with which provenance?
- **Q3 (INIT-03)** Are Maxus-badged models filed under MG or a Maxus brand? (Decides V80's canonical id.)
- **Q4 (INIT-04)** What does a catalog model alias assert? Which of A01–A05 are the same model, a broader family, or a misleading alias?
- **Q5** CREATE verdicts for the first-wave rows, including the two series-coincident candidates that carry no alias (OD-C04 volt, OD-C06 j6).
- **Q6** Pair verdicts for the starter rows, led by the v1-AUTO pairs and the legacy-AUTO rows v1 does not AUTO.
- **Q7** What false-AUTO rate would you accept as AUTO's bar? It fixes how many AUTO labels are needed (ER-T rows) and whether the answer is reachable.
- **Q8** Is a spot-check-then-confirm rule acceptable for the P3 historical bulk, or must every row be reviewed?
- **Q9** Do you want the negative sample (24 groups) labelled now, or only after the starter batch shows whether recall is a concern?

## 9. Inventory and reproduction

`catalog_alias_collisions.csv`, `brand_resolution_cases.csv`, `create_candidates.csv`, `r6_create_reconciliation.csv`, `verdict_crosswalk.csv`, `r6_priority_view.csv`, `brand_folds.csv`, `negative_sample.csv`, `pending_threshold_sensitivity.csv`, `calibration_entry_requirements.csv`, `initial_owner_decisions.csv`, `decision_queue.csv`, `calibration_procedure.json`, `MANIFEST.json`, and `inputs/` (four byte-pinned PR #201 files with `PROVENANCE.json`, `series_evidence.json`).

```
cd automotive/vehicle_master
python -m identity_resolution.calibration.owner_decision_pack collect   # once; needs the archived M7.0 package
python -m identity_resolution.calibration.owner_decision_pack build     # offline
python -m identity_resolution.calibration.owner_decision_pack verify    # offline
```

