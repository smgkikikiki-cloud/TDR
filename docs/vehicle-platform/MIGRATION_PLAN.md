# Migration Plan

This is the high-level sequence for converging `main` toward the target architecture in
`MASTER_ARCHITECTURE.md`, while preserving every rule in `INVARIANTS.md`. **Only Phase 0 is
authorized and implemented by this pass.** Phases 1–7 are described here at the level of intent
and acceptance criteria only, precisely so a future agent does not need to guess the sequence —
implementing any of them is explicitly out of scope until a separate, later task authorizes it.

## Relationship to the existing `docs/consolidation/MASTERPLAN.md` (Phase A–J)

This repository already contains a detailed, previously-approved migration plan:
`automotive/vehicle_master/docs/consolidation/MASTERPLAN.md` ("Revision 2 — Approved
architecture, 9 September 2026", Thai-language), with its own **Phase A–J** sequence covering
the consolidation of a second repository (`vehicle-market-master`) into this one. Per
`REPOSITORY_CUTOVER.md`, that consolidation's structural steps (Phase A "freeze/baseline" and
Phase B "bring the engine into TDR") are complete, and Phase C ("canonical write pipeline") is
partially live in shadow mode (`PHASE_C_WRITE_PIPELINE.md`).

**The Phase 0–7 sequence below is a different, complementary numbering.** It does not restart or
supersede Phase A–J. Where they overlap conceptually, this document says so explicitly. A future
agent must not conflate "Phase 1" in this document with "Phase A" or any letter phase in the
Masterplan — always name the source document when referring to a phase number.

| This plan | Masterplan (A–J) relationship |
|---|---|
| Phase 0 — architecture contract and parity foundation | Roughly parallel to Masterplan Phase A's baseline/documentation intent, but scoped specifically to the five-plane target and Phase 0–7 sequence; does not repeat Masterplan Phase A's TDR-schema inventory work, which is already done. |
| Phase 1 — canonical identity registry / external identity abstraction | Overlaps with unresolved parts of Masterplan §16 ("Canonical IDs") and the Mechanism A/B crosswalk duplication documented in `CURRENT_STATE.md` §10. Not the same as any single lettered phase. |
| Phase 2 — canonical DLT v2 shadow pipeline | New work; the Masterplan's Phase-A/§7 registration architecture description informs it but does not implement a "v2" pipeline itself. |
| Phase 3 — registration analytics read cutover | Related to, but narrower than, Masterplan Phase D ("entitlement boundary") + §19 ("Registration Serving Model") — this plan's Phase 3 is specifically about retiring `CURRENT_STATE.md`'s duplicate-path item 4 (legacy dashboard views bypassing the crosswalk), which Masterplan §19/REGISTRATION_MARKET_CONTRACT.md already flags as a "Transition rule" to resolve later. |
| Phase 4 — generic source observation/resolution infrastructure, incl. ECO convergence | New work; the Masterplan's Phase-C/ECO description does not by itself unify ECO and DLT ingestion — masterplan explicitly forbids that unification without a dedicated decision (§25.10). |
| Phase 5 — canonical command/write-path consolidation | Overlaps with Masterplan Phase C/H intent (retire duplicate TDR/Streamlit vehicle editors once the canonical write pipeline is proven) and with `CURRENT_STATE.md` §11 item 3 (`pages/7_Prices.py` bypassing `CanonicalWritePipeline`). |
| Phase 6 — Variant/Configuration, MarketTrim, DLT-detail semantic consolidation | Corresponds to Masterplan §20 ("Trim-Level Market Analytics") and §8 ("DLT Trim Ledger") intent, plus the `MASTER_ARCHITECTURE.md` `Variant → Configuration` rename. |
| Phase 7 — legacy decommissioning | Corresponds to Masterplan Phase J ("Archive Old Repo") for the repository-consolidation angle, plus retiring whichever side of each `CURRENT_STATE.md` §11 duplicate pair loses the reconciliation in Phases 1–6. |

## Phase 0 — Architecture contract and parity foundation *(this pass)*

**Goal**: make the current system's actual behavior legible and protected before any later
phase is allowed to change it. No architecture change. No data semantics change.

Deliverables (this change):
- `docs/vehicle-platform/{CURRENT_STATE.md, MASTER_ARCHITECTURE.md, INVARIANTS.md,
  MIGRATION_PLAN.md, status/CURRENT.md, BASELINE.md}`.
