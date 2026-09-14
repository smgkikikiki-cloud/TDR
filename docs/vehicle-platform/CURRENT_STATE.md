# Current State — As-Built, From `main`

This document describes the system as it actually exists in code on `main` as of this Phase 0
pass (2026-09-14), not the target architecture (`MASTER_ARCHITECTURE.md`) and not the aspirational
brief that motivated this documentation effort. Every claim below cites the file(s) that back it.
Where the code contradicts a simplified mental model of the system, that is called out explicitly
rather than smoothed over.

Canonical engine path: `automotive/vehicle_master/` (Python, package `vehreg` + `tdr_bridge`).
Web/serving path: repository root `app/`, `lib/`, `supabase/` (Next.js + Supabase Postgres).

## 1. Canonical product identity hierarchy

Declared hierarchy (`automotive/vehicle_master/vehreg/entities.py` module docstring):

```
Brand → Model → Generation → Variant
                           └→ MarketTrim   (a fifth, catalog-only child of Generation)
```

All entities are `@dataclass(frozen=True, slots=True)`. IDs are **deterministic, path-composed
slugs**, not database surrogate keys and not UUIDs:

| Entity | ID shape | Example |
|---|---|---|
| Brand | `<slug>` | `toyota` |
| Model | `<brand_id>.<model_slug>` | `toyota.yaris_ativ` |
| Generation | `<model_id>.<code_slug>` | `toyota.yaris_ativ.mxpa10` |
| Variant | `<generation_id>.<variant_slug>` | `toyota.yaris_ativ.mxpa10.smart` |
| MarketTrim | `<generation_id>.trim.<identity_slug>` | `toyota.alphard.ah40.trim.z_premier` |

IDs are derived from the JSON tree position at load time, so nothing in a data file repeats a
parent key and nothing is ever assigned by a database sequence that could later collide or be
recycled (`vehreg/catalog.py`).

`RESOLUTION_CHAIN = ("variant", "generation", "model", "brand")` (`vehreg/entities.py`) — the
walk used by registration resolution is variant→generation→model→brand, most specific first.
**`MarketTrim` is never a member of this tuple.** `Catalog.iter_resolved()` iterates Variants
only, with the explicit comment: "Retail trims enrich the catalog but never multiply or
allocate registration facts" (`vehreg/catalog.py`).

**Important correction to a naive reading of the hierarchy diagram**: `MarketTrim.generation_id`
is its structural parent — MarketTrim nests directly under **Generation**, as a *sibling* of
Variant, not as a child of Variant. `MarketTrim.variant_id` is a separate, optional field that
cross-references its analytical counterpart when one exists; it is not a nesting relationship.
This is exactly the shape `MASTER_ARCHITECTURE.md` calls a **canonical identity graph** (Brand →
Model → Generation, with Configuration/Variant and MarketTrim as two distinct children of
Generation, linked optionally, not chained) — the target architecture does not change this shape,
only the eventual name `Variant → Configuration`.

## 2. Variant vs. MarketTrim semantics

| | `Variant` | `MarketTrim` |
|---|---|---|
| Purpose | Analytical/registration classification line | One marketed, sold trim/grade |
| Parent | `generation_id` only | `generation_id` (structural), plus optional `variant_id` cross-reference |
| `powertrain` | May be `UNKNOWN` (source limitation is legal) | Must be exact; `UNKNOWN` is rejected both at catalog load and in the entity's own `validate()` |
| Price fields | `price_thb`, `price_min_thb`, `price_max_thb` — live analytical fields, records the spread of multiple retail trims folded into one line | `price_thb` exists but is explicitly legacy/deprecated; canonical retail price lives in `PriceLedger` only |
| Physical spec fields | none | dimensions, tires, wheels, transmission, engine_code, `source_refs` (provenance) |
| Registration resolution | Yes — the only entity DLT volume resolves to | **Never** — not in `RESOLUTION_CHAIN`, not in `iter_resolved()` |

