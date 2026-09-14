# Live External-Identity Baseline — 2026-09-15

**Status of this document**: this is a dated record of live evidence, not a repository-derived
baseline. Everything under "Live evidence" below was **supplied by architecture review from a
read-only query against the live TDR Supabase project, performed 2026-09-15 Asia/Bangkok time**.
This Phase 0 session did not independently query Supabase — no live-database credentials were
available in this session, and none were used. Treat the counts below as reviewer-supplied
evidence, cited and reasoned about here, not as something this session verified firsthand. A
future agent with live credentials should re-run the check itself (see "Reproducing this check")
and record the result as its own dated addendum, the way this document supersedes-by-addition
the 2026-09-09 checks in `docs/consolidation/PHASE_A_BASELINE.md`/`LIVE_SUPABASE_VERIFICATION.md`
rather than overwriting them.

No live data was read destructively and none was modified. Every query described below is a
`SELECT`/count-style read against existing tables/views; nothing in this document authorizes or
implies a write, migration, or schema change.

## What was checked

Two external-identity mechanisms, both documented structurally in `CURRENT_STATE.md` §10:

1. **Mechanism A** — the release-build crosswalk, read live from `current_vehicle_models` and
   `current_vehicle_brands` (the views over the active canonical release's
   `canonical_model_projection`/`canonical_brand_projection` tables, defined in
   `supabase/migration_v15_canonical_vehicle_release.sql`).
2. **Mechanism B** — the `canonical_object_map` table (defined in
   `supabase/migration_v12_canonical_write_pipeline.sql`), read live for its `status` distribution
   by `source_table`/`canonical_entity_type`.

## Live evidence (reviewer-supplied, 2026-09-15)

### Mechanism A — `current_vehicle_models` / `current_vehicle_brands`

| Metric | Count |
|---|---:|
| `current_vehicle_models` rows with non-null `tdr_model_id` | 321 |
| `current_vehicle_brands` rows with non-null `tdr_brand_id` | 62 |
| Total Brand+Model external-ID links | 383 |

### Mechanism B — `canonical_object_map`, live status counts

| `source_table` | `canonical_entity_type` | `status` | Count |
|---|---|---|---:|
| `models` | `model` | `unmatched` | 326 |
| `models` | `model` | `verified` | 1 |
| `models` | `generation` | `verified` | 1 |
| `model_powertrains` | `variant` | `verified` | 3 |
| `trims` | `market_trim` | `verified` | 4 |

