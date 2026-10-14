# TDR Data Infrastructure — Locked Completion Contract v1.0.0

**Owner directive:** 2026-10-14. **Scope status:** LOCKED TARGET / IMPLEMENTATION INCOMPLETE.
**Authority:** This completion contract defines *what done means*, not authorization to modify production or merge. The existing approved [Master Roadmap](TDR_MASTER_ROADMAP_V1.md), [portfolio.plan.json](portfolio.plan.json), [WORK_STATE](../WORK_STATE.md), [Ice gates](../market-track/ROADMAP.md), and [Vehicle DB v3](../vehicle-db/VEHICLE_DB_V3.md) keep their existing independent operational permissions. Where they conflict, stop and obtain the owner's decision. Do not infer a Production GO from this document.

## Non-negotiable outcome

TDR must operate a repeatable, auditable, operator-light monthly Ice market pipeline on a canonical, safe, source-aware Vehicle Master foundation. A production user receives a consistent, access-controlled accepted market release. The next independent **Price Fetcher** and **Spec Filler** can submit representative evidence fixtures end-to-end through governed review, apply, serve and revert, without inventing an alternative writer. They are future components; this contract does not silently commission their full ingestion/crawling engines.

**Project COMPLETE iff EVERY requirement A-01..E-07 is ACCEPTED with independently reviewable evidence and the owner signs final acceptance.** A green CI, a merged PR, successful deploy, screenshot, mock endpoint, passing unit test or agent assertion alone is insufficient. An uncompleted accepted-scope item remains OPEN/BLOCKED; do not rename it post-launch or move it to "follow-up" and claim completion.

## Scope and specific end-user journeys

1. **Ice:** Owner uploads one declared final ZIP plus independently confirmed manifest, explicitly authorizes the monthly import once, then the pipeline verifies, imports, reconciles, reuses historical owner decisions, queues new ambiguities, runs real-data acceptance and switches only a complete accepted release. The operator can explain every unmatched/excluded registration without losing units or silently guessing identity.
2. **Website:** On owner-approved R8, member views read the same accepted Ice period/version with correct tier restrictions, show source and freshness, and can be rolled back without changing canonical data.
3. **Admin:** Owner can review a new Ice model group, link/create/exclude it, preserve scoped registration class decisions (RY1/2/3/10), handle retries/errors and audit decisions.
4. **Vehicle Master:** Existing Supabase master tables remain the only canonical model/trim/price/spec authority; observations and changes pass one governed writer with field-source arbitration and auditable revert.
5. **Next engines:** Separate, mockable Price Fetcher and Spec Filler adapters prove one accepted fixture each traverses observation→validation→identity match→review→apply→readback→revert. Price Fetcher reads OEM pages/pricelists/promotions. Spec Filler provides trim-level technical facts. **Neither is the Ice file reader**. Do not conflate Ice→TDR identity, CN→TH comparable vehicle mapping and TH competitor substitution mapping.

## Requirements (immutable acceptance targets)

The machine-readable IDs, acceptance statements and required evidence are frozen in [data-infra.requirements.json](data-infra.requirements.json). The prose below must agree with the JSON.

