# Phase 1D — independent QA of owner-uploaded private Vehicle Master backup

**Review date:** 2026-10-14 ICT. **Decision:** BACKUP INTEGRITY AND BOUNDED EIGHT-MODEL CLIENT PREFLIGHT ACCEPTED. **FULL POSTGRESQL CATALOG ACCEPTANCE NOT RUN; ALL PRODUCTION GATES BLOCKED.**

Owner uploaded `vehicle-master.zip` to a private conversation. **The ZIP and extracted records are NOT committed to GitHub.** All observations below are aggregate/sanitized QA findings.

## Exact file and verifier results

- ZIP SHA256: `e5f6ac00b221aa43ca15f1cf85f76f65dac3df4e9750cac930705922f2c35a46`.
- 10 backup objects (2026-10-04 through 2026-10-13). Each ZIP entry extracted without integrity errors; each nested GZIP decompressed and parsed. All use `tdr-vehicle-master-backup` format v1, the exact 15-table allowlist of `automotive/vehicle_master/tools/vehicle_master_backup.py`, and each declared count matches actual array length.
- **10/10 payload SHA256 verified** by recalculating SHA256 over canonical UTF-8 JSON (`sort_keys=True`, compact separators, `ensure_ascii=False`). **All ten payload SHA256 hashes are the same** (unchanged canonical contents despite different backup export times).
- Latest member: `vehicle-master/2026-10-13/vehicle-master-20261013T005340Z.json.gz`; exported `2026-10-13T00:53:40Z`. Latest compressed SHA256: `8b7dc88cf42c27516ec08ddf170173feff85891ac655caa9a6f3eb5511d8b962`.
- All ten payload SHA256: `c51c20966be5f49dd0fe9a953793e666f6becf0f4d27a986158b6805e7659dad`. Latest payload uncompressed JSON 53,938,200 bytes (PRIVATE).
- **28,319** rows across 15 business tables, exactly matching previously observed source table counts. Physical rows include 62 brands / 323 models / 326 generations / 370 variants / 1,569 trims / 24,492 facts / 1,004 price rows, plus campaigns, promotions, eco evidence, retail sets, state and legacy identity sidecars.

## Fresh source parity evidence (READ-ONLY)

Independently reran a strict `REPEATABLE READ READ ONLY` SELECT aggregate on live source project `ltvwzkffmpudpjfjomrg`. Compared count + sorted MD5 of stable textual identity/key fields between the private backup and live source for `vehicle_brands`, `vehicle_models`, `vehicle_generations`, `vehicle_variants`, `vehicle_trims`, `vehicle_facts` and `vehicle_price_ledger`: **7/7 MATCH**; all other eight table counts matched prior source baseline. Sorting with explicit `COLLATE "C"` is required to make PostgreSQL's ordering comparable with the Python verifier; otherwise the source collation creates false mismatches.

**Scope restriction:** selected fields/key MD5 comparisons do not prove that every payload value, changed price, RLS result, DB function, trigger, grant or serving view is identical. MD5 is an equality check, not a security authentication primitive. The backup code exports per-table by paged GET; no single SQL MVCC snapshot across the 15 tables is guaranteed. The file is timestamped before the later source baseline. Thus DO NOT mark full-catalog post-migration parity green.

## Eight-model offline first-pass check

Against all 323 catalog models in the uploaded backup, the proposed brands all exist, the exact canonical model IDs are all absent, and there are no normalized-token matches from the existing model `name_en`, `name_th`, or string array `payload.aliases` for these eight proposed English names:

`honda.jazz`, `jaecoo.j6`, `toyota.vios`, `gwm.ora_5`, `nissan.march`, `nissan.note`, `zeekr.7x`, `toyota.sienta`.

Preflight normalized names via Python Unicode NFKC/lowercase/brand-prefix/alphanumeric logic analogous to Phase1C SQL. **This is NOT a SQL-executed exact normalizer proof or all-source alias clearance.** There are 17 normalized tokens already shared across different CATALOG model IDs; preserve those conflicts, never auto-merge or silently suppress evidence. 15 offline FK-style parent reference checks covering model/generation/variant/trim/fact/price etc had zero missing parents. Existing Ford Ranger Raptor stays HOLD, 12,839 registration units.

The proposed eight represent 47,109 registration units in frozen simulation only; **0 BASIC identities in Production** and no R6 link activated.

## Unresolved gates / next action

1. **FULL_CATALOG_POSTGRESQL_ACCEPTANCE_NOT_RUN.** Reviewer runtime has no Docker, Podman, PostgreSQL binaries (`psql`, `initdb` or `postgres`). Did not restore 28,319 rows, apply Phase1C SQL, execute triggers/61-case suite against this full catalog, run six serving-view before/after comparisons, or prove real DB RLS/ACL compatibility. Python integrity/FK/name checks are NOT substitutes.
2. **Schema/provenance:** private backup serializes **data only**, not live view/function definitions, grants, policies, migrations or revisions. Rebuild faithful disposable v57–v64 schema and collect independently reviewed source ACL/view metadata, then reconcile same-snapshot consistency/updated source field drift.
3. **ADMIN_AUTH_ACCEPTANCE_BLOCKED:** deployed immutable Admin principal/approval record→DB issuer/executor trust unproven.
4. **MIGRATION_GATE_BLOCKED:** latest live applied v64 known, but C02 and audit migration approval unresolved.
5. **ENFORCER_ADMISSION_BLOCKED:** stacked Draft PR admission still needs authorized resolution.
6. **C01/R6 crosswalk NOT authorized:** separate gate.

**Do next:** in Codex/local owner-authorized environment with a disposable offline PostgreSQL 16+ and private copy of ONLY the last GZIP member, verify the backup via `python -m tools.vehicle_master_backup_verify PATH`, restore repo-compatible v57–v64 schema and the 15 tables, then run catalog baseline and unnumbered Phase1C SQL plus original 61 cases and 8 bounded operations. Do not commit/share the raw backup, touch Production, invent approval records or begin more candidates. Stop for independent QA and owner acceptance. This doc is evidence-only; it is NOT a migration/writer activation or a grant of production authority.
