# Upcoming Cars — recovery, design coherence, and admin capability audit (2026-10-12)

**Status:** factual repository audit + Codex handoff, NOT a feature implementation, not schema/deployment approval. Sources read at `main` and `feature/upcoming-cars` on 2026-10-12. Review any new commits before implementation. No source SQL, application, canonical or production data changed by this audit.

## 1. Verified repository state

- Legacy branch: [`feature/upcoming-cars`](https://github.com/smgkikikiki-cloud/TDR/tree/feature/upcoming-cars), head `f2ed3719d4defc86f0ca1ab7450cd3bac5d3d17c` (2026-09-28). It has **two feature commits**: `6e59fe4` (standalone tables/data foundation, Chunk 1) and `f2ed371` (Admin CRUD and update log, Chunk 2). It had **no associated PR** at inspection and was 258 commits behind `main`, with 2 commits ahead and a diverged merge base. Treat as historical *source material*, not a branch to blindly merge/rebase into today's production.
- On `main`, `app/upcoming/page.tsx` **redirects to `/models`**; no public Upcoming P16/P17 implementation is deployed in the inspected code. The old branch has **Admin only** (`/admin/upcoming`, `/admin/upcoming/new`, `/admin/upcoming/[UP-ID]`); code is not in `main`, so do NOT describe the current deployed Admin as supporting these operations.
- The two legacy branches' chunks have source code and smoke/assertion scripts, **not an independently verified current-main integration QA or deployed migration**. No new Upcoming SQL was run here.

## 2. Design coherence — specification exists, finished dedicated mockup does not

**Authoritative later-approved design is documented**, not absent: `docs/MERGE_DECISIONS.md` U1–U6 (owner approval recorded 2026-09-29), `design/PAGES.md` P02/P16/P17/P27, `design/SCHEMA_PLAN.md` §1, `design/DATA_MAP.md` §Upcoming and `design/GRAFT_PLAN.md` row 12. `design/DESIGN.md` documents the system/tokens. `design/reference/components.html` has some shared component references but **no complete dedicated P16/P17 screen mockup, responsive screenshot set or approved final Upcoming page rendering has been verified**. Do not state “no design exists”; note the precise visual/mockup gap. Visual UI must use the current design system and receive its own preview/owner review.

| Concern | Legacy implemented in `feature/upcoming-cars` | Later approved design | Coherence |
| --- | --- | --- | --- |
| Lifecycle classification | `RUMORED` / `CONFIRMED` as one status field | Six `stage` values (`RUMOR`, `REPORTED`, `OEM_TEASED`, `OEM_CONFIRMED`, `LAUNCH_DATE_SET`, `PRE_ORDER`), plus separate `state` ACTIVE/DELAYED/CANCELLED/LAUNCHED and publication `draft`/`published` | **CONFLICT**: different domain model, not just labels |
| Confidence | HIGH/MEDIUM/LOW | LOW/MEDIUM/HIGH/CONFIRMED, with stage-specific restrictions | **CONFLICT** |
| Timing | year + H1/H2 for rumors; quarter/month/day for confirmed | optional window_from/window_to and precision YEAR/HALF/QUARTER/MONTH/DAY; range, display override and sorting | **CONFLICT**; only partial presentation overlap |
| Entity | auto-generated `UP-0001` editorial vehicle_id + name; no canonical references | UUID + public slug, official/working/segment naming, brand_text, optional canonical brand/predecessor/launched model refs; editorial estimates clearly separate | **CONFLICT / missing data**; do not silently reuse `UP-####` as canonical ID |
| Publishing/provenance | no public status, source list, proof requirements, or image licence | published needs >=1 source, controlled source visibility, last verified, stage history, licence-gated image; explicit estimates | **MISSING** |
| Public UX | no P16/P17 pages in branch; main /upcoming redirect | P16 list, filtered stage cards + sort; P17 source-backed detail/timeline + LAUNCHED redirect; tab in /models | **NOT IMPLEMENTED** |
| Admin UX | functional list/form/edit/delete/update log in old branch | P27 admin management aligned to the above publication/source/state schema | **PARTIAL** |

**Interpretation rule:** The later owner-approved U1–U6/P16/P17 design is the repository's documented target. The September 28 lightweight Admin contract is a historical implementation, **not** evidence that all six-stage/publishing rules were revoked. If the owner wants to retain the simplified Rumored/Confirmed model instead, request an explicit scoped design decision before schema/application port. Never covertly substitute one design for the other.

## 3. Exactly what the legacy Admin can and cannot do (branch code only)

| Location/action | Fields, behavior and constraints actually implemented | Not implemented / caution |
| --- | --- | --- |
| `/admin/upcoming` list | Read `upcoming_cars` through server-side `adminDb`; show generated ID, car name, RUMORED/CONFIRMED, confidence, launch timing, updated date; links to create/edit. | No publishing, filters, source/verification status, lifecycle or independent provenance display. **Not present on main**. |
| `/admin/upcoming/new` → `createUpcomingCar` | Form accepts vehicle_name, status, confidence, launch_year, rumor_half OR confirmed_quarter/month/day, description, internal_notes; validates and inserts; generated `UP-####` ID is **read-only** and appears after create. | No brand, canonical link, source citation, image/licence, stage history, state, window range, draft/published, review/publish action. |
| `/admin/upcoming/[id]` → `updateUpcomingCar` | Edits exactly the create fields on one existing editorial row. Switch RUMORED ↔ CONFIRMED clears the inactive set of timing fields on save; month derives quarter for display; server-side guards prevent invalid month/day. | No partial update of publish/source lifecycle. No canonical model editing. |
| `/admin/upcoming/[id]` → `deleteUpcomingCar` | Red **delete whole car** button with browser `confirm` prompt. Server action DELETEs `upcoming_cars` row by `vehicle_id`; SQL `upcoming_car_updates` FK has `ON DELETE CASCADE`: all its update logs are permanently deleted as well. | **Hard delete**, not soft-archive; no audited undo/retention, no per-update delete. Require explicit owner review before transplanting destructive semantics into current Admin. |
| `/admin/upcoming/[id]` → `addUpcomingCarUpdate` | Add update_date + nonempty message as a new append-only `upcoming_car_updates` row; display dated log. | **Cannot edit/delete a single log entry**; no update source URL, per-update stage transition, author/provenance verification. |
| Permissions/access | Admin layout checks `isAdmin`; each server mutation invokes `dbForAdmin` and enforces `isAdmin`; uses service-role server client. SQL RLS enabled; no anon/auth table privileges. | Legacy role model and schema need re-audit against current `main` auth and Supabase. No proof here of live setup/deployment. |

Legacy SQL table names are `upcoming_cars` and `upcoming_car_updates` (`supabase/migration_v52_upcoming_cars.sql` **only on old branch**). Later approved design names `upcoming_vehicles` (and its richer contract). They are **different schemas**, not a safe column-for-column rename. No Update Log CRUD beyond creation was requested/implemented in the old branch.

## 4. Migration and platform blocker: previously reserved numbers are occupied

- The legacy branch has `supabase/migration_v52_upcoming_cars.sql`, but `main` already has `migration_v52_vehicle_specs_import_kind.sql`. **Never replay/cherry-pick the old migration number**.
- `docs/MERGE_DECISIONS.md`, `design/SCHEMA_PLAN.md` and `design/GRAFT_PLAN.md` still reserve `v57` for Upcoming and `v58` for Analysis, **historically**. They conflict with newer deployed/current repository inventory: `main` holds `migration_v57_vehicle_master_tables.sql`, `migration_v58_vehicle_serving_parity.sql`, and further migrations through **v65** at inspection; `docs/WORK_STATE.md` explicitly documents Vehicle Master Phase 0 migrations v57–v61 as LIVE.
- This is a **migration-authority drift requiring a deliberate docs/schema-number reconciliation**. Do not rename already-applied migrations, overwrite numbers, create dummy migrations, or assert an unused number is approved without rechecking production's migration ledger / branch collisions. A future feature migration needs a fresh uniquely authorized number and current-platform schema/security review. No SQL was deployed or reserved in this audit.

## 5. Recovery sequence for Codex — one reviewed chunk at a time

**R0 — repository recovery/design contract (next safe chunk, no migration):**
1. Start from **latest `main`**, in a **new scoped Codex branch and Draft PR**; retain `feature/upcoming-cars` read-only as reference. Read `AGENTS.md`, `docs/WORK_STATE.md`, the Master Roadmap, `docs/MERGE_DECISIONS.md`, P16/P17/P27/SCHEMA_PLAN, and this audit.
2. Produce a field-by-field **design-to-schema-to-admin action** mapping for later-approved U1–U6, including publication state, public data isolation, source/rights checks, source visibility, update-log retention, canonical-link boundaries, dates/stage/confidence constraints, and migration authority. Identify reusable code from old branch without applying old SQL.
3. Build an **offline-only visual preview/design handoff** for P16/P17/Admin and test plan against present design tokens/components; record where no dedicated mockup exists. No sample data as purported live evidence.
4. Verify current migration inventory and authorization, propose a collision-free scheme; **do not execute or write any migration** in R0. Escalate whether the owner intends the later full U1–U6 contract or a deliberate simplified replacement if unresolved, rather than inventing policy.
5. Run relevant static/design checks; push R0 to Draft PR and **STOP for owner/QA**.

**R1 — Admin + storage implementation, only after approved contract and migration scope:** port/adapt reusable CRUD, authorized non-destructive update history, source evidence and publishing validation. Preserve Admin permissions and editorial/canonical boundaries; schema migration requires separate approval, no deployment by inference.

**R2 — public P16/P17:** source-backed listing and detail using public-only DTOs; publish filtering and image licensing; LAUNCHED redirects and correct unknown/estimated labeling. Preview at current design breakpoints, no fake public data.

**R3 — /models tab + navigation, data/QA integration:** remove old redirect only when P16 works; no extra top-level menu; negative tests for unpublished/internal notes, canonical identity, permissions, source visibility and editorial estimate leakage; final owner QA, CI and separate merge/deploy gate.

**Acceptance of R0 is NOT approval of R1–R3.** No production schema writes, Supabase data reads/writes, Vehicle Master mutations, autonomous merge, deployment or implicit application of the stale `feature/upcoming-cars` branch.

## 6. Inspection boundaries

This audit is based on repository code and documents, not a browser/UI test of a running deployment, live Supabase database inspection, production migration query, or owner sign-off of a new mockup. `main` has no inspected functional Upcoming feature; both early chunks exist as **legacy branch code only**. No visual page design was invented here. If the source of truth changes, update this dated note rather than rewriting prior owner approvals.
