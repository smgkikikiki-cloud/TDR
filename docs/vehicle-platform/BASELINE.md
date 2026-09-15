# Phase 0 Baseline

Everything in this file was either computed directly from repository state during this pass
(2026-09-14, `main`) or is explicitly marked as carried forward from a prior, dated document.
Nothing here is a live production statistic — see "What requires live Supabase verification" at
the end. Re-run the commands shown to reproduce any number.

**2026-09-15 amendment**: one live-Supabase gap in this file (Mechanism A/B crosswalk coverage)
is now recorded as reviewer-supplied live evidence rather than left open — see
`LIVE_IDENTITY_BASELINE_2026-09-15.md` and the updated "Known legacy-to-canonical dependency
points" and "What requires live Supabase verification" sections below. This did not involve this
session querying Supabase itself; the counts are reviewer-supplied and cited as such throughout.

## Canonical catalog counts (repository-testable, computed directly)

Computed by loading the catalog directly (not via a test assertion, though it matches
`test_tdr_bridge.py`'s hardcoded expectations):

```python
from vehreg.catalog import Catalog, DATA_DIR, DEFAULT_YEAR, available_years
available_years(DATA_DIR)  # -> [2021, 2022, 2023, 2024, 2025, 2026]
cat = Catalog.load(DATA_DIR, DEFAULT_YEAR)  # DEFAULT_YEAR = 2026
```

| Entity | Count (catalog year 2026) |
|---|---:|
| Brand | 62 |
| Model | 321 |
| Generation | 322 |
| Variant | 367 |
| MarketTrim | 1,043 |
| Brands flagged `trim_detail: true` (feed the DLT Trim Ledger) | 19 — `aion, avatr, byd, changan, chery, deepal, denza, gac, geely, gwm, jaecoo, leapmotor, mg, neta, riddara, tesla, wuling, xpeng, zeekr` |

Catalog years exist independently back to 2021; nothing reads across years
(`vehreg/catalog.py`). Counts above are for 2026 only — the year the release pipeline currently
builds from (`DEFAULT_YEAR`).

## Release build counts (repository-testable, from committed integration fixtures)

From `automotive/vehicle_master/integration_data/tdr_2026-09-09.json` +
`crosswalk_overrides.json`, built via `ReleaseBuilder` and asserted by
`tests/test_tdr_bridge.py::test_all_canonical_models_crosswalk_without_creating_registration_trims`:

| Metric | Value |
|---|---:|
| Models in release | 321 |
| Brands with a verified crosswalk mapping | 62 |
| Crosswalk review items (unresolved) | 6 |
| `registrations` key present in release payload | No (confirmed absent — release never carries registration facts) |

Release identity is deterministic for identical inputs (both the base `ReleaseBuilder` output
and the production-published `release_enriched.enrich_release` output) — verified by
`tests/test_tdr_bridge.py::test_release_identity_is_stable_for_the_same_inputs` and (added this
pass) `test_enriched_release_identity_is_stable_and_covers_lifecycle_and_history`.

## Registration source periods represented in the repository (computed from file listing)

```
ls automotive/vehicle_master/data/raw/dlt_*.csv
ls automotive/vehicle_master/data/raw_pivot/{long,pivot}_*.csv
```

| Source tier (strongest first) | File count | Periods present |
|---|---:|---|
| API export (`data/raw/dlt_YYYY-MM.csv`) — has real DLT registration class | 48 | 2022-01 .. 2026-01 |
| Long-form workbook (`data/raw_pivot/long_YYYY-MM.csv`) — has real DLT registration class | 19 | 2021-01 .. 2021-12, and 2023-12, 2026-02 .. 2026-07 |
| Pivot workbook (`data/raw_pivot/pivot_YYYY-MM.csv`) — no registration-class column | 1 | 2026-08 |
| `data/raw/withdrawn/` — superseded/withdrawn monthly snapshots, kept for audit, not read by ingest | 2 CSV+meta pairs | 2023-12, 2026-02 (both have a stronger replacement present above) |

Combined, this is calendar coverage **2021-01 through 2026-08 (68 distinct months)**, matching
the prior-recorded figure in `docs/consolidation/PHASE_A_BASELINE.md` (2026-09-09: "68 periods
(2021-01..2026-08)") — independently re-derived here from the file listing rather than from a
built SQLite warehouse. `docs/registration-analytics.md`'s documented 2026 source-precedence
statement ("January API export, February-July long-form snapshots, and August pivot") matches
this listing exactly.

Registered/matched **unit totals** (e.g. "4,064,148 units / 35,212 fact rows") require building
the SQLite registration warehouse from these CSVs (`vehreg ingest` / `vehreg.db`) — this was not
rebuilt in this pass to avoid asserting a number that could drift from what a future agent
computes; the last recorded figure is in `docs/consolidation/PHASE_A_BASELINE.md` (dated
2026-09-09, `vehreg` commit `f9c6abe`) and should be treated as **stale evidence, not a
Phase-0-verified baseline** — a future packet that needs this number should rebuild it fresh
with `python -m vehreg <ingest/report command>` rather than trusting either document.

## Known registration grain behavior (repository-testable)

- Grain is one of `BRAND` / `MODEL` / `VARIANT` (`vehreg/taxonomy.py::Grain`), determined per
  row at ingest time by `Resolver.resolve()` (`vehreg/ingest.py`).
- `MIXED` is emitted, never guessed, when a MODEL/BRAND-grain row's child Variants disagree on a
  facet (`vehreg/db.py::_consensus()`), and/or asserted from curated raw-label evidence
  (`vehreg/powertrain_rules.py`).
- Trim-detail brands (19, listed above) are capped at `Grain.MODEL` in the master facts by
  design; their extra detail lives only in the separate DLT Trim Ledger (`vehreg/trimledger.py`).
- RY1/รย.1 (double cab) vs. RY3/รย.3 (other cabs) pickup disambiguation is resolved via the DLT
  registration-class column when present; the pivot-only 2026-08 month lacks this column and is
  flagged via `coverage.py`'s `coarse_notice` rather than guessed.

Full detail and code citations: `CURRENT_STATE.md` §5, `INVARIANTS.md` rules 2–4 and 15.

## Existing reconciliation checks (repository-testable)

| Check | Mechanism | Test |
|---|---|---|
| Pivot-workbook model rows vs. declared subtotal | `dlt_pivot.period_totals()` == `declared_period_totals()`; `tools/import_dlt_pivot.py` aborts write on >0.5 unit disagreement | `tests/test_dlt_pivot.py::test_model_rows_reconcile_against_the_declared_subtotal` |
| DLT Trim Ledger vs. master model totals | `vehreg/trimledger.py::reconcile()`; CLI `vehreg trim check` | `tests/test_vehreg.py::test_a_mismatch_between_the_two_books_is_reported`, `test_reconcile_does_not_fan_out_across_years` |
| Provincial vs. national totals | `vehreg/provincial.py::reconciliation_for_period()` | No dedicated unit test found (only its building blocks are unit-tested); exercised via `provincial_cli.py` |
| Ingest row accounting (`matched + review == read`) | `vehreg/ingest.py` `IngestReport` counters | `tests/test_vehreg.py::test_ingest_matches_and_preserves_totals` and related |
| Release payload counts vs. declared `counts` block | `publish_vehicle_release` SQL function, self-check only (not against DLT/ECO source) | **No test** — requires live/dockerized Postgres, not available in this pass |

## Known legacy-to-canonical dependency points

| Dependency | What depends on it | Where |
|---|---|---|
| `registrations.model_id` (legacy `models.id` UUID) | Raw registration facts; both registration read paths | `supabase/schema.sql`, `migration_v17_registration_analytics.sql` |
| `registration_brand_aliases` / `registration_model_aliases` | Populating `registrations.model_id` from raw DLT text at ingest | `migration_v17_registration_analytics.sql` |
| `current_vehicle_models.tdr_model_id` / `current_vehicle_brands.tdr_brand_id` (Mechanism A) | Public catalog serving; the canonical-crosswalk registration read path (`/api/report/market`) | `migration_v15_canonical_vehicle_release.sql`, built per-release by `tdr_bridge/release.py` |
| `canonical_object_map` (Mechanism B) | Phase-C canonical-write shadow; legacy per-model serving projection | `migration_v12_canonical_write_pipeline.sql` |
| Legacy `public.models`/`model_powertrains`/`trims` | Legacy dashboard registration views (no crosswalk hop); the older per-model serving projection | `migration_v19`/`v20`, `migration_v14_serving_projection.sql` |

Mechanisms A and B are independently implemented, with no shared contract or automated
reconciliation between them — see `CURRENT_STATE.md` §10 for full structural detail. **This is no
longer an unverified gap as of the 2026-09-15 amendment**: a live inspection
(`LIVE_IDENTITY_BASELINE_2026-09-15.md`) found Mechanism A carries 383 derived Brand+Model
external-ID links while Mechanism B carries exactly 1 verified Brand/Model mapping, with zero
disagreements and zero conflicts in the one case where both mechanisms have an opinion. This
confirms the two are not competing/duplicate registries in practice — they are a broad derived
mapping (A) and a sparse, deliberately narrow verification gate (B) serving different consumers.
The corrected Phase 1 problem statement (`MIGRATION_PLAN.md`) is about building one external-
identity contract that can represent both trust levels without conflating them, not about closing
a coverage gap between A and B.

## Test suite baseline (run this pass)

```
cd automotive/vehicle_master && python3 -m pytest -q
# 747 passed, 4334 subtests passed  (was 746 before this pass's one added test)

cd /home/user/TDR && npm ci && npm run check
# tsc --noEmit + 10 check-*.ts scripts: 237 "ok" assertions, 0 FAIL, exit 0
```

Both commands ran fully offline, no Supabase credentials, no network access beyond `npm ci`
against the npm registry. See "Tests" in the final completion report for exact commands and
environment notes.

## What is repository-testable vs. what requires live Supabase verification

**Repository-testable today** (no external dependency beyond installing `requirements.txt` /
`npm ci`): everything in this file above — catalog counts, release-build determinism, registration
source-period coverage, DLT/trim-ledger/pivot reconciliation, the full pytest suite, and the full
`npm run check` suite (all 10 `check-*.ts` scripts are pure source/logic assertions, not live
Supabase integration tests — confirmed by running them offline in this pass).

**Now verified via reviewer-supplied live evidence** (2026-09-15, see
`LIVE_IDENTITY_BASELINE_2026-09-15.md` — not independently queried by this session, but recorded
as dated reviewer evidence rather than left as an open gap):
- Mechanism A (`current_vehicle_models`/`current_vehicle_brands`) live coverage: 383 derived
  Brand+Model external-ID links (321 models + 62 brands).
- Mechanism B (`canonical_object_map`) live status distribution: 1 verified Brand/Model mapping
  (`jaecoo.jaecoo_5_ev`), 326 `unmatched` model rows, no verified Brand rows.
- Mechanism A/B agreement where both have an opinion: 1 case checked, 0 disagreements, 0
  conflicts — see the full cross-mechanism table in `LIVE_IDENTITY_BASELINE_2026-09-15.md`.

**Still requires live Supabase verification** (not obtainable from repository state, not checked
by the 2026-09-15 review, and explicitly not fabricated in this document):
- Whether `migration_v15`'s replacement of the `registrations` anon-read policy with a
  paid-entitlement-gated one has actually been applied to the production project. The last live
  check (`docs/consolidation/LIVE_SUPABASE_VERIFICATION.md`, 2026-09-09) predates `migration_v15`
  and found the *old* anon-read policy live with zero rows in the table. The 2026-09-15 review was
  scoped to the identity crosswalk question only and did not re-check this policy.
- Actual row counts in `registrations`, live `public.models`/`brands`/`trims` (legacy serving
  tables), and which `canonical_vehicle_state.active_release_id` is currently active in
  production.
- Whether `publish_vehicle_release`/`rollback_vehicle_release` behave as designed against a real
  Postgres instance — no local/offline Postgres harness exists in this repository to test these
  functions directly.
- Whether the scheduled `canonical-input.yml` worker and `vehicle-release.yml` publisher are
  currently green in production CI (this pass did not have access to GitHub Actions run history
  beyond what's in the repository's own committed workflow files).
- Live legacy-vs-canonical registration read parity (Phase 3's eventual acceptance criterion).
- Whether the Mechanism A/B counts above remain stable over time — both mechanisms can change
  independently (A on every release build, B whenever a model is Phase-C verified), so this is a
  point-in-time snapshot, not a standing guarantee.

A future agent with live Supabase credentials should re-run
`docs/consolidation/LIVE_SUPABASE_VERIFICATION.md`'s style of read-only inspection against the
current project and record the result as a dated addendum, the same way that document did on
2026-09-09 — do not overwrite this file's repository-testable numbers with live numbers; add
them alongside, dated, the way the existing consolidation docs already do.
