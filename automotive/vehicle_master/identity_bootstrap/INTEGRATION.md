# Identity Bootstrap — persistence analysis and integration proposals

**Proposals only.** Nothing here is a migration, a workflow or a code change; no SQL below is to be executed. Every item needs its own owner gate.
Evidence is cited from the repository at `7963ebf0` (main after #199). PR #200 (Identity Resolution Contract v1) was read, not modified.

## 1. Can the live `vehicle_models` hold a minimal `DISCOVERED` identity?

**No — not today, and not without relaxing rules that are live in production.** Findings, each verified in the repository:

| # | Where | What it requires | Effect on a shell |
|---|---|---|---|
| C1 | `migration_v57` `vehicle_models.status` (`:85`) | `check (status in ('CURRENT','HISTORICAL','UNVERIFIED'))`, `not null` | There is no lifecycle axis for "exists but not vetted/published". `status` means *on sale*, a different question; overloading it with `DISCOVERED` would make every status reader wrong. |
| C2 | `migration_v59` `_vm_model_problems` (`:155-205`) behind constraint `vm_rule_model_validate` | `body_type` ∈ 11 values (null is "unknown body_type null"), `cab_type`, `registration_type`, `market_scope`, `retail_status` all required; `retail_status CURRENT` needs source + checked-at | A shell with null attributes is **rejected by the DB**. The brief's "unknown attributes remain null" cannot be stored. |
| C3 | `migration_v59` `vm_rule_model_identity` (`:673`) | `payload->>'body_type' = body_type`, `payload->>'name_en' = name_en`, `payload->>'id' = canonical_id` | Null = null passes a CHECK, but it only helps if C2 is relaxed; the payload must also carry identity fields. |
| C4 | `migration_v59` `vm_rule_structure` (`:853-863`, trigger `:1175`) | a model must have ≥ 1 generation (`model_has_generation`) and, unless `payload.incomplete`, ≥ 1 variant | A shell with no generation is rejected at commit. |
| C5 | `migration_v58` `current_vehicle_models` and the other `current_*` views (`:239-263`) | `where deleted_at is null` only | **Any inserted row is served to the consumer catalog.** A shell would leak. This is the most dangerous conflict. |
| C6 | `migration_v57` `vehicle_models.seed_release_id`, `served_as_of` (`:91`) | `not null` | Semantically "the seed release this row was served from"; a runtime-created row has none. A sentinel works but is a stretch. |
| C7 | `migration_v57` `slug text not null unique` | public URL slug, "stored, frozen" (ENGINE_RULES) | A shell needs a slug at creation; the current slug is a release-time crosswalk output. v1 derives `{brand}-{local}` with `_`→`-` (**assumption**, owner to confirm). |
| C8 | `migration_v63` `ice_model_crosswalk.match_method` (`:40`) | `check in ('SERIES','NAME','ADMIN')` | The origin mapping (`method: ORIGIN`) has no legal value; `ADMIN` would falsely say a human decided. |
| C9 | `docs/WORK_STATE.md` ("Vehicle DB v3 platform state"), `migration_v60` | The legacy writer is closed; **Phase 1 (write layer, change log, permissions) has not started** | There is no governed write path to hand a plan to. `lib/canonical-vehicle-create.ts` targets the closed path. |
| C10 | `VEHICLE_DB_V3.md` §1.4, §4 | AI "may only *propose*" model creation; admin creates instantly | A machine creating a model directly contradicts the permission table unless the owner amends it (see §4). |
| C11 | `lib/canonical-vehicle-create.ts` | The only existing "new car with unknown specs" precedent writes `incomplete: true` with `body_type = OTHER`, plus a first generation | That *fabricates* `OTHER`/cab/registration/market values and a placeholder generation. Rejected as a base for Bootstrap (§2, option C). |

Positive findings: `lib/ice-market-data.ts:206` already reads `vehicle_models` directly for segment/body (it tolerates null → the "ไม่ระบุ" bucket), so internal market reads of a shell work; `ice_model_crosswalk.canonical_model_id` is an FK to `vehicle_models(canonical_id)`, so the crosswalk can reference a shell only if the shell is a `vehicle_models` row. The nightly backup (`tools/vehicle_master_backup.py`) exports `vehicle_models` and would include shells (desired: ids are reserved state).

## 2. Options and the smallest change

| Option | Idea | Verdict |
|---|---|---|
| **A (recommended)** | Add lifecycle columns **in place**; make the model rules and the serving views state-aware. One canonical table, no shadow copy. | Smallest that satisfies the brief. Touches live validation and serving, so it needs a leak audit and the owner's gate. |
| B | A separate `vehicle_identities` registry owns ids and state; `vehicle_models` is created at promotion. | Leaves live validation and views untouched, but the crosswalk FK and every id lookup must repoint, and identity fields exist twice. The brief asks not to shadow the master. Fallback if A is judged too risky. |
| C | Reuse the `incomplete: true` hatch. | **Rejected.** It fabricates attribute values, needs a placeholder generation, and the row is served. |

### Option A — what changes (sketch; not a migration)

```sql
-- 1. lifecycle, additive. Backfill = every existing row is PUBLISHED/COMPLETE; no default, so a writer must always choose.
alter table public.vehicle_models add column identity_state    text;
alter table public.vehicle_models add column enrichment_state  text;
update public.vehicle_models set identity_state = 'PUBLISHED', enrichment_state = 'COMPLETE';
alter table public.vehicle_models alter column identity_state set not null, alter column enrichment_state set not null;
alter table public.vehicle_models add constraint vm_identity_lifecycle check ((identity_state, enrichment_state) in (<lifecycle.yaml allowed_state_pairs>));

-- 2. the attribute rules apply only once an identity leaves the shell stage
--    _vm_model_problems(p) must see the state: add it to payload ('identity_state') and return only identity problems (name_en, id, brand) when
--    payload->>'identity_state' in ('DISCOVERED','ENRICHING'); vm_rule_structure skips model_has_generation / model_has_variant for the same states.
--    status stays NOT NULL: a shell is 'UNVERIFIED' (VEHICLE_DB_V3 §6.A defines it for trims as "real but unconfirmed; hidden from the public site"; whether models are filtered the same way was NOT verified, which is why the view filter in step 3 is required rather than relying on status).

-- 3. serving: current_* views add  AND identity_state = 'PUBLISHED'  (same columns, same payload shape -> the serving contract is unchanged)
--    plus an INTERNAL view  internal_vehicle_identities  (all states except WITHDRAWN) for the market engine and the crosswalk.

-- 4. side tables (append-only / ledger, NOT copies of Vehicle Master attributes):
--    vehicle_identity_aliases    (provider, external_id) PK -> canonical_id FK, state ACTIVE|RETIRED, relation
--    vehicle_identity_provenance canonical_id PK FK, the §12.4 record, unique (brand_id, identity_key) where identity_state <> 'WITHDRAWN' is enforced by the writer
--    vehicle_identity_events     transactional outbox, event_id PK
```

Required tests if this is ever approved: a DB test that **no non-`PUBLISHED` row appears in any `current_*` view**; a `_vm_model_problems` parity test over all existing rows (identical results for `PUBLISHED`); the v59 rule tests unchanged; a replay test of `migration_v57..v65` after the new migration; the backup export round-trip.

Leak audit before approval: a grep of `lib/` and `app/` found one reader of the *table* (not a view) that this analysis inspected, `lib/ice-market-data.ts:206` (wants all states). Other files mention `vehicle_models` in comments or through `current_vehicle_models`; they were **not** individually audited and each must be checked for "published only" intent.

## 3. Proposed interface amendments to Identity Resolution (PR #200 — not applied)

Bootstrap needs nothing from the resolver beyond what a thin adapter can already derive. Requested, in priority order:

1. **Targets carry `identity_state`** (`record.schema.json#/$defs/target`: today `status` is only `CURRENT|HISTORICAL|UNVERIFIED`). The candidate pool should include `DISCOVERED`/`ENRICHING` identities so a later run can bind a subject to a shell. Without it IR returns `NO_CANDIDATE` for a subject whose shell already exists (Bootstrap still holds it as `IDENTITY_ALREADY_DISCOVERED`, but the mapping never forms).
2. **Expose excluded candidates' relations.** `alternatives[].evidence` should carry `name_relation` and `brand_relation` for `EXCLUDED` candidates (`NAME_SIBLING_VARIANT`, `STRUCTURAL_PROVIDER_FINER`…) so Bootstrap's `relations` can be filled from the IR record alone.
3. **Keep `DISCOVERY_CATALOG_GAP` routing-only.** Its trigger `subject_quality.discovery.catalog_gap_min_units: 500` is a volume threshold. It is acceptable for queue routing; it MUST NOT be read as new-target eligibility. The interface sends structure and evidence, never volume.
4. **A `ORIGIN` match method** for the mapping Bootstrap proposes (`PROPOSE_ORIGIN_MAPPING`, state `AUTO`): v63 `match_method` has no legal value (C8). Needs a schema decision; until then the origin mapping is only the alias row.
5. **A pure `name_relation(a, b)` function** exported by the IR lexical layer once an engine exists, so Bootstrap can compute subject↔subject relations itself instead of being handed them. Until then relations travel as data, which keeps both subsystems independently testable.
6. **Lineage first.** Bootstrap assumes IR §9 lineage has been processed (renames followed, split parents flagged) before it runs, and refuses a run whose lineage source is missing — consistent with IR's `LIN_SOURCE_MISSING`.

Hand-off record Bootstrap needs per subject (all already present or derivable): `resolution.outcome`, `resolution.reason_codes`, brand resolution (`brand_id`, relation), the list of non-`CONTRADICTION` relations to targets (with the peer's `identity_state`).

## 4. Owner decisions this integration needs

1. Amend VEHICLE_DB_V3 §4 so a deterministic, non-AI actor (`BOOTSTRAP`) may create hidden `DISCOVERED` shells — or keep `apply_mode: PROPOSE` (every creation is an admin card).
2. Choose Option A, B or neither; approve a leak-audit-first migration milestone.
3. Confirm the slug derivation for shells (C7) and the canonical-name rule (strip the brand prefix; legacy ids such as `jaecoo.jaecoo_5_ev` keep it).
4. Where the lifecycle fields live and who owns the Phase-1 write layer that will apply plans (C9).

## 5. The write path (design)

One service-role RPC, `vehicle_identity_apply(plan jsonb, invocation jsonb)`, in a single transaction: take `pg_advisory_xact_lock(hashtext(lock_key))`; verify the plan's preconditions (§SPEC 11); on `ALREADY_APPLIED` return without writing; on a violated precondition return `STALE:<kind>` and write nothing; otherwise insert the shell, aliases, provenance and outbox event, record a `canonical_write_revisions` change-log row with `actor_kind = BOOTSTRAP` (V3 §3: reuse the existing change log), and — through the Identity Resolution mapping writer, not here — the origin mapping. `PROPOSE` mode stores the same plan as an admin card (`admin_edit_sessions`, kind `NEW_IDENTITY`); approval calls the RPC with `creator_type: admin`. Every other model-creating path (admin editor, Excel) MUST take the same advisory lock, otherwise the digest precondition can only detect, not prevent, a race.
