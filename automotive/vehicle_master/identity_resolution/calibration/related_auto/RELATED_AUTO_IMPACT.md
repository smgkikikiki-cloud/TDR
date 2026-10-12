# Rev 5 impact — a RELATED brand may reach AUTO (measured against the accepted rev 4 baseline)

> Owner decision `od_related_brand_auto_eligible` (2026-10-12). **Draft, `binding: false`, not frozen.** The same M7.0 snapshot (1200 Ice model groups) was resolved by the same reference evaluator under the rev 4 baseline policy and under the live rev 5 policy. The rev 4 run reproduces the committed relation export for all 1200 subjects (0 mismatches). Nothing from rev 4 is rewritten: the export, the calibration outputs, the owner review sheet and the Owner Decision Pack stay the baseline.

## Result

- Decisions that changed: **1** of 1200. AUTO groups: **69 → 69**. Newly AUTO groups: **0**.
- RELATED-brand candidate pairs in the M7.0 pools: **90** (in 8 subjects). Pairs that pass every AUTO gate under rev 5: **0**.
- **False-AUTO exposure on the real data: 0 newly AUTO-eligible pairs** (there are no owner labels on any of them: 0). The rule is armed, but no M7.0 pair uses it yet.

### Outcomes

| outcome | rev 4 | rev 5 |
|---|---|---|
| AUTO | 69 | 69 |
| INSUFFICIENT_DATA | 53 | 54 |
| NO_CANDIDATE | 883 | 882 |
| PROPOSE | 195 | 195 |

### Decisions that changed

| group | brand | rev 4 | rev 5 | codes added |
|---|---|---|---|---|
| JETOUR\|ไม่ระบุ | JETOUR | NO_CANDIDATE (BRND_NOT_IN_TDR) | INSUFFICIENT_DATA (INSUFFICIENT_DATA_NO_BASIS) | BRND_PREFIX_STRIPPED, INSUFFICIENT_DATA_NO_BASIS, SER_COVERAGE_ASYMMETRIC, SER_MISSING_ROW_SEMANTICS_UNCONFIRMED, SER_NO_COMMON_WINDOW, SER_UNOBSERVED_NOT_ZERO |

### What stops a RELATED-brand pair from reaching AUTO (first failing gate)

| first gate | pairs |
|---|---|
| EXCLUDED:GEN_LIFECYCLE_DISJOINT | 2 |
| EXCLUDED:NAME_CONTRADICTION | 87 |
| NAME_RELATION_UNAVAILABLE | 1 |

By alias class: `chery_jetour` 3, `land_range_rover` 12, `mercedes_amg_maybach` 57, `mg_maxus_registration` 18. Per-pair detail: `related_pairs.csv`.

## Reading the numbers

- The brand relation only removes the brand cap. Name, series, body, lifecycle, gap, lineage, margin, cardinality and state gates are unchanged (SPEC I20), so a related-brand pair is as AUTO as the same pair under an equal brand and no more.
- JETOUR is a separate marque related to Chery (`chery_jetour`, RELATED, owner-seed provenance). The only M7.0 JETOUR group has an unspecified name (3 units), so the new class moves it from `NO_CANDIDATE` (brand not in the pool) to `INSUFFICIENT_DATA` and creates no AUTO pair.
- Classes now AUTO-capable whose provenance is still `assumption`: `gwm_sub_brands`, `land_range_rover`. They are the owner's to confirm (`alias_assumptions`); an AUTO through them is only as sound as that assumption.
- Behaviour that changes without changing any M7.0 decision: a RELATED candidate whose target is held by another subject's APPROVED / LOCKED claim now raises `STRUCTURAL_REVIEW` (as an equal-brand candidate does) instead of being silently excluded; covered by `classify.related-brand-twin-claim-conflict-protected-target`.
- This is a dry run on one package; it says nothing about future packages. Whether any RELATED pair is *correct* is an owner question (R6 pair verdicts), and AUTO remains an auditable machine state, not an approval.

## Files

`impact.json` (summary), `changed_decisions.csv`, `related_pairs.csv`, `MANIFEST.json`. Regenerate: `python -m identity_resolution.calibration.related_auto collect` (needs the archived M7.0 package); check offline: `... verify`.

