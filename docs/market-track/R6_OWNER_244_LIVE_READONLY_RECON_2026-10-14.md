# Ice R6 — owner 244 decisions vs real Production, READ-ONLY reconciliation (2026-10-14)

**Status: evidence for Issue #228 / Draft PR #235, NOT R6 release acceptance.**
**Authoritative project ref:** `ltvwzkffmpudpjfjomrg` (Vehicle Master and imported Ice M7.0).
**Bounded scope:** SELECT-only PostgreSQL, immutable existing 244-decision CSV and M7.0 class-scope manifest. No crosswalk writes, no Schema changes, no R6 gate advancement and no owner re-adjudication. A 244-row joined Production export was deliberately NOT committed; the already committed owner ledger remains the only source for the original decision details.

## 1. Real live state and C01 observation

- Imported M7.0 `ice_package_imports`: one `2569-09`, package v3 / master `7.0` record at **2026-10-10 13:53:42 UTC**.
- Actual `ice_model_crosswalk`: **490 rows / 489 source groups**; **82 AUTO, 408 PROPOSED, 0 APPROVED**. Observed row creation/update window **2026-10-10 15:40:20–15:42:28 UTC**. `ice_model_group_redirects`: **50**; `ice_known_model_groups`: **1,200**.
- These timestamps and rows prove **execution state** (some matcher output exists) but DO NOT prove who authorized the execution or that any owner approvals were applied. **C01 is still OPEN**.
- `ice_model_crosswalk_scoped` table does NOT exist. V63 has a partial unique index `ice_model_crosswalk_active_canonical_uniq` on **canonical_model_id where status AUTO/APPROVED**. It cannot represent multiple independently approved Ice groups pointing to one canonical; the old group-level schema also lacks reg_type grain. R6 v2 scoped SQL remains unnumbered and undeployed.

## 2. Frozen owner's original 244 decisions — checked against live

Source: `data/packages/ice_crosswalk_r6_offline_recovery_M7.0/owner_decision_ledger_244.csv`; frozen SHA256 `9f251b6120d88e52c33215c5127fb6f87cd8c6cc334c39dc227bb540860ae1a8`. **244 unique decision IDs, 244 distinct Ice group IDs**. Each group exists in the stored 1,407-scope M7.0 evidence and has **exactly one** old Production Crosswalk record (read-only join verified). The existing owner actions were NOT changed.

| Frozen owner action | Rows | Current live-model/old-crosswalk position | Actual next dependency |
|---|---:|---|---|
| `KEEP_EXISTING_AUTO` | **63** | **63/63** already AUTO to the exact approved existing canonical; still 0 APPROVED in DB | Preserve owner directive, do not rerun scoring; integrate owner authority into reviewed v2 reader |
| `OWNER_LINK_EXISTING` | **92** | **64** target canonical IDs currently materialized; remaining **28** target IDs absent | V2 source-grain mapping for all; all 28 absent targets are already covered by frozen `OWNER_CREATE_IDENTITY` actions in this SAME 244 ledger, not new owner questions |
| `OWNER_CREATE_IDENTITY` | **38** | **38/38** canonical targets absent in current live Vehicle Master; old source crosswalk PROPOSED | Governed identity writer + owner-approved CREATE batch; do not link to unmaterialized target or claim approved |
| `OWNER_EXCLUDE_FROM_COUNT` | **51** | **51/51** old records still PROPOSED, not marked owner EXCLUDED | V2 owner exclusion records with immutable reason; raw Ice registrations stay in source denominator and source tables |
| **TOTAL** | **244** | **244 source groups present / 0 DB APPROVED** | **No new owner re-adjudication requested** |

This is exact-key comparison with live v63 group-level state, not approval of that state. An old AUTO row is not proof of completed R6 approval. Among the 193 non-exclusion owner source groups, **21 canonical targets are shared by 80 source groups**, demonstrating that a globally unique active canonical constraint cannot encode the intended owner decisions. Some old AUTO target collisions require owner-first v2 precedence and careful reader cutover.

## 3. Independent REAL Ice source-scope equality proof

Frozen source: `data/packages/ice_crosswalk_r6_offline_recovery_M7.0/qa/filtered_identity_manifest/final_scope_dispositions.csv` from Draft PR #235 (not the 244 owner ledger).

Read-only SQL computed `SELECT model_group_id, reg_type, sum(reg_count) FROM public.ice_reg_trend GROUP BY model_group_id,reg_type` and **FULL OUTER JOINED all 1,407 frozen (model_group_id,reg_type,registrations) keys** supplied as an in-memory SQL VALUES CTE. Key uniqueness was checked before query. Query ran within `REPEATABLE READ READ ONLY`; no temp table, DML or file upload.

- Frozen scopes **1,407**, source scopes **1,407**; both sum to **4,141,987** registrations.
- **0** scope mismatches, **0** unexpected live scopes, **0** missing live scopes, **0** absolute unit differences.
- Live `ice_reg_trend` spans 69 months **2564-01 through 2569-09**, 262,985 monthly/province rows, 1,200 groups.
- This proves M7.0 **class-grain input parity** against current source, NOT proof that any proposed mapping or site consumer is correct.

