# Invariants

These rules govern the whole vehicle-platform migration, from Phase 0 through Phase 7 and
beyond. They are not aspirational — each one is either already enforced in code/SQL today
(citation given) or must be enforced before the behavior it protects is allowed to change.
Any future phase, packet, or agent that touches `automotive/vehicle_master/`, `supabase/`,
`app/`, or `lib/registration-*`/`lib/admin-registration-market.ts` must preserve every rule
below unless a specific migration packet explicitly revises it — and any such revision must
update this file in the same change.

A rule marked **Enforced** already has code/SQL/tests behind it. A rule marked **Policy-only**
is a design commitment that current code follows in the paths inspected, but has no automated
guard yet — treat it as a candidate for a future regression test, not as already safe to rely on.

## 1. Raw source observations must remain immutable and reproducible

Once written, a raw snapshot cannot be silently overwritten by a re-run with different content.

- **Enforced (ECO):** `vehreg/ecosticker_ingest.py` `build_snapshot(..., write=True)` refuses to
  rewrite an existing `vehreg/data/<year>/ingest/ecosticker/snapshots/<date>/` directory with
  different bytes — raises `ECOIngestError("snapshot ... is immutable and already differs on
  disk")`. An identical rerun is a documented no-op.
- **Enforced (DLT fetch):** `vehreg/dlt.py` writes each month's raw CSV alongside a
  `.meta.json` sidecar recording fetch timestamp, row counts, and a `sha256` of the payload
  (`vehreg/dlt.py`, `fetch_month`).
- **Enforced (canonical write):** `CanonicalInputPipeline`/`CanonicalWritePipeline` stage every
  write against a full copy of the data tree and only copy back atomically after full-batch
  validation succeeds (`vehreg/input_pipeline.py`, `vehreg/canonical_write.py`), so a partially
  applied or invalid batch never lands as a mutation of existing files.
- **Enforced (release):** `canonical_vehicle_releases` rows are only ever inserted by
  `publish_vehicle_release`; there is no update/delete RPC. A release whose content changes
  gets a new `release_id` (hash-derived); the old row is marked `SUPERSEDED`, never deleted or
  rewritten (`supabase/migration_v15_canonical_vehicle_release.sql`).

## 2. Registration totals must reconcile exactly to the source data

