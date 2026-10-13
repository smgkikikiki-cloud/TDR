# ICE R6 Scoped Crosswalk V2 — offline consumer design (Issue #230)

**Status:** PROPOSAL / TEST-ONLY. The repository's R6 production crosswalk gate
remains closed. No SQL migration ID is allocated, no production DDL or crosswalk
write is permitted, and this branch is not wired into live pages.

## Why V2 is required

M7.0 contains 1,200 Ice model groups / 4,141,987 registration units.
The frozen owner package has 430 exact approved source group mappings, pointing
to 348 distinct canonical IDs. 117 source groups intentionally share 35 target
identities (notably Hilux Vigo, Camry, BMW i8). The deployed v63
`ice_model_crosswalk_active_canonical_uniq` UNIQUE partial index constrains one
canonical ID to one active Ice group. Relaxing this index **alone** is unsafe:
the existing code's matched-monthly-series logic, untyped group joins and
potential many-canonical-to-one-group links also need review.

A second problem is within **one source group**: pickup registrations of
`รย.1` and `รย.3` can refer to different TDR identities. The existing
`lib/ice-market-engine.ts` groups by `model_group_id` only. The shadow QA counts
1,461,079 pickup-class registration units that cannot be correctly represented
by that group-grain production join.

## Proposed binding / cardinality

1. Source grain: `(ice master release, Ice model_group_id, reg_type)` is a
   **single-valued active resolution slot**. It may be unresolved, excluded,
   ambiguous/rejected (never served), or linked to exactly one canonical model.
   Every resolved slot keeps its owner decision reference and source evidence.
2. Canonical target cardinality: **many distinct source slots may point to
   the same canonical model ID**. Do not enforce uniqueness on the target ID.
3. Keep separate candidate/proposal/history rows as immutable evidence,
   including older v63 multiple-candidate review state. Do not let source
   candidate fanout multiply counted registrations.
4. Keep `APPROVED/ADMIN` distinct from `AUTO` and from unapproved
   `PROPOSED`. An owner decision wins over correlation; score remains
   diagnostic. Missing catalog identities are **PENDING_MATERIALIZATION**.
5. Explicitly distinguish `EXCLUDE` (owner exclusion from KPI target universe)
   from a vehicle deletion or missing registration fact. Raw registration totals
   never disappear.
6. **Scoped-wins-with-no-fallback:** when ANY scoped mapping exists for an Ice
   group, a missing `reg_type` must remain unlinked. Never borrow a group-only
   legacy target for a missing class.
7. Normalize the reg_type presentation token (RY1 = รย.1, RY3 = รย.3);
   **do not infer RY2 = RY1 globally**. Only explicit pickup owner rules can
   assign RY2 to Double Cab.
8. Bind to a specific Ice release / source package hash; do not imply that
   the same group ID means unchanged identity in a newer release without
   processing `id_changes.csv` and redirects.

## Candidate schema concept — NOT executable SQL / not migration approval

Add an append-only reviewed-decision/event record with owner authority, source
grain, target, action and provenance. Add a separate resolved-serving snapshot
whose unique active key is **`(source_release_id, model_group_id, reg_type)`**,
not `canonical_model_id`. The serving snapshot is built transactionally only
from reviewed, validated and materialized targets. Preserve v63 tables as
historical evidence until read parity is proven.

A classless legacy row is a compatibility fallback **only for groups with no
scoped rules at all**. The new reader must join by both `model_group_id` and
`reg_type` from `ice_reg_trend`. The model-dimension response still uses
Ice group identity as its entity key, with any canonical attachment rendered as
scoped/possibly mixed metadata; do not silently pick one canonical for a group
whose RY1 and RY3 go to different models. For segment/body_type, sum per source
row after resolution, never per joined target row.

A mixed scoped group may need `canonical_model_id=null` on group-level model
summary, with per-reg_type subdivisions available through an **explicitly
versioned** response field or endpoint. Any serving-contract change is gated,
not silently rolled into the existing API.

## Offline implementation already in this branch

`lib/ice-scoped-crosswalk-contract.ts` and
`scripts/check-ice-scoped-crosswalk.ts` demonstrate deterministic resolution,
safe legacy fallback, class-exact routing and registration conservation. This
is intentionally **NOT** wired into `lib/ice-market-data.ts` yet.

`npm run check` includes these fixtures. They assert shared Vigo/BMW i8 IDs,
RY1+RY3 within a Triton group, RY2 only when explicitly supplied for Travo,
proposed/rejected never served, ambiguous target fanout never double counted,
and raw = linked + unresolved + excluded + ambiguous.

## Required before any integration or production proposal

- Resolve portfolio C01 (prior live R6 write provenance) and C02 (migration
  numbering/authority) without inferred permission.
- Design and test additive V2 persistence, migration and rollback with the
  existing 490 live crosswalk candidate rows, 50 redirects and versioned
  source import metadata. Do not overwrite migration_v63.
- Replay 244/244 frozen owner decisions without modifications; materialize the
  114 genuinely absent vehicle identities using a future governed master
  writer (retired input/release path is forbidden).
- Wire a versioned V2 server reader and validate exact unit conservation
  across market dimensions, monthly windows, province/reg_type and unknown
  buckets; independently compare with Ice totals.
- Report **approved served coverage** separately from `AUTO`, `PROPOSED`
  target availability and the 99.5309% shadow simulation. The fixed M7.0
  denominator is 4,141,987 registrations; owner exclusions must be reported
  separately, not silently removed to inflate the KPI.
- Require owner-reviewed gate advancement, green CI, explicitly approved
  production migration + rollback evidence before a real crosswalk writer
  or M5 market cutover. No further owner re-review of 244 vehicles.
