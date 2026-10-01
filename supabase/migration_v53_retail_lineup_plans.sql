-- Durable immutable preview plans for the Retail Lineup Bootstrap.
--
-- Chunk 5 deliberately stops before Admin UI / source-import integration.
-- The compiler (Chunk 3) produces an immutable plan; this table is the durable
-- server-only handoff that lets a later request review and approve exactly that
-- plan instead of recompiling whatever the workbook/canonical tree looks like
-- at click time.
--
-- The source workbook may later be linked to import_runs by Chunk 7. Keep that
-- FK nullable here so the state primitive is usable/testable before the new
-- source_kind is wired into the ordinary import worker.

create table if not exists public.retail_lineup_plans (
  id uuid primary key default gen_random_uuid(),
  import_run_id uuid references public.import_runs(id) on delete restrict,

  status text not null default 'PREVIEW_READY'
    check (status in (
      'PREVIEW_READY',
      'APPLYING',
      'WRITTEN_PENDING_PUBLISH',
      'COMPLETED',
      'FAILED',
      'STALE',
      'CANCELLED'
    )),

  -- Admin who caused the preview to be compiled. Approval is recorded
  -- separately so a different authorised admin may explicitly apply it later.
  actor text not null check (btrim(actor) <> ''),

  -- Immutable identity of the uploaded source and the exact compiler result.
  source_sha256 text not null
    check (source_sha256 ~ '^[0-9a-f]{64}$'),
  baseline_hash text not null
    check (baseline_hash ~ '^[0-9a-f]{64}$'),
  plan_hash text not null
    check (plan_hash ~ '^[0-9a-f]{64}$'),
  compiled_plan jsonb not null
    check (jsonb_typeof(compiled_plan) = 'object'),
  summary jsonb not null default '{}'::jsonb
    check (jsonb_typeof(summary) = 'object'),

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  approved_at timestamptz,
  approved_by text,
  applying_at timestamptz,
  written_at timestamptz,
  completed_at timestamptz,

  -- Filled only after the exact previewed plan has reached the repository and
  -- then the serving release. A failed Git push must never claim completion.
  applied_commit_sha text,
  release_id text,
  error text,

  constraint retail_lineup_plan_hash_matches_payload
    check ((compiled_plan ->> 'plan_hash') = plan_hash),
  constraint retail_lineup_baseline_matches_payload
    check ((compiled_plan ->> 'baseline_hash') = baseline_hash),
  constraint retail_lineup_plan_schema_v1
    check ((compiled_plan ->> 'schema_version') = '1'),
  constraint retail_lineup_plan_has_models
    check (jsonb_typeof(compiled_plan -> 'models') = 'array'
           and jsonb_array_length(compiled_plan -> 'models') > 0),
  constraint retail_lineup_apply_has_approval
    check (status <> 'APPLYING'
           or (approved_at is not null and applying_at is not null
               and approved_by is not null and btrim(approved_by) <> '')),
  constraint retail_lineup_written_has_commit
    check (status <> 'WRITTEN_PENDING_PUBLISH'
           or (written_at is not null and applied_commit_sha is not null
               and applied_commit_sha ~ '^[0-9a-f]{40,64}$')),
  constraint retail_lineup_completed_has_publish_identity
    check (status <> 'COMPLETED'
           or (completed_at is not null and applied_commit_sha is not null
               and applied_commit_sha ~ '^[0-9a-f]{40,64}$'
               and release_id is not null and btrim(release_id) <> ''))
);

create unique index if not exists retail_lineup_plans_import_run_key
  on public.retail_lineup_plans(import_run_id)
  where import_run_id is not null;

create index if not exists retail_lineup_plans_status_created_idx
  on public.retail_lineup_plans(status, created_at desc);

create index if not exists retail_lineup_plans_actor_created_idx
  on public.retail_lineup_plans(actor, created_at desc);

-- The preview payload and all of its hashes are write-once.  Service-role
-- access intentionally does not bypass this trigger: even privileged code must
-- create a new preview if any compiled content changes.
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

  if new.status is distinct from old.status then
    if old.status = 'PREVIEW_READY' and new.status not in ('APPLYING','STALE','CANCELLED') then
      raise exception 'invalid retail lineup plan transition % -> %', old.status, new.status;
    elsif old.status = 'FAILED' and new.status not in ('APPLYING','STALE','CANCELLED') then
      raise exception 'invalid retail lineup plan transition % -> %', old.status, new.status;
    elsif old.status = 'APPLYING' and new.status not in ('WRITTEN_PENDING_PUBLISH','FAILED','STALE') then
      raise exception 'invalid retail lineup plan transition % -> %', old.status, new.status;
    elsif old.status = 'WRITTEN_PENDING_PUBLISH' and new.status not in ('COMPLETED') then
      raise exception 'invalid retail lineup plan transition % -> %', old.status, new.status;
    elsif old.status in ('COMPLETED','STALE','CANCELLED') then
      raise exception 'terminal retail lineup plan % cannot transition to %', old.status, new.status;
    end if;
  end if;

  new.updated_at := now();
  return new;
end;
$$;

revoke all on function public.tdr_guard_retail_lineup_plan_update() from public, anon, authenticated;

