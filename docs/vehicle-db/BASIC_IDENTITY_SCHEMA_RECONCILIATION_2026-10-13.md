# BASIC Identity schema reconciliation — 2026-10-13

**Offline reconciliation only.** This report compares checked-in SQL with the owner-supplied, SELECT-only production snapshot dated 2026-10-13. No database connection or production introspection was performed for this change. No SQL in this directory was executed; no migration ID is assigned.

## Deployed ledger and repository state

The supplied production ledger ends at `20261009135816 / v64_ice_panel_grain_fix`. It reports no v65 or v66 row. The snapshot also reports no deployed `vm_apply_price_changes`, `vm_inbox_*`, `vm_observations`, `vm_inbox`, or `ice_model_crosswalk_scoped` objects. Treat this as owner-provided evidence, not a fresh read made by this branch.

| Version | Repository artifact | Supplied live-ledger state | Relevant result |
| --- | --- | --- | --- |
| v57 | `supabase/migration_v57_vehicle_master_tables.sql` | Applied | `vehicle_models.status`, `served_as_of`, and `seed_release_id` are NOT NULL. `generation_id`, segment/body and price band can be NULL, but that does not make the row a BASIC identity. |
| v58 | `supabase/migration_v58_vehicle_serving_parity.sql` | Applied | `current_vehicle_models` selects every non-deleted master row; it has no identity-level admission predicate. A BASIC row cannot be inserted without exposing it to this serving surface. |
| v59 | `supabase/migration_v59_vehicle_engine_rules.sql` | Applied | `_vm_model_problems` requires body, cab, registration and market scope plus a recognized `retail_status`; deferred structure constraints validate catalog children/payloads. Reusing `UNVERIFIED`, `OTHER`, `RY1`, or an invented generation would falsify unknown facts. |
| v60 | `supabase/migration_v60_close_legacy_vehicle_write_path.sql` | Applied | Retires legacy mutation paths. This work does not use or reopen them. |
| v63 | `supabase/migration_v63_ice_model_crosswalk.sql` | Applied | Only group-level `ice_model_crosswalk` exists, without registration-class key, revision/CAS or the frozen-scope contract. `ADMIN` is a legacy protected `match_method`; preserve that protection during any future translation. |
| v64 | `supabase/migration_v64_ice_panel_grain_fix.sql` | Applied | Ice panel grain correction; not a Vehicle Master identity writer. |
| v65 | `supabase/migration_v65_ice_commit_delete_where.sql` | Repository only | Not in the supplied deployed ledger. Do not infer it was applied because its SQL file exists. |
| v66 | `supabase/migration_v66_vehicle_master_governed_writer.sql` | Repository only | This is a price-ledger writer draft. Its public `vm_apply_price_changes` is not a structural RPC. Its observation field check omits `STRUCTURAL_IDENTITY`; its change-log edit drops `command_id NOT NULL` but does not remove the FK to retired `canonical_write_commands`. It cannot be treated as deployed support for BASIC identities. |

## C02 and schema blockers

The v57/v58 Vehicle Master migrations are reported applied while the portfolio/design reservation record still assigns v57 to Upcoming and v58 to Analysis. This is the open G0 C02 collision. Do not rename/overwrite applied SQL, choose new numbers, or resolve the reservation in this PR. The separate C02 decision must enumerate actual deployed and pending migration names and authorize fresh IDs before any migration can be numbered.

The production snapshot reports `canonical_write_revisions.command_id NOT NULL` with a foreign key to the retired read-only `canonical_write_commands`, and a unique constraint on `command_id`. The local v66 draft only relaxes NOT NULL; it does not address truthful structural attribution or the retired-command FK. Do not fabricate command rows, re-enable the legacy command queue, or assume a nullable structural revision path is deployed. The compatibility layer therefore emits a truthful blocked result and only serializes a draft RPC envelope.

The supplied snapshot reports no scoped crosswalk table. Legacy `ice_model_crosswalk` is group-level; the PR #237 engine's `(model_group_id, reg_type_scope)` identity, revision/CAS and frozen owner-source rules cannot be projected into it. Structural BASIC identity work does not authorize R6 links; the RPC envelope rejects link intents.

## BASIC boundary and future governed RPC requirements

The existing `StructuralIdentityWriter` remains the sole planner, validator, proposal, alias-repair and fake-transaction engine. Its simulated `identity_level=BASIC` shape is not currently insertable into `vehicle_models`. A later, separately numbered and approved additive schema change must:

1. Represent `BASIC` explicitly in the same canonical `vehicle_models` master, with truthful creation provenance and without a fabricated generation, catalog lifecycle, segment/body, seed release or served date.
2. Keep existing CATALOG constraints intact for catalog rows and add a safe discriminator/constraint branch for BASIC; update all catalog serving consumers so BASIC rows cannot appear as saleable catalog entries. Market-analysis identity lookup admission requires its own reviewed contract.
3. Add immutable structural observation support, trusted actor attribution, idempotency receipt semantics, and a revision path that preserves legacy command foreign-key semantics for legacy revisions while supporting structural revisions without fake legacy commands.
4. Define one private, non-exposed, transaction-owning structural RPC. It must re-read/lock canonical IDs, brand FK, normalized same-brand aliases, revisions and source evidence; enforce CAS and concurrent uniqueness; commit identity, observations, revisions and receipt together or roll all back. Authorization must come from trusted server context, not request flags or service-role possession alone.
5. Keep R6 scoped-crosswalk mutation in its separately authorized slice. Do not use a structural CREATE grant as crosswalk authority.

The accompanying `[structural RPC SQL sketch](drafts/basic_identity_governed_structural_rpc.sql)` is a non-executable design aid. It intentionally does not modify the v66 migration and is not an approved migration.

## Outstanding dependencies

- A fresh SELECT-only production schema/ledger readback from an authorized operator before migration design is finalized.
- Owner/governance resolution of C02 and allocation authority for any future migration ID.
- Approval of BASIC identity lifecycle/provenance and Market Analysis serving semantics; catalog consumers must remain isolated.
- Independent design review of the structural revision/audit shape against the real v57/v12 constraints.
- Review and authorization for a private schema/RPC, least-privilege grants, trusted identity propagation, RLS, transaction isolation and database race tests.
- Separate owner authorization and the open C01/R6 gate for any scoped crosswalk mutation.
- Independent QA of this PR and the prior nine-identity preflight; this work does not approve/create any of those identities or change their counts.

