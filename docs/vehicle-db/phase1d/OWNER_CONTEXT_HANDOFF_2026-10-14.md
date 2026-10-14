# TDR Vehicle Master / Ice Identity — Owner context handoff

## Owner-corrected decision: Layer 2 is ONE working end-to-end user product (2026-10-14)

**Explicit owner correction to an earlier wrong boundary:** Do NOT define Layer 2 as finished just because Vehicle Catalog identity/trim/price/spec is populated. **Ice registration crosswalk, accurate market registration comparisons and the actual website experience MUST work too.** A split between data-engineering streams cannot be used to split away product acceptance. The previous note claiming Ice R6/registration matching is outside Layer 2's completion criterion was **WRONG and superseded** by this section.

**Unified Layer 2 delivery scope and sequential milestones:**
1. **Vehicle Identity / Crosswalk foundations:** finish and QA initial eight proposed BASIC model identities safely before expansion, while preserving frozen Ice review decisions and Ford Ranger Raptor HOLD. Vehicle Master structural identity ≠ registration group crosswalk; implement both correctly through separate reviewed engines and independent permissions.
2. **Verified CURRENT retail Trim and official Price:** reconstruct OEM current-market lineups, distinguish historical/retired and MY versions, verify trims/prices against official evidence using separate Trim Checker and Price Fetcher. Honor existing Admin lock, price basis, provenance and lifecycle confidence. Absence from one page is not proof of discontinuation. Price Fetcher is distinct from Ice's DLT file reader.
3. **Spec Enrichment:** re-use PR #203 Queue B for applicable P1/P2 current-trim specs from documents/OEM/ECO. Store evidence-backed `vehicle_facts`, correct applicability/units/powertrain, missing/unknown states and source/version/authority; never invent specs or silently modify structure.
4. **Ice data + Crosswalk → real registration comparison:** complete the separately governed **R6 reviewed identity matching**, **R7 real-data acceptance**, and **R8 site read/UI wiring** as required by `docs/market-track/ROADMAP.md`. Registration classes must resolve to the correct existing/new models, and relationships `EQUIVALENT`, `PART_OF`, `COMPOSED_OF` must not spuriously double-count, split or imply exactness. Preserve unmatched/HOLD and coverage disclosure. Ensure the actual Ice registration read models and user-facing brand/model/time-period comparisons return correct totals, denominator/cohort definitions and source freshness.
5. **Layer 2 integrated website E2E QA and owner acceptance:** The original TDR website and Website Pro must let real users search/compare vehicle models, trim specs and prices **AND** compare registration market outcomes reliably. Verify portal visibility/entitlements, canonical IDs/links, cross-source joins, zero-doubled units, zero fabricated facts, time-series comparisons, missing/uncertain case treatment and continuous update/reconciliation. Test representative OEM, trim, price, spec, registration and current/historical variations on real source-backed data. No unapproved legacy data fallback. Independent QA and explicit owner acceptance are required.

**PRODUCT definition of DONE:**
- Vehicle identity and approved Ice Crosswalk resolve registration data to correct model/brand; relevant coverage/HOLD and exclusions are honest and traceable.
- CURRENT trim/price and prioritized specs are accurate/evidence-backed, with unknown values represented as unknown and maintenance flows working.
- Actual website Layer 2 catalog comparison **and registration/market comparison both function** for intended user scopes with correct counts, zero false attribution/double-counting, appropriate freshness, privacy/entitlement, and useful comparisons.
- Automated refresh/validation and audit behavior is proven end-to-end. Independent QA + owner's product sign-off occurs **after these integrated outcomes**, not just after completing individual engineering components.

**GOVERNANCE DISTINCTION (not a product scope exclusion):** Structural Identity Writer/Admin Approval, Ice R6/R7/R8, Trim/Price, Spec Maintainer and Website read contracts are separate implementer workstreams with their own authorization, rollout and data gates. Preserve independent R6 review and production permissions, but **all are dependencies for one Layer 2 delivery milestone**. The user specifically rejected describing Ice as a separately optional or post-Layer-2 task. Layer 3 Dealership Toolkit remains a separate application; it is not a condition for Layer 2 completion.