- **Enforced (pivot workbook):** `dlt_pivot.period_totals()` (summed model rows) must equal
  `declared_period_totals()` (workbook's own subtotal rows); `tools/import_dlt_pivot.py`
  aborts the whole write if they differ by more than 0.5 units. Test:
  `tests/test_dlt_pivot.py::test_model_rows_reconcile_against_the_declared_subtotal`.
- **Enforced (ingest completeness):** every input row becomes either a classified fact or an
  `ingest_review` row with a reason; `rows_matched + rows_review == rows_read` always holds
  (`vehreg/ingest.py`).
- **Enforced (trim ledger vs. master):** `vehreg/trimledger.py::reconcile()` diffs
  `SUM(fact_trim.units)` against `SUM(fact_registration.units WHERE grain='MODEL')` per
  model/period; an empty result means the two ledgers agree everywhere. CLI: `vehreg trim
  check`, exits 1 on any disagreement. Tests in `tests/test_vehreg.py`
  (`test_a_mismatch_between_the_two_books_is_reported`,
  `test_reconcile_does_not_fan_out_across_years`).
- **Enforced (provincial vs. national):** `vehreg/provincial.py::reconciliation_for_period()`
  compares summed province rows against the national `province='ALL'` row; exposed via
  `provincial_cli.py`.
- **Policy-only (release counts):** `publish_vehicle_release` recomputes array lengths from
  the release payload and rejects the publish if they don't match the declared `counts` block
  — but this checks the release against itself, not against the DLT/ECO source data it was
  built from. No test exercises this RPC (see `status/CURRENT.md` parity gaps).

## 3. Missing granularity must remain missing — never fabricate detail to satisfy a schema

- **Enforced (registration matching):** unmatched or ambiguous DLT rows are queued for review,
  never guessed. `vehreg/ingest.py` comments and tests
  (`test_unmatched_rows_are_queued_never_guessed`).
- **Enforced (registration crosswalk, Supabase):** `registration_brand_aliases`/
  `registration_model_aliases` are reviewed-only tables; a missing/ambiguous match stays NULL
  (`supabase/migration_v17_registration_analytics.sql`, table comments).
- **Enforced (comparable specs):** `SpecLedger`/`SpecRegistry` use explicit `KNOWN` /
  `UNKNOWN` / `NOT_AVAILABLE` states rather than inventing values
  (`vehreg/comparable_specs.py`).
- **Enforced (market analytics denominator):** `REGISTRATION_MARKET_CONTRACT.md` — unmapped
  model rows remain visible as coverage diagnostics, never redistributed into guessed models,
  segments, body types, or powertrains.
- **Policy-only (general):** `docs/consolidation/MASTERPLAN.md` §22 states this as explicit
  product policy across specs/price/local content/MiT; not every field has a dedicated test.

## 4. `MIXED` is legitimate information when source grain spans multiple child values

- **Enforced:** `vehreg/db.py::_consensus()` returns the shared value only if every child
  (Variant) row agrees on a facet, else the literal `"MIXED"` — applied per-facet when building
  MODEL- and BRAND-grain `dim_unit` rows. `vehreg/powertrain_rules.py` can also assert `MIXED`
  from raw-label evidence for specific nameplates (e.g. Honda CR-V, Toyota Corolla Altis, BMW 3
  Series) rather than guessing a single powertrain.
- **Enforced:** `MIXED` volume is reported (`CubeResult.mixed_units`), never dropped, and an
  explicit, versioned allocation profile is the only sanctioned way to split it further
  (`vehreg/cube.py`, `vehreg/allocate.py`) — the split is a derived analytical layer and does
  not mutate the canonical registration fact.
- Tests: `tests/test_vehreg.py::test_model_grain_row_reports_mixed_only_where_trims_disagree`,
  `test_model_grain_volume_shows_as_mixed_not_as_a_guess`,
  `test_allocation_splits_mixed_and_conserves_the_total`,
  `test_the_yaris_ativ_is_mixed_because_dlt_cannot_split_it`.
- **Enforced (web contract):** `docs/REGISTRATION_MARKET_CONTRACT.md` — "a multi-powertrain
  nameplate is `MIXED`"; the serving layer must not invent allocations.

## 5. Canonical IDs must be stable and must never be recycled

- **Enforced (structure):** canonical IDs are deterministic, path-composed slugs
  (`brand`, `brand.model`, `brand.model.generation`, `brand.model.generation.variant`,
  `brand.model.generation.trim.<slug>`), derived from catalog position, not database
  surrogate keys that could be reassigned (`vehreg/catalog.py`, `vehreg/entities.py`).
- **Enforced (release identity):** `release_id`/`source_hash` are content hashes of a fixed
  semantic key set; a real content change always produces a new `release_id` rather than
  mutating one in place (`tdr_bridge/release.py`, `tdr_bridge/release_enriched.py`).
- **Policy-only (legacy UUID crosswalk):** `docs/consolidation/MASTERPLAN.md` §16 and
  `PHASE_C_WRITE_PIPELINE.md` state legacy TDR UUIDs must never be regenerated or reused to
  match canonical IDs, and that `canonical_object_map`/`current_vehicle_models.tdr_model_id`
  mappings must be human/evidence-verified, never name-matched. This is policy plus a schema
  guard (`status = 'verified'` gate in `canonical_object_map`), not an automated ID-recycling
  detector.

## 6. Legacy TDR UUIDs are eventually external/crosswalk identities, not primary canonical IDs — but existing production dependencies remain until explicitly migrated

- **Current state:** legacy `models.id`/`brands.id` UUIDs are still load-bearing today in at
  least three places: (a) `registrations.model_id` (raw registration fact), (b)
  `canonical_model_projection.tdr_model_id`/`canonical_brand_projection.tdr_brand_id` (the
  release-build crosswalk consumed by `current_vehicle_models`/`current_vehicle_brands`), and
  (c) `canonical_object_map` (the separate Phase-C/Phase-E write-shadow and legacy
  serving-projection crosswalk). None of these may be deleted or repointed silently — see
  `CURRENT_STATE.md` for the full duplicate-crosswalk map.
- **Do not** in Phase 0 or any phase before an explicit migration packet: remove
  `registrations.model_id`, remove `registration_brand_aliases`/`registration_model_aliases`,
  or collapse the two independent legacy-UUID→canonical crosswalks into one without a shadow/
  reconciliation period (Rule 12).

## 7. DLT registration input must not autonomously create retail MarketTrim identity

- **Enforced:** `vehreg/dlt.py`, `vehreg/dlt_pivot.py`, and `vehreg/trimledger.py` never import
  or call `vehreg/canonical_write.py` or `vehreg/canonical_queue.py`. Trim-detail brands
  (`brand.trim_detail == true`) are deliberately capped at `Grain.MODEL` in the master
  registration facts — "the master stops at the model by design" (`vehreg/ingest.py`) — and
  the extra trim/battery/range detail lands only in the separate `dim_trim`/`fact_trim` ledger,
  never in `vehreg/data` catalog files.
- **Enforced:** `MarketTrim` is never a member of `RESOLUTION_CHAIN`, and
  `Catalog.iter_resolved()` iterates Variants only — "Retail trims enrich the catalog but
  never multiply or allocate registration facts" (`vehreg/catalog.py`).

## 8. Identity-resolution decisions requiring human judgment must remain auditable

- **Enforced (ECO):** `ecosticker_promote.py::build_market_trim_input_batch` requires
  `origin == "HUMAN"` (rejects `agent-proposed`), requires an explicit reviewer-supplied trim
  name (never the raw ECO label), and verifies the normalized-snapshot hash against the
  manifest before allowing a new `MarketTrim` to be created. Review dispositions
  (`reject`/`defer`/`reopen`) go through `UPSERT_ECO_REVIEW`, which is itself applied through
  the same audited `CanonicalInputPipeline` as every other canonical write.
- **Enforced (canonical write audit trail):** every `CanonicalWritePipeline.apply()` call
  appends to `revisions.jsonl`, `outbox.jsonl`, and a `shadow/<revision_id>.json` snapshot
  under `vehreg/data/<year>/canonical_state/` — an immutable, append-only audit log of who
  changed what and why.
- **Enforced (legacy crosswalk):** `canonical_object_map` rows are only executable when
  `status = 'verified'`; a name/slug match alone produces `unmatched`/`ambiguous`, never
  `verified` (`supabase/migration_v12_canonical_write_pipeline.sql`,
  `docs/consolidation/PHASE_C_WRITE_PIPELINE.md`).

## 9. Canonical product truth remains Git-reviewed

- **Enforced:** automated writers (`tools/canonical_input_worker.py` via
  `.github/workflows/canonical-input.yml`) write to `vehreg/data`, run the full test/validation
  suite, and open a PR (`gh pr create`) — no workflow in this repository auto-merges that PR.
  Landing on `main` requires a human-reviewed merge.
- **Policy-only:** `pages/7_Prices.py` (the Streamlit admin UI) writes directly through
  `vehreg/product.py` to the same `vehreg/data` files, but through a different code path than
  `CanonicalWritePipeline` — it produces no `revisions.jsonl`/`outbox.jsonl` audit entry, and
  getting that change into Git still depends on a human committing the resulting working-tree
  diff. This is a real, pre-existing duplicate write path (see `CURRENT_STATE.md` §"Duplicate
  identity-resolution / write paths") — Phase 0 documents it; a later phase must decide whether
  to route it through the audited pipeline.

## 10. Serving releases remain immutable and atomically activated

- **Enforced:** `publish_vehicle_release(jsonb)` (`supabase/migration_v15_canonical_vehicle_release.sql`)
  performs projection insert/delete, supersedes the previous `ACTIVE` release, activates the
  new one, and repoints `canonical_vehicle_state.active_release_id` — all inside one
  `security definer` Postgres function, i.e. one transaction. `rollback_vehicle_release(text)`
  is the dedicated, equally atomic inverse: it only ever moves the pointer among
  already-materialized releases, never recomputes data.
- **Gap:** no automated test exercises `publish_vehicle_release` or
  `rollback_vehicle_release` (they are Postgres functions; no local/offline Postgres harness
  exists in this repository today). See `status/CURRENT.md` and `BASELINE.md` for what this
  means for future migration verification.

## 11. Existing application consumers must remain operational through migration

- **Policy, actively followed today:** `docs/REGISTRATION_MARKET_CONTRACT.md` "Transition
  rule" — the legacy static dashboard views and `/api/report/registration` stay untouched
  while the new canonical-crosswalk contract (`/api/report/market`,
  `lib/admin-registration-market.ts`) is introduced in parallel. Phase 0 makes no consumer-
  facing change.

## 12. New replacement pipelines must shadow/reconcile against existing production behavior before cutover

- **Policy, actively followed today:** the Phase-C canonical write pipeline runs in shadow
  mode behind the legacy Supabase editor (`app/admin/catalog-actions.ts` still performs the
  legacy write, then best-effort enqueues a canonical shadow command —
  `docs/consolidation/PHASE_C_WRITE_PIPELINE.md`, "Legacy editor shadow mode"). The new
  registration-market read contract (`current_vehicle_models` crosswalk) runs alongside, not
  instead of, the legacy dashboard views. No later phase may cut an existing production path
  over to a new one without a demonstrated shadow/reconciliation period first.

## 13. No destructive migration may precede a verified replacement and rollback path

- **Policy, explicitly stated:** `docs/consolidation/MASTERPLAN.md` §25 lists this as a hard
  "must not" list (don't delete Plant/ProductionProgram domains, don't overwrite PriceLedger
  with legacy `price_baht`, don't discard unresolved DLT rows, etc.). Phase 0 performs no
  destructive change and none is planned before Phase 7.

## 14. Source observation, canonical identity, and accepted fact are distinct concepts

- **Enforced today, but only within the ECO and DLT subsystems individually** — not yet as a
  single cross-source abstraction (that unification is target-architecture work, Phase 4, not
  Phase 0). ECO's raw→normalized→review→(attach or promote) pipeline and DLT's raw CSV→
  ingest→review→dimension pipeline each keep these three concepts in separate files/tables
  with no shared vocabulary yet. See `MASTER_ARCHITECTURE.md` for the target Source/
  Observation/Identity/Fact/Serving plane split this rule is converging toward.

## 15. Observed source grain and requested reporting grain are distinct concepts

- **Enforced:** `Grain` (`BRAND`/`MODEL`/`VARIANT`, `vehreg/taxonomy.py`) records what the
  source actually proved; `vehreg/cube.py`'s `DEFAULT_ANALYSIS_GRAINS` and allocation profiles
  are a separate, explicitly-versioned reporting layer that may request a finer split than the
  source grain supports — in which case the result is `MIXED`/`estimated`, never a silent
  invention at the requested grain. See Rule 4.

---

## How to use this file

- A migration packet that touches any invariant above must state, in its own description,
  which rule it affects and how it preserves (or deliberately, explicitly revises) it.
- A **Policy-only** rule is a prompt to add a regression test when the packet touching that
  area is written — not a license to skip the guard indefinitely.
- If a future agent finds a rule above no longer matches `main`, update this file and
  `CURRENT_STATE.md` together, in the same change, with a note explaining what changed and
  why. Do not silently let this file drift from the code.