- One narrowly-scoped regression test closing a confirmed gap: `release_enriched.enrich_release`
  (the payload actually published in production) had no dedicated determinism/shape test —
  only the base `ReleaseBuilder` output did. Added
  `test_enriched_release_identity_is_stable_and_covers_lifecycle_and_history` in
  `automotive/vehicle_master/tests/test_tdr_bridge.py`.

Explicitly not done in Phase 0: any of the non-goals listed in the task brief (no UI change, no
Variant rename, no canonical ID change, no registration migration, no `registration_fact_v2`,
no removal of legacy UUIDs/aliases/trim ledger, no ECO/DLT unification, no serving-contract
change, no release-activation change, no destructive migration).

**Exit criteria** (must all hold before Phase 1 may begin): `CURRENT_STATE.md` is confirmed
accurate against `main` (it is, as of this pass); `INVARIANTS.md` rules are each either
Enforced-and-cited or explicitly flagged Policy-only; the full Python test suite and `npm run
check` pass (see `BASELINE.md`); no production behavior has changed (confirmed — this pass adds
only documentation and one test file).

## Phase 1 — Canonical identity registry / external identity abstraction

**Problem it solves**: `CURRENT_STATE.md` §10 documents two independent, unsynchronized
legacy-UUID→canonical crosswalks (Mechanism A, rebuilt per-release from name/alias matching;
Mechanism B, `canonical_object_map`, durable and human-verified). Neither is aware of the other.

**Intent**: introduce one authoritative external-identity registry that both the release-build
crosswalk and the canonical-write shadow can read from and write to, without changing what
either currently does operationally. This is explicitly an *abstraction* step — it does not
change which crosswalk is authoritative for which consumer yet (that is a Phase-1 acceptance
question to resolve with evidence, not assumed up front).

**Must preserve**: Invariant 5 (no ID recycling), Invariant 6 (legacy UUIDs stay load-bearing
until explicitly migrated), Invariant 8 (auditable human verification) — a name/slug match
must never silently become `verified`.

**Acceptance criteria** (sketch, to be refined when this phase is authorized): every legacy
model/brand UUID currently resolved by Mechanism A also resolves consistently (or is flagged as
disagreeing) against Mechanism B; a shadow report can enumerate every case where A and B would
answer differently, with zero silent divergence.

## Phase 2 — Canonical DLT v2 shadow pipeline

**Intent**: build a next-generation DLT ingestion/resolution pipeline (informed by the
Source/Observation/Identity plane split in `MASTER_ARCHITECTURE.md`) that runs **alongside**
the current `vehreg/ingest.py`/`vehreg/dlt.py` pipeline, writing to a clearly-separate output,
reconciled against it, before anything reads from the new pipeline.

**Must preserve**: Invariant 2 (exact reconciliation), Invariant 4 (MIXED semantics), Invariant
15 (source grain vs. reporting grain), and the RY1/RY3 disambiguation behavior documented in
`CURRENT_STATE.md` §5 — the brief is explicit that `registration_fact_v2` must not be introduced
in Phase 0, and this phase is exactly where that decision gets made deliberately, with a shadow
period, not before.

**Acceptance criteria**: v2 pipeline's per-model, per-period totals reconcile exactly against
the current pipeline's totals for every month in the fixture/production history before any
consumer is switched.

## Phase 3 — Registration analytics read cutover

**Problem it solves**: `CURRENT_STATE.md` §11 item 4 — the legacy dashboard views
(`/api/report/registration`) read `registrations.model_id` joined straight to legacy
`public.models`, with no canonical crosswalk hop, while the newer `/api/report/market` path
performs the full crosswalk. `docs/REGISTRATION_MARKET_CONTRACT.md` already names this as a
known transition to complete later ("Transition rule").

**Must preserve**: Invariant 11 (existing consumers stay operational) — the legacy
`/api/report/registration` endpoint and its views may only be retired after the new contract has
demonstrated parity, per the Masterplan's own instruction ("Only after the new paid UI and Admin
Bench pass parity checks should the legacy Streamlit presentation layer and static dashboard
views be considered for retirement").

**Acceptance criteria**: side-by-side parity report between legacy and canonical-crosswalk
registration reads for every currently-served dimension/window before cutover; entitlement
boundary (`has_market_access`) verified against the live Supabase project, not only migration
files.

