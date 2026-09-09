-- Phase C: canonical write pipeline bridge.
--
-- These tables do not become a second vehicle master.  They only bridge the
-- existing TDR admin surface to the file-backed canonical Vehicle Master while
-- consolidation is in progress: verified ID mapping, command intake, immutable
-- revision audit, and publish outbox.
--
-- No public policies are created.  Browser/anon clients must not be able to
-- inspect or submit canonical commands; server-side admin/service-role code is
-- the only intended caller.

create extension if not exists pgcrypto;

create table if not exists canonical_object_map (
  id uuid primary key default gen_random_uuid(),
  source_table text not null check (source_table in ('brands','models','model_powertrains','trims')),
  source_id uuid not null,
  canonical_entity_type text not null check (canonical_entity_type in ('brand','model','generation','variant','market_trim')),
  canonical_id text,
  status text not null default 'unmatched' check (status in ('verified','ambiguous','unmatched','retired')),
  match_basis jsonb not null default '{}'::jsonb,
  verified_by text,
  verified_at timestamptz,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (source_table, source_id, canonical_entity_type),
  check ((status = 'verified' and canonical_id is not null and verified_at is not null)
      or status <> 'verified')
);

create unique index if not exists canonical_object_map_verified_target_uq
  on canonical_object_map (canonical_entity_type, canonical_id)
  where status = 'verified';

create index if not exists canonical_object_map_source_idx
  on canonical_object_map (source_table, source_id, status);

create table if not exists canonical_write_commands (
  id uuid primary key default gen_random_uuid(),
  command_key text not null unique,
  source_table text,
  source_id uuid,
  canonical_entity_type text not null check (canonical_entity_type in ('brand','model','generation','variant','market_trim','price','spec')),
  canonical_id text,
  operation text not null check (operation in ('UPSERT_MODEL_BUNDLE','WITHDRAW_MODEL','APPEND_PRICE','APPEND_SPEC')),
  payload jsonb not null,
  actor text not null default 'tdr-admin',
  reason text,
  status text not null default 'queued' check (status in ('queued','needs_crosswalk','applied','rejected','superseded')),
  revision_id text,
  error text,
  created_at timestamptz not null default now(),
  applied_at timestamptz,
  check (source_table is null or source_table in ('brands','models','model_powertrains','trims')),
  check ((status = 'applied' and revision_id is not null and applied_at is not null)
      or status <> 'applied')
);

create index if not exists canonical_write_commands_status_idx
  on canonical_write_commands (status, created_at);
create index if not exists canonical_write_commands_source_idx
  on canonical_write_commands (source_table, source_id, created_at desc);

create table if not exists canonical_write_revisions (
  id uuid primary key default gen_random_uuid(),
  revision_id text not null unique,
  command_id uuid not null unique references canonical_write_commands(id) on delete restrict,
  topic text not null check (topic in ('catalog','price','spec')),
  entity_type text not null,
  entity_id text not null,
  before_hash text not null,
  after_hash text not null,
  before_payload jsonb,
  after_payload jsonb not null,
  actor text not null,
  reason text,
  created_at timestamptz not null default now()
);

create index if not exists canonical_write_revisions_entity_idx
  on canonical_write_revisions (entity_type, entity_id, created_at desc);

create table if not exists canonical_publish_outbox (
  id uuid primary key default gen_random_uuid(),
  event_key text not null unique,
  revision_id text not null references canonical_write_revisions(revision_id) on delete restrict,
  topic text not null check (topic in ('catalog','price','spec')),
  entity_type text not null,
  entity_id text not null,
  payload jsonb not null,
  state text not null default 'pending' check (state in ('pending','published','failed','superseded')),
  attempts integer not null default 0 check (attempts >= 0),
  last_error text,
  created_at timestamptz not null default now(),
  published_at timestamptz
);

create index if not exists canonical_publish_outbox_state_idx
  on canonical_publish_outbox (state, created_at);

alter table canonical_object_map enable row level security;
alter table canonical_write_commands enable row level security;
alter table canonical_write_revisions enable row level security;
alter table canonical_publish_outbox enable row level security;

-- Intentionally no anon/authenticated policies.  The Next.js admin action uses
-- the server-only service role.  Later phases may add narrower authenticated
-- RPCs, but Phase C must not turn this command/audit surface into a public API.

comment on table canonical_object_map is
  'Verified bridge from legacy TDR UUIDs to stable Vehicle Master IDs. Matching candidates are never authority until status=verified.';
comment on table canonical_write_commands is
  'Phase-C command intake. Shadow-mode admin writes enqueue here before legacy duplicate writes are retired.';
comment on table canonical_write_revisions is
  'Immutable audit mirror of successful canonical Vehicle Master revisions.';
comment on table canonical_publish_outbox is
  'Outbox for later staged serving publishers. Phase C does not publish market/registration data.';