| ID | Phase | Requirement | Mandatory acceptance | Evidence required |
|---|---|---|---|---|
| A-01 | Ice integration completion | Ice R7 acceptance | 69 months lossless; latest Ice panels reconcile exactly; segment/body unknown remains visible; redirect cycle-free; wheel/tyre period_from respected. | Read-only production R7 report + workflow run + frozen package/master SHA. |
| A-02 | Ice integration completion | Scoped decision and queue | Every Ice group + registration-type pair is covered or visibly unresolved, including RY1/RY2/RY3/RY10; no silent ALL fallback. | V70 regression plus live class-specific queue readback, 3 known pickup fixtures. |
| A-03 | Ice integration completion | Admin create/link/exclude resilience | Authorized create, link, exclude are idempotent and recoverable; failed partial writes never masquerade as DONE. | DB transaction/compensation test, concurrent/retry tests and audit-log readback. |
| A-04 | Ice integration completion | Powertrain estimate fidelity | Use available Ice reg_est as estimate for range instead of midpoint; preserve min/max, certainty and source; no false exactness. | G63 2026-09 regression 5 not 7.5 + missing-estimate, aggregation, certainty and bounds tests. |
| A-05 | Ice integration completion | Ice PR readiness | Current Ice branch CI passes; roadmap and PR body reflect real production; owner explicitly authorizes merge; merge alone is not R8. | Immutable commit SHA, CI jobs, owner merge approval and reviewed work-state/roadmap diff. |
| B-01 | R8 production serving | Ice production cutover | Production member market serves approved Ice release at its real period/master with no mixed legacy totals. | Production /member/market and API readback, latest period and total reconcile. |
| B-02 | R8 production serving | Entitlements | Free/Pro quotas, scopes and authorization remain effective after cutover; no privileged data leak. | Free/Pro/admin negative and positive E2E tests, authenticated API logs. |
| B-03 | R8 production serving | Reversible cutover | Owner-controlled flag off restores previous supported read path without data mutation; rollback rehearsed. | Flag-off/flag-on smoke reports, deployment SHA, rollback timings/observed output. |
| B-04 | R8 production serving | Consistent website freshness | Any displayed registration total declares source/period; no August legacy and September Ice figures silently mixed. | Route inventory and screenshot/API fixture checks for /member and /member/market. |
| C-01 | Monthly import and identity lifecycle | Authorized package upload | One private-source upload accepts M7-sized or larger package; SHA matches independently owner-confirmed Ice delivery manifest; no write on failed check. | Upload/download exact-byte replay, wrong-hash, missing-signoff, oversize and access-control tests. |
| C-02 | Monthly import and identity lifecycle | Atomic import and audit | New package is staged, validated, committed once, read back against panel counts and totals; retries do not duplicate facts. | Same-package rerun + injection failures, import ledger, panel crosschecks. |
| C-03 | Monthly import and identity lifecycle | Versioned crosswalk carry-forward | Changing master 7.0 to another version preserves immutable historical owner decisions and produces a version-compatible serving snapshot without mismatched master errors. | Synthetic master upgrade 7.0→8.0 with unchanged identities and immutable provenance tests. |
| C-04 | Monthly import and identity lifecycle | Identity delta handling | Renames safely carry approved mapping; splits/merges/class changes create review or explicit evidence, never silent owner approval. | Fixture pack rename, split, merge, redirect cycle, stale target and registration-class collision. |
| C-05 | Monthly import and identity lifecycle | One-upload one-owner-confirm workflow | After one upload + explicit monthly owner approval, import→matcher/redirect→queue→acceptance runs without per-month code edits. | Realistic new-month end-to-end dry-run and manual go/no-go checkpoint. |
| C-06 | Monthly import and identity lifecycle | Release activation and rollback | Current member serving points only at accepted dataset+crosswalk pair; failed jobs cannot expose half-updated release. | Release pointer/feature-gate test, mid-pipeline failure replay, rollback evidence. |
| D-01 | Quality, modules, website operations | Unmapped/Excluded accounting | Isuzu unidentified and other unknown units are preserved in total brand/missingness without guessing a model or pretending excluded means zero. | Historical/monthly accounting and raw-versus-covered report with samples. |
| D-02 | Quality, modules, website operations | RY and matcher replay | RY class-specific decisions and Mercedes/Rolls matcher changes replay safely without overwriting owner locks. | Production-shaped shadow replay diff with no unauthorized approved-row mutation. |
| D-03 | Quality, modules, website operations | Ice panel access audit | Registration province, powertrain, rim, tyre and metadata availability match package access/free-scope and period_from; not-yet-built UI is identified explicitly. | Panel-to-route matrix with API/permission/coverage and missingness checks. |
| D-04 | Quality, modules, website operations | Chinese EV ranking | Clearly scoped and sourced BEV Chinese-brand ranking appears only when data + entitlement allow; otherwise explicit unavailable state. | Golden brand/origin/BEV/filter fixtures and Free/Pro UI smoke. |
| D-05 | Quality, modules, website operations | Website navigation cleanup | Remove obsolete 4-of-6 selector when approved intelligence navigation is delivered without regressions. | Owner-approved design decision, route screenshots and navigation tests. |
| D-06 | Quality, modules, website operations | Catalog attributes completeness | Segment/body status is enriched only from traceable evidence and governed edits; remaining unknown is truthfully counted. | Before/after missingness report, source refs and governed writer readback. |
| D-07 | Quality, modules, website operations | Legacy cleanup and operational docs | Remove superseded one-time upload function only after dependency audit; record actual operational SOP and restore path. | Reference search, deployment report, access/readback and rollback checklist. |
| E-01 | Price Fetcher / Spec Filler integration-ready foundation | Canonical source/authority boundaries | Ice registrations remain separate from Vehicle Master; only governed writer mutates canonical model, trim, price and spec facts. | Authorization tests and prohibited legacy/direct-write negative tests. |
| E-02 | Price Fetcher / Spec Filler integration-ready foundation | Price Fetcher adapter readiness | Official OEM price/trim observation fixture traverses parse→evidence→identity reconcile→review→approved apply→serving. | Five-stage integration fixture, source/observed/effective metadata, missing/ambiguous/no-change tests. |
| E-03 | Price Fetcher / Spec Filler integration-ready foundation | Spec Filler adapter readiness | Spec fixture maps brand/model/generation/variant/trim/field/unit/source to reviewable proposed changes without guessing or overwriting owner-locked values. | Fixture roundtrip and conflict tests, field-specific provenance/coverage, approved serve. |
| E-04 | Price Fetcher / Spec Filler integration-ready foundation | Safe structural changes | Model/brand/trim identity changes have scoped validation, deterministic revisions, idempotent retries, fail-closed partial writes. | Duplicate/concurrent/failure-injection and identity-collision tests. |
| E-05 | Price Fetcher / Spec Filler integration-ready foundation | Auditable revert | Every applied field mutation creates traceable change event; approved changes can revert safely without erasing history. | Apply→serve→revert→serve integration and actor/source audit readback. |
| E-06 | Price Fetcher / Spec Filler integration-ready foundation | Stable read/API contracts | Consumer, TDR Pro and separately authorized Dealership Toolkit share canonical facts through typed entitlement-safe read models. | Negative tenant/scope tests, stable contract fixtures, snapshot consistency. |
| E-07 | Price Fetcher / Spec Filler integration-ready foundation | Parallel engine safety | Price Fetcher, Spec Filler, Ice file reader, CN–TH crosswalk and Thai competitor graph do not share unauthorized write/identity mechanisms. | Source/fact authority table and forbidden-crosswalk/write integration tests. |