## Phase 4 — Generic source observation/resolution infrastructure, including ECO convergence

**Intent**: implement the shared Source Plane / Observation Plane abstraction from
`MASTER_ARCHITECTURE.md` — a common vocabulary and code path for "a source claims X," whether
the source is ECO, DLT, or a future feed — and migrate ECO ingestion onto it. This is the phase
where `CURRENT_STATE.md`'s observation that ECO and DLT independently implement similar-but-not-
identical raw→normalize→review concepts gets resolved.

**Must preserve**: Invariant 7 (DLT never autonomously creates MarketTrim identity — this must
remain true of whatever shared infrastructure replaces the current DLT path), Invariant 8
(human-only trim creation for ECO), and every ECO lifecycle transition currently tested in
`tests/test_ecosticker_*.py`.

**Acceptance criteria**: ECO ingestion running on the shared infrastructure produces identical
review-queue/candidate output to the current `vehreg/ecosticker_ingest.py` for the existing
golden snapshot (the committed 1,640-record ECO snapshot referenced in
`tests/test_ecosticker_phase2.py`) before cutover.

## Phase 5 — Canonical command/write-path consolidation

**Problem it solves**: `CURRENT_STATE.md` §11 item 3 — `pages/7_Prices.py` writes to
`vehreg/data` directly through `vehreg/product.py`, bypassing `CanonicalWritePipeline`'s
revision/outbox/audit trail entirely, while every other write path goes through it.

**Must preserve**: Invariant 8 (auditability) and Invariant 9 (Git review) — consolidating onto
one write path must not weaken either; per the Masterplan's own cutover gate
(`PHASE_C_WRITE_PIPELINE.md` "Cutover gate to retire duplicate writes"), the legacy editor may
only be disabled once canonical create/update/withdraw is proven end-to-end, crosswalks are
verified for the objects being edited, and rollback is tested.

**Acceptance criteria**: `pages/7_Prices.py` (or its replacement) produces the same
`revisions.jsonl`/`outbox.jsonl`/`shadow/*.json` audit trail as every other canonical write, with
no loss of existing Streamlit-admin functionality, verified end-to-end before the direct
`vehreg/product.py` write path is removed.

## Phase 6 — Variant/Configuration, MarketTrim, and DLT-detail semantic consolidation

**Intent**: the `Variant → Configuration` rename described in `MASTER_ARCHITECTURE.md`, plus
tightening how DLT Trim Ledger evidence attaches to MarketTrim (Masterplan §20's "three must
stay separate" — Market Model Ranking from canonical registration facts, Chinese EV Trim Ranking
from the DLT Trim Ledger, Retail Trim Catalog from MarketTrim).

**Must preserve**: Invariant 7 absolutely — this phase must not become the phase where DLT
detail starts creating MarketTrim identity. A rename of `Variant` to `Configuration` must not
change `RESOLUTION_CHAIN` semantics or let `MarketTrim` re-enter it.

**Acceptance criteria**: every existing Variant-keyed test and data file has an unambiguous,
mechanical migration to the renamed concept; DLT Trim Ledger reconciliation (Invariant 2) still
passes at the same scope granularity (source/period/registration class/province/model) named in
the Masterplan.

## Phase 7 — Legacy decommissioning

**Intent**: retire whichever side of each duplicate pair in `CURRENT_STATE.md` §11 did not
become authoritative through Phases 1–6, and complete Masterplan Phase J (archive
`vehicle-market-master`) if not already done.

**Must preserve**: Invariant 13 (no destructive migration without a verified replacement and
rollback path already proven) above all else — this is explicitly the last phase for a reason.

**Acceptance criteria**: every retirement gate listed in
`docs/consolidation/REPOSITORY_CUTOVER.md` is green, plus a demonstrated rollback of at least
one retired path back to its predecessor in a non-production environment before deletion.

## What Phase 0 authorizes for the future — and what it does not

Writing this plan down does not authorize starting Phase 1. Each phase above must be proposed,
scoped, and explicitly authorized as its own task before implementation begins, per the task
brief's own instruction: "You are implementing only the first foundation phase. You are not
authorized to begin the later architectural migration yet." `status/CURRENT.md` records exactly
where the migration stands and what the next approved step is — keep it current.