A DLT label that happens to match a `MarketTrim` exactly does not let registration volume land
on that MarketTrim; it can only ever become an **evidence-backed reference** (via the separate
DLT Trim Ledger, §9 below), never a registration fact write.

`MarketTrim.variant_id`, when present, is validated at catalog load time
(`Catalog._resolve_trim_variant_ref`, `vehreg/catalog.py`): it accepts a full ID, a local slug,
or a name match under the same Generation, and raises `CatalogError` if it doesn't resolve — so
a MarketTrim can point at a nonexistent Variant only by a data-authoring mistake the loader
would already reject, not silently.

## 3. Product fact / ledger storage

Product facts are deliberately **not** one mutable vehicle row. Each concern is a physically
separate store, all under `vehreg/data/<year>/`, all plain JSON/JSONL, all read/written through
their own module:

| Concern | Module | On-disk location |
|---|---|---|
| Identity (Brand/Model/Generation/Variant/MarketTrim) | `vehreg/catalog.py`, `vehreg/entities.py` | `models/<brand_id>.json` |
| Prices | `vehreg/pricing.py` (`PriceLedger`, `PriceRecord`) | `market/prices/*.json` |
| Campaigns | `vehreg/pricing.py` (`Campaign`) | `market/campaigns/<brand>.json` |
| Retail lifecycle disposition | `vehreg/retail_lifecycle_review.py` | `market/retail_lifecycle/trim_review.json` |
| Comparable specifications | `vehreg/comparable_specs.py` (`SpecLedger`, `SpecFact`) | `product/comparable_specs/{registry.json,facts/*.json,cohorts/*.json}` |
| ECO/homologation evidence (input, not itself canonical) | `vehreg/comparable_specs.py`, `vehreg/homologation.py` | `ingest/ecosticker/snapshots/...` |
| Canonical write audit trail | `vehreg/canonical_write.py` | `canonical_state/{revisions.jsonl,outbox.jsonl,shadow/*.json,input_batches/*.json}` |

Prices are append-only, never overwritten in place (`vehreg/pricing.py`): a correction is a new
dated record. Comparable-spec facts are immutable by `fact_id` — reusing an ID with different
content is rejected (`vehreg/comparable_specs.py`). Money is explicitly barred from the spec
registry (`_is_price_field()` guard): "prices belong in PriceLedger, not the spec registry."

`ProductMaster` (`vehreg/product.py`) is the read-side composition layer that joins Catalog +
PriceLedger + ECOStickerSpecStore + SpecLedger per trim at query time — confirming these are
genuinely separate stores joined on read, not one row that happens to have many columns.

## 4. ECO Sticker ingestion flow

```
raw snapshot  →  normalized snapshot  →  review queue  →  human decision  →  (attach evidence | create MarketTrim | reject | defer)
```

- **Raw**: `tools/ecosticker_fetch.py` pulls the public `ecosticker.go.th` list/detail
  endpoints and writes a deterministic gzip JSONL.
- **Normalize**: `vehreg/ecosticker_ingest.py::build_snapshot()` produces, per row, matched
  brand/model/generation candidates, a powertrain candidate + basis, a raw trim candidate
  object, and a `review_status` (`ready_for_review` / `needs_model_review` /
  `needs_powertrain_review`) with explicit `review_reasons`. Writes `raw.jsonl.gz`,
  `normalized.jsonl.gz`, `review_queue.jsonl.gz`, and a `manifest.json` with content hashes —
  immutable per snapshot date (§ Invariant 1).
- **Human review, two independent decision sets**:
  - *Attach to existing MarketTrim* — an `accept_existing_trim` decision
    (`vehreg/ecosticker_ingest.py::validate_decisions`) requires a real `trim_id` and matching
    powertrain. The actual spec attachment is a separate, PR-reviewed JSON file under
    `product/specs/ecosticker/*.json`, cross-checked against the catalog by
    `ECOStickerSpecStore.validate_against_catalog` (`vehreg/homologation.py`).
  - *Create a new MarketTrim* — `vehreg/ecosticker_promote.py::build_market_trim_input_batch`
    requires `origin == "HUMAN"` (rejects `agent-proposed`), requires an explicit
    reviewer-supplied trim name (never the raw ECO label), verifies the snapshot hash against
    the manifest, and refuses if the ECO source is already attached elsewhere or the row is
    not `ready_for_review`. It emits one `UPSERT_MODEL_BUNDLE` command per new trim,
    deliberately omitting price/tyre/dimension fields.
  - *Reject / defer / reopen* — `vehreg/eco_review_write.py::upsert_review_dispositions`,
    applied as the canonical command `UPSERT_ECO_REVIEW`.
