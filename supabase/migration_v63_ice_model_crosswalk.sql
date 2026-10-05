-- Market Track M3 (docs/vehicle-db/VEHICLE_DB_V3.md §14.2): the crosswalk between an
-- Ice `model_group_id` (migration_v62's `ice_dims_model_group`/`ice_reg_trend`/
-- `ice_reg_powertrain`) and a TDR canonical vehicle model (`vehicle_models.canonical_id`,
-- migration_v57). Purely additive -- no existing table, view, or RPC is touched.
--
-- No real Ice Full Package has been imported yet (M2 state, docs/WORK_STATE.md), so the
-- fact tables this crosswalk points at (`ice_reg_trend` etc.) are empty in production.
-- This migration is package-independent infrastructure: the tables, constraints and
-- RPCs below do not depend on any row existing in them yet, and seed no real crosswalk
-- mapping -- only the brand-alias seed rows explicitly required by §14.2.
--
-- --------------------------------------------------------------------------
-- Row identity -- not specified by §14.2, documented choice
-- --------------------------------------------------------------------------
-- §14.2 lists the columns (model_group_id, canonical_model_id, match_method, score,
-- status, master_version, timestamps) but not the table's row identity/PK. The smallest
-- schema that preserves the required cardinality:
--   "many TDR canonical models may map to one Ice model_group_id" and
--   "one TDR canonical model may map to at most one active Ice group"
-- is: a surrogate bigint PK (so a row can be referenced/updated regardless of whether
-- canonical_model_id is null), plus three partial unique indexes that encode the
-- cardinality rule directly in the schema instead of leaving it to application code:
--   1. one row per (model_group_id, canonical_model_id) pair when matched -- no duplicate
--      proposals for the same candidate;
--   2. one row per model_group_id when it has no candidate at all (canonical_model_id is
--      null) -- a "no candidate" row, not multiple;
--   3. one row per canonical_model_id while *active* (AUTO or APPROVED) -- enforces "at
--      most one active Ice group" without restricting how many PROPOSED/REJECTED rows
--      mention the same canonical model, and without restricting how many *different*
--      canonical models point at the *same* model_group_id (the many-to-one direction is
--      intentionally unrestricted).
-- "No candidate" rows are never inserted (see tools/ice_crosswalk_match.py): a
-- model_group_id simply absent from this table means "no candidate was found", so index 2
-- above is a safety net against the matcher ever writing more than one such row, not a
-- row this migration itself creates.
create table if not exists public.ice_model_crosswalk (
  id bigint generated always as identity primary key,
  model_group_id text not null,
  canonical_model_id text references public.vehicle_models(canonical_id),
  match_method text not null check (match_method in ('SERIES', 'NAME', 'ADMIN')),
  score numeric,
  status text not null check (status in ('AUTO', 'APPROVED', 'PROPOSED', 'REJECTED')),
  master_version text not null,
  -- A stable fingerprint of the inputs that produced this decision (series values,
  -- name score, Ice master_version). Lets the matcher tell "the data behind a REJECTED
  -- row actually changed" (SKILL.md/§14.2: never silently re-propose a rejected mapping
  -- otherwise) from "nothing changed, re-run produced the same inputs" without having to
  -- re-derive history. Nullable: ADMIN-set rows (including the id_changes "แยก" STRUCTURE
  -- proposals below) carry no computed fingerprint.
  decision_fingerprint text,
  -- Concise evidence for the one-time review sheet (§14.2 "4. One-time review sheet");
  -- also carries the id_changes "แยก" explanation for STRUCTURE proposals.
  reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists ice_model_crosswalk_pair_uniq
  on public.ice_model_crosswalk (model_group_id, canonical_model_id)
  where canonical_model_id is not null;

create unique index if not exists ice_model_crosswalk_no_candidate_uniq
  on public.ice_model_crosswalk (model_group_id)
  where canonical_model_id is null;

create unique index if not exists ice_model_crosswalk_active_canonical_uniq
  on public.ice_model_crosswalk (canonical_model_id)
  where canonical_model_id is not null and status in ('AUTO', 'APPROVED');

create index if not exists ice_model_crosswalk_group_idx on public.ice_model_crosswalk (model_group_id);
create index if not exists ice_model_crosswalk_canonical_idx on public.ice_model_crosswalk (canonical_model_id);
create index if not exists ice_model_crosswalk_status_idx on public.ice_model_crosswalk (status);

do $$ begin
  create trigger ice_model_crosswalk_updated before update on public.ice_model_crosswalk
    for each row execute function set_updated_at();
exception when duplicate_object then null; end $$;

