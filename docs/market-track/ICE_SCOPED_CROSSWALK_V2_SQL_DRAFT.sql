-- DESIGN CANDIDATE ONLY. DO NOT APPLY. DO NOT RENAME AS A MIGRATION WITHOUT
-- C01/C02 GOVERNANCE RESOLUTION AND OWNER-AUTHORIZED MARKET TRACK R6 WORK.
-- Source: docs/market-track/ICE_SCOPED_CROSSWALK_V2.md.
-- All commands here are documentation, not execution authorization.

begin;

-- A reviewed effective mapping, not a table of fuzzy candidates.
-- Ice replaces its group dimension on new imports, so historical IDs must remain
-- available for audit and redirects; no FK to the replace-whole-set dimension.
create table if not exists public.ice_model_crosswalk_scoped (
  model_group_id text not null,
  reg_type_scope text not null,
  status text not null check (status in ('APPROVED', 'EXCLUDED', 'PENDING')),
  canonical_model_id text references public.vehicle_models (canonical_id),
  pending_target_id text,
  master_version text not null,
  decision_ref text not null,
  source_sha256 text not null check (source_sha256 ~ '^[0-9a-f]{64}$'),
  reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (model_group_id, reg_type_scope),
  constraint ice_scoped_reg_type_format check (
    reg_type_scope = 'ALL' or reg_type_scope ~ '^รย\.[0-9]+$'
  ),
  constraint ice_scoped_nonblank_source check (
    btrim(model_group_id) <> '' and btrim(decision_ref) <> ''
    and btrim(master_version) <> ''
  ),
  constraint ice_scoped_status_target_check check (
    (status = 'APPROVED' and canonical_model_id is not null and pending_target_id is null)
    or (status = 'EXCLUDED' and canonical_model_id is null and pending_target_id is null)
    or (status = 'PENDING' and canonical_model_id is null)
  )
);

-- MANY Ice groups/registration scopes may intentionally target ONE canonical.
-- The unique key is the SOURCE grain, never the target canonical ID.
-- Do not drop/change the v63 active-canonical index under this draft.
create index if not exists ice_scoped_canonical_idx
  on public.ice_model_crosswalk_scoped (canonical_model_id)
  where canonical_model_id is not null;
create index if not exists ice_scoped_master_version_idx
  on public.ice_model_crosswalk_scoped (master_version);

-- This draft is read-only even for service_role. A separate, governed,
-- audited writer must be approved before exposing insert/update/delete.
alter table public.ice_model_crosswalk_scoped enable row level security;
revoke all on public.ice_model_crosswalk_scoped from public, anon, authenticated;
revoke insert, update, delete on public.ice_model_crosswalk_scoped from service_role;
grant select on public.ice_model_crosswalk_scoped to service_role;

commit;