- **Write path**: both `UPSERT_MODEL_BUNDLE` and `UPSERT_ECO_REVIEW` go through the same
  `CanonicalInputPipeline` (§7) as every other canonical write — approved ECO changes become
  ordinary Git-reviewed PRs against `vehreg/data`, not a separate mechanism.

The ECO price field (`recommended_price_thb`) is explicitly tagged `price_classification:
"ECO_STICKER_PRICE"` and is never treated as MSRP.

## 5. Python DLT (registration analytics) flow

**Observed grain** is an explicit closed enum, `Grain.BRAND | Grain.MODEL | Grain.VARIANT`
(`vehreg/taxonomy.py`), determined during ingest by `Resolver.resolve()`
(`vehreg/ingest.py`): brand match, then model match within brand, then (only when there is
residual raw text beyond the matched brand+model, and only for brands that don't publish
trim-level DLT detail) a variant match. A model that cannot be found stays at `Grain.BRAND`; a
variant that cannot be found stays at `Grain.MODEL`. Unmatched/ambiguous rows are queued for
review, never guessed.

**MIXED behavior**: when building a MODEL- or BRAND-grain `dim_unit` row, `vehreg/db.py`'s
`_consensus()` returns the shared value only if every child Variant row agrees on a facet, else
the literal string `"MIXED"`. A curated rulebook (`vehreg/powertrain_rules.py`) can also assert
`MIXED` (or a specific powertrain) from raw-label evidence for named nameplates — "classification,
never allocation." `MIXED` volume is always reported (`CubeResult.mixed_units`), never dropped;
an explicit, versioned allocation profile (`vehreg/allocate.py`) is the only sanctioned way to
split it further, as a labeled derived/estimated layer that never mutates the underlying fact.

**RY1/RY3 pickup disambiguation**: `CabType` (`vehreg/taxonomy.py`) treats a double cab as รย.1
and every other cab as รย.3. Each cab body is modeled as its **own catalog Model row** sharing
one `nameplate` (e.g. `toyota.hilux_revo_cab` vs. `toyota.hilux_revo_double_cab`). When a bare
DLT label is ambiguous across cab-split models, `Resolver._narrow_by_class()`
(`vehreg/ingest.py`) narrows candidates using the DLT registration-class column (RY1/RY2/RY3)
on the source row; a รย.2 pickup falls back to the รย.1 (double-cab) group as a passenger
conversion. This mechanism only works when the source carries a class column at all — the
coarse pivot-workbook source does not, and is flagged via `coverage.py`'s `coarse_notice`
rather than guessed.

**Reconciliation** exists at several independent layers (see `INVARIANTS.md` rule 2 for the
full list): pivot-workbook internal subtotals, ingest row-accounting, trim-ledger vs. master,
and provincial vs. national. None of these are automatic fixers — all report-only, fail-closed
on disagreement.

**Data shapes**: `data/raw/dlt_YYYY-MM.csv` (API export, has a real class column) →
`data/raw_pivot/long_YYYY-MM.csv` (long-form workbook, has class) →
`data/raw_pivot/pivot_YYYY-MM.csv` (pivot workbook, `registration_type=*`, no class — weakest
source, used only when nothing stronger exists). `docs/registration-analytics.md` documents the
actual 2026 source chain per month.

## 6. DLT Trim Ledger

