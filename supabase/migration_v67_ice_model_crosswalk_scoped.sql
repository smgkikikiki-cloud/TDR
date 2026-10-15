-- v67: Ice scoped crosswalk -- owner decisions keyed by (Ice model_group_id, registration class).
-- Why: v63 ice_model_crosswalk allows ONE Ice group per canonical model and cannot say "รย.1 -> A, รย.3 -> B".
--      Owner decisions (244-row audit + 430 approved overrides) need many Ice groups -> one model.
-- Numbering: production ledger (checked 2026-10-14) ends at v64. v65/v66 exist in the repo but are NOT applied; v67 does not clash.
-- Safe to re-run. Does not touch v63 tables. Rollback: supabase/rollback_v67_ice_model_crosswalk_scoped.sql
-- Not applied by this PR. Apply only on owner "go".

begin;

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
  constraint ice_scoped_reg_type_format check (reg_type_scope = 'ALL' or reg_type_scope ~ '^รย\.[0-9]+$'),
  constraint ice_scoped_nonblank_source check (btrim(model_group_id) <> '' and btrim(decision_ref) <> '' and btrim(master_version) <> ''),
  constraint ice_scoped_status_target_check check (
    (status = 'APPROVED' and canonical_model_id is not null and pending_target_id is null)
    or (status = 'EXCLUDED' and canonical_model_id is null and pending_target_id is null)
    or (status = 'PENDING' and canonical_model_id is null)
  )
);

-- Provenance (who decided, from which package) never changes; a decision may only move PENDING -> APPROVED.
create or replace function public.ice_scoped_crosswalk_keep_provenance()
returns trigger language plpgsql security invoker set search_path = public as $$
begin
  if new.model_group_id is distinct from old.model_group_id
     or new.reg_type_scope is distinct from old.reg_type_scope
     or new.master_version is distinct from old.master_version
     or new.decision_ref is distinct from old.decision_ref
     or new.source_sha256 is distinct from old.source_sha256
     or new.created_at is distinct from old.created_at then
    raise exception 'scoped crosswalk decision provenance is immutable';
  end if;
  if old.status <> new.status and not (old.status = 'PENDING' and new.status = 'APPROVED') then
    raise exception 'scoped crosswalk status may only move PENDING -> APPROVED';
  end if;
  new.updated_at := now();
  return new;
end $$;

drop trigger if exists ice_scoped_crosswalk_provenance_immutable on public.ice_model_crosswalk_scoped;
create trigger ice_scoped_crosswalk_provenance_immutable
  before update on public.ice_model_crosswalk_scoped
  for each row execute function public.ice_scoped_crosswalk_keep_provenance();

-- Many source scopes may point at one model: the key is the SOURCE scope, never the target.
create index if not exists ice_scoped_canonical_idx on public.ice_model_crosswalk_scoped (canonical_model_id) where canonical_model_id is not null;
create index if not exists ice_scoped_master_version_idx on public.ice_model_crosswalk_scoped (master_version);

alter table public.ice_model_crosswalk_scoped enable row level security;
revoke all on public.ice_model_crosswalk_scoped from public, anon, authenticated;
-- Writer: the monthly import job (service role). No DELETE: a decision is never erased, only superseded by a new master_version.
grant select, insert, update on public.ice_model_crosswalk_scoped to service_role;

commit;
