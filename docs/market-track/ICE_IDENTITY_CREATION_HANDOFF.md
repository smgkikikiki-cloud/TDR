# Ice identity creation — handoff to Codex (2026-10-14)

Owner decision: park this in Claude's session; **Codex builds and runs the new-identity system.** Owner chose option 2:
the new models appear in the public catalogue as well as in market analysis.

## What "done" means (the only acceptance test)
The 114 owner-decided new models exist as rows in production `vehicle_models` **and** their Ice registrations show on the
member market page (`/member/market`, model grain). Anything short of that is not done. Offline tests are a means, not the
result: do not add features or re-test once these two facts are true on a Vercel Preview built from the branch.

## Facts already established (do not re-derive)
- Production project: Supabase `ltvwzkffmpudpjfjomrg`. Applied through **v64**; v65 and v66 exist in the repo and are NOT applied.
  v67 (`ice_model_crosswalk_scoped`) **is applied** and loaded: APPROVED 448 / PENDING 137 / EXCLUDED 63.
- Plan: `data/packages/ice_crosswalk_r6_offline_recovery_M7.0/qa/materialization_plan_114.csv` — 114 CREATE rows
  (38 from the original owner CREATE decisions = 3,112 units; 76 from the owner overlay = 94,913 units; 98,025 units total).
  109 have `NO_EXACT_COLLISION_IN_SNAPSHOT`; **5 are `OWNER_DISTINCT_ALIAS_COLLISION`** and need the owner per row.
- The old create path (admin "+ สร้างรถใหม่", `UPSERT_MODEL_BUNDLE`, `enqueueCanonicalInputBatch`) is **closed by v60**. Do not revive it.
- Vehicle DB v3: Supabase Vehicle Master is the authority; structural changes are proposals approved by a human, reversible via
  `canonical_write_revisions`. v66 has `vm_inbox` (kind `STRUCTURE`) but only a **price** writer (`vm_apply_price_changes`).
  There is no model-create writer yet — that is the work.
- New models have no trims, prices or specs. Their catalogue pages must degrade cleanly (no broken page) — check `/models/[slug]`.
- Loader for decisions: `scripts/ice-scoped-crosswalk-load.ts` (dry-run by default). After a model is created, its PENDING scoped
  row moves to APPROVED (the trigger allows only PENDING→APPROVED).

## Work, in order
1. Model-create writer (SQL RPC, idempotent, batch id, writes a `canonical_write_revisions` row, reversible). Migration **v68**
   (v65/v66 unapplied — state in the PR which of them must be applied first).
2. Inbox card per model (or per batch) with evidence; owner approves in the admin UI. No auto-apply.
3. Apply the 109 clean models; hold the 5 collisions for the owner.
4. Flip the matching PENDING scoped rows to APPROVED; verify on Preview.

## Separate, small, do first: Mercedes etc. (47,891 units)
`DETERMINISTIC_EXACT_EXISTING_LINK`: 28 scope rows (Mercedes C/GLC/GLA/E/CLS/A/GLE/S/Vito/GLS/G/V/Sprinter, Rolls-Royce Ghost)
whose target models already exist. Root cause fixed in `vehreg/ice_crosswalk.py::normalize_brand` (punctuation/spacing
ignored; commit `f5047179`). They still need the owner's approval before loading as APPROVED — do not self-approve.

## Rules
No production write, migration apply, deploy, merge or flag change without the owner's explicit "go" in chat. The owner is a
beginner coder: show him the exact SQL/actions, not code. One PR (#246 carries everything so far); no more Draft PRs.
