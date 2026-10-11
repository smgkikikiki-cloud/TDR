# Catalog Maintainer contract v0.1 (proposal)

Status: offline implementation draft; no production authority. Vehicle DB v3 §4 currently permits AI to propose structural MarketTrim changes only. Phase 1 governed DB writer is not implemented. This package makes no database connection and cannot apply a proposal.

## Scope and outcomes

- Accept only existing, non-deleted `CURRENT` Thai-market models with a resolvable generation. Never create model/generation identities.
- If current showroom activity is not established, issue `RETAIL_AUDIT_ONLY`; do not infer discontinuation from status, price, registration, or missing rows.
- For a model with an owner-approved current-retail set, that complete set is authoritative. Only listed existing trims can enter spec enrichment. A mismatch becomes one model-level review item.
- For models without an owner set, a complete source-confirmed current lineup is required before spec enrichment. Unverified identities remain in Retail Audit.
- Exclude HISTORICAL, upcoming, discovered/pending shells, deleted and owner-retired identities from spec research.
- Two queues: `RETAIL_AUDIT` for lineup confirmation; `SPEC_ENRICH` for eligible verified/current marketed trims.
- Work units are model/document bundles. Applicable field gaps may be grouped; there is no independent task for each trim × field.

## Field and gap semantics

Use the existing comparable-spec field registry as authority in production. The synthetic fixture registry in this package only defines test keys and does not replace it. Fields carry tier and applicable powertrains. P0 is lineup/price correctness (price remains Price Ledger-owned); P1 is core comparison; P2 is differentiating equipment; P3 is incidental. P3 never creates a standalone research task.

Known values are resolved across canonical facts and payload layers. A canonical fact is preferred; payload/variant/model/generation values suppress duplicate gaps and may be flagged for trace/reconciliation, never copied blindly. `UNKNOWN`, `NO`, `ABSENT`, `NOT_APPLICABLE`, locked tombstones, conflicts, and source-trace needs remain distinct. Price fields are excluded from spec gap fill. Registration is a score input only.

## Existing-code inventory and boundary map

- `lib/spec-field-registry.ts` reads the canonical comparable-spec registry and defines the serving/editor semantics, including empty `applicablePowertrains` meaning universal. The simulator mirrors the shape in its synthetic fixture only; production code must consume the canonical registry rather than establish another production registry.
- `vehreg/current_retail.py` defines `vehicle_current_retail_sets` as a sparse owner-approved *complete* model lineup. A missing model entry is no opinion; a present entry is authoritative membership. The simulator preserves that distinction.
- `vehreg/retail_scope.py` answers price-fact eligibility (active generations and lifecycle stops). Its `CURRENT` status and generation dates do not establish a complete actual showroom lineup, so it is not the Retail Audit gate.
- `vehreg/trim_reconciliation.py` records source-backed trim candidates and unresolved powertrain/lifecycle ambiguity. It is useful as a future proposal-validation boundary; it does not grant trim creation or lifecycle-write authority.
- `docs/RETAIL_LINEUP_BOOTSTRAP.md` is an admin-only complete-set reset flow, not an autonomous maintenance API. Existing bootstrap/legacy file-release writers remain outside this package.
- `docs/vehicle-db/VEHICLE_DB_V3.md` §4 limits AI structural trim changes to proposals. `docs/WORK_STATE.md` says Phase 0 is live, the legacy writer is closed, and the Phase 1 governed writer is not implemented. This simulator therefore stops at local plans/proposals.

No new scheduler, production agent, Supabase adapter, migration, storage write, or call into the retired canonical input/release pipeline is added.

## Decisions

`ELIGIBLE_ENRICH`, `RETAIL_AUDIT_ONLY`, `EXCLUDED_HISTORICAL`, `EXCLUDED_UPCOMING`, `EXCLUDED_DISCOVERED`, `EXCLUDED_ADMIN_RETIRED`, `EXCLUDED_NON_MEMBER`, `HOLD_IDENTITY`.

Each emitted row has a stable key derived from normalized input, policy version, model, work kind, and field group. Ties use stable identifiers. Re-running the same fixture produces byte-identical outputs.

## Proposed V3 §4 permission amendment — not adopted

Keep the existing proposal-only rule until a separate owner-approved permission amendment and Phase 1 governed writer exist. A future narrow rule could permit autonomous **ADD** only for an exact Thai-market grade/powertrain under an existing CURRENT model and generation, with collision-free identity and corroborated contemporaneous official lineup evidence. Otherwise route to REVIEW.

Autonomous **soft-DISCONTINUE** could require prior confirmed CURRENT membership plus an explicit first-party end-of-sale statement, or two independently dated complete first-party Thai lineup snapshots at least seven days apart. Partial pages, failed fetches, conflicting sources, owner-protected sets, major lineup transitions, or an apparent whole-model withdrawal route to REVIEW/HOLD. Never hard-delete identities or their history. Rename, reactivate, generation changes and new models remain human-reviewed.

Owner-approved retail sets, owner lifecycle choices, admin-provided identities, locked facts and tombstones always win. A conflicting observation creates one deduplicated model review item. Any future APPLY requires atomic per-model baseline/hash/lock checks, revision audit and compensating revert through the governed writer; no direct table update or admin impersonation.

## Modes and safety

Only fixture `MOCK` is implemented. `REPLAY`, shadow reads, live research, writer and scheduling are absent. `allow_external_http=false`, paid calls/tokens/spend are zero, writer and cron are disabled. There is no provider SDK or database dependency in this package.