## Progress and proof: separated from goals

* **Immutable goal source:** this contract and `data-infra.requirements.json`. Work package sequencing is documented in [TDR_DATA_INFRA_EXECUTION_PLAN.md](TDR_DATA_INFRA_EXECUTION_PLAN.md); it cannot relax the goal registry. Never set "accepted" within the goal registry itself.
* **Mutable evidence ledger:** `docs/portfolio/TDR_DATA_INFRA_ACCEPTANCE_LEDGER.json`; default is OPEN, never use fake PASS. An ACCEPTED requirement MUST identify evidence URI(s), independently verifiable execution context, tested commit SHA (40 hex), and explicit owner acceptance reference. **Owner acceptance and evidence are distinct**.
* **Allowed states:** OPEN, IN_PROGRESS, BLOCKED, EVIDENCED, ACCEPTED. EVIDENCED is not DONE.
* **Phase COMPLETE:** all its IDs ACCEPTED. **Project COMPLETE:** five phases COMPLETE plus separate, explicit signed owner final acceptance event. No auto-accept from CI.
* Every progress report must enumerate OPEN/BLOCKED/EVIDENCED IDs, the specific missing test, evidence and next allowed action; do not equate ticket close with requirement completion.

## Mandatory agent start-of-task handshake

In **EVERY** coding, reviewing, test or planning session touching Ice, Vehicle Master, price, trim, specs, data services or product surfaces:
1. Read `AGENTS.md`; this exact contract; the immutable JSON; acceptance ledger; `docs/WORK_STATE.md`; and the relevant domain gate and Master Roadmap. Read from repository, not chat memory.
2. Report `contract_version`, source commit SHA, target requirement IDs, existing OPEN state, bounded changed paths, execution gate, rollback, tests and current blockers **before** modifying code.
3. If a task cannot map to at least one requirement ID or has a conflicting requirement, STOP and request owner scope decision; do not implicitly weaken targets.
4. After implementing, attach test result, provenance, code SHA and production readback where required to the ledger. No "DONE" until owner acceptance.
5. When the owner changes a goal, propose a *separate* explicit amendment PR with a machine-readable before/after diff, affected tests and owner review. No silent version downgrade, loss of IDs or relaxed acceptance criteria.

## Controls and implementation constraints

* CI validates registry shape, frozen IDs, ledger state/evidence semantics and mandatory pointers from AGENTS/CLAUDE; PR author assertions cannot attest their own review.
* The PR contract gate evaluates changes against the trusted **PR BASE**. Changing the candidate validator does not silently change the trusted checker. Contract/registry amendments are BLOCKED by default pending independently verified owner approval and updated contract version; this is distinct from normal progress ledger updates.
* This repository's `main` branch currently lacks enforced protection as checked 2026-10-14. The owner must enable **required check** `data-infra-contract` + CODEOWNERS review via GitHub Rulesets/Branch Protection for an enforceable merge barrier. Until configured and independently confirmed, a passing workflow is **advisory** against direct pushes/unchecked merges.
* No automatic task dispatch; `portfolio.plan.json` execution remains disabled. Do not run Production Import, R8 cutover, permission changes or schema writes without domain-specific GO.
* Never expose secrets, trust a standalone SHA computed after upload as independent sender attestation, or bypass negative tests/role checks to get green CI.

## Order, scope, and stop conditions

**A → B → C → D → E** is the delivery order, with E design constraints considered from the beginning; parallel purely offline development is allowed only under its own owner-cleared task gate. Scope D improvements must not become a pretext for postponing B's legitimate R8. Nothing here reopens already approved Ice owner mapping without an explicit reason.

**Stop:** checksum/signoff mismatch; master/crosswalk release incompatibility; loss or duplication of registrations; scope/owner identity collision; unauthorized data write; missing rollback; tests fail; missing owner production/merge approval; attempts to override a domain gate.

## Acceptance signature

Owner acceptance must identify this version, accepted requirement ledger commit, supporting evidence, exceptions explicitly authorized by amendment (not by deferral), and final acceptance timestamp. This section is **NOT signed**. No agent may sign for the owner.
