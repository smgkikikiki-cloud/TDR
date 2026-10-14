# TDR Master Development Roadmap v1.0

**Owner decision:** APPROVED 2026-10-11, after review of the full portfolio roadmap (PR #204).  
**Scope of approval:** overall product/system architecture, workstream responsibilities, engineering sequencing and dependencies, release order, evidence-first engine discipline, proposed governance model as the direction of development.  
**Repository adoption:** owner approved on 2026-10-11; initial merge tracked in [PR #204](https://github.com/smgkikikiki-cloud/TDR/pull/204). Consult GitHub for current merge state. Agents only receive this contract when the file exists in their working branch and their bootstrap rules reference it.
**Execution:** NOT ENABLED. Existing PRs, Market Track, migrations, releases, billing, production and autonomous runners still require their own gates and any separately required owner authorization.

This is the concise central entrypoint for the approved development **roadmap**, not an assertion that all attached formulas, external-data licensing and data quality are validated. No hypothetical event or historical coverage becomes real because this roadmap is approved.

## 1. Product system

One shared TDR data foundation and several evidence-based analytic capabilities serving **two distinct customer products**:

- **Original TDR website and Website Pro:** public/consumer catalog, comparable vehicle facts, registration/market comparison and research (Layers 1–2). Preserve existing member entitlement and actual deployed payment obligations; no account-specific dealership interpretation silently moved into Website Pro.
- **Standalone Dealership Toolkit:** organization/team licensed SaaS providing Layer 3 account-scoped interpretation and prioritization of the same verified facts, with represented brands, authorized region and optional TDR-verified My Branch; no customer-entered inventory, stock, leads, deals, CRM/DMS, dealer sales uploads, or assumed dealer unit sales.

**Layer semantics:** L1 raw evidence and provenance → L2 canonical/queryable, comparable facts → L3 account-specific changes + reason/evidence + decision context. Layer 4 what-if simulations are not part of this roadmap.

## 2. Approved workstream boundaries

| Lane | System and responsibility | Boundary |
| --- | --- | --- |
| I-1 | **PR #200 Ice→TDR Identity Resolution**: reviewed `EQUIVALENT/PART_OF/COMPOSED_OF` relationships between existing Ice groups and canonical models | Crosswalk association is not a new Model, not a competitor graph, and does not allocate units without defensible relation grain |
| I-2 | **PR #201 Identity Bootstrap**: source-unmatched candidate new identity and `DISCOVERED` proposals | Does not mark current retail, auto-create in master, or bypass writer permissions |
| I-3 | **PR #203 Catalog Maintainer**: Queue A verify CURRENT retail lineups; Queue B enrich missing applicable specs for eligible current trims | Not the historical MSRP/promotion archive; no admin lock bypass or silent structural trim changes |
| W | **Original website / Ice UI graft**: typed read contracts, Layer 1–2 consumer pages, accepted UX design and secure serving | Ice R6/R7/R8 cutover gates stay independent; no fallback to unauthorized legacy dataset |
| P-1 | **Thai pricing evidence/events and PDI**: long-run observation/effective-time source ledger, verified mainstream cash offers, frozen eligible universes and discount measures | ECO sticker != MSRP; missing offer != zero; historical 2021 completeness not assumed |
| P-2 | **CTPDI**: admin-reviewed/approved/locked CN–TH comparable vehicle pairs, source/FX/price-basis methodology and comparable gap | Does not measure dealer margin, assured future price cuts or substitute relationships |
| S | **Dealer Geography + Network Watch**: verified Site/Franchise/Operator Master, effective-dated changes, mapped registrations and spatial accessibility | Province registrations != branch sales; site absence != closure; one shared Spatial workspace with two local modes |
| L3 | **Dealership Toolkit**: Competitive Pressure and its five-section Model Analysis, org/team controls, account-scoped evidence and reports; later spatial products | Pressure index and prediction cannot be fabricated; customer report snapshots must be authorized and reproducible |
| X | **Vehicle Master Phase 1 Governed Writer** (*enabler, not a sellable product*): source observations, authority-safe reconciliation, review, apply/change log/revert | Required before #201/#203 production data mutations; not required for pure offline analysis or design |

**Three graph types must never be collapsed:** Ice group↔TDR identity, CN↔TH comparable-price crosswalk, and TH reference↔TH competitor substitution. **PDI eligibility is NOT a competitor-universe filter.**

## 3. Approved Layer 3 release progression

1. **V1 Competitive Pressure** ships first, focused on observed rival competitive positioning, defensible substitution, verified price movement and qualified regional *registration context*. The Model Analysis interface has the existing owner-locked five sections: (1) Pressure Overview, (2) Competitive Landscape, (3) Pressure Investigation, (4) Regional Market Context, (5) Events & Outlook. Pressure scores are *not* published as arbitrary 0–100 until calibrated/approved. Model-level, not fake trim-level behavioral prediction.
2. **V1.5 Dealer Geography** follows, inside the single map-first Spatial workspace, drawing on verified site/franchise/operator master. Near-border neutral competitor locations can appear, but out-of-region market figures may not. Optional network-modeled accessibility is not sales attribution.
3. **V2 Competitive Network Watch** follows progressively in the same Spatial workspace, verified opening/closure/franchise/operator changes, distinct detection and effective dates and branch-relevant evidence; Market Watch remains a notification inbox, not a duplicate analytical product.

These labels are **sequence**, not fixed calendar dates. The site master, event collection, spatial UX and organization infrastructure **develop in parallel with V1**, rather than waiting for V1 to ship. The owner approved progressive follow-through on **all three**.

## 4. Portfolio milestones and dependencies

| Gate | Work / deliverable | Exit proof and constraints |
| --- | --- | --- |
| **G0 — Roadmap adoption and authority reconciliation** | **Roadmap content approved 2026-10-11**; owner review record; reconcile C01–C04 independently | Portfolio direction locked; **operational gate not cleared** until R6 state, migration IDs and billing authority are reconciled where relevant. CTPDI formula grain remains a published-metric blocker, not a blocker for unrelated offline work |
| **G1 — Offline reliability** | correct and independently QA #203; review/calibrate #200/#201; define typed Ice/Vehicle/Toolkit adapters; pure substitution cases | scoped owner go per task, golden fixtures, deterministic replay, focused tests and GitHub CI verified, no scope breach |
| **G2 — Evidence foundation** | price history and offers, source completeness and frozen observations back to 2564 where actually available; initial Dealer Master, network event evidence, manual CN–TH crosswalk; writer interface planning | observed data, source evidence/rights, effective dates, missingness, versioning and complete/partial coverage. **CP-00 audit observed only 273/1,431 current trims with any LIST_PRICE**, all LIST_PRICE observed Sep 2026, so national pricing history is not ready |
| **G3 — Measurable engines and safe integration** | PDI, CTPDI, market/spatial and pressure components, each under versioned methodology and coverage; Ice R6→R7→R8 only with original independent gates | measurement construct, valid grain, approved formula, adversarial tests, independent review and data-source/permission checks |
| **G4 — Customer Layer 3 first slice** | org/team access → reference model/rivals → evidence-backed Model Analysis five sections → authorized region context → immutable 1-page or 5-page A4-landscape report | truthful missing data, no fabricated scores/forecasts, strict cross-account and cross-region negative tests |
| **G5 — Controlled operations** | bounded idempotent updater/monitor queue and audits; optional Claude Code implementer ↔ Codex independent QA via deterministic Enforcer | task packet by exact branch SHA and approved contract version, least-privilege scopes, capped repair loops, owner-held merge/production gate |

**Parallelization rule:** a blocker applies to its **dependent capability**, not to unrelated pure functions, UI design or read-only audits. G4 UX design can start alongside G1–G3, but cannot claim a live populated output until its sources are ready. Stage names describe delivery maturity; they are **not a single forced serial execution queue**.

### W — Upcoming Cars recovery and design-alignment status (2026-10-12)

**Repository snapshot / status, not a new workstream or owner design override:** Upcoming Cars is part of the original Website W lane (`design/GRAFT_PLAN.md` row 12, `design/PAGES.md` P16–P17/P27). The old `feature/upcoming-cars` branch, head `f2ed3719d4defc86f0ca1ab7450cd3bac5d3d17c` (2026-09-28), contains standalone editorial tables and Admin create/edit/hard-delete + append-only update history (legacy Chunks 1–2). **It is unmerged, had no PR at inspection, and is 258 commits behind `main`.** On `main`, `/upcoming` remains a redirect to `/models`; no public P16/P17 is implemented.

**Design audit:** The owner-approved later U1–U6/P16/P17 design **does exist as text/schema requirements** (six stage values, four confidence levels, separate lifecycle/publication state, source-backed publishing, launch windows, image license, public list/detail and canonical links). **No dedicated complete Upcoming screen mockup/approved responsive previews were verified**, so visual fidelity remains an explicit preview/owner-review task. The earlier legacy Admin form instead has Rumored/Confirmed, three confidence levels, simpler dates and no publishing/source controls. These must not be mistaken for a coherent implementation of the later design. Legacy delete removes the whole car and cascades all update logs; individual log entries cannot be edited/deleted.

**Migration blocker:** The old branch's `migration_v52_upcoming_cars.sql` conflicts with `main` v52; design-doc reservations `v57` Upcoming and `v58` Analysis have been superseded in practice by existing Vehicle Master migrations v57/v58 (and repository migrations run through at least v65). **No old SQL or legacy branch merge is authorized.** Verify deployed migration ledger/numbering and current security/data contract before proposing a new, separately reviewed editorial migration.

**Next Codex chunk (R0 ONLY):** recover from **latest `main` on a fresh scoped branch/Draft PR**, use old branch strictly as reference, map P16/P17/P27/U1–U6 fields to permitted Admin operations and public-only DTOs, audit the migration slot and missing visual preview, prepare deterministic offline tests and a preview/contract for owner QA. **No schema application, canonical writes, production access, public route activation or R1–R3 implementation in R0.** Follow the detailed [Upcoming Cars recovery/design/Admin audit](UPCOMING_CARS_RECOVERY_AUDIT_2026-10-12.md). Any owner choice to replace the later full design with the old simplified contract requires a separately explicit decision. This dated note does not alter the owner-approved v1.0 product/release architecture.


## 5. Approved engine validity doctrine — not blanket formula approval

Each engine must pass measurement gates M0–M5:
**M0 construct**; **M1 source sufficiency**; **M2 identity/grain/unit**; **M3 versioned deterministic formula/rule**; **M4 falsification/independent comparison**; **M5 commercially truthful interpretation/coverage.**

At each decision point:
- source facts, calculated evidence and business interpretations must be separately represented;
- `UNKNOWN ≠ VERIFIED_ZERO ≠ NOT_APPLICABLE ≠ CONFLICT`; timestamp of observation differs from effective date;
- source/denominator/cohort/methodology and identity-link versions are inspectable and reports reproducible;
- no unsupported causal sales loss, no provincial branch-sales inference, no guessed 90D forecasts, no high CTPDI implying margin or guaranteed discount;
- target output can explicitly be `NOT_SCORABLE` even when UX has a visual slot.

The method direction and falsification discipline are part of **approved roadmap direction**. Numeric PDI aggregation, CTPDI pair-vs-model headline grain, PDI Japan admission implementation, score weights/bands, dataset license, commercial price/seat terms and statistical validation results **remain unresolved gates exactly as written in their source review docs**. This approval is not a silent selection among conflicting candidate equations.

Detailed source/review documents:
- [Owner review and decision history](OWNER_REVIEW.md)
- [Domain boundaries and workstreams](DOMAIN_BOUNDARIES.md)
- [Evidence + contradiction register](G0_RECONCILIATION.md)
- [Engine validity and dependency tests](ENGINE_VALIDITY_AND_DEPENDENCIES.md)
- [Competitive Pressure method review](COMPETITIVE_PRESSURE_METHODOLOGY_REVIEW.md)
- [PDI/CTPDI candidate-method review](PRICING_ENGINES_METHODOLOGY_REVIEW.md)
- [Spatial/Network candidate-method review](SPATIAL_NETWORK_METHODOLOGY_REVIEW.md)
- [Actual CP-00 read-only source audit](CP00_SOURCE_COVERAGE_AUDIT_2026-10-11.md)
- [Non-executable machine plan](portfolio.plan.json)

## 6. Execution governance — authoritative plan, no automatic execution

**Authority hierarchy:** `AGENTS.md` and workstream-specific owner-locked repository contracts / adopted decisions continue to govern current code and its domain; this roadmap coordinates the portfolio **without overriding those rules**. On conflict, do not guess or take latest edit as implicit authorization. Escalate the **named specific issue**, not the entire portfolio.

**Planning approved:** the team/agents should use this roadmap as *the* unified source for what is being built, in what order, and which acceptance gates apply.

**Not yet activated:**
- autonomously merge future PRs, bypass branch review/CI, activate a runner or change GitHub branch protection without a separately reviewed implementation;
- grant a Task Packet or permission to run the Night Shift;
- run paid AI or HTTP research, R6/R7/R8, canonical data writers, schema changes, migrations, billing changes or deployments;
- implicitly approve open draft PR #200/#201/#203 or their separate correction QA gates.

**Enforcement implementation after owner go:** add roadmap links to both `AGENTS.md` and `CLAUDE.md`; enforce `roadmap_version`, pinned source SHA, path allowlist, domain gate, offline/production boundaries and reviewer tests. Prompt loading alone is not proof; CI/Enforcer adoption and actual required-branch-check configuration must be separately verified. `portfolio.plan.json` stays `execution.enabled=false`, `task_queue=[]` until separately enabled.

**Change control:** edits to **product boundaries, release order, layer split or measurement doctrine** create v1.1+ and require new owner review; factual evidence updates and execution status can append dated observations without rewriting v1.0 design approval. No developer/AI may unilaterally reinterpret this approval as permission to alter a previously frozen domain contract.
