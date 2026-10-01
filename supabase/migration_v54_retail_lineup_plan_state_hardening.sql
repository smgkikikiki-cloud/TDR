-- Harden Chunk-5 durable preview state after the initial v53 table/RPCs.
--
-- The immutable compiler payload was already write-once in v53. This migration
-- closes the same-status audit-field hole as well: a privileged caller must not
-- be able to rewrite who approved a plan, the commit SHA, or the release ID by
-- issuing an UPDATE that leaves status unchanged. Every audit mutation now has
-- to be part of the one transition that owns it.

create or replace function public.tdr_guard_retail_lineup_plan_update()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if new.import_run_id is distinct from old.import_run_id
     or new.actor is distinct from old.actor
     or new.source_sha256 is distinct from old.source_sha256
     or new.baseline_hash is distinct from old.baseline_hash
     or new.plan_hash is distinct from old.plan_hash
     or new.compiled_plan is distinct from old.compiled_plan
     or new.summary is distinct from old.summary
     or new.created_at is distinct from old.created_at then
    raise exception 'RETAIL_LINEUP_PLAN_IMMUTABLE: create a new preview instead of editing compiled plan state';
  end if;

  -- Audit fields may never be rewritten while staying in the same state.
  if new.status is not distinct from old.status then
    if new.approved_at is distinct from old.approved_at
       or new.approved_by is distinct from old.approved_by
       or new.applying_at is distinct from old.applying_at
       or new.written_at is distinct from old.written_at
       or new.completed_at is distinct from old.completed_at
       or new.applied_commit_sha is distinct from old.applied_commit_sha
       or new.release_id is distinct from old.release_id
       or new.error is distinct from old.error then
      raise exception 'RETAIL_LINEUP_STATE_UPDATE_REQUIRES_TRANSITION';
    end if;
    new.updated_at := now();
    return new;
  end if;

  if old.status = 'PREVIEW_READY' and new.status not in ('APPLYING','STALE','CANCELLED') then
    raise exception 'invalid retail lineup plan transition % -> %', old.status, new.status;
  elsif old.status = 'FAILED' and new.status not in ('APPLYING','STALE','CANCELLED') then
    raise exception 'invalid retail lineup plan transition % -> %', old.status, new.status;
  elsif old.status = 'APPLYING' and new.status not in ('WRITTEN_PENDING_PUBLISH','FAILED','STALE') then
    raise exception 'invalid retail lineup plan transition % -> %', old.status, new.status;
  elsif old.status = 'WRITTEN_PENDING_PUBLISH' and new.status <> 'COMPLETED' then
    raise exception 'invalid retail lineup plan transition % -> %', old.status, new.status;
  elsif old.status in ('COMPLETED','STALE','CANCELLED') then
    raise exception 'terminal retail lineup plan % cannot transition to %', old.status, new.status;
  end if;

  -- Approval ownership belongs only to PREVIEW/FAILED -> APPLYING.
  if not (old.status in ('PREVIEW_READY','FAILED') and new.status = 'APPLYING') then
    if new.approved_at is distinct from old.approved_at
       or new.approved_by is distinct from old.approved_by
       or new.applying_at is distinct from old.applying_at then
      raise exception 'RETAIL_LINEUP_APPROVAL_AUDIT_IMMUTABLE';
    end if;
  end if;

  -- Repository identity belongs only to APPLYING -> WRITTEN_PENDING_PUBLISH.
  if not (old.status = 'APPLYING' and new.status = 'WRITTEN_PENDING_PUBLISH') then
    if new.written_at is distinct from old.written_at
       or new.applied_commit_sha is distinct from old.applied_commit_sha then
      raise exception 'RETAIL_LINEUP_COMMIT_AUDIT_IMMUTABLE';
    end if;
  end if;

  -- Serving-release identity belongs only to WRITTEN_PENDING_PUBLISH -> COMPLETED.
  if not (old.status = 'WRITTEN_PENDING_PUBLISH' and new.status = 'COMPLETED') then
    if new.completed_at is distinct from old.completed_at
       or new.release_id is distinct from old.release_id then
      raise exception 'RETAIL_LINEUP_RELEASE_AUDIT_IMMUTABLE';
    end if;
  end if;

  new.updated_at := now();
  return new;
end;
$$;

-- A retry from FAILED is a fresh explicit approval attempt. Record its own
-- approver/time instead of keeping the first failed attempt's timestamp while
-- silently replacing approved_by.
create or replace function public.tdr_begin_retail_lineup_plan_apply(
  p_plan_id uuid,
  p_actor text,
  p_expected_plan_hash text,
  p_expected_baseline_hash text
)
returns setof public.retail_lineup_plans
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  changed integer;
begin
  if btrim(coalesce(p_actor, '')) = '' then
    raise exception 'admin actor is required';
  end if;

  return query
  update public.retail_lineup_plans
  set status = 'APPLYING',
      approved_at = now(),
      approved_by = p_actor,
      applying_at = now(),
      error = null
  where id = p_plan_id
    and status in ('PREVIEW_READY','FAILED')
    and plan_hash = p_expected_plan_hash
    and baseline_hash = p_expected_baseline_hash
  returning *;

  get diagnostics changed = row_count;
  if changed <> 1 then
    raise exception 'RETAIL_LINEUP_PLAN_NOT_APPLICABLE: stale hash, terminal state, or unknown plan';
  end if;
end;
$$;

revoke all on function public.tdr_guard_retail_lineup_plan_update() from public, anon, authenticated;
revoke all on function public.tdr_begin_retail_lineup_plan_apply(uuid,text,text,text)
  from public, anon, authenticated;
grant execute on function public.tdr_begin_retail_lineup_plan_apply(uuid,text,text,text)
  to service_role;
