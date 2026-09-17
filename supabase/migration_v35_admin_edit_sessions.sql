-- Server-side storage for the Canonical Vehicle Editor's review-before-queue
-- step (app/admin/vehicle-editor-actions.ts, lib/edit-session-store.ts).
--
-- The review page carries only an opaque id; the proposal's canonical command
-- payload, diff, evidence and reason are read back server-side, and every
-- check (ownership, expiry, one-time consumption, active-release match) is
-- enforced in application code against this table rather than trusted from
-- client state.
--
-- Same admin-only, service-role-only access pattern as
-- migration_v22_unified_vehicle_input.sql's canonical_input_batches: no
-- anon/authenticated grants, RLS enabled with zero policies (default deny),
-- application code enforces per-admin ownership since the server always
-- connects with the service-role key.
--
-- NOT applied to production by this branch.

create table if not exists public.admin_edit_sessions (
  id text primary key,
  kind text not null check (kind in ('MODEL_GENERATION', 'TRIM')),
  status text not null default 'PENDING_REVIEW'
    check (status in ('PENDING_REVIEW', 'CONSUMED')),
  model_id text not null,
  trim_id text,
  actor text not null,
  page_release_id text not null,

  -- The immutable, already-compiled canonical batch this proposal will submit,
  -- and the human-readable diff the review page shows.
  batch_payload jsonb not null check (jsonb_typeof(batch_payload) = 'object'),
  diff jsonb not null check (jsonb_typeof(diff) = 'array'),
  reason text not null,
  evidence jsonb not null,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  expires_at timestamptz not null,
  consumed_at timestamptz,

  constraint admin_edit_sessions_consumed_has_timestamp
    check (status <> 'CONSUMED' or consumed_at is not null)
);

create index if not exists admin_edit_sessions_owner_idx
  on public.admin_edit_sessions(actor, status, model_id);
create index if not exists admin_edit_sessions_expiry_idx
  on public.admin_edit_sessions(expires_at);

alter table public.admin_edit_sessions enable row level security;
revoke all on table public.admin_edit_sessions from public, anon, authenticated;
grant select, insert, update, delete on table public.admin_edit_sessions to service_role;

comment on table public.admin_edit_sessions is
  'Server-only: pending Canonical Vehicle Editor proposals awaiting human review before entering canonical_input_batches. An admin''s review URL carries only this table''s id -- never the payload, diff, evidence or reason.';
