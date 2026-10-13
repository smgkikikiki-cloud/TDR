# Phase 1D — C02 migration and Enforcer decision pack

**Verdict: `MIGRATION_GATE_BLOCKED`.** No migration number was chosen and no migration was executed. The checkout contains SQL files through v66; a dated owner-supplied ledger reconciliation says the deployed Vehicle Master/Market ledger ended at v64 on 2026-10-13. That evidence was not freshly confirmed against the live database and is not treated as a current production fact.

## Inventory and material conflicts

`supabase/` contains numbered files v1–v66 (gaps in the sequence are normal in this repository). The affected files are:

| Version | Checked-in file | Dated supplied ledger | Phase 1D interpretation |
|---|---|---|---|
| v57 | `migration_v57_vehicle_master_tables.sql` | reported applied | Vehicle Master tables and strict catalog provenance/status fields |
| v58 | `migration_v58_vehicle_serving_parity.sql` | reported applied | `current_vehicle_models` admits every non-deleted model; BASIC exclusion is not present |
| v59 | `migration_v59_vehicle_engine_rules.sql` | reported applied | deferred CATALOG structure rules |
| v60–v64 | corresponding repository migrations | reported applied | legacy write closure, backup bucket, Ice panels/crosswalk, panel-grain fix |
| v65 | `migration_v65_ice_commit_delete_where.sql` | reported absent | repository-only Ice importer fix |
| v66 | `migration_v66_vehicle_master_governed_writer.sql` | reported absent | repository-only price writer; not structural BASIC identity support |

C02 remains OPEN because `design/GRAFT_PLAN.md` reserved v57 for Upcoming and v58 for Analysis while those numbers are used by applied Vehicle Master migrations according to the supplied ledger. The same supplied reconciliation reports `canonical_write_revisions.command_id` as `NOT NULL`, `UNIQUE`, and FK-linked to the retired `canonical_write_commands`; repository v66 only drops NOT NULL and does not remove the FK. Its DDL cannot establish that live state. Phase 1C remains unnumbered local-only SQL.

The supplied schema reconciliation also reports v57 `vehicle_models.status`, `served_as_of` and `seed_release_id` as `NOT NULL`; v58 `current_vehicle_models` selects all non-deleted models without a BASIC admission predicate; v59 deferred structural rules require CATALOG-specific classifications. Therefore a BASIC identity cannot be inserted safely by relaxing a field in isolation: the same reviewed additive schema must preserve all CATALOG checks and prevent BASIC rows from leaking into catalog/current-retail serving.

Relevant local migration hashes are recorded by `acceptance_report.json` and by `sha256sum supabase/migration_v57_vehicle_master_tables.sql ... supabase/migration_v66_vehicle_master_governed_writer.sql`. Repository hashes establish checkout content, not deployed checksums.

## Owner decisions required

1. **Fresh readback authority:** a database owner/operator must provide or perform an authorized SELECT-only read of the actual project, exact migration ledger/checksums, catalog counts/fingerprints, relevant definitions, RLS, effective grants and `canonical_write_revisions` constraints. The 2026-10-13 supplied result is stale for any later live claim.
2. **Migration allocation:** portfolio/roadmap owner resolves the Upcoming/Analysis reservation collision and authorizes fresh IDs after reconciling all applied and pending migration files. Vehicle Master owner separately approves the BASIC structural change. Toolkit DB owner separately approves Toolkit additions. No developer assigns numbers on their behalf.
3. **Audit/revision shape:** DB schema owner approves a backward-compatible structural revision mechanism that preserves legacy command FK/uniqueness and does not manufacture `canonical_write_commands` rows or form parallel canonical state.
4. **Admin trust and RLS:** Admin security owner plus independent DB security reviewer approve the trusted session→issuer→immutable approval record→executor design, private-schema ACLs, function owner/search_path and grant/revoke policy.
5. **C01/R6:** remains a separate identity-crosswalk authorization and must not be inferred from BASIC identity readiness.

## Decision options for C02

| Option | Effect | Risk / disposition |
|---|---|---|
| A. Preserve all applied history; obtain fresh ledger; reserve new monotonic IDs through the migration owner; update Upcoming/Analysis plans in a separate reviewed change | Keeps deployed files immutable and removes the conflicting reservations only after evidence | **Recommended**, but blocked until fresh ledger and explicit owner allocation |
| B. Reuse reserved v57/v58 names or rename already-applied Vehicle Master migrations | Makes file names disagree with applied history or overwrites historical identity | Reject; creates irreconcilable replay/deployment ambiguity |
| C. Put Phase 1D SQL in a new file with an assumed next integer | Produces a plausible local sequence without knowing deployed state or owner reservation authority | Reject; still resolves C02 without authority |
| D. Leave Phase 1C unnumbered and stop at isolated acceptance pending C02 | No migration state changes; preserves all gates | Safe holding state, but does not complete production-readiness acceptance |

Recommended path: D now, then A in a separate owner-authorized planning/migration task. There is no Phase 1D deployment sequencing approval in this PR.

## Enforcer and PR stack

The issue/PR #241 handoff reports exact-base admission failures `UNEXPECTED_BASE_BRANCH` and `UNMANAGED_PR_NOT_TASK_AUTHORIZED` for the Phase 1C stack. They were reproduced locally against the exact `01ff6af...` policy checkout using a synthetic event for the Phase 1D branch: result `UNMANAGED_AUDIT_ONLY`, error `UNEXPECTED_BASE_BRANCH`, warning `UNMANAGED_PR_NOT_TASK_AUTHORIZED`, `enforcerAuthorized=false`, exit 1. This is a deterministic policy rehearsal, not hosted PR CI. `.github/workflows/enforcer-pr-admission.yml` checks the exact PR base policy first and runs trusted central compatibility behavior when no modern policy exists; missing authorization is fail-closed. It does not declare a stacked dependency chain automatically authorized. Keep this PR based on the Phase 1C branch requested for review; preserve the Enforcer failure as a governance blocker. Do not retarget, amend Enforcer, change branch protection, elevate permissions, or merge around it.

Safe review order for owner decision: review/accept #235 evidence → #237 writer offline contract → #239 serializer offline contract → #241 isolated PostgreSQL proof → #242 Phase 1D blocked/evidence package. Each merge/base transition must be explicitly admitted by current Enforcer policy. No merge is part of this task.

## Rollout state

The associated rehearsal runbook is planning only. Backup verification, production preflight, window selection, owner approvals, DDL, live ACL changes, adapter activation, RPC invocation and post-apply live checks were not performed.
