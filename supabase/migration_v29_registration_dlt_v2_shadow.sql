-- Phase 2: DLT v2 shadow pipeline (observation -> canonical resolution ->
-- registration fact v2), running alongside the existing production
-- registration path, not instead of it.
--
-- This migration is purely additive: three new, service-role-only shadow
-- tables. It does not touch `registrations`, `registration_brand_aliases`,
-- `registration_model_aliases`, `match_registration_model`,
-- `ingest_registration_snapshot`, or any of the `registration_*` analytics
-- views. Nothing here is granted to `anon`/`authenticated` - these are
-- internal shadow tables for the backfill/dual-run tooling
-- (`automotive/vehicle_master/tools/backfill_registration_v2.py`,
-- `.../registration_v2_dlt_ingest.py`, `.../registration_v2_parity.py`),
-- not a new public API, matching the access model
-- `registration_brand_aliases`/`registration_model_aliases` already use.
--
-- Design (`docs/vehicle-platform/DLT_V2_ARCHITECTURE.md`):
--
--   registration_observations_v2  raw, immutable source rows, one per
--                                  DLT/legacy-registration row actually
--                                  read. Never mutated after insert.
--   registration_facts_v2         the resolved fact for an observation,
--                                  addressed by canonical Vehicle Master
--                                  text id (never a legacy `models.id`
--                                  uuid) at the grain the source actually
--                                  proved (BRAND/MODEL/VARIANT). A row
--                                  exists here only when resolution
--                                  produced a canonical id at all -
--                                  Invariant 6: an observation whose brand
--                                  could not even be placed gets no fact
--                                  row, its units stay visible only on the
--                                  observation itself.
--   registration_resolution_review_v2   one row per observation whose
--                                  resolution stopped short of the deepest
--                                  grain the raw text plausibly claimed -
--                                  a model ambiguity, a brand that could
--                                  not be found, a variant the catalog does
--                                  not have. A row can exist here *and* in
--                                  facts_v2 at once (a brand-only fact with
--                                  a "model-not-found" review row) -
--                                  exactly ingest_review's own local
--                                  pattern in `vehreg/db.py`.
--
-- Every row is keyed by a deterministic id computed from the source's own
-- identity (`vehreg/registration_observation.py::observation_id`), never a
-- random uuid - re-running the backfill or a DLT ingest over the same
-- source therefore upserts the same rows instead of duplicating them.

create table if not exists public.registration_observations_v2 (
  observation_id     text primary key,
  source_kind        text not null check (source_kind in
                        ('dlt_ckan', 'dlt_csv', 'legacy_registrations_backfill')),
  source_ref         text not null,
  period             text not null,               -- 'YYYY-MM'
  registration_type  text not null,
  province           text not null default 'ALL',
  raw_brand          text not null default '',
  raw_model          text not null default '',
  raw_variant        text not null default '',
  raw_label          text not null default '',
  units              numeric not null,
  normalized_brand   text not null default '',
  normalized_model   text not null default '',
  payload_hash       text not null,
  source_metadata    jsonb not null default '{}'::jsonb,
  ingested_at        timestamptz not null default now()
);
create index if not exists registration_observations_v2_period_idx
  on public.registration_observations_v2(period);
create index if not exists registration_observations_v2_source_idx
  on public.registration_observations_v2(source_kind, source_ref);

create table if not exists public.registration_facts_v2 (
  observation_id     text primary key
                        references public.registration_observations_v2(observation_id)
                        on delete cascade,
  period             text not null,
  registration_type  text not null,
  province           text not null default 'ALL',
  canonical_id       text not null,                -- Vehicle Master text id; never a legacy uuid
  grain              text not null check (grain in ('BRAND', 'MODEL', 'VARIANT')),
  units              numeric not null,
  match_how          text not null,
  match_score        numeric,
  resolution_reason  text not null default '',
  trim_detail        jsonb,                         -- MODEL-grain trim-detail-brand evidence only
  resolved_at        timestamptz not null default now()
);
create index if not exists registration_facts_v2_canonical_period_idx
  on public.registration_facts_v2(canonical_id, period);
create index if not exists registration_facts_v2_period_idx
  on public.registration_facts_v2(period, registration_type);

create table if not exists public.registration_resolution_review_v2 (
  observation_id     text primary key
                        references public.registration_observations_v2(observation_id)
                        on delete cascade,
  reason             text not null,
  candidates         jsonb not null default '[]'::jsonb,
  best_grain         text,
  best_canonical_id  text,
  match_score        numeric,
  reviewed_at        timestamptz not null default now()
);
create index if not exists registration_resolution_review_v2_reason_idx
  on public.registration_resolution_review_v2(reason);

alter table public.registration_observations_v2 enable row level security;
alter table public.registration_facts_v2 enable row level security;
alter table public.registration_resolution_review_v2 enable row level security;

revoke all on table public.registration_observations_v2 from anon, authenticated;
revoke all on table public.registration_facts_v2 from anon, authenticated;
revoke all on table public.registration_resolution_review_v2 from anon, authenticated;

grant select, insert, update, delete on table public.registration_observations_v2 to service_role;
grant select, insert, update, delete on table public.registration_facts_v2 to service_role;
grant select, insert, update, delete on table public.registration_resolution_review_v2 to service_role;

comment on table public.registration_observations_v2 is
  'DLT v2 shadow pipeline (Phase 2): immutable raw source rows, one per DLT/legacy-registration observation. Internal/service-role only - not a new public API. Does not affect registrations, registration_brand_aliases, registration_model_aliases, match_registration_model, or any registration_* analytics view.';
comment on table public.registration_facts_v2 is
  'DLT v2 shadow pipeline (Phase 2): resolved registration fact per observation, addressed by canonical Vehicle Master text id at the grain the source proved (BRAND/MODEL/VARIANT). Never a legacy models.id uuid. Shadow-only - no production consumer reads this table yet (Phase 3).';
comment on table public.registration_resolution_review_v2 is
  'DLT v2 shadow pipeline (Phase 2): one row per observation whose resolution stopped short of the deepest grain the raw text plausibly claimed (ambiguous, brand-not-found, model-not-found, variant-not-found) or that produced no fact at all. Never auto-resolved by this migration.';