**Current ACTIVE focus is unchanged:** first-eight BASIC Identity full-catalog SQL rehearsal in Issue #244 / Draft PR #245. Do not prematurely open new parallel implementation or bypass Admin/C02/Enforcer/R6 gates. After initial eight accepted, progress through the remaining work with each feature tested, then run unified end-to-end Layer 2 acceptance. These owner product-level decisions add no Production/deploy authority by themselves.

**Reference contracts:** `docs/portfolio/TDR_MASTER_ROADMAP_V1.md` (original site includes registration/market comparison as Layer 1–2), `docs/portfolio/DOMAIN_BOUNDARIES.md`, `docs/market-track/ROADMAP.md`, `docs/vehicle-db/VEHICLE_DB_V3.md`, `docs/WORK_STATE.md`.

## 2026-10-14 QA update: Issue #244 restore fingerprints and actionable numeric reserialization suspicion

**Review PR #245 (Draft):** https://github.com/smgkikikiki-cloud/TDR/pull/245. Codex pushed `d0cf9c837a0d6fd120fcebc18d7fa1d36d8e8942` to `codex/vm-phase1d-full-catalog-eight-20261014`, successfully restored 15 tables/28,319 rows to isolated PostgreSQL 16.10; **15/21 source pre-Phase1C relation/view fingerprints matched, 6/21 differed** with identical row counts. The runner CORRECTLY stopped before applying Phase1C; **zero** BASIC rows were created in that run or Production. Other 61 existing PG SQL cases passed separately on only a Toyota catalog fixture. Reviewer successfully opened PR #245 after Codex PR-create HTTP 403.

**Six mismatches:** vehicle_variants, vehicle_trims, vehicle_facts, vehicle_eco_evidence, current_market_trims, current_spec_facts. Inspector found a concrete likely cause in `scripts/phase1d-full-catalog-postgres-acceptance.ts`: after verifying the original backup checksum the runner does `JSON.parse(gunzipSync(compressed).toString('utf8'))` then `fs.writeFileSync(prettyPayload, JSON.stringify(envelope))` before `::jsonb` restoration. JS JSON.stringify **rewrites numeric lexical scale**, e.g. `405.0 → 405`, so source JSONB textual hash can change although numeric value is equivalent. The **four mismatching physical tables are exactly the four tables with floating-point-valued numbers** in the owner's private JSON. Counts of integral-valued floats: variants **184**, trims **1,910**, facts **4,004**, eco_evidence **3**; four source-matching business tables and other sampled tables without these floats lack this rewrite pattern. Two affected Views depend on the affected Trims/Facts. This is a **strong, testable hypothesis**, NOT yet a proof all six mismatches have this sole cause.

**Independent reviewer SELECT-only source diagnostics saved to GitHub (metadata and hashes, NOT raw vehicle rows):** `docs/vehicle-db/phase1d/issue244_live_source_schema_acl_diagnostic_2026-10-14.json`. Contains 21 relations metadata, 274 column types/default hashes, 96 constraint hashes, 29 trigger hashes, 7 RLS policies, 63 effective role privilege rows, 34 source function hashes, 61 column-level value multiset hashes for the four differing underlying tables. This helps identify an exact differing column on local PG16 if byte preservation alone does not close the gate. It is NOT a complete deployed function/view/policy SQL restore manifest or a single transaction of all scans.