A **second, independent** set of fact/dimension tables (`dim_trim`/`fact_trim`,
`vehreg/trimledger.py`) capturing trim/battery/range/drivetrain detail that certain marques
(brands flagged `trim_detail: true` in the catalog — currently the Chinese-marque brands plus
Tesla) push into the DLT `รุ่น` (model) field. For these brands, the **master** registration
facts stop at `Grain.MODEL` by design — "letting the master split some brands and fold others
would make every brand-versus-brand comparison unsafe" (`vehreg/ingest.py`). The extra detail
goes only into the separate ledger, populated from the same resolved rows the master already
classified, so the two "can never disagree about which car it was."

Reconciliation is mandatory and tested: `trimledger.reconcile()` diffs summed trim-ledger units
against the master's MODEL-grain total per model/period; an empty result means agreement. CLI:
`vehreg trim check`. This ledger **never** feeds back into canonical registration facts or into
`vehreg/data` catalog identity — confirmed by import-graph inspection (`trimledger.py` never
imports `canonical_write.py`/`canonical_queue.py`) and by the Chinese EV trim ranking module
(`vehreg/rankings.py`) reading `fact_trim` only, "so the detailed ranking cannot double-count
master registrations."

## 7. Canonical write / canonical input queue

**Not** a second master, and not a purely local mechanism — the queue is a Supabase table,
`canonical_input_batches`. `docs/CANONICAL_INPUT.md` and `vehreg/canonical_queue.py` module
docstring both describe it as an adapter/worker contract, explicit that "the queue is
intentionally not a second master."

Flow (`docs/CANONICAL_INPUT.md`, `tools/canonical_input_worker.py`):

1. An editor (or the ECO promotion tooling) submits a schema-v1 JSON batch.
2. `canonical_input_batches` deduplicates by `batch_id` + checksum.
3. A scheduled worker (`.github/workflows/canonical-input.yml`, cron) claims `QUEUED` rows,
   applies each batch through `CanonicalInputPipeline.apply()`
   (`vehreg/input_pipeline.py`) — which stages the **entire** batch against a temporary copy of
   the data tree and only copies changed files back atomically if every command in the batch
   validates. A `batch_hash` marker makes exact retries idempotent.
4. The worker runs the full pytest suite and a release build, then the **workflow itself**
   (not the Python code) runs `git add`, `git commit`, `git push`, and `gh pr create` — opening
   a PR against `main`. **No workflow auto-merges this PR.** Landing on `main` still requires a
   human-reviewed merge (§8).
5. Merging triggers `vehicle-release.yml`, which builds and publishes a release (§8).
6. The release job marks the originating batches `PUBLISHED` with the release ID
   (`tools/canonical_input_worker.py mark-published`).

`CanonicalWritePipeline` (`vehreg/canonical_write.py`) is the underlying single-command writer:
supports `UPSERT_MODEL_BUNDLE`, `WITHDRAW_MODEL`, `APPEND_PRICE`, `CORRECT_PRICE`,
`CLOSE_PRICE`, `UPSERT_CAMPAIGN`, `APPEND_SPEC`. Every `apply()` re-validates the whole catalog
before writing, is idempotent by `command_id`, and appends to the audit trail described in §3.
`vehreg/canonical_queue.py` is a narrower, separate adapter used specifically for one-off
legacy-model-shadow backfills (see §10) — it is not the same code path as
`CanonicalInputPipeline`.

The queue and worker fail closed without `SUPABASE_URL`/`SUPABASE_SECRET_KEY` (or legacy
`SUPABASE_SERVICE_ROLE_KEY`) — both workflows probe the credential before doing any build or
write.

## 8. Git authoring boundary and immutable release pipeline

```
vehreg/data (Git-backed)
   → tdr_bridge.release.ReleaseBuilder  (crosswalks legacy TDR inventory → canonical, base release)
   → tdr_bridge.release_enriched.enrich_release  (+ fail-closed retail lifecycle, + historical_model_state)
   → deterministic release_id / source_hash  (sha256 over a fixed semantic key set)
   → tdr_bridge.publish  → Supabase RPC publish_vehicle_release(jsonb)
   → canonical_*_projection tables (versioned by release_id)
   → canonical_vehicle_state.active_release_id  (atomically repointed, same transaction)
   → current_* views (current_vehicle_brands/models/generations/market_trims/price_ledger/spec_facts)
   → app consumers (lib/canonical-data.ts, lib/admin-registration-market.ts)
```