-- --------------------------------------------------------------------------
-- Redirect record for a retired Ice model_group_id (SKILL.md §3: "ย้ายประวัติ/
-- บุ๊กมาร์ก/ลิงก์ไปรหัสใหม่"). This table only records WHICH id replaced WHICH --
-- it is the crosswalk/redirect fact, not the bookmark/URL storage itself. Bookmark
-- and public-link redirection (actually rewriting a saved link so a visitor lands on
-- the new id) has no backend contract yet in this repository and is explicitly out of
-- M3's scope (M2/M3 kickoff instruction): that consumption is a handoff to M4/M5, which
-- must read this table rather than inventing a second redirect mechanism.
-- --------------------------------------------------------------------------
create table if not exists public.ice_model_group_redirects (
  old_model_group_id text primary key,
  new_model_group_id text not null,
  change_type text not null check (change_type in ('เปลี่ยนรหัส', 'รวม')),
  reason text,
  created_at timestamptz not null default now()
);

create index if not exists ice_model_group_redirects_new_idx
  on public.ice_model_group_redirects (new_model_group_id);

-- --------------------------------------------------------------------------
-- Brand alias seed (§14.2 "2. Brand alias"). Matching aid only -- never merges brands
-- in Vehicle Master (vehicle_brands/vehicle_models are untouched by this migration and
-- by every M3 tool). Two or more brand strings sharing the same alias_group are treated
-- as the same brand for crosswalk comparison purposes only.
--
-- UNVERIFIED ASSUMPTION, isolated here as in migration_v62: the exact brand strings as
-- Ice actually spells them in reg_trend.brand/ice_dims_brand.brand (casing, spacing, "MG
-- Maxus" vs "Maxus" vs "MAXUS") have never been observed in a real Full Package -- no
-- complete delivery has been imported (M2 state). The rows below use the spellings given
-- in the §14.2 prototype note. If a real delivery uses different spellings,
-- vehreg/ice_crosswalk.py's normalize_brand already lowercases+trims before lookup, but
-- the alias_group rows themselves may need new entries -- nothing else in this migration
-- depends on the exact spelling.
create table if not exists public.ice_brand_aliases (
  brand text primary key,
  alias_group text not null
);

create index if not exists ice_brand_aliases_group_idx on public.ice_brand_aliases (alias_group);

insert into public.ice_brand_aliases (brand, alias_group) values
  ('Deepal', 'deepal_changan'),
  ('Changan', 'deepal_changan'),
  ('MG Maxus', 'maxus_mifa'),
  ('MAXUS', 'maxus_mifa')
on conflict (brand) do nothing;

-- --------------------------------------------------------------------------
-- Discovery ledger (§14.2 "Ongoing, on every Ice import" -- "Ice groups appearing for
-- the first time"). ice_dims_model_group itself has no history (migration_v62 replaces
-- it wholesale on every import, per CLAUDE.md rule 1's "replace whole set" semantics),
-- so "appearing for the first time" cannot be read off that table alone -- a group that
-- disappeared and reappeared, or one that has simply never produced a crosswalk row yet,
-- would be misread as new every run. This ledger durably records the first master_version
-- each model_group_id was ever seen in, independent of whether it has (or ever gets) a
-- crosswalk row at all.
-- --------------------------------------------------------------------------
create table if not exists public.ice_known_model_groups (
  model_group_id text primary key,
  first_seen_master_version text not null,
  first_seen_at timestamptz not null default now()
);

-- --------------------------------------------------------------------------
-- Access: server-side only, same private pattern as migration_v62/v57.
-- --------------------------------------------------------------------------
do $$
declare
  relation_name text;
begin
  foreach relation_name in array array[
    'ice_model_crosswalk', 'ice_model_group_redirects', 'ice_brand_aliases',
    'ice_known_model_groups'
  ] loop
    execute format('alter table public.%I enable row level security', relation_name);
    execute format('revoke all on public.%I from public, anon, authenticated', relation_name);
    execute format('grant select, insert, update, delete on public.%I to service_role', relation_name);
  end loop;
end
$$;

-- --------------------------------------------------------------------------
-- Single-row upsert for one matcher decision. One call per Ice model_group_id (not a
-- batch of all groups in one transaction): each group's decision is independent, so a
-- conflict on one group must never abort another group's otherwise-valid write.
-- Never overwrites an existing APPROVED row or a row an admin already set
-- (match_method = 'ADMIN') -- the auto-matcher (SERIES/NAME) must not flip a human
-- decision, matching §14.2 "ADMIN can explicitly approve/reject/set a mapping".
-- --------------------------------------------------------------------------
create or replace function public.ice_crosswalk_upsert_match(
  p_model_group_id text,
  p_canonical_model_id text,
  p_match_method text,
  p_score numeric,
  p_status text,
  p_master_version text,
  p_decision_fingerprint text,
  p_reason text
)
returns jsonb
language plpgsql
set search_path = public, pg_temp
as $$
declare
  existing_status text;
  existing_method text;
begin
  if p_canonical_model_id is not null then
    select status, match_method into existing_status, existing_method
    from public.ice_model_crosswalk
    where model_group_id = p_model_group_id and canonical_model_id = p_canonical_model_id;
  else
    select status, match_method into existing_status, existing_method
    from public.ice_model_crosswalk
    where model_group_id = p_model_group_id and canonical_model_id is null;
  end if;

  if existing_status = 'APPROVED' or existing_method = 'ADMIN' then
    return jsonb_build_object('applied', false, 'conflict', 'protected_admin_row');
  end if;

  begin
    if p_canonical_model_id is not null then
      insert into public.ice_model_crosswalk
        (model_group_id, canonical_model_id, match_method, score, status, master_version,
         decision_fingerprint, reason)
      values
        (p_model_group_id, p_canonical_model_id, p_match_method, p_score, p_status,
         p_master_version, p_decision_fingerprint, p_reason)
      on conflict (model_group_id, canonical_model_id) where canonical_model_id is not null
      do update set
        match_method = excluded.match_method, score = excluded.score, status = excluded.status,
        master_version = excluded.master_version, decision_fingerprint = excluded.decision_fingerprint,
        reason = excluded.reason, updated_at = now();
    else
      insert into public.ice_model_crosswalk
        (model_group_id, canonical_model_id, match_method, score, status, master_version,
         decision_fingerprint, reason)
      values
        (p_model_group_id, null, p_match_method, p_score, p_status,
         p_master_version, p_decision_fingerprint, p_reason)
      on conflict (model_group_id) where canonical_model_id is null
      do update set
        match_method = excluded.match_method, score = excluded.score, status = excluded.status,
        master_version = excluded.master_version, decision_fingerprint = excluded.decision_fingerprint,
        reason = excluded.reason, updated_at = now();
    end if;
  exception when unique_violation then
    return jsonb_build_object('applied', false, 'conflict', 'canonical_model_already_active_elsewhere');
  end;

  return jsonb_build_object('applied', true, 'conflict', null);
end;
$$;

revoke all on function public.ice_crosswalk_upsert_match(
  text, text, text, numeric, text, text, text, text
) from public, anon, authenticated;
grant execute on function public.ice_crosswalk_upsert_match(
  text, text, text, numeric, text, text, text, text
) to service_role;

-- --------------------------------------------------------------------------
-- One id_changes.csv row (SKILL.md §3, VEHICLE_DB_V3.md §14.2 "5. id_changes handling").
-- Never recomputes registration units -- the replace-whole-set Ice import already
-- contains the corrected history (migration_v62); this only moves crosswalk MAPPING
-- rows and records a redirect fact.
--
--   เปลี่ยนรหัส / รวม: every crosswalk row under the old id is moved to the new id, one
--     row at a time, deleting the old copy *before* inserting its replacement -- so an
--     AUTO/APPROVED row's own canonical_model_id is never briefly duplicated across the
--     old and new id at once, which would otherwise make the active-canonical unique
--     index reject the move as a false self-conflict. A row that would collide with one
--     already under the new id (the "รวม" case where multiple old ids merge) is left
--     as-is rather than duplicated -- its old copy is still deleted. A row that would
--     violate the one-active-group-per-canonical-model rule against some other,
--     unrelated active mapping is deliberately left untouched at the old id (the delete
--     is rolled back together with the failed insert), flagged for manual resolution
--     rather than silently lost. The old id ends up with zero rows in the ordinary
--     (non-conflicting) case -- the id_changes test suite's "no orphan crosswalk rows"
--     case. The old id is retired: a redirect row records old -> new.
--   แยก: the old id is untouched (not moved, not retired -- it keeps selling/registering
--     under both going forward per Ice). For every canonical model currently actively
--     mapped (AUTO/APPROVED) to the old id, this creates one STRUCTURE proposal: a
--     PROPOSED row under the new id for the same canonical model, for human review of
--     whether that TDR model should also map to the new id. STRUCTURE proposals use
--     match_method = 'ADMIN' (score is not computed by any algorithm here; the row exists
--     purely to route a human decision, matching how ADMIN is used for every other
--     human-review-required row) with status = 'PROPOSED' -- never auto-approved.
-- --------------------------------------------------------------------------
create or replace function public.ice_crosswalk_apply_id_change(
  p_old_model_group_id text,
  p_new_model_group_id text,
  p_type text,
  p_master_version text,
  p_reason text default null
)
returns jsonb
language plpgsql
set search_path = public, pg_temp
as $$
declare
  r record;
  moved_count integer := 0;
  conflict_count integer := 0;
  proposal_count integer := 0;
begin
  if p_type not in ('เปลี่ยนรหัส', 'รวม', 'แยก') then
    raise exception using errcode = '22023', message = format('invalid id_changes type: %s', p_type);
  end if;

  if p_type in ('เปลี่ยนรหัส', 'รวม') then
    for r in select * from public.ice_model_crosswalk where model_group_id = p_old_model_group_id loop
      begin
        -- Delete the old row *before* inserting its replacement, both inside this
        -- same exception-catching block: an AUTO/APPROVED row's own canonical_model_id
        -- must not transiently exist twice (once at old_model_group_id, once at
        -- new_model_group_id) while both are present, or the active-canonical unique
        -- index (ice_model_crosswalk_active_canonical_uniq) would reject the insert as
        -- a false self-conflict against the very row being moved. Deleting first means
        -- that index sees at most one row for this canonical_model_id at every instant.
        -- If the insert still raises (a genuinely different, unrelated row elsewhere
        -- holds this canonical_model_id active), PL/pgSQL rolls back the whole block --
        -- including this delete -- so the row ends up untouched at the old id, not
        -- deleted-and-lost.
        delete from public.ice_model_crosswalk where id = r.id;
        if r.canonical_model_id is not null then
          insert into public.ice_model_crosswalk
            (model_group_id, canonical_model_id, match_method, score, status, master_version,
             decision_fingerprint, reason)
          values
            (p_new_model_group_id, r.canonical_model_id, r.match_method, r.score, r.status,
             r.master_version, r.decision_fingerprint, r.reason)
          on conflict (model_group_id, canonical_model_id) where canonical_model_id is not null
          do nothing;
        else
          insert into public.ice_model_crosswalk
            (model_group_id, canonical_model_id, match_method, score, status, master_version,
             decision_fingerprint, reason)
          values
            (p_new_model_group_id, null, r.match_method, r.score, r.status,
             r.master_version, r.decision_fingerprint, r.reason)
          on conflict (model_group_id) where canonical_model_id is null
          do nothing;
        end if;
        moved_count := moved_count + 1;
      exception when unique_violation then
        conflict_count := conflict_count + 1;
      end;
    end loop;

    insert into public.ice_model_group_redirects
      (old_model_group_id, new_model_group_id, change_type, reason)
    values
      (p_old_model_group_id, p_new_model_group_id, p_type, p_reason)
    on conflict (old_model_group_id) do update set
      new_model_group_id = excluded.new_model_group_id,
      change_type = excluded.change_type,
      reason = excluded.reason,
      created_at = now();
  else
    for r in
      select * from public.ice_model_crosswalk
      where model_group_id = p_old_model_group_id
        and canonical_model_id is not null
        and status in ('AUTO', 'APPROVED')
    loop
      insert into public.ice_model_crosswalk
        (model_group_id, canonical_model_id, match_method, score, status, master_version,
         decision_fingerprint, reason)
      values
        (p_new_model_group_id, r.canonical_model_id, 'ADMIN', null, 'PROPOSED', p_master_version, null,
         coalesce(p_reason, format(
           'STRUCTURE PROPOSAL -- NOT YET APPROVED: id_changes แยก split %s -> %s. '
           'A human must decide whether %s should also map to %s; match_method is ''ADMIN'' '
           'only because this came from an id_changes event rather than the SERIES/NAME '
           'matcher, not because an admin has reviewed or approved it.',
           p_old_model_group_id, p_new_model_group_id, r.canonical_model_id, p_new_model_group_id)))
      on conflict (model_group_id, canonical_model_id) where canonical_model_id is not null
      do nothing;
      proposal_count := proposal_count + 1;
    end loop;
  end if;

  return jsonb_build_object(
    'type', p_type,
    'old_model_group_id', p_old_model_group_id,
    'new_model_group_id', p_new_model_group_id,
    'moved', moved_count,
    'conflicts', conflict_count,
    'structure_proposals', proposal_count
  );
end;
$$;

revoke all on function public.ice_crosswalk_apply_id_change(
  text, text, text, text, text
) from public, anon, authenticated;
grant execute on function public.ice_crosswalk_apply_id_change(
  text, text, text, text, text
) to service_role;
