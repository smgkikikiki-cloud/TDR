-- Vehicle DB v3, Phase 1, slice 1: the governed price writer (observations, change log, revert, inbox).
--
-- Design: docs/vehicle-db/VEHICLE_DB_V3.md §3, §4, §5.4, §6.B, §6.H, §9.1. Phase 0 left the Vehicle Master with no
-- write layer; this adds the first one, for the price ledger only. Facts, structure and Excel arrive in later slices
-- on the same tables and RPC conventions.
--
-- What this migration is NOT: it does not compute served values. `current_list_price`, `price_history`,
-- `campaign_quote` and the model price band are derived by the ported TypeScript rules (lib/vehicle-engine, ENGINE_RULES
-- §4) and passed in. The RPC below only (a) enforces authority, revision and jump guards, (b) writes the ledger,
-- the stored served values and the change log in ONE transaction per item. It never decides whether a price is true.
--
-- Everything is additive. No existing row, constraint or trigger changes except relaxing `command_id` on the
-- (empty) change log so master writes, which have no legacy command, can use it.

begin;

-- ---------------------------------------------------------------------------
-- 1. Observations: what a source said. Immutable (v3 §3).
-- ---------------------------------------------------------------------------
create table if not exists public.vm_observations (
  id uuid primary key default gen_random_uuid(),
  run_id text not null,
  source_kind text not null check (source_kind in ('SCRAPE', 'AGENT', 'EXCEL', 'ADMIN_PANEL')),
  field_key text not null check (field_key in ('LIST_PRICE', 'CAMPAIGN_PRICE', 'TRIM_LISTING')),
  model_id text,
  trim_id text,                       -- hint only; may be null until reconcile pairs it
  trim_name_raw text,
  amount_thb bigint check (amount_thb is null or amount_thb > 0),
  vat_included boolean,
  raw jsonb not null default '{}'::jsonb,
  source_url text not null,
  content_hash text,                  -- sha256 of the fetched document
  snapshot_ref text,
  observed_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);
create index if not exists vm_observations_trim_idx on public.vm_observations (trim_id, field_key, observed_at desc);
create index if not exists vm_observations_run_idx on public.vm_observations (run_id);
create index if not exists vm_observations_model_idx on public.vm_observations (model_id, field_key, observed_at desc);

create or replace function public._vm_observations_immutable() returns trigger
language plpgsql as $$
begin
  raise exception using errcode = 'P0001',
    message = 'vm_observations is immutable: an observation records what a source said and is never changed or deleted';
end;
$$;

drop trigger if exists vm_observations_no_change on public.vm_observations;
create trigger vm_observations_no_change before update or delete on public.vm_observations
  for each row execute function public._vm_observations_immutable();

-- ---------------------------------------------------------------------------
-- 2. Change log: reuse canonical_write_revisions (v3 §3), extended.
-- ---------------------------------------------------------------------------
alter table public.canonical_write_revisions alter column command_id drop not null;
alter table public.canonical_write_revisions
  add column if not exists field text,
  add column if not exists before_revision integer,
  add column if not exists after_revision integer,
  add column if not exists actor_kind text,
  add column if not exists source text,
  add column if not exists batch_id text,
  add column if not exists reverts_id uuid references public.canonical_write_revisions (id);

alter table public.canonical_write_revisions drop constraint if exists canonical_write_revisions_actor_kind_check;
alter table public.canonical_write_revisions add constraint canonical_write_revisions_actor_kind_check
  check (actor_kind is null or actor_kind in ('ADMIN', 'OFFICIAL', 'AI', 'EXCEL'));

create index if not exists canonical_write_revisions_entity_idx
  on public.canonical_write_revisions (entity_type, entity_id, created_at desc);
create index if not exists canonical_write_revisions_batch_idx
  on public.canonical_write_revisions (batch_id) where batch_id is not null;
create unique index if not exists canonical_write_revisions_one_revert_idx
  on public.canonical_write_revisions (reverts_id) where reverts_id is not null;