**Determinism**: `release_id = f"vehicle-{year}-{sha256(semantic_payload)[:16]}"`, hashed over a
fixed key set (`brands, models, generations, market_trims, price_ledger, spec_facts`, plus
revision/as_of/year; the enriched wrapper adds `historical_model_state` to that set). The same
inputs always produce the same `release_id`/`source_hash` — verified by
`tests/test_tdr_bridge.py::test_release_identity_is_stable_for_the_same_inputs` and (added in
this Phase 0 pass) `test_enriched_release_identity_is_stable_and_covers_lifecycle_and_history`.

**Atomic activation/rollback**: `publish_vehicle_release(jsonb)` and
`rollback_vehicle_release(target_release_id)` (`supabase/migration_v15_canonical_vehicle_release.sql`)
are each a single `security definer` Postgres function — projection writes, superseding the old
`ACTIVE` release, activating the new one, and repointing `canonical_vehicle_state` all happen in
one transaction. Rollback never recomputes data; it only moves the pointer among
already-materialized, immutable releases. Both are `service_role`-only.

**Immutability, concretely**: there is no update/delete RPC for `canonical_vehicle_releases`.
Any real content change produces a different hash-derived `release_id` — the old row's status
flips to `SUPERSEDED` but the row (and its projection children) are never deleted or rewritten,
which is exactly what makes rollback possible.

**Authoring boundary**: canonical facts are edited only in `vehreg/data` (directly by an
operator, or via the Streamlit admin at `pages/7_Prices.py`, or via the canonical input queue).
They reach Supabase only through the release/publish pipeline above — Supabase's serving tables
are never the place a fact is edited (with one caveat, §11 item 3).

**CI wiring**: `.github/workflows/vehicle-release.yml` runs
`tdr_bridge.release_enriched` → `tdr_bridge.publish` on every push to `main` touching
`vehreg/**`/`tdr_bridge/**`/`integration_data/**`, stages a recovery copy of the release JSON on
an orphan branch before publishing, and probes Supabase credentials before writing.
`README.md`'s manual quick-start example instead invokes the **base** `tdr_bridge.release`
(not `release_enriched`) — a minor documentation/CI discrepancy worth fixing in a future packet,
noted here rather than silently corrected, since the production path (CI) is the enriched one.

## 9. Supabase serving projection

**Two independent projection mechanisms currently exist in the repository** — this is itself
one of the duplicate paths called out in §10:

1. **The active, full-catalog release path** (§8 above): `publish_vehicle_release` fans a whole
   release out into `canonical_brand_projection` / `canonical_model_projection` /
   `canonical_generation_projection` / `canonical_market_trim_projection` /
   `canonical_price_projection` / `canonical_spec_projection`, all keyed by `release_id`, read
   through the `current_*` views. `docs/consolidation/REPOSITORY_CUTOVER.md` states this is the
   live production path: "Public TDR catalog reads the active canonical release views, not
   legacy `models`/`trims` as vehicle authority."
2. **An older, incremental per-model path** (`docs/phase-e-serving-projection.md`,
   `vehreg/serving_projection.py`, `scripts/publish_serving_projection.py`,
   `supabase/migration_v14_serving_projection.sql`): projects **one model at a time** directly
   into the *legacy* `public.models` / `public.model_powertrains` / `public.trims` tables via
   RPC `apply_vehicle_serving_projection`, gated on a separate, pre-existing verified
   `canonical_object_map` crosswalk. `model_powertrains` here projects canonical **Variant**
   rows ("must not be populated from MarketTrim identity" — `phase-e-serving-projection.md`).
   `trims.price_baht` is documented as a serving cache that may only be populated from
   `PriceLedger.current_list_price()`, never from other price types.