**Exact next action (same Issue #244, same branch and PR; no new workstream):** have Codex retain original uncompressed **byte-exact** gzip-decompressed data for restore (e.g. `fs.writeFileSync(prettyPayload, gunzipSync(compressed),{mode:0o600})`), verify temp-file SHA256 equals original uncompressed bytes, add 405.0/1.0 numeric-scale regression, rerun **unaltered** 21 source fingerprints; do not change expected baseline or waive failing 6. If still differs, compare per-column MD5 from live diagnostic and reproduce field-level cause. Until source CATALOG baseline/view/ACL parity is proven, **do not run Phase1C** on full-catalog database or create first eight. Admin auth / C02 migration / Enforcer remain independently blocked, Production writes never authorized. After full-catalog test passes and eight ONLY created in isolated PG, stop for owner QA.

## Latest next action: Full-catalog PG rehearsal task packet (2026-10-14)

**Issue #244 created / branch ready:** https://github.com/smgkikikiki-cloud/TDR/issues/244 — `codex/vm-phase1d-full-catalog-eight-20261014`, based on `47825542c3fd0b536e49bea173b0e628c9e06517` from Draft PR #243. This is the **same Phase 1D feature's next acceptance** (no new writer), not an authorization to deploy. The reviewed owner-provided backup is ready; a compact **private** ZIP containing only the latest validated GZIP (SHA256 `8b7dc88cf42c27516ec08ddf170173feff85891ac655caa9a6f3eb5511d8b962`) and sanitized manifest was produced for manual transfer to Codex's own private workspace. **Do NOT upload it to GitHub** or assume a GitHub-connected agent can see the private ChatGPT `/mnt/data` file automatically.

The current ChatGPT runtime was checked and has no `docker`, `podman`, `postgres`, `initdb` or `psql`; DNS/network apt installs fail. Thus **NO full 28,319-row real PostgreSQL replay has run** in this environment. Owner's next UI action: attach the private latest-backup package to Codex session and instruct it to implement **Issue #244 only** using its local network-isolated Docker PostgreSQL. Original 61 SQL cases were tested with a Toyota fixture only and remain separate from the required new **full** catalog test. The acceptance gates ADMIN_AUTH / C02 MIGRATION / ENFORCER and actual Production write remain blocked regardless of isolated rehearsal result. Stop for independent QA of Draft PR on the new branch. No automatic Codex session has been launched.

## Latest update: owner backup uploaded and independently verified — 2026-10-14

The owner **uploaded `vehicle-master.zip`**; no further operator/download request is necessary to validate its contents. Independent reviewer read all **10** contained `.json.gz` backups. All 10 have valid recomputed canonical payload SHA256, 15 allowlisted tables, matching declared vs actual row counts and **the same canonical payload**. The latest 2026-10-13 backup contains **28,319 records**; its payload SHA256 is `c51c20966be5f49dd0fe9a953793e666f6becf0f4d27a986158b6805e7659dad`. The uploaded ZIP SHA256 is `e5f6ac00b221aa43ca15f1cf85f76f65dac3df4e9750cac930705922f2c35a46`.

**Source identity/key cross-check:** Fresh authorized READ-ONLY aggregate SQL and comparison with the private backup show **7/7** exact row counts and sorted selected identity-field MD5 matches for Brands, Models, Generations, Variants, Trims, Facts and Price Ledger (explicit `COLLATE "C"` avoids false differences). All 15 original table counts match earlier live baseline, but **full field equality / MVCC snapshot consistency not proven**. Offline parent-link verification reports 0 missing references over 15 checked relations. For the first 8, proposed Brands exist, canonical model IDs are absent and no normalized name_en/name_th/payload.alias matches were found in all 323 backup Catalog models. **17 existing cross-model token conflicts** were detected in catalog and must be retained; Ranger Raptor remains HOLD.

**Definitive QA report:** [PRIVATE_BACKUP_QA_2026-10-14.md](PRIVATE_BACKUP_QA_2026-10-14.md). It records file/checksum provenance, client-side limitations and next gate. **This is backup acceptance, NOT PostgreSQL full-catalog acceptance.** In the reviewer environment Docker/PostgreSQL/psql were unavailable, so no actual data restore, Phase1C schema/RPC application or 61 SQL-case replay against the **full** catalog happened. Raw backup is private conversation data and **was NOT committed to GitHub**.

**Next exact executable step:** in a private, authorized Codex/development machine with real isolated PostgreSQL and a private copy of the uploaded backup, extract the latest `.json.gz`, run the repository's `tools.vehicle_master_backup_verify`, build/reconcile the full v57–v64 schema and grants, restore the 15 tables, measure complete CATALOG and six current_* view parity, apply unnumbered Phase1C SQL and exercise ONLY 8 proposed identities with true SQL authorization and rollback checks; stop for independent QA. **Do not write Production, alter RLS/Admin, allocate a migration number, link Ice classes, or expand candidate scope.** C02/Admin/Enforcer production gates remain BLOCKED. The owner has no immediate new SQL/credential action to perform; the uploaded file removes the prior data-acquisition blocker for offline acceptance (not the need for a runnable PG environment).

## Update: existing private backup located — 2026-10-14

The owner has clarified **they themselves administer TDR/Supabase**. Do NOT instruct the owner to message a hypothetical separate operator. Prefer a single, concrete Supabase Dashboard download request if the connector cannot retrieve Storage object bytes.

**New direct live SELECT-only Storage metadata verification:**
- Source Supabase project: `ltvwzkffmpudpjfjomrg`.
- Private Storage bucket `vehicle-master-backups` **exists**, `public=false`.
- **Latest visible backup object:** `vehicle-master/2026-10-13/vehicle-master-20261013T005340Z.json.gz`, created `2026-10-13T00:54:05Z`, gzip size `1,745,781` bytes (~1.75 MB). Ten total backup objects were found as of inspection. No later object was listed.
- Confirmed in repository `automotive/vehicle_master/tools/vehicle_master_backup.py` that the exporter serializes exactly **15 vehicle-master-only tables** (matching the 15 aggregate baseline tables below), with stable table names, row_counts, SHA256 payload checksum, and compressed JSON; no registration/customer tables or legacy canonical revisions are included in its declared allowlist. `tools/vehicle_master_backup_verify.py` verifies checksum, table list, declared row counts and decompressibility. This is evidence of the **exporter's code contract**, not verification of the actual private object's content.
- The current connector exposes SQL metadata but **no authenticated private Storage download action**, and the reviewer has NOT fetched/read/decompressed or imported the backup. The owner should navigate their own Supabase Dashboard → correct project → Storage → `vehicle-master-backups` → `vehicle-master/2026-10-13/vehicle-master-20261013T005340Z.json.gz` → Download. Inspect sensitive JSON fields/sources before sharing externally; keep raw data outside GitHub. If the user chooses to attach the file to a private current chat, inspect checksum/row counts/allowlist first.
- **Important caveats:** Backup was generated roughly 17 hours before the last live aggregate baseline at `2026-10-13T17:49:44Z`; verify drift or collect a newer private snapshot if source has changed. The repo exporter fetches tables sequentially through paged PostgREST calls, not one database MVCC transaction, so cross-table point-in-time consistency is NOT proven solely by the file name/checksum. Backup carries data only, not live SQL schema, RLS policies, grants, views or functions: pair with a separately reviewed SELECT-only metadata/schema manifest and repository v57–v64 when building a disposable test DB.
- **Next immediate action is to retrieve and verify that existing private backup, not to create a new database role or change RLS.** If valid/compatible, conduct a narrowly scoped offline rehearsal for the eight models only. FULL_CATALOG_ACCEPTANCE_BLOCKED remains until exact legacy CATALOG/view/ACL parity against a faithful isolated database is proven. All other Admin/C02/Enforcer gates remain open.

**Last reviewed:** 2026-10-14 (ICT). **Scope:** Vehicle Master Structural Identity Writer, first-eight BASIC Identity milestone and Phase 1D full-catalog readiness. **Status:** OFFLINE TESTED; PRODUCTION NOT AUTHORIZED, NO NEW BASIC MODELS LIVE.
**Repository:** smgkikikiki-cloud/TDR.
**Source of truth:** Supabase Vehicle Master; NOT a CSV/file-backed writer.
**Approved portfolio roadmap:** docs/portfolio/TDR_MASTER_ROADMAP_V1.md v1.0. Overall roadmap approved, but portfolio.plan.json execution.enabled=false and task_queue empty. Owner approval of a plan does not authorize production mutations.

> This handoff preserves decisions and verification evidence when the ChatGPT conversation reaches its context limit. READ THIS FIRST in a new session, then verify PR HEADs and live DB state before acting. Later evidence supersedes dated observations only when verified. This document does not change any approval gate or authorize a task by itself.

## 1. What are we building and why

The Vehicle Master is missing some model identities needed to interpret Ice's vehicle registration classes. Objective: a governed, evidence-backed Structural Identity Writer that **proposes BASIC Brand/Model identities** and, only following owner/admin approvals, creates missing identities in the authoritative Vehicle Master while preserving all existing consumer CATALOG/trim/price serving. It must not invent trim, generation, status, body type, segment or prices. Registration data are a separate market-data domain; linking registration classes through Ice Crosswalk is separately gated by C01/R6.

Owner delivery doctrine (explicit 2026-10-14): **finish and test one feature end-to-end before moving on**. KPI for this sequence is exactly **8 eligible BASIC model identities correctly materialized and owner-QA-approved** in TDR, not adding more code, engines, candidates, price fetching or UI features. This does NOT approve live writes yet.

First-eight frozen proposals and associated registration-unit coverage:

| Proposed canonical model ID | Proposed model label | Registration units | Preflight |
|---|---|---:|---|
| honda.jazz | Jazz | 13,790 | VALID BASIC proposal |
| jaecoo.j6 | J6 | 8,659 | VALID BASIC proposal |
| toyota.vios | Vios | 6,647 | VALID BASIC proposal |
| gwm.ora_5 | Ora 5 | 4,809 | VALID BASIC proposal |
| nissan.march | Nissan March | 4,000 | VALID BASIC proposal |
| nissan.note | Nissan Note | 3,667 | VALID BASIC proposal |
| zeekr.7x | 7X | 2,892 | VALID BASIC proposal |
| toyota.sienta | Sienta | 2,645 | VALID BASIC proposal |
| **TOTAL** | | **47,109** | **test ONLY; production additions 0** |

**Ninth proposal FORD RANGER RAPTOR double cab:** HOLD, 12,839 units, collision against existing parent alias ford.ranger_double_cab. Do not silently approve or merge it into the eight. Frozen owner inputs: **244 approved decisions**, 1,407 registration-class scopes, 4,141,987 total registration units, 4,123,704 effective and 18,283 excluded. Simulated coverage **98.819047%** is a simulation, not new production availability. Frozen decision-ledger SHA256: 9f251b6120d88e52c33215c5127fb6f87cd8c6cc334c39dc227bb540860ae1a8.

## 2. Development history / GitHub evidence

- PR #235: M7 offline/owner frozen input predecessor (head at handoff b5a6bcff2870afb8d81d672dd284e7935e3cb4ac), Draft.
- PR #237: Structural Identity Writer offline planner (head 271ee6b6bcdffdfa7e6d2a912f613e35f1e5f178), Draft.
- PR #239: BASIC Identity serializer/DB compatibility adapter (head 8b7f8d2eaf034735f7b3a1d9dece3421ef1088ae), Draft. BasicIdentityDbAdapter.submit() stays fail-closed; no live writer.
- PR #241: Phase 1C isolated PostgreSQL schema and governed RPC (head 01ff6af90d488e5b3b990a74dc89ad5a2af7bbb2), Draft. Codex-run PostgreSQL 16.10 network-isolated local suite: 61/61 SQL cases, 8 proposed BASIC rows, 47,109 registration units represented, Ford HOLD. Independent review accepted **offline evidence** and authorization hardening, not production parity/activation. Single Toyota CATALOG fixture only.
- Issue #242 / PR #243: Phase 1D compatibility and governance evidence (initial PR #243 head af558ae7d238bec3af1ef2805ac705b2ca9df10a, base PR #241 branch); author reported all proper blockers, independently reviewed as truthful blocked evidence. PR was successfully opened by assistant after Codex's PR-create HTTP 403. Head will change when this handoff is committed; verify current PR HEAD.
- As of 2026-10-14 checked GitHub, **Test TDR and Test TDR consolidated are success** for pre-handoff af558ae7; **Enforcer PR admission failure** due to UNEXPECTED_BASE_BRANCH / UNMANAGED_PR_NOT_TASK_AUTHORIZED and a sensitive WORK_STATE change. Do not bypass Enforcer or claim the handoff commit itself passed CI.

Useful review entrypoints:
- https://github.com/smgkikikiki-cloud/TDR/issues/242
- https://github.com/smgkikikiki-cloud/TDR/pull/243
- docs/vehicle-db/phase1d/{README.md,acceptance_report.json,full_catalog_coverage_manifest.json,admin_trust_acl_review.md,c02_migration_enforcer_decision_pack.md,isolated_rehearsal_runbook.md}
- docs/vehicle-db/drafts/phase1c/{README.md,basic_identity_schema.sql,governed_structural_rpc.sql,postgres_acceptance_report.json}
- docs/portfolio/G0_RECONCILIATION.md (C02)
- docs/WORK_STATE.md, docs/vehicle-db/VEHICLE_DB_V3.md, AGENTS.md

## 3. Current REAL Supabase observations (READ-ONLY, point in time)

**Target source project:** ltvwzkffmpudpjfjomrg, matching dated Vehicle Master identity snapshot. A different connected Supabase project named TDR ASIA (buzjcgdbtjashzjydxwj) did not contain any of the seven searched master tables; do not confuse by display name.

**Observed applied migration ledger:** latest 20261009135816 / v64_ice_panel_grain_fix. v57 parts a–d and v58–v64 present; v65 and v66 reported absent in live query as of this review. C02 **still OPEN** because old Upcoming v57/Analysis v58 reservations clash with already applied Vehicle Master migrations, and the owner has not authorized fresh migration numbers. Repository v66 is a PRICE writer draft, not BASIC structural migration. Live vehicle_models.status, served_as_of, seed_release_id are NOT NULL; identity_level and the structural BASIC RPC are absent. canonical_write_revisions.command_id remains NOT NULL. Six serving views still use master CATALOG / security_invoker=true, and current_vehicle_models currently includes all nondeleted models (no BASIC exclusion).

**One consistent aggregate baseline (not full exported rows):** Supabase connected execute_sql ran a REPEATABLE READ, READ ONLY transaction at **2026-10-13T17:49:44.9154Z** (2026-10-14 00:49:44 ICT) on source DB. It returned only COUNT(*) and deterministic MD5 aggregates of row JSON across 15 physical vehicle tables and 6 serving views; no raw catalog rows were transferred or committed. MD5 fingerprints are pragmatic equality checks, not cryptographic attestation or per-row audit. Use the SAME canonical expression on both sides and recheck drift before any rehearsal.

| Relation | Rows | Aggregate MD5 |
|---|---:|---|
| vehicle_brands | 62 | 7ce84530fa9dc9af5c87b58b3f652b27 |
| vehicle_campaigns | 44 | a3cd9287b2c0e9e1682eb361c8c221bd |
| vehicle_current_retail_sets | 61 | 98505d5881d32de49de3bddbb915ecd0 |
| vehicle_eco_evidence | 3 | 20d33f0f5260b5f038a41d183269c9cc |
| vehicle_facts | 24,492 | 074a7cf2c603a218fc232e24a9e015a5 |
| vehicle_generations | 326 | 39ad73ac4fcf806f308350c8acbcb7bf |
| vehicle_legacy_identities | 1 | e51d798b7ed8776c8a403b2d3f6cae22 |
| vehicle_master_state | 1 | e73224fca556e9b3271b1e806c1007c3 |
| vehicle_model_operational_states | 0 | d41d8cd98f00b204e9800998ecf8427e |
| vehicle_models | 323 | 40320bee99d7215829bb886a8e5f0583 |
| vehicle_price_ledger | 1,004 | cf37f790454aca0662392fb906c8b400 |
| vehicle_promotions | 48 | 89ede84f53d099695618c214c77523e5 |
| vehicle_trim_lifecycle_decisions | 15 | daa514d81438380bff9babe13bca7b21 |
| vehicle_trims | 1,569 | 61e0230c93dd2cbc6b3a5cbe9ccf64c5 |
| vehicle_variants | 370 | dbcea4aa79471faf9f0a5bcab3e732de |
| current_market_trims | 1,569 | 5d57479684c0faf3ca87b1db373adf55 |
| current_price_ledger | 1,004 | 717c630c162f2b0e76b99ed7ebddbd30 |
| current_spec_facts | 23,083 | 3681ad68ae64e3244bb86f6abbcea001 |
| current_vehicle_brands | 62 | 8b14709c09faa7d7cd9b5ab12820a389 |
| current_vehicle_generations | 326 | 4991637da060e706dc6522a673712794 |
| current_vehicle_models | 323 | 5055ed942a93ae28b5ddd03b32de9418 |

Fingerprint method for each relation t: md5(coalesce(string_agg(md5(to_jsonb(t)::text), '' ORDER BY md5(to_jsonb(t)::text)), '')). For future parity, legacy CATALOG columns must be projected identically; adding Phase1C fields naturally changes full physical to_jsonb hashes and must not be misclassified as data corruption.

**Eight candidate live screening:** all eight proposed canonical IDs absent exactly and eight Brand IDs exist. An additional SELECT-only screening of active master model name_en/name_th/payload.aliases, using NFKC+lowercase+brand-prefix removal+nonalphanumeric stripping consistent with Phase1C canonicalization, found zero matching normalized model identities for those eight proposed labels. This is **partial evidence only**: NOT a complete alias-token clearance across all identity sources or an approval to create.

## 4. Exact blocker to portable full-CATALOG PostgreSQL rehearsal

The source Supabase connector authenticates as current_user=postgres (BYPASSRLS, privileged). The owner **approved catalog data read-only use for a local isolated acceptance fixture**, but **did not approve changing production roles/RLS or exporting through an elevated credential**. We deliberately did not export rows with postgres.

Role inspection found:
- pg_read_all_data has SELECT but is NOLOGIN and NOBYPASSRLS. SET LOCAL ROLE pg_read_all_data under a READ ONLY transaction returned **0** vehicle_models and **0** vehicle_trims because existing RLS policies target anon/authenticated served rows, not this role.
- supabase_read_only_user can LOGIN/SELECT but has BYPASSRLS=true, too broad for the scoped export assurance; SET LOCAL ROLE from connected postgres returned permission denied.
- An independent, vehicle-catalog-scoped NO-BYPASSRLS, non-writer authenticated credential with appropriate historic/unserved catalog visibility has **not been made available**, and no full row-level, restore-ready catalog snapshot was exported.
- Existing private vehicle-master-backups Storage bucket is documented in WORK_STATE (first backup 2026-10-04). A DB/storage owner can check whether a **fresh, complete, access-controlled existing vehicle-only backup** suffices instead of granting any new credential. Verify actual date, completeness, JSON payload classes, provenance and restore fitness before trusting it. The assistant has not fetched this backup.
- A user-facing sandbox ZIP of count/digest baseline and an unexecuted private-export procedure was provided in the original conversation. It is a HANDOFF, not a produced raw data dump; source-controlled SQL should remain non-mutating.
- Export review must inspect JSON payload/catalog_payload/source_ref(s) for personal/confidential material. Do not upload customer data, credentials or raw unapproved bulk rows to GitHub or ChatGPT.

**Owner must do only one immediate coordination action:** ask the person administering source Supabase/storage to choose the **least-change** safe source for vehicle-only snapshot: (A) retrieve and privately hand over a validated current complete existing Vehicle Master backup with read-only permission, or (B) explicitly request and separately approve a time-bound scoped SELECT-only export identity + carefully scoped RLS policy through a reviewed DBA change. Do not require the owner to type SQL or share database passwords in chat. The assistant/Codex can then inspect the private artifact and execute isolated replay if properly made available. Until this is done, FULL_CATALOG_ACCEPTANCE_BLOCKED remains.

## 5. Other gates that a good catalog snapshot cannot magically close

- ADMIN_AUTH_ACCEPTANCE_BLOCKED: current lib/admin-auth.ts supports named password users or a shared TDR_ADMIN_PASSWORD; shared password accepts a caller-supplied label. Signed tdr_admin_session contains name/timestamp, not an immutable verified principal, approval record or server→DB issuer binding. Phase1C isolated DB issuer/executor are separate, but production TDR admin-to-RPC trust still lacks an independently approved mapping. Do not run SQL RPC with service-role, trust display labels or invent approval references.
- MIGRATION_GATE_BLOCKED: migration applied-history is now freshly observed through v64, but C02 reservation collision, new migration identifier owner assignment, dependency sequencing and canonical_write_revisions.command_id compatibility are not approved. Do not self-number or patch old migrations.
- ENFORCER_ADMISSION_BLOCKED: stacked Draft PR base not admitted by current Enforcer. Hosted test suites may pass independently; never retarget merely for green or weaken policy.
- C01/R6 Ice Crosswalk is separately gated: writing BASIC Identity is not authorization to link registrations. Price Fetcher (OEM website prices) is separate from the Ice DLT file reader and from Trim Checker. Do not expand to other workstreams before first-eight acceptance.

## 6. Whole bounded execution plan (one feature, gated steps)

| Gate | Exact work | Evidence / pass condition | Owner approval |
|---|---|---|---|
| **0. Preservation (DONE)** | Freeze 244 decisions and 8 eligible models; preserve Ranger HOLD; leave existing writer fail-closed | Verified frozen SHA + Phase1C 61 local SQL-case log; no production additions | Prior owner direction |
| **1. Data access (CURRENT)** | Choose verified existing complete backup or authorized catalog-scoped read-only private export; capture schema/ACLs, dependent rows, relevant views, dated ledger | Complete consistent restore-ready privately held vehicle-only dataset plus provenance; no unknown content/scope | DB/storage owner; owner separately approves any role/RLS mutation |
| **2. Full-catalog isolated acceptance (NEXT)** | Restore full current catalog into network-isolated disposable PostgreSQL; replay repo v57–v64 and unnumbered Phase1C SQL; test 8 exact candidates only; compare every existing CATALOG row/key/price/current view, SQL grants and RLS, normalized identity tokens, release state, and reversible audit | 0 unintended CATALOG/serving diffs, 0 unresolved collisions, 8 BASIC in isolated DB; 61 original SQL cases still pass; report reproducible exact commands/hosted CI | Independent QA |
| **3. Admin/auth contract** | Stable immutable admin actor and approved decision record; independent issuer/executor binding and authorized RPC route design; adversarial auth tests | Real gate verifies identity, explicit approval, role/grant, expiry/revocation and receipts; no forged admin/action works | Admin/security and DB reviewers |
| **4. Migration & Enforcer governance** | Resolve C02 on fresh ledger; approve schema/revision audit compatibility and migration IDs; dependency-safe PR admission sequence #235→#237→#239→#241→#243 | Owner-approved ledger/ids/plan, Enforcer accepts exact branch; isolated rollback tested | Portfolio/DB/Enforcer owners |
| **5. Preproduction dress rehearsal** | Repeat full-catalog tests against current snapshot with approved final migration artifacts and bounded eight-action plan; backup/abort/runbook sign-off | Zero diff; all 8 expected identities; no catalog contamination; reversible, clean preflight | Independent owner QA |
| **6. FIRST LIVE 8 (FUTURE; NOT AUTHORIZED NOW)** | Separate explicit owner authorization for production migration, secure Admin activation, and exact 8 identity writes; pre/post SQL readback and rollback readiness | Exactly 8 canonical BASIC rows in authoritative Vehicle Master, 8 auditable receipts, no duplicate/ghost aliases, existing public CATALOG trims/prices/views unchanged. BASIC rows not public retail until separately enriched. Stop and request owner acceptance | Explicit, specific production release approval |
| **7. AFTER owner acceptance only** | Expand remaining identity candidates in bounded batches, address Ranger HOLD as a separate decision; then separately authorize C01/R6 matching and later Trim/Price Fetcher projects | Each new feature independently tested and owner signed off | New scope/gate |

Never equate “8 created in disposable PostgreSQL” with “8 created live” or “8 identities materialized” with “47,109 registration units now linked/servable”.

## 7. Forbidden actions / execution hygiene

No production/staging DDL or DML or actual production BASIC inserts; no migration number without C02 owner decision; no Admin/RLS/grant change from read-only data consent; no privileged postgres/service-role raw export or secrets in GitHub; no Enforcer bypass, no new writer, no auto-merge/deploy, no Ice crosswalk links, no Trim/Price Fetcher scope. Snapshots must stay private and minimised. Code changes must be separately planned and QA-reviewed; portfolio.plan.json execution remains disabled.

**Do not schedule work in the background.** GitHub Issue/PR and this handoff only persist instructions/evidence. Actual Codex coding sessions require the owner's action/approved task.

## 8. Start of next chat — exact recovery instructions

Open this file plus Issue #242 / PR #243, read AGENTS.md, docs/portfolio/TDR_MASTER_ROADMAP_V1.md v1.0, portfolio.plan.json, docs/WORK_STATE.md and docs/vehicle-db/VEHICLE_DB_V3.md. Recheck PR HEADs and live DB as needed. **Do not assume this file's 2026-10-14 baseline is current.** Confirm whether the DB/storage owner provided a reviewed fresh complete vehicle-only backup or separately authorized read-only export credential. If not, stop and request only that missing owner/operator handoff, not another engine or giant phase. Once provided, do the eight-row isolated full-catalog acceptance and seek independent QA; Production remains blocked until separate Admin, C02 and Enforcer approvals. Do not start a new phase or expand the model list.