## 4. Real offline M7.0 scope partitions, NOT production approved coverage

| Offline M7.0 disposition | Reg-type scopes | Units |
|---|---:|---:|
| Excluded (all exclusions, overlapping rules applied once) | 879 | 18,283 |
| `MATCH_EXISTING` candidate (NOT v2 Production APPROVED) | 395 | 4,027,896 |
| `NEW_BASIC_IDENTITY_NEEDED` proposal (NOT CREATE permission) | 111 | 94,432 |
| Unresolved evidence | 22 | 1,376 |
| **TOTAL** | **1,407** | **4,141,987** |

There are **84 unique new-identity proposals** in the filtered manifest: **73 SAFE_CANDIDATE and 11 REVIEW_HOLD**. A SAFE_CANDIDATE is not an owner authorization to write a live model. The 244 frozen owner group-level actions are a different subset of the 1,200 group M7.0 source universe: do not confuse the 38 expressly owner-directed CREATEs with the 84 broader proposals, nor count two scopes of one Ice group twice. `new BASIC` proposed units are not currently approved/servable units.

At least **9 group IDs** in the complete class-scope manifest have different canonical targets on different registration classes, including Ford Ranger, Isuzu D-Max, Toyota Hilux Revo/Travo, Nissan Navara, Mitsubishi Triton and others. Exact **(model_group_id, reg_type)** authority is required BEFORE class-reduction; no RY2=RY1 inference or parent-name fallback.

Reported offline possible coverage after all still-unapproved links/proposals: **4,122,328 / 4,141,987** on fixed original denominator, not an approved or live KPI. The approval target remains **≥99.1% approved/servable on the fixed 4,141,987** without giving credit to PROPOSED, unmaterialized BASIC or unsupported pickup class.

## 5. Engineering next action — scoped v2 contract is the FIRST coding priority

Continue the already existing **PR #229/PR #232/PR #235** assets, not another matcher from scratch:
1. In a disposable PostgreSQL environment, apply the **unnumbered v2 scoped schema draft** from PR #232, not a Production migration. Prove many Ice group IDs → one canonical model, and one group → distinct canonicals by reg_type; fail on conflicting exact-scope decisions, invalid source version or orphan target.
2. Load all **244 frozen owner decisions** preserving action, provenance and CREATE dependencies. Exact class-scoped approved mappings must override ALL fallback, old AUTO, and old PROPOSED. Uncreated targets become `PENDING_MATERIALIZATION`, not a fake mapping. All approved exclusions suppress legacy fallback but preserve raw registrations.
3. Run both Python/TypeScript existing scoped resolvers + actual Ice `reg_trend` row-grain fixture (period, province, reg_type, group), asserting unit sum **4,141,987**, 0 duplicates/drops, 0 cross-class leakage. Validate both the 21-owner-shared canonical collision constraint and the >=9 truly class-split groups. Document 244/244 decisions explicitly exercised, not just present in file.
4. Report which groups are independently servable with existing canonical IDs, which are blocked only by scoped schema/reader, which depend on the **38 owner-approved absent CREATEs**, and which require separate evidence. Prevent a "99.9%" PASS from shadow-only proposals.
5. Present independently reviewed v2 R6 schema/writer/read-path plan with no split-brain. Only **after** C01 provenance and C02 fresh migration-number owner authorization may any deploy/migration be requested. **Do not** run a live matcher or create Model rows now.

**STOP / not authorized:** Production/staging DDL/DML, crosswalk promotions, merge, migration number allocation, Enforcer bypass, Ice R7/R8 cutover, Price Fetcher, Trim Checker, Spec Enrichment or any re-review of the frozen 244. The first 8 Vehicle Master IDs remain a subordinate controlled test, not a replacement for working Crosswalk.

This report is intentionally sanitized (aggregate counts / already documented source references). It does not contain new private Production row dumps or credential material.

## 6. Production Ice reg_trend LEFT JOIN conservation test (2026-10-14)

Executed a **second independent SELECT-only, REPEATABLE READ** test on production: feed all 1,407 `final_scope_dispositions.csv` keys as SQL CTE VALUES, LEFT JOIN the actual `public.ice_reg_trend` on **both** `model_group_id` and `reg_type` (unique scoped keys checked client-side), without writing or changing any Production mapping. Count the actual row-grain facts before and after JOIN.

| Check | Before | After | Difference |
|---|---:|---:|---:|
| `ice_reg_trend` fact rows | **262,985** | **262,985** | **0** |
| Registration units (all periods) | **4,141,987** | **4,141,987** | **0** |
| Unmatched Ice raw facts to 1,407 frozen scoped keys | | **0** | |

Disposition-linked raw fact counts: **4,988 source fact rows excluded** (not deleted); **4,027,896** units matched to existing-ID *offline candidates*, **94,432** units to new-BASIC *offline proposals*, **1,376** unresolved, and **18,283** units excluded (as established by the original scope manifest). These labels are **NOT** Production APPROVED, nor a test of v2 deployed schema/reader. Exact scoped static JOIN is a proof that the input grain can conserve 100% of the imported raw facts/units. Production v2 table does not exist, so v2 actual deployment remains blocked.
