-- One server-only intake ledger for Vehicle Master market facts.
-- Registration ingestion remains intentionally separate.

create table if not exists public.canonical_input_batches (
  id uuid primary key default gen_random_uuid(),
  batch_key text not null unique,
  domain text not null default 'VEHICLE_MARKET'
    check (domain = 'VEHICLE_MARKET'),
  source_kind text not null
    check (source_kind in ('ADMIN','ECO','OEM','MEDIA','PRICE_HARVEST','MIGRATION','API')),
  source_ref text,
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  payload_sha256 text not null check (payload_sha256 ~ '^[0-9a-f]{64}$'),
  item_count integer not null check (item_count between 1 and 500),
  actor text not null,
  status text not null default 'QUEUED'
    check (status in ('QUEUED','PROCESSING','STAGED','PUBLISHED','NEEDS_REVIEW','REJECTED','FAILED')),
  pull_request_url text,
  release_id text,
  error text,
  attempts integer not null default 0 check (attempts >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  processing_started_at timestamptz,
  staged_at timestamptz,
  published_at timestamptz,
  constraint canonical_input_batch_payload_key_check
    check (coalesce(payload ->> 'batch_id', '') = batch_key),
  constraint canonical_input_batch_registration_separation_check
    check (upper(coalesce(payload #>> '{source,kind}', '')) not in ('DLT','REGISTRATION'))
);

create index if not exists canonical_input_batches_work_idx
  on public.canonical_input_batches(status, created_at);

alter table public.canonical_input_batches enable row level security;
revoke all on table public.canonical_input_batches from public, anon, authenticated;
grant select, insert, update, delete on table public.canonical_input_batches to service_role;

comment on table public.canonical_input_batches is
  'Server-only idempotent intake for canonical vehicle-market command batches. DLT registration facts never enter this table.';
