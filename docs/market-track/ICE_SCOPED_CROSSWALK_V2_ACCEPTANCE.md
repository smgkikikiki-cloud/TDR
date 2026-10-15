# R6 scoped Crosswalk v2 — offline integration acceptance

**Status:** offline integration candidate for a separate main-based Draft PR. It depends only on PR #232's scoped resolver implementation commit `15f1747d`; no unrelated changes from that branch are included. No production gate advanced, no production data or schema changed, no migration number assigned, no merge/deploy/cutover.

## Source and replay evidence

The acceptance uses PR #229's frozen Issue #228 recovery source at `872a1117b163feac42e0ce55314cd7a7408896b5` and PR #232's original reviewed base at `3050beb1cdad4530808177de7b9d66abb21364f3`. `source_manifest.json` and `artifact_manifest.json` verify all recovered source and output file hashes and byte counts. The M7.0 ZIP SHA256 is `c558d2d4cc3ed667f8b30ea028dbb66c4030cdce4e7daabe735df870cb94677`.

The acceptance runner opens the real M7.0 package, extracts all 262,985 `reg_trend` facts, groups them by `(model_group_id, reg_type)`, and compares all 1,407 keys and counts with the frozen shadow input. The key sets and values match exactly and both sum to the fixed denominator **4,141,987**. It sends the 1,407 frozen scope rows through the v2 resolver, then reads the complete 262,985 period/province/class facts one-for-one through the Python adapter. The adapter's scoped status totals match the 1,407-row replay exactly; there is no loss, duplication, or inferred `RY2` from `RY1`.

A SELECT-only read fetched all current production `ice_reg_trend` rows and compared a canonical row SHA256 to the frozen ZIP. Both had 262,985 rows, 4,141,987 units, and SHA256 `1c58780ce6d620b4da7b485d6a2a27093172dca13fa06797c3ada5a1d6663b66`. The reproducible, credential-free replay and sanitized live-readback metadata are saved under [`qa/`](</workspace/TDR/data/packages/ice_crosswalk_r6_offline_recovery_M7.0/qa/acceptance_report.md>).

The Python and TypeScript scoped reader implementations pass the same shared JSON fixture. It includes repeated periods and provinces, many Ice groups mapping to one canonical model, RY1/RY2/RY3 pickup scope, excluded and pending rows, missing targets, an ambiguous legacy target, and a proposed target. Both implementations retain all units and produce the same canonical-model, segment, body, mapping-status and period/province/class totals.

## Frozen decisions and measured coverage

The immutable owner ledger remains exactly 244 rows: **92 LINK, 63 retained AUTO, 51 EXCLUDE, 38 CREATE**. The 1,200-row owner overlay, original override package, pickup split source and decision references are retained and hash-verified. The replay reports zero decision mismatches and zero rows needing owner re-review.

| State | Registrations | Share of fixed denominator |
|---|---:|---:|
| Owner-approved and servable | 3,763,511 | 90.8625% |
| Retained legacy AUTO and servable | 213,045 | 5.1435% |
| **Combined approved + legacy AUTO** | **3,976,556** | **96.0060%** |
| Pending, including identity materialization and unresolved pickup classes | 99,116 | 2.3931% |
| Owner-excluded, retained in denominator | 13,901 | 0.3354% |
| Unmatched or ambiguous | 52,414 | 1.2656% |
| Fixed denominator | 4,141,987 | 100% |

Five legacy `PROPOSED` class rows cover 30 registrations; this is a subset of pending and receives no approved-coverage credit. The 99.1% fixed-denominator target requires 4,104,710 servable registrations. Measured approved plus legacy AUTO coverage is short by **128,154** registrations, so acceptance fails the target honestly. The report does not count PROPOSED, shadow-only, or unavailable identities as approved.

The TypeScript reader remains disconnected from production routes. Python and TypeScript group by each fact's existing period, province, DLT class and Ice group; no consumer behavior changes.

## The 114 missing identity targets

The deterministic materialization plan has 114 unique owner-directed CREATE targets. It carries source Ice group, frozen owner decision reference, M7.0 registration units, owner lifecycle/distinctness instructions, collision evidence, required master fields and status. A current SELECT-only snapshot of all 323 `vehicle_models` rows found no canonical-ID or exact same-brand name collision for these targets. Five targets match an existing same-brand alias; they remain frozen as distinct owner decisions and are marked for a governed-writer collision guard, not owner re-review. The other 109 have no exact same-brand name/alias match in the captured snapshot.

All 114 stay `BLOCKED_GOVERNED_VEHICLE_MASTER_WRITER_PHASE1`. The repository's v66 governed writer handles price changes; it does not authorize structural model CREATE. `brand_id`, slug and payload must come from the future structural writer's controlled reconciliation. Models without an explicit discontinued instruction remain `UNVERIFIED`; no segment/body facts are invented.

## SQL and governance review

The unnumbered scoped SQL draft's source-grain primary key `(model_group_id, reg_type_scope)` supports many-to-one links. Its canonical FK references `vehicle_models(canonical_id)`; status constraints distinguish APPROVED, EXCLUDED and PENDING; the design preserves `pending_target_id` without a false FK for an unmaterialized identity. The draft now rejects updates that change the source key, master version, decision reference, source hash or creation time. The service role has SELECT only; it receives no DML grants. Static tests check this contract. The SQL remains a design candidate and was not executed.

**C01 remains open.** The current live readback confirms the final import (period `2569-09`, package v3, M7.0), 490 existing crosswalk rows (82 SERIES/AUTO, 408 PROPOSED), 50 redirects (31 merges, 19 renames), and 1,200 known groups. It confirms executed state, not who ran the prior R6 workflow or whether that run was authorized. GitHub API access to workflow history returns HTTP 403. No prior row is newly approved by this evidence.

**C02 remains open.** Repository and governance evidence record v57/v58 as already applied while older design reservations still claim those numbers. The repository currently contains migrations through v66, but no independently reconciled production ledger/owner-approved allocation for this new table. The scoped SQL stays unnumbered and unapplied.

## Later execution sequence

After C01 provenance and C02 numbering are independently reconciled and the required owner gates are current:

1. Have the owner assign a safe migration number and authorize a separately reviewed migration. Verify the exact table/function/privilege diff against the static contract before DDL.
2. Backfill from the pinned M7.0 package and frozen owner sources into a staging relation. Require 1,200 group / 1,407 group-class parity, exact 244 ledger checks, preserved exclusions, and `4,141,987` raw units before insert. Insert only approved rows whose canonical FK exists; keep missing targets PENDING. Never copy PROPOSED into APPROVED.
3. Compare the staged scoped reader to M4 and raw Ice by period, province, class, brand and source group. Confirm no unit changes, correct many-to-one totals, RY-specific pickup behavior, and fixed-denominator coverage of at least 99.1% using only servable approved/retained AUTO rows.
4. If migration verification fails, keep the scoped reader disconnected; remove only the newly added scoped objects through an owner-authorized rollback after proving no consumer depends on them. Leave v63 and all raw Ice tables untouched.
5. Keep production reader cutover blocked until R7 acceptance and the separate R8 owner go. Cutover requires a controlled serving flag and a tested rollback to the previous M4 reader; it must not blend legacy and scoped totals.

**Current blocker:** measured coverage is 96.0060%, the 114 creates lack an authorized structural writer, and C01/C02 remain unresolved. The next permissible engineering step is independent offline QA of this Draft PR; any production schema, materialization, or reader activation requires those gates and the separate owner authorization above.
