# R6 scoped Crosswalk v2 — real M7.0 offline acceptance

Source: PR #229 frozen recovery head `872a1117b163feac42e0ce55314cd7a7408896b5`; resolver base: PR #232 head `3050beb1cdad4530808177de7b9d66abb21364f3`.

Run from repository root with `PYTHONPATH=automotive/vehicle_master python automotive/vehicle_master/tools/ice_scoped_m7_acceptance.py`. The runner is offline; its only live input is the versioned, SELECT-only catalog snapshot saved alongside this report.

The exact M7.0 ZIP SHA is `c558d2d4cc3ed667f8b30ea028dbb66c4030cdce4e7daabe735df870cb94677d`. Its 262,985 raw `reg_trend` rows aggregate to 1,407 `(model_group_id, reg_type)` rows and 4,141,987 registrations. All 1,407 keys and counts match the frozen PR #229 shadow rows exactly; the same resolver then reads all 262,985 raw facts once with zero unit loss or duplication. A SELECT-only read of live `ice_reg_trend` also matches the frozen M7.0 rows exactly by canonical row SHA256. The reproducible evidence and sanitized readback are stored beside this report in `qa/`.

## Fixed-denominator coverage

| Mapping state | Registrations | Share |
|---|---:|---:|
| Owner-approved and currently servable | 3,763,511 | 90.8625% |
| Retained legacy AUTO and currently servable | 213,045 | 5.1435% |
| Combined approved + legacy AUTO | 3,976,556 | 96.0060% |
| Pending, including shadow identities and unresolved pickup classes | 99,116 | 2.3930% |
| Excluded by owner, retained in denominator | 13,901 | 0.3356% |
| Unmatched or ambiguous | 52,414 | 1.2654% |
| Fixed denominator | 4,141,987 | 100.0000% |

The 99.1% target requires 4,104,710 approved/servable units. Measured approved + retained AUTO coverage is 3,976,556; the shortfall is 128,154. The 30 registrations in five legacy PROPOSED crosswalk rows are a subcount of pending and are not approved coverage.

## Materialization and remaining gates

The owner-approved missing-identity plan contains 114 CREATE targets. The live read-only `vehicle_models` snapshot contains 323 models; 109 targets had no exact same-brand name/alias collision and 5 match an existing same-brand alias. Those five keep their frozen owner identity decision and require the governed writer's collision guard; none is sent back for owner re-review. Every target remains blocked on a structural Vehicle Master Phase 1 writer.

All 244 decisions remain exact (92 LINK, 63 retained AUTO, 51 EXCLUDE, 38 CREATE); no owner decision was reopened. Raw segment/body outputs and unknown buckets are in `real_m7_reader_totals.json`. C01 production-run authorization provenance and C02 migration number reservation remain unresolved, so there is no migration assignment, production write, reader cutover, merge, or deployment.
