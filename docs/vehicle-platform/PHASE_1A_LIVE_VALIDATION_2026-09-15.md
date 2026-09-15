# Phase 1A Live Validation — 2026-09-15

**This is reviewer-supplied validation, not a CLI execution log.** No session that implemented or
hardened Phase 1A (`docs/vehicle-platform/EXTERNAL_IDENTITY_CONTRACT.md`,
`lib/external-identity/`, `scripts/audit-external-identity.ts`) had live Supabase credentials —
confirmed at the time by an empty `env | grep -i supabase` and no local `.env`/`.env.local` with
real values. **The checked-in `scripts/audit-external-identity.ts` CLI was not run against
production by any Claude session.** Do not read this document as a record of that script having
been executed live; it was not.

What actually happened: after the Phase 1A implementation (commit `d272584`) passed architecture
review, the architecture reviewer performed a separate, independent, read-only live query against
the TDR production Supabase project on **2026-09-15, Asia/Bangkok time**, using logic equivalent
to the (then-being-hardened) audit semantics described in `EXTERNAL_IDENTITY_CONTRACT.md`. The
results below are exactly as supplied by that review. No live data was modified by that query or
by anything in this repository as a result of it.

This document is distinct from, and postdates the methodology of,
`docs/vehicle-platform/LIVE_IDENTITY_BASELINE_2026-09-15.md` (the earlier, Phase-0-amendment-era
manual comparison, scoped only to Brand+Model external IDs). This document reflects the full
Phase 1A contract — all four Mechanism B external entity types
(`brand`/`model`/`model_powertrain`/`trim`), all four mapping states, and the corrected
`canonicalId`/mapping-state invariant — even though both happen to have been captured on the same
calendar date.

## Supplied result

```text
Mechanism A assertions: 383
  brand: 62
  model: 321

Mechanism B rows: 335

Total assertions represented: 718

Audit classification groups:
  exact_agreement:          1
  disagreement:             0
  derived_only:            62
  verified_only:            8
  mechanism_b_unmatched:  326
  mechanism_b_ambiguous:    0
  mechanism_b_retired:      0

Total comparability groups/findings: 397

Mechanism A duplicate comparability keys: 0

External Mechanism-B identities appearing at more than one
canonical target entity type: 1
```

## Interpretation (as supplied)

- All 62 Brand Mechanism-A mappings currently have no Mechanism-B Brand counterpart at all →
  `derived_only`. (Mechanism B currently has zero verified Brand rows — see
  `LIVE_IDENTITY_BASELINE_2026-09-15.md`.)
- The one verified Model mapping (the Jaecoo 5 EV pilot, `jaecoo.jaecoo_5_ev`) agrees exactly
  between Mechanism A and Mechanism B → the single `exact_agreement`.
- The remaining seeded Mechanism B model rows are `unmatched`, which correctly takes classification
  precedence over a generic `derived_only` even where Mechanism A also has an opinion — exactly the
  behavior `EXTERNAL_IDENTITY_CONTRACT.md`'s classification table specifies.
- The 8 `verified_only` groups are the Jaecoo pilot's deeper identity mappings beyond the Brand/
  Model scope Mechanism A can reach: 1 generation, 3 variants, 4 MarketTrims — all verified in
  Mechanism B, none of which Mechanism A asserts anything about (Mechanism A only ever produces
  Brand/Model-scope assertions; see `EXTERNAL_IDENTITY_CONTRACT.md`, "Mechanism A's structural
  limitation").
- There are currently **zero** cross-mechanism disagreements.
- There are currently **zero** observed duplicate Mechanism-A comparability keys — i.e., the
  hardening in this pass (duplicate-assertion anomaly detection, `AuditAnomaly` in
  `lib/external-identity/audit.ts`) currently has nothing to report against live data. That
  detection exists for the case where this assumption is ever violated, not because it was found
  violated here.
- One external Mechanism-B identity appears at more than one canonical target entity type (the
  Jaecoo pilot's legacy model row, used as evidence for both its canonical `model` and its
  canonical `generation`) — this is exactly the "non-comparable at another canonical entity level"
  case `EXTERNAL_IDENTITY_CONTRACT.md`'s comparability rule exists to keep from being misread as a
  disagreement.

## What this document does and does not establish

**Establishes**: that the corrected Phase 1A contract and classification logic, applied to live
production data on 2026-09-15, produce the counts above, with zero cross-mechanism disagreements
and zero observed anomalies. This is meaningful independent validation that the hardened
semantics behave sensibly against real data, supplied by architecture review rather than by
running the checked-in tool.

**Does not establish**: that `scripts/audit-external-identity.ts` itself has ever been executed
against production (it has not, by any Claude session to date); that these counts are current
beyond 2026-09-15 (both mechanisms move independently — Mechanism A on every release build,
Mechanism B whenever a model is Phase-C verified); or any decision about which mechanism, if
either, becomes a future persistence layer (explicitly out of scope for Phase 1A — see
`MIGRATION_PLAN.md`'s Phase 1 section).

## Reproducing this independently

The exact SQL/read shape is documented in `LIVE_IDENTITY_BASELINE_2026-09-15.md` (Mechanism A/B
raw counts) and implemented end-to-end in `scripts/audit-external-identity.ts` (the checked-in,
SELECT-only CLI implementing the corrected Phase 1A audit semantics this document validates). A
future agent or operator with live Supabase credentials can run:

```
node --experimental-strip-types scripts/audit-external-identity.ts
```

and compare its output to this document, the same way this document itself was produced
independently of that script. No credentials are recorded in this repository.