-- ---------------------------------------------------------------------------
-- 3. Inbox (v3 §11): three kinds only. A new table rather than widening admin_edit_sessions,
--    whose kind/status/page_release_id constraints belong to the trim-editor review flow.
-- ---------------------------------------------------------------------------
create table if not exists public.vm_inbox (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('STRUCTURE', 'PRICE_JUMP', 'SOURCE_BROKEN')),
  status text not null default 'OPEN' check (status in ('OPEN', 'APPROVED', 'REJECTED', 'EXPIRED')),
  dedupe_key text not null,           -- same issue found again updates the same card (§6.E)
  model_id text,
  trim_id text,
  source_hash text,                   -- content that produced the proposal; a rejected card re-opens only if this changes
  payload jsonb not null default '{}'::jsonb,
  seen_count integer not null default 1,
  decided_by text,
  decided_at timestamptz,
  expires_at timestamptz not null default (now() + interval '30 days'),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists vm_inbox_open_dedupe_idx on public.vm_inbox (dedupe_key) where status = 'OPEN';
create index if not exists vm_inbox_status_idx on public.vm_inbox (status, kind, created_at);

-- ---------------------------------------------------------------------------
-- 4. Row level security: service_role only.
-- ---------------------------------------------------------------------------
do $$
declare relation_name text;
begin
  foreach relation_name in array array['vm_observations', 'vm_inbox'] loop
    execute format('alter table public.%I enable row level security', relation_name);
    execute format('revoke all on public.%I from public, anon, authenticated', relation_name);
    execute format('grant select, insert, update, delete on public.%I to service_role', relation_name);
  end loop;
end $$;
revoke update, delete on public.vm_observations from service_role;   -- the trigger also refuses it

-- ---------------------------------------------------------------------------
-- 5. Inbox upsert (§6.E): update the open card; never re-propose a rejected one unless the source changed.
-- ---------------------------------------------------------------------------
create or replace function public.vm_inbox_propose(
  p_kind text, p_dedupe_key text, p_model_id text, p_trim_id text, p_source_hash text, p_payload jsonb
) returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  open_card public.vm_inbox%rowtype;
  last_decided public.vm_inbox%rowtype;
  new_id uuid;
begin
  select * into open_card from public.vm_inbox where dedupe_key = p_dedupe_key and status = 'OPEN' for update;
  if found then
    update public.vm_inbox
       set payload = coalesce(p_payload, '{}'::jsonb), source_hash = p_source_hash,
           seen_count = seen_count + 1, updated_at = now(), expires_at = now() + interval '30 days'
     where id = open_card.id;
    return jsonb_build_object('status', 'UPDATED', 'id', open_card.id);
  end if;
  select * into last_decided from public.vm_inbox
   where dedupe_key = p_dedupe_key order by coalesce(decided_at, updated_at) desc limit 1;
  if found and last_decided.status in ('REJECTED', 'APPROVED')
     and last_decided.source_hash is not distinct from p_source_hash then
    return jsonb_build_object('status', 'SUPPRESSED', 'id', last_decided.id);   -- decided on identical data
  end if;
  insert into public.vm_inbox (kind, dedupe_key, model_id, trim_id, source_hash, payload)
  values (p_kind, p_dedupe_key, p_model_id, p_trim_id, p_source_hash, coalesce(p_payload, '{}'::jsonb))
  returning id into new_id;
  return jsonb_build_object('status', 'CREATED', 'id', new_id);
end;
$$;
revoke all on function public.vm_inbox_propose(text, text, text, text, text, jsonb) from public, anon, authenticated;
grant execute on function public.vm_inbox_propose(text, text, text, text, text, jsonb) to service_role;