Both mechanisms are real, committed, tested (`tests/test_serving_projection.py` covers
mechanism 2), and neither has been removed. `docs/consolidation/PHASE_C_WRITE_PIPELINE.md`
confirms `brands`/`models`/`model_powertrains`/`trims` "remain a legacy serving/editor surface
during shadow mode... not promoted to canonical truth by this phase" — i.e. mechanism 2's
target tables are explicitly legacy, and mechanism 1 (the `canonical_*_projection`/`current_*`
views) is the one described as authoritative going forward. Phase 0 does not remove either.

## 10. Legacy UUID → canonical crosswalk — two mechanisms with different trust semantics

This is the clearest concrete duplication found during this pass, and the brief specifically
asked it be documented rather than collapsed. **A 2026-09-15 architecture review and live
Supabase inspection refined this section's framing — see `LIVE_IDENTITY_BASELINE_2026-09-15.md`
for the full dated evidence.** The two mechanisms below are not two equivalent, competing
registries; they have overlapping schema intent but materially different scope and purpose, and
conflating them would be a mistake in either direction.

**Mechanism A — release-build crosswalk** (used for the public catalog and, downstream, for
registration-market reads):

- `tdr_bridge.release.ReleaseBuilder._brand_crosswalk` / `_model_crosswalk`
  (`tdr_bridge/release.py`) match canonical brand/model names/aliases against a legacy TDR
  `inventory` JSON snapshot (`integration_data/tdr_2026-09-09.json`) plus an explicit
  human-authored override file (`integration_data/crosswalk_overrides.json`).
- Result is stored **per release** as `canonical_model_projection.tdr_model_id` /
  `canonical_brand_projection.tdr_brand_id` (`supabase/migration_v15_canonical_vehicle_release.sql`),
  exposed for reads through the `current_vehicle_models`/`current_vehicle_brands` views.
- Consumed at read time by `lib/admin-registration-market.ts::canonicalize()` — this is exactly
  the "raw DLT identity → legacy TDR model identity → canonical crosswalk → canonical market
  analytics" chain described in the task brief: `registrations.model_id` (legacy TDR UUID,
  populated at ingest via `registration_brand_aliases`/`registration_model_aliases`, §11) is
  looked up in a `Map` built from `current_vehicle_models`, yielding `canonical_id`. This is the
  contract documented in `docs/REGISTRATION_MARKET_CONTRACT.md`: `registrations →
  current_vehicle_models → current_vehicle_brands`.

**Mechanism B — `canonical_object_map`** (used for the Phase-C canonical-write shadow and the
older per-model serving projection, §9 mechanism 2):

- A dedicated table (`supabase/migration_v12_canonical_write_pipeline.sql`): legacy
  `source_table`/`source_id` → `canonical_id`, with a `status` that must be `'verified'` before
  the row is usable — "a candidate produced from a name/slug comparison must stay
  `unmatched`/`ambiguous` until somebody verifies the identity; name equality is not authority"
  (`docs/consolidation/PHASE_C_WRITE_PIPELINE.md`).
- Used by `vehreg/canonical_queue.py`'s legacy-model-shadow adapter and by
  `apply_vehicle_serving_projection` (§9 mechanism 2) to decide whether a legacy model is
  eligible for either a shadow canonical-write command or an old-style serving projection.

**These two crosswalks are not the same table, are not kept in sync with each other by any code
path found in this repository, and answer conceptually different questions** — Mechanism A
answers "what canonical model does this release say this legacy model corresponds to," rebuilt
fresh on every release from name/alias matching plus overrides; Mechanism B answers "has a human
explicitly verified this legacy object maps to this canonical object," a durable, manually
curated record used as a write-authority gate (`lib/canonical-write-shadow.ts` requires
`canonical_object_map.status == 'verified'` before a legacy model save can become an executable
canonical shadow write — an unverified or missing row becomes `needs_crosswalk` instead, never a
silent fallback to name/slug matching).

