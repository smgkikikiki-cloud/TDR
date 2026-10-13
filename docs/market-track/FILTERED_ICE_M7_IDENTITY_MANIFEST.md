# Filtered Ice M7.0 identity manifest

**Status:** offline implementation and evidence; independent QA required. No production crosswalk approval or gate advancement.

## Scope and provenance

This manifest applies the owner-approved Issue #228 recovery ledger to the frozen Ice Full Package M7.0. It retains the original raw evidence and all 244 frozen decisions. Groups below 40 registrations across all M7.0 registration classes, Ferrari, Lamborghini, Lancia, Alfa Romeo, Daihatsu, and all prior owner exclusions are removed from the effective analysis denominator.

Pinned sources:

- M7.0 Full Package: `data/packages/2569-09/v3_M7.0/TDR_FULL_2569-09_v3_M7.0.zip`, SHA-256 `c558d2d4cc3ed667f8b30ea028dbb66c4030cdce4e7daabe735df870cb94677d`.
- Frozen 244-decision ledger SHA-256 `9f251b6120d88e52c33215c5127fb6f87cd8c6cc334c39dc227bb540860ae1a8`; original owner overlay SHA-256 `e660cf9133cd0a99ffe8c87d1ba06dc0c72ef89b8a313a0a7285f54da1332430`.
- Shadow group/class evidence SHA-256 `9d46cad597dba3bbe83369bd9f95cfe6d10b3f6d19e0f46b69e70f10bfab5450`.
- Current Vehicle Master catalog is a sanitized SELECT-only snapshot captured 2026-10-13; model rows SHA-256 `c95c99e3f552cc384b083dac7d69b5625032ac73e6bc40d0bc9e086d8367ea64`.
- The approved portfolio roadmap is v1.0 at `42be6b6a803727086b404b2cb46f75593bb2c1d4`; this branch is based on `main` `c2715cbee494ae076b2582ef99f2bbc590b5dd99`. Ice roadmap: `847fef43`. Vehicle DB v3 as updated on main: `a7007a7c2d43222d1d4d35342f891c832cbcea77`.
- Inspected Draft PR #229 at `872a1117b163feac42e0ce55314cd7a7408896b5` and Draft PR #232 at `3050beb1cdad4530808177de7b9d66abb21364f3`; their remote branch heads still matched those SHAs at implementation time.

## Reconciliation

The original package contains 1,200 model groups and 4,141,987 registration units. The filtered exclusions are 858 unique groups / 18,283 units, leaving 342 groups / 4,123,704 units. The exclusions overlap: 846 groups are below 40 (3,644 units), 43 are excluded marques (1,141 units), and 58 retain prior owner exclusion (13,901 units). The output records each reason per group and retains class-level counts for audit. The effective denominator is fixed at 4,123,704; excluded source facts remain available but are not part of effective analysis.

| Identity result | Groups | Registrations | Share of effective denominator |
| --- | ---: | ---: | ---: |
| `MATCH_EXISTING` | 247 | 2,719,543 | 65.9490% |
| `NEW_BASIC_IDENTITY_NEEDED` | 58 | 87,170 | 2.1139% |
| `UNRESOLVED_EVIDENCE` | 37 | 1,316,991 | 31.9371% |

The former 114 shadow identity targets filter to 61 eligible Ice groups / 97,587 registrations. Catalog collision and equivalence checks reconcile BYD e6 and Mercedes-Benz E300 to existing aliases; BMW 530e remains unresolved because its alias on BMW 5 Series conflicts with the owner-stated BMW identity lock. The remaining 58 are grouped into 58 candidate canonical proposals. They are explicitly **not** create instructions. Duplicate target IDs are coalesced by canonical ID and conflicting target definitions become unresolved.

Pickup links remain scoped by the actual M7.0 registration class. For example, Ford Ranger has explicit RY1/RY2 links to the Double Cab identity and RY3 to the Cab identity. Any unresolved scope in a group with a pickup split stays unresolved; a class is never filled from another class or a group-level alias. For every existing link, the CSV records its source disposition, and `mapping_authority=OFFLINE_MANIFEST_EVIDENCE_ONLY` makes clear that the offline result is not a production approval.

## Outputs and reproduction

Outputs are under `data/packages/ice_crosswalk_r6_offline_recovery_M7.0/qa/filtered_identity_manifest/`:

- `eligible_model_groups.csv` — one row for each of the 342 groups, including source registrations by class and one of the required identity statuses.
- `excluded_model_groups.csv` — all excluded groups, removed registrations, overlapping reasons, class counts, and evidence references.
- `existing_identity_links.csv` — existing Vehicle Master identity links at `(model_group_id, reg_type)` scope.
- `new_basic_identity_proposals.csv` — 58 collision-checked, basic identity candidates; optional generation, lifecycle, segment, body and powertrain facts remain `UNKNOWN` if absent.
- `unresolved_identity_evidence.csv` — unresolved group/class scopes and the evidence gap or conflict.
- `identity_manifest_qa.json` — source and catalog hashes, fixed-denominator reconciliation, owner-ledger replay, category totals, scoped link coverage and output hashes.

Regenerate with:

```bash
PYTHONPATH=automotive/vehicle_master:automotive/vehicle_master/tools \
  python automotive/vehicle_master/tools/ice_filtered_identity_manifest.py
```

Focused tests: `python -m pytest -q automotive/vehicle_master/tests/test_ice_filtered_identity_manifest.py`. The tests cover the 39/40 cutoff, many Ice groups to one canonical target, conflicting duplicate target definitions, discontinued lifecycle preservation, pickup class splits, and all 244 frozen decisions.

Historical models receive only basic identity and evidenced classification facts. This implementation does not reconstruct trims, MSRP, detailed specifications, or prices. Chevrolet is limited to basic identity/crosswalk work and is excluded from all price refresh. No Price Fetcher development is included.

## Writer and database handoff

The exact required future path is the **Vehicle DB v3 Phase 1 structural governed writer** described in §12 and §4 of `docs/vehicle-db/VEHICLE_DB_V3.md`: permission checks, immutable observations, reconciliation into a plan, authorized apply/propose, revisions/change log and revert. That structural writer is not implemented. The merged `vm_apply_price_changes` RPC from migration v66 is a price-only writer; its only model-row mutation updates the retail price band. It cannot create brands/models/generations or apply Ice identity links. Do not route identity changes through it, the retired `canonical_input_batches` path, direct SQL/table writes, or serving views.

Independent production blockers remain: Phase 1 lacks the structural create/link writer and its apply authorization; R6 production-crosswalk permission remains false; C01 provenance for the earlier production run remains unresolved; and C02 migration numbering/transaction integration for the scoped resolver is not approved. The next production dependency is delivery and independent review of that structural writer plus R6 governance resolution. This branch performs none of those operations.