-- ---------------------------------------------------------------------------
-- 6. The governed price write. One call = a batch; each item commits or is skipped independently.
--
-- item = {
--   trim_id, expected_trim_revision,
--   new_row: {amount_thb, price_type, effective_from, observed_at, source, source_ref, vat_included, ...} | null,
--   close_record_ids: [..],        -- set effective_to (the prior open-ended price)
--   close_effective_to: 'YYYY-MM-DD',
--   retract_record_ids: [..],      -- retract (a retraction is never undone)
--   reopen_record_ids: [..],       -- clear effective_to (revert of a close)
--   retraction_reason: text,
--   served: {current_list_price, price_history, campaign_quote},
--   model: {model_id, expected_model_revision, retail_price_min, retail_price_max} | null,
--   actor_kind: ADMIN|OFFICIAL|AI|EXCEL, observation_id, approved_inbox_id, reverts_id, reason
-- }
-- Result per item: APPLIED | STALE_REVISION | AUTHORITY_BLOCKED | JUMP_BLOCKED | REJECTED(+error).
-- ---------------------------------------------------------------------------
create or replace function public._vm_authority_rank(p_authority text) returns integer
language sql immutable as $$
  -- NULL (legacy Phase 0 rows) ranks as OFFICIAL, never ADMIN (VEHICLE_DB_V3 §9.1 item 4).
  select case coalesce(p_authority, 'OFFICIAL') when 'ADMIN' then 3 when 'EXCEL' then 3 when 'OFFICIAL' then 2 when 'AI' then 1 else 0 end
$$;

