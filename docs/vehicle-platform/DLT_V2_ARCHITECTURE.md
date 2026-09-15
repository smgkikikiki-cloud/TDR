# DLT v2 Shadow Pipeline — Phase 2

**Status: implemented and tested in shadow. No production consumer reads this pipeline. No
read cutover — that is Phase 3 (`MIGRATION_PLAN.md`).**

This document records Phase 2: a complete, testable DLT v2 shadow path —

```
DLT / historical source → immutable normalized observation → canonical resolution
  → registration fact v2 → parity against the current production registration path
```

running alongside the existing `vehreg/ingest.py`/`vehreg/dlt.py` pipeline and the existing
production Supabase registration path (`public.registrations`), per `MIGRATION_PLAN.md`'s Phase
2 intent and Invariant 12 (shadow before cutover). This document assumes familiarity with
`CURRENT_STATE.md` (Mechanism A/B, the identity graph) and `INVARIANTS.md` (numbered rules cited
throughout below).

## Why reuse, not rewrite

`vehreg.ingest.Resolver` already implements every one of Phase 2's non-negotiable semantics
correctly — brand-first→model-within-brand→variant-within-model matching, RY-class
tie-breaking, trim-detail brands capped at MODEL grain, refusing to guess across an ambiguity,
never chasing coverage by loosening the match floor. It is the production DLT resolution engine
today. Phase 2 does not touch its internals; it wraps it in an observation-shaped, dependency-
injectable interface (`vehreg/resolution_v2.py`) so the same tested matching logic can be driven
by a new source shape (a live Supabase `registrations` row, not just a DLT CSV) and produce a
new, richer result shape (a `ResolutionResult` record, not a five-element tuple).

## What was built, and what it reuses

| Layer | New file | Reuses |
|---|---|---|
| Observation | `vehreg/registration_observation.py` | `vehreg.ingest.ColumnMap`/`_number`, `vehreg.normalize.{fold,period_key}` |
| Resolution | `vehreg/resolution_v2.py` | `vehreg.ingest.Resolver` (unchanged), `vehreg.trimledger.{parse_trim,residual_trim}` (unchanged) |
| Batch build (pure) | `vehreg/registration_v2_writer.py` | the above two, no I/O |
| Parity (pure) | `vehreg/registration_v2_parity.py` | nothing — new, self-contained comparison logic |
| Shadow schema | `supabase/migration_v29_registration_dlt_v2_shadow.sql` | additive only; touches no existing table/view/function |
| Backfill CLI | `automotive/vehicle_master/tools/backfill_registration_v2.py` | the urllib PostgREST pattern already used by `tools/canonical_input_worker.py`/`tools/sync_external_identity_registry.py` |
| Parity CLI | `automotive/vehicle_master/tools/registration_v2_parity.py` | same pattern; imports `backfill_registration_v2`'s fetch/credential helpers rather than duplicating them |

`vehreg/ingest.py`, `vehreg/dlt.py`, `vehreg/normalize.py`, `vehreg/trimledger.py`,
`vehreg/db.py`, and every existing registration-related test are unmodified by this packet.
`vehreg/db.py`'s own local SQLite `fact_registration` pipeline is untouched and keeps running
exactly as before — Phase 2 is a second, independent consumer of the same `Resolver`/`Catalog`,
not a replacement for the local warehouse.

## Observation layer

`RegistrationObservation` (`vehreg/registration_observation.py`) is the serialization-independent
shape every source adapts into: `observation_id`, `source_kind`, `source_ref`, `period`,
`registration_type`, `province` (`"ALL"` when the source has none — every source in production
today), `raw_brand`/`raw_model`/`raw_variant`/`raw_label`, `units`, `normalized_brand`/
`normalized_model`, `payload_hash`, and `source_metadata`.

**Id is deterministic, never random**: `observation_id(source_kind, source_ref)` is a pure
sha256-derived function of the source's own identity. The same source row, adapted again,
produces the same id — this is the whole idempotency mechanism the backfill tool relies on, not a
side effect of it.

Three adapters, one per source shape actually in production:

