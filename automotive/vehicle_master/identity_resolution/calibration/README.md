# R6 calibration data (2026-10-11)

The calibration-data milestone of Identity Resolution Contract v1: the real first-run R6 rows, a dataset that puts what the legacy matcher saw next to what Contract v1 says
on the same pairs, the sheet the owner labels, and a report. **It calibrates nothing.** `adoption.yaml` keeps `binding: false`, no threshold is adopted, the contract is not
frozen, and the owner columns of the sheet are blank.

Read first: [`CALIBRATION_REPORT.md`](CALIBRATION_REPORT.md) (the numbers), then [`r6_owner_review.csv`](r6_owner_review.csv) (what to label).

## What is here

| File | What it is |
|---|---|
| `inputs/` | Read-only extracts of production (`SELECT` only) and their provenance: the 490 `ice_model_crosswalk` rows of the 2026-10-10 run, the 50 redirects, the matcher's inputs (`registrations` summed by canonical model and month, `vehicle_models` / `_brands` / `_generations`). `MANIFEST.json` has the sha256 of every file, `EXTRACT_QUERY.sql` the query. |
| `r6_calibration_dataset.csv` | One row per (Ice group, candidate TDR target) pair worth a look: **legacy** evidence (what the first run saw and stored), **Contract v1** evidence (recomputed on the common observation window), volumes, lineage, link type, reason codes by role. |
| `r6_calibration_groups.csv` | One row per Ice group (1,200): legacy and v1 outcome, volumes, lineage. Groups with no retained pair are only here. |
| `r6_owner_review.csv` | **The owner's sheet.** Prioritised; machine evidence prefilled; `owner_verdict`, `owner_link_type`, `owner_canonical_model_id`, `owner_notes` are blank. |
| `CALIBRATION_REPORT.md`, `calibration_summary.json` | The report and the numbers behind it. |
| `sensitivity_results.json` | For each provisional value: how many real decisions change when that one value moves (and two hypotheses about absent-row semantics, labelled as hypotheses). |
| `adapters.py`, `legacy.py`, `pairs.py`, `review.py`, `report.py`, `render_report.py`, `sensitivity.py`, `build.py` | The tooling. Offline, stdlib + PyYAML, no network, no database. |
| `ref_eval_core.py`, `ref_eval_resolve.py` | The **reference evaluator**: a transcription of SPEC sections 5-9 that says what Contract v1 would conclude. **It is not the engine** (see below). |

## How to rebuild

```bash
cd automotive/vehicle_master
python -m identity_resolution.calibration.build            # rewrite the outputs from inputs/ and the archived Ice package
python -m identity_resolution.calibration.build --check    # fail if a committed output is stale
python -m identity_resolution.calibration.sensitivity run  # ~10 minutes; rewrites sensitivity_results.json
```

## Three kinds of evidence, kept apart

* `legacy_*` — the first run, replayed offline with the legacy module's own functions. The replay reproduces **489 of 489** stored matcher rows exactly (candidate, status, method, reason text, full fingerprint), so these are the run's numbers, not a re-interpretation. The `legacy_*` window columns say exactly which months were compared: the group's newest 24 months *with an Ice row*, every month the TDR side lacked turned into 0.
* `v1_*` — Contract v1, rev 3, as a **dry run** (`binding: false`, invariant I16): common observation window, `null` is never 0, brand/name relation, link type, reason codes. Ice and TDR absent-row semantics stay **UNKNOWN**; an unresolved gap caps AUTO exactly as the SPEC says.
* `owner_*` — blank. The legacy status is in `legacy_r6_status`; it is never copied into an owner column and never used as a label.

## Filling in the sheet

One row = one candidate pair; the verdict is about **that row's candidate**.

| `owner_verdict` | Meaning |
|---|---|
| `CORRECT_EQUIVALENT` | the Ice group and the TDR model are the same vehicle |
| `CORRECT_PART_OF` | the Ice group is a narrower part of the TDR model (several Ice groups may share it) |
| `CORRECT_COMPOSED_OF` | the Ice group is made up of several TDR models (put them all in `owner_canonical_model_id`, `a+b`) |
| `WRONG_TARGET` | the TDR model shown is not right; put the right one in `owner_canonical_model_id` (and say so in `owner_link_type`) |
| `NO_TDR_TARGET` | TDR has no model for this Ice group |
| `INSUFFICIENT_EVIDENCE` | cannot tell |

`other_candidates` lists the best other pairs of the same group to help you name the right target. Rows are ordered by your seven priorities (`review_tier`); `cumulative_unique_group_units_share` says how much of the market the rows above already cover, so you can stop when the rest is not worth it.

## What this is not

* Not the engine. `ref_eval_*.py` is stdlib, has no persistence, no adapter registry, no CLI and no production wiring; nothing outside `identity_resolution/` imports it (a test enforces that) and the engine gate in `../README.md` section 5 is unchanged. It shares an author with the SPEC; its agreement with the 508 golden cases (`tests/identity_resolution/test_ir_reference_evaluator.py`) is consistency, not correctness.
* Not a write to anything. No production row, flag or gate was changed, no mapping was approved or rejected, R6 was not re-run, R7 was not started, no migration was made.
* Not the Ice answer. `Q-ICE-ABSENT-ROW` is still open and nothing here waits for it; the report sizes what an answer would unlock as a clearly labelled hypothesis.