A live, read-only inspection of the production Supabase project on 2026-09-15 (reviewer-supplied
evidence; recorded in full in `LIVE_IDENTITY_BASELINE_2026-09-15.md`) found these are **not**
two similarly-populated, competing registries:

- Mechanism A: 383 derived Brand+Model external-ID links (321 models + 62 brands), broad-coverage,
  produced by the release builder from the committed inventory plus reviewed overrides.
- Mechanism B: exactly 1 verified Brand/Model mapping (`jaecoo.jaecoo_5_ev`, the Phase-C/Phase-E
  pilot lineage), plus 326 `unmatched` model rows and no verified Brand rows at all.
- Of the 383 Mechanism A links, exactly 1 (the same Jaecoo 5 EV row) also has a verified
  Mechanism B counterpart; there were zero disagreements between A and B on any ID where both
  had an opinion, and zero cases where B was verified but A disagreed or was silent.

The correct interpretation is: **there are two independently implemented external-ID mapping
mechanisms with overlapping schema intent but different operational roles and trust
semantics.** Mechanism A is broad and derived, for serving/read integration. Mechanism B is
sparse and explicitly verified, for write-sensitive Phase-C bridging — its sparseness reflects
its original role as an explicit verification gate, not a coverage defect to be closed by making
it look more like Mechanism A. They currently have no shared contract. This distinction, not "two
competing crosswalks racing to the same answer," is the actual problem Phase 1 needs to address —
see `MIGRATION_PLAN.md`'s Phase 1 section for the corrected problem statement.

**As of Phase 1A (2026-09-16)**, "no shared contract" is narrowed to "no shared *persistence*."
`docs/vehicle-platform/EXTERNAL_IDENTITY_CONTRACT.md` now defines a read-only vocabulary both
mechanisms' rows can be converted into for comparison, implemented in `lib/external-identity/`
and runnable live via `node --experimental-strip-types scripts/audit-external-identity.ts`
(SELECT-only; requires the same server-side Supabase credentials as the rest of the admin
tooling). This is observational infrastructure only — it reads both mechanisms and reports how
they relate; it does not write to either, does not choose one as authoritative, and does not
change `tdr_bridge/release.py` or `lib/canonical-write-shadow.ts`.

**A third, narrower crosswalk layer** exists purely for registration ingestion and does not
resolve to canonical IDs at all: `registration_brand_aliases`/`registration_model_aliases`
(`supabase/migration_v17_registration_analytics.sql`) map raw DLT brand/model text to a
**legacy** `brands.id`/`models.id` UUID only (populating `registrations.model_id`). It is
explicitly documented as "registration-only crosswalks... not MarketTrim records" and must not
be used to mutate the free catalogue.

## 11. Major duplicate identity-resolution / write paths (summary)

Collecting the duplications found across this document, for visibility:

1. **Legacy UUID → canonical crosswalk** — Mechanism A (broad, derived) vs. Mechanism B (sparse,
   verified), different trust semantics rather than competing registries — §10,
   `LIVE_IDENTITY_BASELINE_2026-09-15.md`.
2. **Serving projection** — the full-release `canonical_*_projection`/`current_*` path vs. the
   older per-model `apply_vehicle_serving_projection` path into legacy `models`/`trims`, §9.
3. **Canonical write entrypoint** — `CanonicalWritePipeline`/`CanonicalInputPipeline` (used by
   the queue worker and ECO promotion, produces a full `revisions.jsonl`/`outbox.jsonl` audit
   trail) vs. `pages/7_Prices.py` (Streamlit admin UI) calling `vehreg/product.py` write
   functions **directly**, bypassing `CanonicalWritePipeline` entirely — same target files
   (`vehreg/data/<year>/...`), different audit trail, no shared idempotency/command_id. Getting
   a `pages/7_Prices.py` change into Git depends on whoever runs that Streamlit session also
   committing the resulting diff by hand.