- `from_dlt_record` — one row of a DLT CKAN `datastore_search` result (`vehreg/dlt.py`), keyed by
  `resource_id:_id` (CKAN's own stable per-resource row id).
- `from_mapped_row` — one row of any column-mapped CSV (`vehreg.ingest.ColumnMap`/`read_rows`) —
  covers the current DLT CSV fetcher's own output and any other file the existing column-sniffer
  can map. Keyed by `file_sha256:row_index` (a CSV has no natural stable row id).
- `from_legacy_registration_row` — one row of the live Supabase `public.registrations` table, for
  historical backfill. Keyed by the row's own stable `id` uuid
  (`supabase/schema.sql`). The legacy `model_id`/`mapping_method` are carried into
  `source_metadata` **as parity evidence only** — this adapter never treats them as resolution
  input, and never repairs a null/blank field (Invariant 1: source observations are immutable and
  reproducible, never reinterpreted).

`reconciles(observations, expected_total)` proves the sum of a batch of observations' units
equals the source total they were built from (Invariant 2/8).

## Canonical resolver

`resolve_observation(resolver, observation)` (`vehreg/resolution_v2.py`) calls
`Resolver.resolve()` unchanged and wraps its five-element tuple into a `ResolutionResult`:
`canonical_id`, `grain` (`BRAND`/`MODEL`/`VARIANT`), `match_how`, `match_score`, `reason`,
`candidates` (populated only for a `model-ambiguous` stop). `canonical_id` is a **Vehicle Master
text id** (`brand.model`, `brand.model.generation.variant` — the same ids
`canonical_model_projection.canonical_id` publishes), resolved directly against
`vehreg.catalog.Catalog` — never a legacy `public.models.id` uuid.

`canonical_id` is `None` only when even the brand could not be placed (Invariant 6). In every
other case it is the catalog unit id at the deepest grain the source's own text proved;
`result.reason` is non-empty whenever resolution stopped short of what the raw text plausibly
claimed (a model ambiguity, a variant the catalog does not have, a brand not found at all) — a
non-empty reason does **not** imply `canonical_id is None`; it may still be a real BRAND- or
MODEL-grain fact, honestly flagged as shallower than the source's own words suggested.

**The legacy Supabase crosswalk is parity evidence, never a resolution input.** Nothing in
`resolution_v2.py` reads `registrations.model_id` or `current_vehicle_models`. Where the historical
backfill adapter carries the legacy uuid on `source_metadata`, it exists solely for
`registration_v2_parity.py` to compare against — see "Parity" below. Where the canonical resolver
and the legacy crosswalk disagree, the parity report **names the difference**
(`identity_disagreement` / `grain_difference_v2_coarser` / a resolution-coverage bucket); nothing
forces the two into agreement, and nothing silently promotes the legacy mapping into canonical
truth.

**Trim/battery detail** (`derive_trim_detail`) is derived, never a separate identity:
for a MODEL-grain fact on a `trim_detail` brand (BYD, Jaecoo, Aion, Deepal, Tesla — the same set
`vehreg/trimledger.py` already targets), it reuses `trimledger.residual_trim`/`parse_trim`
unchanged to extract grade/drive/range/battery/powertrain-hint from the raw label, attached to the
fact row as `trim_detail` jsonb — analysis detail about a MODEL-grain fact, never a finer identity
the fact itself claims, and never written as a `MarketTrim` (Invariant 7 — `Grain` has no
MarketTrim member at all, so this pipeline is structurally incapable of producing one; see
`test_resolution_v2.py::test_no_markettrim_output`).

## Fact model

`registration_v2_writer.build_batch()` (pure, no I/O) resolves a list of observations and shapes
three row sets:

- **`registration_observations_v2`** — every observation, unconditionally, unmutated.
- **`registration_facts_v2`** — one row **only** when resolution produced a `canonical_id` at
  all (BRAND, MODEL, or VARIANT grain). An observation whose brand could not be placed gets no
  fact row — Invariant 6: preserve the observation and its unresolved units, never fabricate a
  fact target.
- **`registration_resolution_review_v2`** — one row whenever `result.reason` is non-empty,
  whether or not a fact row also exists for the same observation (mirrors `vehreg/db.py`'s own
  local `ingest_review` pattern exactly: a brand-only fact *and* a `"model-not-found"` review row
  for the same observation is normal, not a contradiction).

A repeated observation (the same `observation_id` twice in one batch — a source returning a row
twice, or a caller re-adding an already-processed page) is collapsed to its first occurrence
**before** resolution runs, so a batch's own summary numbers, and the rows it proposes to write,
are never double-counted (`test_registration_v2_writer.py::test_repeated_observation_does_not_double_count`).

`WriteBatch.reconciles()` proves `resolved_units + unresolved_units == total_units` for every
batch (Invariant 2/8) — structurally, not by convention: `unresolved_units` is defined as exactly
the units of observations that produced no fact row, so the equality cannot fail to hold.

## Shadow Supabase persistence

`supabase/migration_v29_registration_dlt_v2_shadow.sql` adds exactly three tables, additive only —
see the migration's own header comment for the full design rationale. Every id is the
deterministic `observation_id` (or derived one-to-one from it), never `gen_random_uuid()` — a
rerun of the backfill or a DLT ingest upserts the same rows rather than duplicating them
(`Prefer: resolution=merge-duplicates`, `on_conflict=observation_id`, in both CLIs). RLS is
enabled on all three tables; `anon`/`authenticated` are revoked; only `service_role` may read or
write — the same access model `registration_brand_aliases`/`registration_model_aliases` already
use. No grant to `anon`/`authenticated` exists anywhere in the migration — these are internal
shadow tables for the backfill/parity tooling, not a new public API.

`registrations`, `registration_brand_aliases`, `registration_model_aliases`,
`match_registration_model`, `ingest_registration_snapshot`, and every `registration_*` analytics
view are untouched — proven by source-text regression coverage
(`tests/test_registration_dlt_v2_shadow_migration.py`), the same pattern already used for other
migrations in this repository (no dockerized/live Postgres exists in this test suite — see
`status/CURRENT.md`'s known parity gaps).

## Historical backfill

`tools/backfill_registration_v2.py` reads every row of the live `public.registrations` table
(paged, optionally filtered by `--period-from`/`--period-to`), adapts each with
`from_legacy_registration_row`, resolves with the same `Resolver`/`Catalog` pair built once per
run, and — only with `--apply` — upserts the resulting rows into the three shadow tables.

**Idempotency and resumability are structural, not a checkpoint mechanism**: every row's id is a
pure function of the legacy row's own uuid, and every write is an upsert. Re-running the tool —
over the same period, a wider period, the whole table again, after a failure partway through —
reproduces the same rows rather than duplicating them; there is no "resume from here" marker to
maintain or that can go stale. `--period-from`/`--period-to` exist only so an operator can chunk a
very large backfill into separate runs if useful (35.8k rows in one call is not large enough to
require it, but the flags make it possible without the tool depending on it for correctness).

Dry-run (no `--apply`, the default) performs zero writes and prints the batch summary — counts of
observations/facts/review rows and total/resolved/unresolved units — **before** anything is
written, satisfying "produce counts before writing" directly rather than as a side effect of a
verbose log.

**Alias reuse**: `--warehouse` (default `automotive/vehicle_master/data/vehreg.sqlite3`) lets the
backfill reuse `alias_override` lessons already taught to the local vehreg warehouse, if one is
present, so v2's resolution coverage is not artificially lower than v1's purely because those
lessons were not repeated. Where no warehouse file is present (every environment this packet has
run in, including CI), the tool falls back to an empty alias set and says so plainly — this is an
operational quality-of-life feature, not a correctness dependency: with or without it, resolution
never guesses past the match floor, and every unresolved/ambiguous row remains visible in
`registration_resolution_review_v2` either way.

## Parity

`tools/registration_v2_parity.py` is read-only against every table it touches. It fetches v1
`public.registrations` rows, v2 `registration_observations_v2`/`registration_facts_v2` rows, and
`current_vehicle_models` (Mechanism A's own release-build `tdr_model_id → canonical_id`
crosswalk — the *only* source this tool uses to translate a v1 row's legacy uuid into a canonical
id for comparison), then calls the pure `vehreg/registration_v2_parity.py`.

**Pairing is exact, not fuzzy**: a v2 observation built by the backfill adapter carries the
legacy row's own uuid as `source_ref`, so `classify_pairs()` matches v1↔v2 by that id directly — no
label-similarity heuristic, no risk of mispairing two rows that merely look alike. A v1 row with
no matching v2 observation has simply not been backfilled yet (`legacy_rows_missing_v2_backfill`)
— a coverage gap, reported honestly, never conflated with a resolution failure.

**Four questions, kept strictly separate**, per the packet's own explicit requirement that a
mapping disagreement is not automatically a unit mismatch:

| Question | Where |
|---|---|
| Volume parity — do totals agree by period / by registration type? | `volume_parity()`, `VolumeParity.matches` |
| Identity parity — for a comparable pair, do v1 and v2 agree which canonical model? | `classify_pairs()` → `agree` / `identity_disagreement` |
| Resolution-coverage difference — did only one side resolve the row at all? | `resolution_coverage_v1_only` / `resolution_coverage_v2_only` |
| Grain difference — do the two sides agree on the car but v2 stopped shallower? | `grain_difference_v2_coarser` (BRAND-grain v2 fact whose brand matches v1's crosswalked model) |

A separate `v1_uncrosswalked` bucket names a v1 row whose `model_id` has no entry in
`current_vehicle_models` at all — a Mechanism-A crosswalk gap, a different problem from either side
failing DLT resolution, and never folded into `both_unresolved`.

`find_duplicate_source_refs()` and `find_reconciliation_failures()` are the two genuine failure
detectors: a `(source_kind, source_ref)` claimed by two different `observation_id`s should be
structurally impossible (the id is a pure function of that pair) and names a real bug if found; a
paired v1/v2 row whose units disagree means the backfill ran against v1 data that has since
changed, not a resolution disagreement. Only these two, plus a real volume mismatch by period or
registration type, mark the report `is_clean: false` — an `identity_disagreement` or
`grain_difference_v2_coarser` never does, by design
(`test_registration_v2_parity.py::test_identity_disagreement_does_not_by_itself_break_volume_parity`).

## Live result

**No live Supabase credentials are available in this session** — confirmed the same way every
prior phase in this repository confirmed it: no `SUPABASE_*` environment variable set, no local
`.env`/`.env.local` with real values (`tools/backfill_registration_v2.py`'s and
`tools/registration_v2_parity.py`'s own no-credentials path was verified directly: both fail
closed, exit 2, print "Nothing was read," and attempt no live call — see
`tests/test_registration_v2_tools_env.py::test_main_fails_closed_with_no_credentials` and
`::test_parity_main_fails_closed_with_no_credentials`). No Supabase migration in this packet has
been applied to the live production project, no backfill has run against production
`registrations`, and no parity report has been produced against live data. This is deployment
work an operator with credentials performs next, not evidence of an unfinished design — see
`status/CURRENT.md` for the exact commands.

## Tests

Every pure module has fixture-driven unit coverage requiring no network and no credentials:
`tests/test_registration_observation_v2.py`, `tests/test_resolution_v2.py`,
`tests/test_registration_v2_writer.py`, `tests/test_registration_v2_parity.py`,
`tests/test_registration_dlt_v2_shadow_migration.py` (source-text regression on the migration
file), and `tests/test_registration_v2_tools_env.py` (credential parsing and the two CLIs'
no-credentials fail-closed paths). See the completion report for exact pass counts.

## What Phase 2 explicitly does not do

- **No production consumer change.** `/api/report/registration`, `/api/report/market`,
  `lib/registration-analytics.ts`, `lib/admin-registration-market.ts`,
  `app/admin/registration-actions.ts`, and every `registration_*` view/function are byte-for-byte
  unchanged in behavior.
- **No read cutover.** Nothing reads `registration_facts_v2`/`registration_observations_v2` in
  production. That is Phase 3 (`MIGRATION_PLAN.md`'s "Registration analytics read cutover"),
  explicitly not started by this packet.
- **No change to Phase-E** (`apply_vehicle_serving_projection`) or to Phase 1's external-identity
  registry/`canonical_object_map` — this is a different mechanism (registration facts, not
  identity bindings) addressing a different problem.
- **No `vehreg/ingest.py`/`vehreg/dlt.py`/local-warehouse behavior change.** The local SQLite
  `fact_registration` pipeline is unmodified and keeps running exactly as before; Phase 2 is a
  second, independent consumer of the same `Resolver`/`Catalog`, in Supabase, not a replacement.
- **No MarketTrim creation**, ever, from this pipeline (Invariant 7 — structurally enforced, see
  "Canonical resolver" above).
- **No cutover of any kind.** Phase 2 is shadow-mode infrastructure only, per Invariant 12.
