# G0 reconciliation evidence, conflicts and decision requests

**Observed:** 2026-10-11 (GitHub main/open PR metadata, supplemented later by SELECT-only CP-00 Supabase audit; no DB writes).  
**Roadmap decision:** owner APPROVED Master Development Roadmap v1.0 on 2026-10-11 after reviewing the full plan. **G0 operational evidence/permission conflicts remain OPEN**, with R6, migrations, billing and CTPDI method decisions gated separately.  
**Priority:** facts before jobs, authority before autonomy. Status in this document is a point-in-time reading, not an instruction to change workstream heads.

## 1. Source provenance and precedence

| Source | What it establishes | Limits |
|---|---|---|
| [AGENTS.md](../../AGENTS.md) | canonical Vehicle Master is Supabase, Ice/registrations separate, retired writer prohibited, repo single active home | applies directly |
| [WORK_STATE.md](../WORK_STATE.md) | Phase 0 done, Phase 1 writer absent, Market Track R6 gate currently locked | may lag external actions/PR evidence; reconcile, never overwrite silently |
| [Market ROADMAP](../market-track/ROADMAP.md) | R6 → R7 → R8 fixed execution order; owner gates for R6 and R8 | no branch overrides |
| [VEHICLE_DB_V3](../vehicle-db/VEHICLE_DB_V3.md) | authority, observation/write rules, structural AI proposal-only permissions | owner-approved future amendment not adopted |
| [MERGE_DECISIONS](../MERGE_DECISIONS.md) | adopted original TDR Website design/plan choices; outranks design notes and conflicting earlier docs | does not itself certify deployed code behavior |
| [GRAFT_PLAN](../../design/GRAFT_PLAN.md) | UI overhaul, typed adapters, design PR ordering and acceptance | no Vehicle Master edits, data cutover separately gated |
| [PRODUCT_ACCESS](../PRODUCT_ACCESS.md) | website entitlement/code-description at prior snapshot | payment/quota text disagrees with newer owner MERGE_DECISIONS |
| [PR #200](https://github.com/smgkikikiki-cloud/TDR/pull/200) | draft resolver contract rev3, R6 calibration dataset, 490 recovered rows, no new engine | not frozen, owner review sheet unlabelled |
| [PR #201](https://github.com/smgkikikiki-cloud/TDR/pull/201) | draft bootstrap offline engine and M7 shadow (67 CREATE candidates) | no applied identity, no production CREATE authorization |
| [PR #203](https://github.com/smgkikikiki-cloud/TDR/pull/203) | draft fixture-only dual-queue catalog simulator | earlier ten local tests do not resolve requested correction/CI checks |
| 2026-10-08 `TDR_PDI_CTPDI_RETAIL_PRICING_INTELLIGENCE_MASTER_BRIEF_v0.7` | locked universe/price scope vs unapproved pricing methodology | user prior-file design summary, not yet copied/adopted in repo |
| 2026-10-10 `TDR_Enterprise_Master_Architecture_and_Design_Handoff_v0.2_LOCKED_SPATIAL` | owner-locked standalone B2B, spatial IA, five Model Analysis sections and 1/5-page PDF | not yet an adopted repo design contract; pixels/scoring/price/seat count unapproved |

**Conflict handling:** `OWNER_LOCKED` decisions retain their semantics; `DRAFT` proposals cannot supersede; where two apparently approved texts conflict, HOLD and ask owner. The portfolio document is a mirror, never a way to rewrite original authorities.

## 2. GitHub and environment snapshot

- PR #200 is **open draft** on `claude/wizardly-keller-0ixbhj`. It reports 490 crosswalk rows recovered read-only from a 2026-10-10 R6 workflow, 50 redirects, 82 legacy AUTO/407 PROPOSED/1 STRUCTURE, zero approved/rejected. Proposed v1 contract is `binding: false`, has no production resolver and 560 blank owner-verdict fields.
- PR #201 is **open draft** on `claude/fervent-wozniak-ld6lo4`. Offline tests/shadow done; 67 CREATE candidates remain after v2 rules; no production create/approve.
- PR #203 is **open draft** on `codex/vehicle-catalog-maintainer`, fixture-only. A prior correction round requested CI import fix (both working directories), source completeness, Admin lock/tombstone, verification semantics, mixed priorities, HISTORICAL conflict, fairness and local job identity. **These are not accepted as completed based on PR body**; combined status lookup exposed no status entries, which does not prove green CI.
- The original website Home design [PR #173](https://github.com/smgkikikiki-cloud/TDR/pull/173) is **open draft**. It is not an accepted final Home; `design/GRAFT_PLAN.md` demands removal of temporary Market/Analysis placeholders before merge.
- `docs/WORK_STATE.md` says Vehicle Master Phase 0 live, Phase 1 not started; no new canonical writer.
- `docs/WORK_STATE.md` and Market ROADMAP say `R6_PRODUCTION_CROSSWALK` is current and NOT STARTED, `PRODUCTION_CROSSWALK_ALLOWED=false`, `LIVE_CUTOVER_ALLOWED=false`; R5 final package import is done. Preserve these gates regardless of recovered R6 records until reconciled.

## 3. Critical conflicts (do not have an AI silently decide)

### C01 — R6 execution-state inconsistency · P0 / BLOCKS R6 AND downstream R7/R8

**Evidence:** main `WORK_STATE.md` says crosswalk tables empty and R6 not started; PR #200 recovered 490 rows and 50 redirects from an alleged 2026-10-10 production R6 run (but no owner-approved mapping). Both describe different states. **Do not infer what happened, who authorized it or which database state is current.**

**Resolution required:** independent read-only reconciliation against exact production project/version and actual workflow history; record executed step vs *authorized* gate separately. Identify run timestamp, writes, review statuses and approval, then owner controls any correction to WORK_STATE/ROADMAP. Stop before fresh matcher, R7, R8 or crosswalk mutation.

**CP-00 live state check on 2026-10-11 (SELECT-only):** `ice_model_crosswalk` contains **490** rows (**82 AUTO, 408 PROPOSED, 0 APPROVED**) across 489 Ice group IDs, `ice_model_group_redirects` 50 rows and `ice_known_model_groups` 1,200 rows. This confirms PR #200's recorded-row observation and falsifies WORK_STATE's *current factual empty-table assertion* as of the read. It **does not establish whether any R6 action was owner-authorized**, resolve why WORK_STATE was not updated, approve existing AUTO associations, or permit an R6 re-run. C01 stays OPEN until provenance/owner adjudication reconciles execution-state and authorization-state separately. See [CP00 audit](CP00_SOURCE_COVERAGE_AUDIT_2026-10-11.md).

**Follow-up live state check on 2026-10-12 (SELECT-only):** authenticated readback confirms the same 490 crosswalk rows, 50 redirects, and 1,200 discovery-ledger rows; all were created/first-seen on 2026-10-10. Current details: 82 `SERIES/AUTO`, 407 `NAME/PROPOSED`, 12 `SERIES/PROPOSED`, 1 `ADMIN/PROPOSED`; 19 `เปลี่ยนรหัส` and 31 `รวม` redirects; 489 current Ice groups have candidates and 711 are unmatched. The live import is still M7.0, period `2569-09`, package v3. The owner gave a new R6 go on 2026-10-12, but that does not establish prior-run authorization or approve individual mappings. GitHub Actions run history returned HTTP 403 from this environment, so run identity remains unverified. C01 stays OPEN for provenance/authorization; no production rerun was made. Review exports: `/workspace/ice_crosswalk_review_live_M7.0_2026-10-12.csv` (all current groups) and `/workspace/ice_crosswalk_redirect_review_2026-10-12.csv` (redirect decisions).

### C02 — Migration-number reservation collision · P0 / BLOCKS new migrations

**Evidence:** GRAFT_PLAN assigns Upcoming `v57` and Analysis `v58` based on 1 October reservation; `WORK_STATE.md` reports Vehicle Master `migration_v57_vehicle_master_tables.sql` and `migration_v58_vehicle_serving_parity.sql` have ALREADY been executed. An old design reservation cannot safely be turned into real migration filenames now.

**Resolution required:** list *all actual* merged/pending migration filenames and deployed migration ledger; owner authorizes new safe migration IDs for Upcoming/Analysis and any Toolkit DB additions; update conflicting planning documents in their own approved follow-up PR. Never rename or overwrite already applied migration files.

### C03 — Website subscription decisions versus code/docs · P0 / BLOCKS payment modifications

**Evidence:** `docs/MERGE_DECISIONS.md` approved original-site Pro at THB 1,099 monthly/11,490 yearly, Omise and revised Free/Pro rights; older `docs/PRODUCT_ACCESS.md` still says THB 1,290 monthly/2,970 quarterly/9,480 yearly with different quotas; 2026-10-10 Enterprise handoff reports current `lib/billing.ts` as Stripe. **Decision, document and actual running billing may differ.**

**Resolution:** audit current `lib/plans.ts`, billing provider, webhook and deployment state, then produce a *separate* owner-reviewed migration/compatibility plan. No implicit rewrite of paying subscribers; Toolkit organization license stays separate from website personal Pro. Enterprise working THB 5,900/59,000 and 5 seats are proposals, not locked.

### C04 — CTPDI comparable-pair aggregation grain · P1 / BLOCKS publishable formula

**Evidence:** 2026-10-08 pricing brief uses explicit reviewed CN–TH matching with price basis and FX, ratio per comparable pair; 2026-10-10 Enterprise handoff describes model×generation×powertrain and per-country median current trims for an indicator. These may be different analytical measures. Their equivalence has NOT been demonstrated.

**Resolution:** owner chooses candidate-level versus headline aggregation, comparable source/price basis and published `gap %` vs `parity=100` convention. Model-level PDI must not be algebraically subtracted from trim-pair CTPDI to fake comparable net retail prices. Fixture tests can proceed as alternatives but no default published metric.

### C05 — PR #200 source coverage, calibration and owner decision · P1

**Evidence:** R6 calibration changes 218/489 legacy rows under a common-window policy; absent-row semantics for both Ice/TDR remain UNKNOWN. 26 adoption entries unresolved; 560 owner review rows still blank. New resolver must not silently replace the legacy production matcher.

**Resolution:** owner adjudicates prioritized labels and formally freezes a tested policy version; do not treat unlabelled historical AUTO as owner-approved.

### C06 — PR #201 creation permission / catalog eligibility · P1

**Evidence:** PR #201 candidates include dormant legacy and recent models. `DISCOVERED` is not current retailed; PR #203 current-only excludes it.

**Resolution:** label false-CREATE cases, freeze lifecycle/link handshake and only then design governed writer/approval route. No automatic onboarding into spec backfill.

### C07 — PR #203 correction/test gate · P1

**Evidence:** ten locally reported tests and simulator artifacts; active correction requests are more demanding.

**Resolution:** require reproducible commands from repo root AND `automotive/vehicle_master/`, current CI checks (not just combined empty statuses), verified locked-null/NOT_APPLICABLE behavior, no false VERIFIED inference, mixed P1/P2 handling, conflicting retired status, explicit lineup completeness, queue fairness, unrelated-change-stable job IDs, zero-network/writes/paid calls. Do not authorize Chunk 2+ yet.

### C08 — Historical pricing vs current-only catalog agent · P1

**Evidence:** pricing roadmap wants a sourced retrospective chronology going back to BE 2564/2021; PR #203 bans enrichment of HISTORICAL models/trims and does not own MSRP/promo ledger writes.

**Resolution:** separate price evidence/observation/event backfill domain with explicit data as-of/source confidence and frozen history. No false coverage guarantee; don't turn absence into verified-zero discounts.

### C09 — Standalone Toolkit design contract versus website UI · P1

**Evidence:** original website rules and nav in MERGE_DECISIONS/GRAFT_PLAN; Toolkit v0.2 locks separate account-scoped model analysis, one Spatial workspace with local Dealer Geography/Network Watch modes, and 1-page/5-page PDF snapshots; prior portfolio draft described Geography/Network Watch as separate global nav products.

**Resolution:** preserve owner-locked Toolkit IA and keep it distinct from website `design/GRAFT_PLAN`. Move approved Toolkit UX into a separately versioned in-repo product contract on an owner-reviewed PR; don't replace the existing website navigation or confuse Web Pro and corporate license.

### C10 — Dealer evidence and geographic entitlement readiness · P1

**Evidence:** owner requires region-specific registrations and clear separation from dealer branch sales, plus nearby neutral out-of-region dealer site data but not out-of-region registration figures. Dealer source priority and completeness have not been verified.

**Resolution:** source register for sites/franchise/operators; effective vs detected event times; closure verification criteria; per-organization and per-user region ACL tests including map popups, exports, PDFs and deep links. No closed-dealer inference from temporary locator disappearance.

### C11 — PDI methodology / Japan admission / coverage · P1

**Evidence:** owner locked origin classes, sub-THB2m trigger and full-trim inclusion, median MSRP and offer exclusions. Median-discount numerator, equal-model aggregation, coverage floor, freshness policy and Japan inclusion are still proposals.

**Resolution:** run upstream price coverage audit; record explicit Japanese admission and pricing formulation decisions; use versioned frozen universe and source-backed verification of zero vs unknown.

### C12 — Autonomous overnight runner auth / rights · P2

**Evidence:** ChatGPT Chat is not an unattended execution worker; proposed Claude Code CLI + Codex CLI loop needs a distinct runner, bounded tasks, subscription usage ceilings, isolated worktrees and independent QA.

**Resolution:** runner/Auth/allowed-work tests and user authorization for first sandbox task only. Night shift must not run from this portfolio JSON. No unattended merges/deploys/payment calls/API fallbacks.

## 4. Gate outputs & precise next steps

| Gate | Deliverable | Pass condition | Current G0 verdict |
|---|---|---|---|
| G0-A Evidence Inventory | present documents + PR observations + contradiction register | each material source fact points to exact file/PR; owner decisions vs proposals explicit | **Documented; source-state conflicts remain** |
| G0-B Resolve Critical Conflicts | C01 R6, C02 migration allocation, C03 payment roadmap and C04 index grain | approved, versioned decision recorded; relevant authority doc updated via separate scoped PR | **BLOCKED / outstanding** |
| G0-C Adopt Portfolio Contract | domain boundaries and workflow responsibilities | owner accepts the portfolio roadmap; no automatic work permission | **OWNER APPROVED v1.0; unmerged on PR branch** |
| G1 Offline Engineering | narrow approved correction or fixture task | green CI + exact base SHA + no scope/gate breach | **NOT STARTED BY THIS PR** |

**Earliest legitimate autonomous trial:** after review, choose a *new* isolated fixture/test task (potentially a single #203 correction follow-on only after that PR's current correction round stops); pin HEAD SHA and permitted paths; Claude implements, Codex reviews from a clean pinned read-only checkout, enforcer enforces deterministic checks and caps at a proposed three fix cycles, then returns draft PR for owner review. It does not proceed into R6, R8, production writer, external research or paid AI research calls.

## 5. Owner decision queue

- **D01 (critical):** authorize independent R6 state readback/reconciliation and approve the resulting source-of-truth correction *after* actual-state evidence.
- **D02 (critical):** adopt a fresh migration allocation plan based on deployed/merged files; stop any design PR that would reuse v57/v58.
- **D03 (critical):** reconcile the public site's Omise/Stripe/legacy-Pro commitments before any subscription work; keep B2B commercial plan unapproved.
- **D04:** settle CTPDI calculation grain + headline convention; can defer while read-only fixtures progress.
- **D05:** select/freeze first G1 work packet after #203 corrections; no vague permissions to all branches.
- **D06:** choose owner-verified sample labels for #200/#201; full autonomous CREATE/ADD/retire remains separately gated.
- **D07:** approve initial price evidence coverage/freshness rules and Dealer Master source/event verification.
- **D08:** adopt Toolkit design contracts without overruling Website Pro rights; five model analysis sections, local Spatial modes and PDF rules are protected.

The owner approved the **portfolio roadmap and its governance direction** on 2026-10-11. That approval does NOT resolve C01–C04, adopt a specific disputed index formula, create a Task Packet, grant GitHub merge rights or authorize production changes. Those decisions remain explicitly separate.
