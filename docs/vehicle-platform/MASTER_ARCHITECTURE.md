# Master Architecture — Target State

**Status: target architecture. Nothing on this page describes `main` as it exists today.**
For what actually exists right now, read `CURRENT_STATE.md`. This page exists so future work
converges toward one destination instead of every phase inventing its own shape. Phase 0 does
not implement any of this — it only writes it down and preserves the option to get there.

## Why a target architecture, separate from the current one

TDR grew two source domains — vehicle *product* facts (ECO stickers, OEM specs, pricing) and
vehicle *registration* facts (Thai DLT data) — plus a consolidation of a second repository
(`vehicle-market-master`) into this one. Each grew its own ingestion, matching, and identity
logic before any of them had to agree with the others. The result today is workable and
well-tested in isolation, but it contains real duplication: two independent legacy-UUID→
canonical crosswalks, two serving-projection mechanisms, and identity resolution logic that
differs slightly between the Python engine and the Supabase/Next.js layer. `CURRENT_STATE.md`
documents this duplication precisely; this page describes the shape that duplication should
eventually converge to, so that convergence is deliberate rather than accidental.

## The five conceptual planes

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. SOURCE PLANE                                                     │
│    Raw immutable external-source snapshots and metadata.            │
│    ECO Sticker HTML/API pulls, DLT CSV/workbook exports, OEM spec    │
│    pages, price-source pages — as fetched, unmodified, hashed.       │
└───────────────────────────────┬───────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 2. OBSERVATION PLANE                                                 │
│    Normalized claims emitted by those sources.                       │
│    "This source, at this time, claims this brand/model/generation/   │
│    powertrain/trim/price at this grain." Not yet accepted as fact.   │
│    Carries its own confidence, review status, and source reference.  │
└───────────────────────────────┬───────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 3. IDENTITY PLANE                                                    │
│    Stable canonical vehicle identity.                                │
│    Brand → Model → Generation → Configuration → MarketTrim.          │
│    ("Configuration" is the future name for today's "Variant" —       │
│    see "What does NOT change in Phase 0" below.) IDs are stable,     │
│    never recycled, and every observation resolves to the finest      │
│    identity level it can actually prove — never further.             │
└───────────────────────────────┬───────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 4. FACT PLANE                                                        │
│    Accepted product facts and measured registration facts.           │
│    Price Ledger, comparable specs, campaign history, lifecycle       │
│    status — and, on the registration side, registration facts at     │
│    their proven grain (BRAND/MODEL/Configuration), with MIXED        │
│    where the source cannot separate values, and DLT-detail ledgers   │
│    for sources that expose more than the common grain.               │
└───────────────────────────────┬───────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 5. SERVING PLANE                                                     │
│    Query/read models, immutable releases, application projections.  │
│    Deterministic, hash-identified, atomically-activated releases;    │
│    current_* views selected through one active-release pointer;      │
│    paid/entitlement-gated projections separate from public ones.     │
└─────────────────────────────────────────────────────────────────────┘
```

Data flows down the stack. Nothing below a plane may reach back up and mutate it: the Fact
Plane never rewrites an Observation, the Serving Plane never rewrites a Fact. Corrections are
new dated observations/facts, not edits to old ones (this already matches how `PriceLedger`
and `SpecLedger` behave today — see `CURRENT_STATE.md`).

## How the two current source domains map onto this

```
ECO / product sources ──────┐
  (source + observation)    │
                             ├──▶ identity resolution ──▶ canonical vehicle spine
DLT registrations ──────────┘         (Identity Plane)     (Identity Plane)
  (source + observation)                                          │
                                                    ┌───────────────┴───────────────┐
                                                    ▼                                ▼
                                          product facts                   registration facts
                                          (Fact Plane)                    (Fact Plane)
                                                    │                                │
                                                    ▼                                ▼
                                          spec/compare (Serving)          sales analytics (Serving)
```

This is the same picture given in the task brief. The point of naming it in five planes rather
than two source pipelines is that **Source** and **Observation** are conceptually identical
regardless of whether the raw material came from ECO or DLT — today they are implemented twice,
with different code, different file layouts, and different review-state vocabularies (see
`CURRENT_STATE.md` §"ECO ingestion" vs. §"DLT ingestion"). A converged Source/Observation
Plane would let a new source (a third OEM feed, a new registration authority) plug in without
re-deriving matching/review/audit logic from scratch. That convergence is Phase 4 work, not
Phase 0 — Phase 0 changes no code, only names this destination.

## Target canonical vehicle spine

```
Brand
  → Model
    → Generation
      → Configuration     (target name for today's "Variant")
      → MarketTrim         (already a sibling of Variant/Configuration today,
                             not a child of it — see CURRENT_STATE.md)
```

`Configuration` is the eventual name for the concept the codebase currently calls `Variant` —
the analytical/registration-grain classification line. Renaming it, or changing what it means,
is Phase 6 work ("Variant/Configuration, MarketTrim and DLT-detail semantic consolidation") —
see `MIGRATION_PLAN.md`. **Phase 0 does not rename or restructure anything.** The current
`Variant`↔`MarketTrim` relationship (MarketTrim optionally references a Variant by ID, but is
not nested under it) already matches the shape this target spine describes; what changes in a
later phase is mainly the *name* `Variant → Configuration`, plus tightening how registration
observations attach to it.

## Source grain vs. reporting grain, formalized

The current DLT engine already keeps these separate in practice (`Grain` enum vs. the cube's
`DEFAULT_ANALYSIS_GRAINS` and allocation profiles — see `INVARIANTS.md` rule 15). The target
architecture makes this a first-class distinction everywhere, not just in the DLT engine:

- **Source grain**: the finest identity level a given source observation can actually prove.
  A DLT row that only names a model proves `MODEL` grain, full stop — no amount of downstream
  cleverness may promote it to `Configuration` grain.
- **Reporting grain**: the level a query or dashboard asks for. When reporting grain is finer
  than source grain for some rows, the honest answers are `MIXED` (evidence shows a split
  exists but not how) or an explicit, versioned allocation profile (a derived, clearly-labeled
  analytical estimate) — never a silent guess written back as if it were a fact.

Every future source (ECO, DLT, a future OEM feed) must be able to attach an observation to the
finest canonical entity it actually proves, and no finer. This is already true independently
in both current pipelines; the target work is making it one shared rule enforced by one shared
identity-resolution component instead of two.

## What does NOT change in Phase 0 (or without an explicit later-phase decision)

- `Variant` is not renamed to `Configuration` in code, data, or APIs.
- `MarketTrim` and `Variant` are not merged.
- No canonical ID scheme changes.
- No registration data is re-resolved against a new grain model.
- No existing crosswalk (legacy UUID ↔ canonical ID, either of the two current mechanisms) is
  removed or unified.
- ECO and DLT ingestion are not merged into a shared Source/Observation Plane implementation.
- Supabase's multiple roles (canonical command inbox, serving database, auth/application data,
  registration fact storage) are not restructured.

See `docs/consolidation/MASTERPLAN.md` for a second, complementary target-architecture document
(in Thai, "Revision 2 — Approved architecture, 9 September 2026") that predates this one and
covers the TDR/`vehicle-market-master` repository consolidation specifically. `MIGRATION_PLAN.md`
explains how that document's Phase A–J sequence relates to this document's Phase 0–7 sequence —
they are not the same numbering and must not be confused.