drop trigger if exists retail_lineup_plans_guard_update on public.retail_lineup_plans;
create trigger retail_lineup_plans_guard_update
before update on public.retail_lineup_plans
for each row execute function public.tdr_guard_retail_lineup_plan_update();

-- Atomic compare-and-set used by the Admin confirmation action.  The caller
-- must present both hashes it reviewed.  No row => no apply; there is no
-- fallback that recompiles a newer plan behind the operator's back.
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
      approved_at = coalesce(approved_at, now()),
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

-- Repository write completed.  Publishing is deliberately a separate state,
-- matching import_runs' WRITTEN_PENDING_PUBLISH rule.
create or replace function public.tdr_mark_retail_lineup_plan_written(
  p_plan_id uuid,
  p_expected_plan_hash text,
  p_commit_sha text
)
returns setof public.retail_lineup_plans
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  changed integer;
begin
  if coalesce(p_commit_sha, '') !~ '^[0-9a-f]{40,64}$' then
    raise exception 'invalid commit sha';
  end if;

  return query
  update public.retail_lineup_plans
  set status = 'WRITTEN_PENDING_PUBLISH',
      written_at = now(),
      applied_commit_sha = p_commit_sha,
      error = null
  where id = p_plan_id
    and status = 'APPLYING'
    and plan_hash = p_expected_plan_hash
  returning *;

  get diagnostics changed = row_count;
  if changed <> 1 then
    raise exception 'RETAIL_LINEUP_PLAN_NOT_APPLYING';
  end if;
end;
$$;

create or replace function public.tdr_complete_retail_lineup_plan(
  p_plan_id uuid,
  p_expected_plan_hash text,
  p_commit_sha text,
  p_release_id text
)
returns setof public.retail_lineup_plans
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  changed integer;
begin
  if btrim(coalesce(p_release_id, '')) = '' then
    raise exception 'release id is required';
  end if;

  return query
  update public.retail_lineup_plans
  set status = 'COMPLETED',
      completed_at = now(),
      release_id = p_release_id,
      error = null
  where id = p_plan_id
    and status = 'WRITTEN_PENDING_PUBLISH'
    and plan_hash = p_expected_plan_hash
    and applied_commit_sha = p_commit_sha
  returning *;

  get diagnostics changed = row_count;
  if changed <> 1 then
    raise exception 'RETAIL_LINEUP_PLAN_PUBLISH_MISMATCH';
  end if;
end;
$$;

create or replace function public.tdr_fail_retail_lineup_plan_apply(
  p_plan_id uuid,
  p_expected_plan_hash text,
  p_error text
)
returns setof public.retail_lineup_plans
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  changed integer;
begin
  return query
  update public.retail_lineup_plans
  set status = 'FAILED',
      error = left(coalesce(p_error, 'apply failed'), 4000)
  where id = p_plan_id
    and status = 'APPLYING'
    and plan_hash = p_expected_plan_hash
  returning *;

  get diagnostics changed = row_count;
  if changed <> 1 then
    raise exception 'RETAIL_LINEUP_PLAN_NOT_APPLYING';
  end if;
end;
$$;

create or replace function public.tdr_mark_retail_lineup_plan_stale(
  p_plan_id uuid,
  p_expected_plan_hash text,
  p_error text
)
returns setof public.retail_lineup_plans
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  changed integer;
begin
  return query
  update public.retail_lineup_plans
  set status = 'STALE',
      error = left(coalesce(p_error, 'STALE_BASELINE'), 4000)
  where id = p_plan_id
    and status in ('PREVIEW_READY','FAILED','APPLYING')
    and plan_hash = p_expected_plan_hash
  returning *;

  get diagnostics changed = row_count;
  if changed <> 1 then
    raise exception 'RETAIL_LINEUP_PLAN_NOT_STALEABLE';
  end if;
end;
$$;

alter table public.retail_lineup_plans enable row level security;
revoke all on table public.retail_lineup_plans from public, anon, authenticated;
grant select, insert, update on table public.retail_lineup_plans to service_role;

revoke all on function public.tdr_begin_retail_lineup_plan_apply(uuid,text,text,text)
  from public, anon, authenticated;
revoke all on function public.tdr_mark_retail_lineup_plan_written(uuid,text,text)
  from public, anon, authenticated;
revoke all on function public.tdr_complete_retail_lineup_plan(uuid,text,text,text)
  from public, anon, authenticated;
revoke all on function public.tdr_fail_retail_lineup_plan_apply(uuid,text,text)
  from public, anon, authenticated;
revoke all on function public.tdr_mark_retail_lineup_plan_stale(uuid,text,text)
  from public, anon, authenticated;

grant execute on function public.tdr_begin_retail_lineup_plan_apply(uuid,text,text,text)
  to service_role;
grant execute on function public.tdr_mark_retail_lineup_plan_written(uuid,text,text)
  to service_role;
grant execute on function public.tdr_complete_retail_lineup_plan(uuid,text,text,text)
  to service_role;
grant execute on function public.tdr_fail_retail_lineup_plan_apply(uuid,text,text)
  to service_role;
grant execute on function public.tdr_mark_retail_lineup_plan_stale(uuid,text,text)
  to service_role;

comment on table public.retail_lineup_plans is
  'Server-only immutable Retail Lineup Bootstrap preview plans. Canonical apply must execute the stored compiled_plan identified by source/baseline/plan hashes; changing the proposal requires creating a new preview row.';