create or replace function public.vm_apply_price_changes(p_batch_id text, p_items jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  item jsonb;
  results jsonb := '[]'::jsonb;
  outcome jsonb;
  trim_row public.vehicle_trims%rowtype;
  model_row public.vehicle_models%rowtype;
  new_row jsonb;
  actor text;
  prior public.vehicle_price_ledger%rowtype;
  prior_amount bigint;
  new_amount bigint;
  new_record_id text;
  rid text;
  log_id uuid;
  before_rev integer;
  rev_label text;
  jump_ok boolean;
  ptype text;
  stored_authority text;
  new_start date;
begin
  if p_items is null or jsonb_typeof(p_items) <> 'array' then
    raise exception using errcode = 'P0001', message = 'vm_apply_price_changes: p_items must be a JSON array';
  end if;

  for item in select * from jsonb_array_elements(p_items) loop
    begin
      actor := item ->> 'actor_kind';
      if actor is null or actor not in ('ADMIN', 'OFFICIAL', 'AI', 'EXCEL') then
        raise exception using errcode = 'P0001', message = 'actor_kind must be ADMIN, OFFICIAL, AI or EXCEL';
      end if;

      select * into trim_row from public.vehicle_trims where canonical_id = item ->> 'trim_id' for update;
      if not found or trim_row.deleted_at is not null then
        raise exception using errcode = 'P0001', message = format('unknown or hidden trim %s', item ->> 'trim_id');
      end if;
      before_rev := trim_row.revision;

      -- optimistic concurrency: the plan was computed against this revision
      if (item ->> 'expected_trim_revision')::integer is distinct from before_rev then
        outcome := jsonb_build_object('trim_id', trim_row.canonical_id, 'status', 'STALE_REVISION', 'revision', before_rev);
        results := results || outcome;
        continue;
      end if;

      new_row := item -> 'new_row';
      new_amount := null;
      if new_row is not null and jsonb_typeof(new_row) = 'object' then
        new_amount := (new_row ->> 'amount_thb')::bigint;
        ptype := coalesce(new_row ->> 'price_type', 'LIST_PRICE');
        stored_authority := case when actor = 'EXCEL' then 'ADMIN' else actor end;   -- v3 §5: EXCEL carries ADMIN authority

        -- authority: a lower tier never overwrites a higher one (§1.2); admin always wins (§1.3).
        select * into prior from public.vehicle_price_ledger
         where trim_id = trim_row.canonical_id and price_type = ptype
           and retracted_at is null and (effective_to is null or effective_to >= current_date)
         order by coalesce(effective_from, observed_at) desc, observed_at desc, amount_thb desc limit 1;
        if found and ptype = 'LIST_PRICE' and prior.amount_thb <> new_amount
           and public._vm_authority_rank(actor) < public._vm_authority_rank(prior.authority) then
          outcome := jsonb_build_object('trim_id', trim_row.canonical_id, 'status', 'AUTHORITY_BLOCKED',
                                        'prior_authority', coalesce(prior.authority, 'OFFICIAL'));
          results := results || outcome;
          continue;
        end if;

        -- defence in depth for §5.4: a change above 15% never applies without an approved PRICE_JUMP card.
        if found and prior.amount_thb > 0 and ptype = 'LIST_PRICE' and actor in ('OFFICIAL', 'AI') then
          jump_ok := abs(new_amount - prior.amount_thb)::numeric / prior.amount_thb <= 0.15;
          if not jump_ok then
            jump_ok := (item ->> 'approved_inbox_id') is not null and exists (
              select 1 from public.vm_inbox
               where id = (item ->> 'approved_inbox_id')::uuid and kind = 'PRICE_JUMP' and status = 'APPROVED');
          end if;
          if not jump_ok then
            outcome := jsonb_build_object('trim_id', trim_row.canonical_id, 'status', 'JUMP_BLOCKED',
                                          'prior_amount_thb', prior.amount_thb, 'new_amount_thb', new_amount);
            results := results || outcome;
            continue;
          end if;
        end if;
        prior_amount := case when found then prior.amount_thb else null end;
      else
        prior_amount := null;
      end if;

      -- close / retract / reopen existing rows (the only mutable ledger columns, see _vm_price_append_only)
      for rid in select jsonb_array_elements_text(coalesce(item -> 'close_record_ids', '[]'::jsonb)) loop
        update public.vehicle_price_ledger
           set effective_to = (item ->> 'close_effective_to')::date,
               payload = jsonb_set(payload, '{effective_to}', to_jsonb(item ->> 'close_effective_to'))
         where record_id = rid and trim_id = trim_row.canonical_id;
      end loop;
      for rid in select jsonb_array_elements_text(coalesce(item -> 'retract_record_ids', '[]'::jsonb)) loop
        update public.vehicle_price_ledger
           set retracted_at = current_date, retraction_reason = coalesce(item ->> 'retraction_reason', 'retracted'),
               in_release = false,
               payload = payload || jsonb_build_object('retracted_at', current_date::text,
                                                       'retraction_reason', coalesce(item ->> 'retraction_reason', 'retracted'))
         where record_id = rid and trim_id = trim_row.canonical_id and retracted_at is null;
      end loop;
      for rid in select jsonb_array_elements_text(coalesce(item -> 'reopen_record_ids', '[]'::jsonb)) loop
        update public.vehicle_price_ledger
           set effective_to = null, payload = jsonb_set(payload, '{effective_to}', 'null'::jsonb)
         where record_id = rid and trim_id = trim_row.canonical_id and retracted_at is null;
      end loop;

      -- append the new price
      if new_amount is not null then
        -- The engine's conflict rule is a deferred constraint, so it would fire at COMMIT and take the whole batch
        -- with it. Check it here instead, after the close/retract above, so only this item is refused.
        new_start := coalesce(nullif(new_row ->> 'effective_from', '')::date, (new_row ->> 'observed_at')::date);
        if ptype = 'LIST_PRICE' and exists (
          select 1 from public.vehicle_price_ledger p
           where p.trim_id = trim_row.canonical_id and p.price_type = 'LIST_PRICE' and p.retracted_at is null
             and coalesce(p.effective_from, p.observed_at) = new_start
             and (p.effective_to is null or p.effective_to >= new_start)
             and p.amount_thb <> new_amount
        ) then
          raise exception using errcode = 'P0001',
            message = format('%s: same-start conflict: an active LIST_PRICE already starts %s at a different amount; '
                             'retract or close it in the same item', trim_row.canonical_id, new_start);
        end if;
        new_record_id := substr(md5(random()::text || clock_timestamp()::text || trim_row.canonical_id), 1, 24);
        insert into public.vehicle_price_ledger (
          record_id, trim_id, amount_thb, price_type, effective_from, effective_to, observed_at,
          source, source_ref, source_document_id, notes, vat_included, authority, in_release, payload, seed_release_id)
        values (
          new_record_id, trim_row.canonical_id, new_amount, ptype,
          nullif(new_row ->> 'effective_from', '')::date, null, (new_row ->> 'observed_at')::date,
          coalesce(new_row ->> 'source', ''), coalesce(new_row ->> 'source_ref', ''),
          coalesce(new_row ->> 'source_document_id', ''), coalesce(new_row ->> 'notes', ''),
          (new_row ->> 'vat_included')::boolean, stored_authority, true,
          jsonb_build_object(
            'notes', coalesce(new_row ->> 'notes', ''), 'source', coalesce(new_row ->> 'source', ''),
            'trim_id', trim_row.canonical_id, 'option_id', null, 'record_id', new_record_id,
            'amount_thb', new_amount, 'price_type', ptype,
            'source_ref', coalesce(new_row ->> 'source_ref', ''), 'campaign_id', null,
            'observed_at', new_row ->> 'observed_at', 'reviewed_by', '', 'effective_to', null,
            'retracted_at', null, 'effective_from', nullif(new_row ->> 'effective_from', ''),
            'retraction_reason', '', 'source_document_id', coalesce(new_row ->> 'source_document_id', ''),
            'reference_price_thb', null),
          (select seed_release_id from public.vehicle_master_state where scope = 'vehicle_master'));
      end if;

      -- stored served values (computed by lib/vehicle-engine, never here)
      update public.vehicle_trims
         set current_list_price = item -> 'served' -> 'current_list_price',
             price_history = coalesce(item -> 'served' -> 'price_history', price_history),
             campaign_quote = coalesce(item -> 'served' -> 'campaign_quote', campaign_quote),
             revision = revision + 1, updated_at = now()
       where canonical_id = trim_row.canonical_id;

      if item -> 'model' is not null and jsonb_typeof(item -> 'model') = 'object' then
        select * into model_row from public.vehicle_models where canonical_id = item -> 'model' ->> 'model_id' for update;
        if found then
          if (item -> 'model' ->> 'expected_model_revision')::integer is distinct from model_row.revision then
            raise exception using errcode = 'P0001', message = format('model %s changed during the write', model_row.canonical_id);
          end if;
          update public.vehicle_models
             set retail_price_min = (item -> 'model' ->> 'retail_price_min')::numeric,
                 retail_price_max = (item -> 'model' ->> 'retail_price_max')::numeric,
                 revision = revision + 1, updated_at = now()
           where canonical_id = model_row.canonical_id;
        end if;
      end if;

      -- change log
      rev_label := 'vm-' || replace(gen_random_uuid()::text, '-', '');
      insert into public.canonical_write_revisions (
        revision_id, command_id, topic, entity_type, entity_id, before_hash, after_hash,
        before_payload, after_payload, actor, reason, field, before_revision, after_revision,
        actor_kind, source, batch_id, reverts_id)
      values (
        rev_label, null, 'price', 'trim', trim_row.canonical_id,
        md5(coalesce(trim_row.current_list_price::text, 'null')),
        md5(coalesce((item -> 'served' -> 'current_list_price')::text, 'null')),
        jsonb_build_object('current_list_price', trim_row.current_list_price, 'amount_thb', prior_amount,
                           'record_ids_closed', coalesce(item -> 'close_record_ids', '[]'::jsonb),
                           'record_ids_reopened', coalesce(item -> 'reopen_record_ids', '[]'::jsonb)),
        jsonb_build_object('current_list_price', item -> 'served' -> 'current_list_price', 'amount_thb', new_amount,
                           'record_id', new_record_id,
                           'record_ids_retracted', coalesce(item -> 'retract_record_ids', '[]'::jsonb),
                           'observation_id', item ->> 'observation_id'),
        actor, item ->> 'reason', 'LIST_PRICE', before_rev, before_rev + 1,
        actor, new_row ->> 'source_ref', p_batch_id, nullif(item ->> 'reverts_id', '')::uuid)
      returning id into log_id;

      outcome := jsonb_build_object('trim_id', trim_row.canonical_id, 'status', 'APPLIED',
                                    'log_id', log_id, 'record_id', new_record_id, 'revision', before_rev + 1);
      results := results || outcome;
      new_record_id := null;
    exception when others then
      -- The savepoint of this block rolled the item back; report it and carry on with the rest of the batch.
      results := results || jsonb_build_object('trim_id', item ->> 'trim_id', 'status', 'REJECTED', 'error', sqlerrm);
      new_record_id := null;
    end;
  end loop;

  return jsonb_build_object('batch_id', p_batch_id, 'results', results);
end;
$$;
revoke all on function public.vm_apply_price_changes(text, jsonb) from public, anon, authenticated;
grant execute on function public.vm_apply_price_changes(text, jsonb) to service_role;
revoke all on function public._vm_authority_rank(text) from public, anon, authenticated;
grant execute on function public._vm_authority_rank(text) to service_role;

commit;