There are currently **no verified Brand mappings** in `canonical_object_map`. The one verified
model is `jaecoo.jaecoo_5_ev`; the verified generation, Variant, and MarketTrim rows are the same
Jaecoo 5 EV Phase-C/Phase-E pilot lineage referenced in `docs/consolidation/PHASE_C_WRITE_PIPELINE.md`
("The first live pilot is Jaecoo 5 EV because its TDR row and canonical model were inspected
directly").

### Cross-mechanism comparison, Brand/Model external-ID scope

| Metric | Count |
|---|---:|
| Mechanism A mappings (Brand+Model) | 383 |
| Mechanism B verified mappings (Brand+Model) | 1 |
| Exact A/B agreements on the same external ID | 1 |
| Same-external-ID disagreements | 0 |
| A-only external IDs (present in A, no verified B row) | 382 |
| B-only verified external IDs (verified in B, absent from A) | 0 |

## Interpretation

Mechanism A and Mechanism B are structurally overlapping (both ultimately map a legacy TDR
UUID to a canonical identifier) but are **not two equivalent, competing registries**:

- **Mechanism A** — broad, deterministic, derived. Produced by the release builder
  (`tdr_bridge/release.py`'s `_brand_crosswalk`/`_model_crosswalk`) from the committed TDR
  integration inventory plus reviewed overrides/matching rules, rebuilt fresh on every release.
  It is the mechanism actually used by serving/read-side integration today — the public catalog
  and the canonical-crosswalk registration-market read path both depend on it. A derived,
  name/alias-based match here is **not** equivalent to a human-verified identity assertion, even
  though it is deterministic and reviewed-override-capable.
- **Mechanism B** — sparse, explicit, human-verified. It exists as an authority *gate* for the
  Phase-C legacy write shadow (`lib/canonical-write-shadow.ts`) and the older per-model serving
  projection path, not as a general-purpose registry. `lib/canonical-write-shadow.ts` requires
  `canonical_object_map.status == 'verified'` before a legacy model save becomes an executable
  canonical shadow write (`enqueueCanonicalModelShadow`, `verified = mapping?.status ===
  "verified" && Boolean(mapping?.canonical_id)`); otherwise the command is recorded with
  `status: "needs_crosswalk"` rather than falling back to a name/slug guess. Names and slugs are
  deliberately not accepted as write authority.

**The fact that Mechanism B is sparse (1 of 383 possible Brand/Model links verified) is not, by
itself, a coverage defect.** It reflects Mechanism B's original and current role as an explicit
Phase-C verification gate, not an attempt at comprehensive crosswalk coverage. Zero disagreements
between A and B where both have an opinion is a mildly reassuring data point (the one case where
both mechanisms weighed in, they agree), but the sample is too small (n=1) to generalize from,
and generalizing from it is not the point — the two mechanisms are answering different questions
for different consumers, not competing to answer the same one.

This finding directly corrects the framing in the original Phase 0 pass, which risked implying
two similarly-populated, competing crosswalks in need of reconciliation. See
`MIGRATION_PLAN.md`'s Phase 1 section for the corrected problem statement, and
`CURRENT_STATE.md` §10 for the updated structural description.

## Reproducing this check

No credentials, project ref, or connection string are recorded here. The shape of the check,
reproducible by anyone with live read access to the project:

```sql
-- Mechanism A: release-build crosswalk coverage
select count(*) as models_with_tdr_id
from current_vehicle_models
where tdr_model_id is not null;

select count(*) as brands_with_tdr_id
from current_vehicle_brands
where tdr_brand_id is not null;

-- Mechanism B: canonical_object_map status distribution
select source_table, canonical_entity_type, status, count(*)
from canonical_object_map
group by source_table, canonical_entity_type, status
order by source_table, canonical_entity_type, status;

-- Mechanism B: verified rows, for spot inspection
select source_table, canonical_entity_type, source_id, canonical_id, status
from canonical_object_map
where status = 'verified'
order by source_table, canonical_entity_type;

-- Cross-mechanism comparison at Brand/Model scope (conceptual shape; the actual
-- comparison requires joining Mechanism A's tdr_model_id/tdr_brand_id against
-- Mechanism B's source_id for source_table in ('models','brands') and
-- canonical_entity_type in ('model','brand'), which is not automated anywhere
-- in this repository today — this was a manual reviewer query, not a checked-in
-- script or view).
```

All of the above are read-only `SELECT`s against tables/views that already exist per the
migrations cited above. Running them requires live project credentials, which are intentionally
not recorded in this document, this repository, or any file committed to it.

## What this document does and does not establish

**Establishes**: the live counts above, as supplied by architecture review on 2026-09-15; that
Mechanism A and Mechanism B are live, real, and behave as `CURRENT_STATE.md` §7/§10 describe them
structurally; that no disagreement exists in the one case where both mechanisms currently have an
opinion.

**Does not establish**: whether this snapshot is representative of a later point in time (both
mechanisms can change independently — Mechanism A on every release build, Mechanism B whenever a
model is verified for Phase-C); whether the `registrations` RLS policy question from
`docs/consolidation/PHASE_A_BASELINE.md`/`LIVE_SUPABASE_VERIFICATION.md` (2026-09-09, predates
`migration_v15`) has been separately re-verified (it was not part of this check — see
`BASELINE.md`'s remaining live-Supabase gaps); any automated, repeatable comparison mechanism
between A and B (none exists in the repository — the comparison above was ad hoc).