4. **Registration read path** — the legacy static dashboard views (`migration_v19`/`v20`,
   `/api/report/registration`, `lib/registration-analytics.ts`) join
   `registrations.model_id` straight against the legacy `public.models` table, with **no**
   canonical crosswalk hop at all, vs. the newer `/api/report/market`
   (`lib/admin-registration-market.ts`) which performs the full
   `registrations → current_vehicle_models → current_vehicle_brands` canonical crosswalk.
   `docs/REGISTRATION_MARKET_CONTRACT.md` explicitly keeps both running in parallel during
   transition (Invariant 11).

None of these are bugs to fix in Phase 0 — each is a deliberate, documented shadow/transition
state per the project's own consolidation docs. They are recorded here because a future
migration packet must reconcile or retire one side of each pair explicitly (Invariant 12), not
assume only one path exists.

## 12. Important source-of-truth boundaries

- **`automotive/vehicle_master/vehreg/data/` is the only authoritative store for canonical
  vehicle identity, prices, campaigns, comparable specs, and retail lifecycle.** Supabase never
  originates these facts; it only serves versioned projections of them (with the `pages/7_Prices.py`
  duplicate-write caveat in §11 item 3, which still targets the same files, not Supabase).
- **Supabase `registrations` is the authoritative store for raw registration snapshot facts**
  as ingested — the Python engine's own SQLite-backed registration warehouse
  (`vehreg/db.py`, used by the Streamlit dashboard) is a separate, not-Supabase-backed store
  covering different history depth (`docs/REGISTRATION_MARKET_CONTRACT.md` "Historical
  backfill": "the canonical warehouse retains substantially more registration history than the
  current Supabase serving table").
- **`registration_brand_aliases`/`registration_model_aliases` are authoritative only for
  raw-DLT-string → legacy-UUID resolution**, never for canonical vehicle identity.
- **Supabase has multiple concurrent roles** (per the task brief and confirmed in code): canonical
  command inbox (`canonical_input_batches`, `canonical_write_commands`), serving database
  (`canonical_*_projection`, `current_*` views, legacy `models`/`trims`), auth/application data
  (`auth.users`, `tdr_entitlements`), and registration fact storage (`registrations`). Phase 0
  preserves this multi-role design; `MASTER_ARCHITECTURE.md`'s five-plane split is the eventual
  destination, not a Phase 0 change.
- **`registrations` access control**: `supabase/migration_v08_catalog_industry.sql` originally
  granted anonymous `SELECT` on `registrations`. `supabase/migration_v15_canonical_vehicle_release.sql`
  (§216-221) **replaces** that with a paid-entitlement-gated policy
  (`public.has_market_access('MARKET_ANALYTICS')`) and revokes anon/public select — this
  resolves the open risk flagged in `docs/consolidation/PHASE_A_BASELINE.md`/
  `LIVE_SUPABASE_VERIFICATION.md` (both dated 2026-09-09, before v15 landed). Whether this
  migration has actually been applied to the live production Supabase project is not verifiable
  from repository state alone — see `BASELINE.md` "What requires live Supabase verification."

## 13. Prior consolidation documentation this builds on

`automotive/vehicle_master/docs/consolidation/` already contains a detailed, Thai-language
migration plan (`MASTERPLAN.md`, "Revision 2 — Approved architecture, 9 September 2026") plus
baseline/verification/phase-tracking notes (`PHASE_A_BASELINE.md`, `LIVE_SUPABASE_VERIFICATION.md`,
`PHASE_C_QUEUE_ADAPTER.md`, `PHASE_C_WRITE_PIPELINE.md`, `REPOSITORY_CUTOVER.md`) covering the
consolidation of a second repository (`vehicle-market-master`) into this one. That plan uses its
own Phase A–J sequence, largely already executed (the Python engine, tests, and tooling are
confirmed present under `automotive/vehicle_master/` today; the repository cutover is marked
complete in `REPOSITORY_CUTOVER.md`). This Phase 0–7 documentation set (per `MIGRATION_PLAN.md`)
is a **different, complementary numbering** focused on the source/identity/observation-plane
convergence described in `MASTER_ARCHITECTURE.md`, not a restart or replacement of the
Masterplan's A–J sequence. See `MIGRATION_PLAN.md` for how the two relate.
