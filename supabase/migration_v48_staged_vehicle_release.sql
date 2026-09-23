-- Staged, chunked release publishing.
--
-- publish_vehicle_release(jsonb) (v15/v44/v47) rewrites all six projection
-- tables for a release in one INSERT...SELECT-per-table transaction. For a
-- release the size of the September 2026 ECO Sticker bulk import (~20,800
-- spec facts, ~820 price records) that transaction measured ~34.5s and
-- still exceeded even the 45s function-level statement_timeout v47 gave it
-- (Postgres error 57014 on every attempt; the transaction always rolled
-- back cleanly, so the previous release stayed ACTIVE, but nothing ever
-- activated). The payload is also too large to keep POSTing as one HTTP
-- request/one jsonb argument at this scale.
--
-- This migration adds a three-phase alternative that keeps the same
-- versioned-projection-table data model (no shadow schema) and the same
-- atomic-pointer-flip activation, but lets the *staging* work happen as
-- many small, independently retryable calls instead of one giant one:
--
--   1. begin_vehicle_release(manifest jsonb)
--      Registers a release row in STAGING with a small manifest (the
--      release's own scalar/metadata fields -- schema_version, release_id,
--      canonical_revision, source_hash, as_of, year, counts,
--      historical_model_state, revision_ordinal -- never the six bulk
--      arrays). Safe to call again for the same release_id, but its
--      identity/activation fields are immutable once the row exists: a
--      call whose semantic manifest matches exactly is a no-op replay
--      (ACTIVE/SUPERSEDED) or a resumable re-open (still STAGING); a call
--      whose semantic manifest differs -- revision_ordinal included -- is
--      always an error, never a silent overwrite.
--
--   2. stage_vehicle_release_chunk(release_id, section, chunk_index,
--      chunk_hash, rows)
--      Inserts one chunk of one section's rows into that section's
--      existing projection table, scoped by release_id exactly as
--      publish_vehicle_release always has. `section` is one of six
--      hard-coded literal names, matched with a plain IF/ELSIF chain --
--      no dynamic SQL, no table name ever built from a string. Chunks are
--      idempotent by (release_id, section, chunk_index, chunk_hash): a
--      retry of an already-applied chunk is a no-op; a chunk_index sent
--      again with a *different* hash is rejected, since that can only mean
--      the client itself disagrees with an earlier call about what that
--      chunk contains. Foreign-key order is enforced explicitly (brands
--      before models before generations before market_trims before
--      price_ledger/spec_facts) against the chunk ledger's own row-count
--      totals, not left to be discovered as a raw FK violation.
--
--   3. activate_vehicle_release(release_id)
--      Serializes with every other vehicle_catalog activation via a
--      transaction-scoped advisory lock, acquired before anything else is
--      read -- without it, two concurrent activations for two different
--      releases each lock only their own release row and can both read
--      the same currently-active release/ordinal before either commits,
--      so the older of the two could still win the race after the newer
--      one has already activated. Once serialized, validates -- by
--      summing the chunk ledger, not by trusting anything the caller says
--      at this step -- that every section's staged row count matches the
--      count the manifest promised at begin, refuses a stale
--      revision_ordinal exactly as publish_vehicle_release does (same
--      guard, same semantics), and then does the identical atomic tail
--      every release activation has always done: supersede the old ACTIVE
--      release, activate this one, flip canonical_vehicle_state. This is
--      the only step that changes what the public serving views show.
--
-- publish_vehicle_release(jsonb) itself is untouched by this migration --
-- not redefined, not wrapped, not wired to call the new functions
-- internally. It keeps doing the real single-transaction rewrite it always
-- has, for callers/release sizes that don't need staging.
--
-- The other half of this migration is the RLS gap the staged design would
-- otherwise open: today all six projection tables grant anon/authenticated
-- an unconditional `using (true)` SELECT, so a STAGING release's
-- half-written rows -- invisible to publish_vehicle_release's callers only
-- because that function does its rewrite in one transaction other
-- sessions can't see mid-flight -- would otherwise be plainly visible to
-- any PostgREST client for the whole span of a staged publish, which can
-- now last minutes instead of one transaction. This migration narrows
-- those six policies to ACTIVE and SUPERSEDED releases only. Nothing in
-- this codebase reads a projection table's raw rows through anon or
-- authenticated: every admin surface that touches these tables directly
-- (lib/canonical-editor.ts, app/admin/(secure)/prices, data-quality, and
-- the historical/price-coverage helpers under app/admin and lib) goes
-- through adminDb(), the service_role client, which RLS never applies to;
-- the six current_* views (security_invoker) already only ever surface
-- the ACTIVE release regardless of this policy. So this is a real gap
-- being closed, not a behavior change for any existing reader.

create table if not exists public.canonical_release_chunks (
  release_id text not null references public.canonical_vehicle_releases(release_id) on delete cascade,
  section text not null,
  chunk_index integer not null,
  chunk_hash text not null,
  row_count integer not null,
  applied_at timestamptz not null default now(),
  primary key (release_id, section, chunk_index)
);

comment on table public.canonical_release_chunks is
  'The ledger stage_vehicle_release_chunk() records against, so a repeated (release_id, section, chunk_index) call with the same chunk_hash is a safe no-op, a different hash is rejected, and activate_vehicle_release() can validate every section''s staged total against the manifest without trusting the caller.';

alter table public.canonical_release_chunks enable row level security;
grant all on public.canonical_release_chunks to service_role;

-- The subset of a manifest whose values are the release's actual identity
-- and activation semantics -- everything begin_vehicle_release must never
-- silently overwrite once a release_id exists. Deliberately NOT "whatever
-- the caller's _manifest() happened to drop the bulk arrays from": the
-- release also carries ephemeral fields (created_at, stamped fresh every
-- time release_enriched.py rebuilds an otherwise-identical release) that
-- legitimately differ across two calls describing the same semantic
-- release, and comparing those would reject a legitimate resume.
create or replace function public._release_semantic_manifest(m jsonb)
returns jsonb
language sql
immutable
as $$
  select jsonb_strip_nulls(jsonb_build_object(
    'schema_version', m->'schema_version',
    'release_id', m->'release_id',
    'canonical_revision', m->'canonical_revision',
    'source_hash', m->'source_hash',
    'year', m->'year',
    'as_of', m->'as_of',
    'counts', m->'counts',
    'historical_model_state', m->'historical_model_state',
    'revision_ordinal', m->'revision_ordinal'
  ));
$$;

create or replace function public.begin_vehicle_release(manifest jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  rid text := manifest->>'release_id';
  incoming_semantic jsonb;
  existing_status text;
  existing_payload jsonb;
  staged jsonb;
begin
  if rid is null or rid !~ '^vehicle-[0-9]{4}-[a-f0-9]{16}$' then
    raise exception 'invalid release_id';
  end if;
  if coalesce((manifest->>'schema_version')::integer, 0) <> 1 then
    raise exception 'unsupported schema_version';
  end if;
  if manifest->>'source_hash' is null or manifest->>'canonical_revision' is null
     or manifest->>'as_of' is null then
    raise exception 'source_hash, canonical_revision and as_of are required';
  end if;
  if manifest->'counts' is null or jsonb_typeof(manifest->'counts') <> 'object'
     or not ((manifest->'counts') ?& array['brands','models','generations',
                                            'market_trims','price_ledger','spec_facts'])
  then
    raise exception 'manifest counts must name all six release sections';
  end if;

  incoming_semantic := public._release_semantic_manifest(manifest);

  select status, payload into existing_status, existing_payload
    from public.canonical_vehicle_releases where release_id = rid
    for update;

  if found then
    -- Identity/activation semantics are immutable once a release_id
    -- exists, in every status: a second begin_vehicle_release call
    -- naming the same release_id must describe the exact same release,
    -- whether it is still being staged or already finalized. A mismatch
    -- here can only mean the caller itself disagrees with an earlier
    -- call -- content-hash release_ids mean a genuinely different
    -- release always gets a different id -- so this always errors
    -- rather than silently overwriting anything, revision_ordinal
    -- (the staleness guard's own input) included.
    if incoming_semantic <> public._release_semantic_manifest(existing_payload) then
      raise exception
        'begin_vehicle_release: % already exists (status %) with an incompatible manifest',
        rid, existing_status;
    end if;
    if existing_status in ('ACTIVE', 'SUPERSEDED') then
      return jsonb_build_object('release_id', rid, 'status', existing_status,
                                'already_finalized', true);
    end if;
    -- STAGING and the manifest matches exactly: a pure resume. Nothing
    -- about the release row is updated -- there is nothing to update.
  else
    insert into public.canonical_vehicle_releases
      (release_id, schema_version, canonical_revision, source_hash, as_of,
       counts, payload, status, revision_ordinal)
    values
      (rid, 1, manifest->>'canonical_revision', manifest->>'source_hash',
       (manifest->>'as_of')::date, manifest->'counts', manifest, 'STAGING',
       nullif(manifest->>'revision_ordinal', '')::bigint);
  end if;

  select jsonb_object_agg(section, done) into staged
    from (
      select section, sum(row_count) as done
        from public.canonical_release_chunks
       where release_id = rid
       group by section
    ) s;

  return jsonb_build_object('release_id', rid, 'status', 'STAGING',
                            'counts', manifest->'counts',
                            'staged', coalesce(staged, '{}'::jsonb));
end;
$$;

revoke all on function public._release_semantic_manifest(jsonb) from public, anon, authenticated;
grant execute on function public._release_semantic_manifest(jsonb) to service_role;

revoke all on function public.begin_vehicle_release(jsonb) from public, anon, authenticated;
grant execute on function public.begin_vehicle_release(jsonb) to service_role;

create or replace function public.stage_vehicle_release_chunk(
  p_release_id text,
  p_section text,
  p_chunk_index integer,
  p_chunk_hash text,
  p_rows jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
set statement_timeout = '30s'
as $$
declare
  rel_status text;
  expected_counts jsonb;
  existing_hash text;
  n_rows integer := jsonb_array_length(coalesce(p_rows, '[]'::jsonb));
  prereq_sections text[];
  prereq text;
  prereq_expected integer;
  prereq_done bigint;
begin
  if p_section not in ('brands', 'models', 'generations',
                        'market_trims', 'price_ledger', 'spec_facts') then
    raise exception 'unknown release section %', p_section;
  end if;
  if p_chunk_hash is null or p_chunk_hash = '' then
    raise exception 'chunk_hash is required';
  end if;

  select status, counts into rel_status, expected_counts
    from public.canonical_vehicle_releases where release_id = p_release_id
    for update;
  if not found then
    raise exception 'unknown release %', p_release_id;
  end if;
  if rel_status <> 'STAGING' then
    raise exception 'release % is not staging (status %)', p_release_id, rel_status;
  end if;

  select chunk_hash into existing_hash
    from public.canonical_release_chunks
   where release_id = p_release_id and section = p_section and chunk_index = p_chunk_index;
  if found then
    if existing_hash = p_chunk_hash then
      return jsonb_build_object('release_id', p_release_id, 'section', p_section,
                                'chunk_index', p_chunk_index, 'status', 'already_staged',
                                'row_count', n_rows);
    end if;
    raise exception
      'chunk %/% for release % was already staged with a different hash',
      p_section, p_chunk_index, p_release_id;
  end if;

  -- Foreign-key order, made explicit instead of discovered as a raw FK
  -- violation: a section may only be staged once every section it
  -- references is fully staged, per the manifest's own expected counts.
  prereq_sections := case p_section
    when 'models' then array['brands']
    when 'generations' then array['models']
    when 'market_trims' then array['models', 'generations']
    when 'price_ledger' then array['market_trims']
    when 'spec_facts' then array['market_trims']
    else array[]::text[]
  end;
  foreach prereq in array prereq_sections loop
    prereq_expected := coalesce((expected_counts->>prereq)::integer, 0);
    select coalesce(sum(row_count), 0) into prereq_done
      from public.canonical_release_chunks
     where release_id = p_release_id and section = prereq;
    if prereq_done < prereq_expected then
      raise exception
        'cannot stage section % for release % before section % is fully staged (% of % rows staged)',
        p_section, p_release_id, prereq, prereq_done, prereq_expected;
    end if;
  end loop;

  if p_section = 'brands' then
    insert into public.canonical_brand_projection
      (release_id, canonical_id, tdr_brand_id, slug, name_en, name_th, origin_country, payload)
    select p_release_id, x->>'canonical_id', nullif(x->>'tdr_brand_id', '')::uuid,
      x->>'slug', x->>'name_en', x->>'name_th', x->>'origin_country', x->'payload'
    from jsonb_array_elements(p_rows) x;

  elsif p_section = 'models' then
    insert into public.canonical_model_projection
      (release_id, canonical_id, tdr_model_id, brand_id, slug, name_en, name_th,
       generation_id, status, segment, body_type, retail_price_min, retail_price_max, payload)
    select p_release_id, x->>'canonical_id', nullif(x->>'tdr_model_id', '')::uuid,
      x->>'brand_id', x->>'slug', x->>'name_en', x->>'name_th',
      x->>'generation_id', x->>'status', x->>'segment', x->>'body_type',
      nullif(x->>'retail_price_min', '')::numeric,
      nullif(x->>'retail_price_max', '')::numeric, x->'payload'
    from jsonb_array_elements(p_rows) x;

  elsif p_section = 'generations' then
    insert into public.canonical_generation_projection
      (release_id, canonical_id, model_id, code, segment, launched, ended, payload)
    select p_release_id, x->>'canonical_id', x->>'model_id', x->>'code', x->>'segment',
      nullif(x->>'launched', '')::date, nullif(x->>'ended', '')::date, x->'payload'
    from jsonb_array_elements(p_rows) x;

  elsif p_section = 'market_trims' then
    insert into public.canonical_market_trim_projection
      (release_id, canonical_id, model_id, generation_id, variant_id, name,
       powertrain, status, payload, current_list_price, campaign_quote, price_history, source_refs)
    select p_release_id, x->>'canonical_id', x->>'model_id', x->>'generation_id',
      nullif(x->>'variant_id', ''), x->>'name', x->>'powertrain',
      coalesce(x->>'status', 'current'), x->'payload',
      x->'current_list_price', coalesce(x->'campaign_quote', '{}'::jsonb),
      coalesce(x->'price_history', '[]'::jsonb), coalesce(x->'source_refs', '{}'::jsonb)
    from jsonb_array_elements(p_rows) x;

  elsif p_section = 'price_ledger' then
    insert into public.canonical_price_projection
      (release_id, record_id, trim_id, amount_thb, price_type, effective_from,
       effective_to, observed_at, campaign_id, option_id, source, source_ref, payload)
    select p_release_id, x->>'record_id', x->>'trim_id', (x->>'amount_thb')::bigint,
      x->>'price_type', nullif(x->>'effective_from', '')::date,
      nullif(x->>'effective_to', '')::date, nullif(x->>'observed_at', '')::date,
      x->>'campaign_id', x->>'option_id', x->>'source', x->>'source_ref', x
    from jsonb_array_elements(p_rows) x;

  elsif p_section = 'spec_facts' then
    insert into public.canonical_spec_projection
      (release_id, fact_id, trim_id, field_key, verification_status, payload)
    select p_release_id, x->>'fact_id', x->>'trim_id', x->>'field_key',
      x->>'verification_status', x
    from jsonb_array_elements(p_rows) x;
  end if;

  insert into public.canonical_release_chunks
    (release_id, section, chunk_index, chunk_hash, row_count)
  values
    (p_release_id, p_section, p_chunk_index, p_chunk_hash, n_rows);

  return jsonb_build_object('release_id', p_release_id, 'section', p_section,
                            'chunk_index', p_chunk_index, 'status', 'staged',
                            'row_count', n_rows);
end;
$$;

revoke all on function public.stage_vehicle_release_chunk(text, text, integer, text, jsonb)
  from public, anon, authenticated;
grant execute on function public.stage_vehicle_release_chunk(text, text, integer, text, jsonb)
  to service_role;

create or replace function public.activate_vehicle_release(p_release_id text)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
set statement_timeout = '30s'
as $$
declare
  rel_status text;
  expected_counts jsonb;
  incoming_ordinal bigint;
  active_release_id text;
  active_ordinal bigint;
  sec text;
  sec_expected integer;
  sec_done bigint;
  incomplete text[] := array[]::text[];
begin
  -- Transaction-wide serialization point for every vehicle_catalog
  -- activation, acquired before anything else is read. The `for update`
  -- below only locks the ONE release row this call names -- two
  -- concurrent activations for two DIFFERENT releases each lock their own
  -- row and can both read the same currently-active release/ordinal
  -- before either commits, so the older of the two can still win the race
  -- after the newer one has already activated (the exact scenario v44's
  -- staleness guard exists to prevent). An advisory lock is
  -- session/transaction scoped, not tied to any row, so acquiring it
  -- before the staleness read blocks every other activation for this
  -- scope regardless of which release_id it names, and it is released
  -- automatically at commit or rollback -- no unlock call, no risk of
  -- leaking it past this transaction.
  perform pg_advisory_xact_lock(hashtext('canonical_vehicle_release_activation:vehicle_catalog')::bigint);

  select status, counts, revision_ordinal into rel_status, expected_counts, incoming_ordinal
    from public.canonical_vehicle_releases where release_id = p_release_id
    for update;
  if not found then
    raise exception 'unknown release %', p_release_id;
  end if;
  if rel_status = 'ACTIVE' then
    return jsonb_build_object('release_id', p_release_id, 'status', 'ACTIVE',
                              'already_active', true);
  end if;
  if rel_status <> 'STAGING' then
    raise exception 'release % cannot be activated from status %', p_release_id, rel_status;
  end if;

  -- Manifest-based, not caller-trusted: every section's staged total is
  -- re-summed from the chunk ledger and compared to what begin_vehicle_release
  -- recorded as the expected count, regardless of what this call is told.
  foreach sec in array array['brands', 'models', 'generations',
                              'market_trims', 'price_ledger', 'spec_facts'] loop
    sec_expected := coalesce((expected_counts->>sec)::integer, 0);
    select coalesce(sum(row_count), 0) into sec_done
      from public.canonical_release_chunks
     where release_id = p_release_id and section = sec;
    if sec_done <> sec_expected then
      incomplete := incomplete || (sec || ': ' || sec_done || '/' || sec_expected);
    end if;
  end loop;
  if array_length(incomplete, 1) is not null then
    raise exception 'release % is not fully staged: %', p_release_id,
      array_to_string(incomplete, ', ');
  end if;

  -- The same staleness guard publish_vehicle_release has carried since
  -- migration_v44, unchanged: refuse to activate an older revision_ordinal
  -- over a newer one already serving, when both sides know theirs.
  select r.release_id, r.revision_ordinal into active_release_id, active_ordinal
    from public.canonical_vehicle_state s
    join public.canonical_vehicle_releases r on r.release_id = s.active_release_id
   where s.scope = 'vehicle_catalog';

  if incoming_ordinal is not null and active_ordinal is not null
     and incoming_ordinal < active_ordinal and p_release_id <> active_release_id then
    raise exception
      'stale revision: % (ordinal %) is older than the active release % (ordinal %); refusing to activate',
      p_release_id, incoming_ordinal, active_release_id, active_ordinal;
  end if;

  update public.canonical_vehicle_releases
    set status = 'SUPERSEDED'
    where status = 'ACTIVE' and release_id <> p_release_id;
  update public.canonical_vehicle_releases
    set status = 'ACTIVE', activated_at = now()
    where release_id = p_release_id;
  insert into public.canonical_vehicle_state(scope, active_release_id, activated_at)
    values ('vehicle_catalog', p_release_id, now())
    on conflict (scope) do update set
      active_release_id = excluded.active_release_id,
      activated_at = excluded.activated_at;

  return jsonb_build_object('release_id', p_release_id, 'status', 'ACTIVE', 'counts', expected_counts);
end;
$$;

revoke all on function public.activate_vehicle_release(text) from public, anon, authenticated;
grant execute on function public.activate_vehicle_release(text) to service_role;

comment on function public.begin_vehicle_release(jsonb) is
  'Phase 1 of the staged release protocol: opens (or resumes) a release in STAGING from a small manifest, never the bulk section arrays. See migration_v48.';
comment on function public.stage_vehicle_release_chunk(text, text, integer, text, jsonb) is
  'Phase 2 of the staged release protocol: idempotently applies one chunk of one section to its projection table, enforcing FK section order. See migration_v48.';
comment on function public.activate_vehicle_release(text) is
  'Phase 3 of the staged release protocol: validates every section''s staged total against the manifest, applies the same staleness guard and atomic activation publish_vehicle_release always has, and is the only step that changes what current_* serves. See migration_v48.';

-- Close the STAGING-visibility gap: a staged publish can now take minutes
-- of wall-clock time across many small transactions, so "only ACTIVE and
-- SUPERSEDED rows are readable" has to be a real policy rather than an
-- accident of publish_vehicle_release doing all its writes in one
-- transaction other sessions never see mid-flight.
--
-- canonical_vehicle_releases itself has row level security enabled but no
-- policy or grant at all for anon/authenticated (v15) -- nothing in this
-- codebase needs those roles to read it directly, and its own payload
-- column is exactly the thing not to widen access to. A plain EXISTS
-- subquery against it from these policies would therefore fail with
-- "permission denied" for those roles, not silently deny rows. This
-- SECURITY DEFINER function is the same pattern has_market_access (v15)
-- already uses for the identical reason: it runs with its owner's
-- privileges regardless of the caller's own grants, so the six policies
-- below can ask it a yes/no question without either role ever gaining
-- direct access to canonical_vehicle_releases.
create or replace function public.release_is_publicly_readable(target_release_id text)
returns boolean
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.canonical_vehicle_releases r
    where r.release_id = target_release_id
      and r.status in ('ACTIVE', 'SUPERSEDED')
  );
$$;

revoke all on function public.release_is_publicly_readable(text) from public;
grant execute on function public.release_is_publicly_readable(text)
  to anon, authenticated, service_role;

drop policy if exists "public read canonical brands" on public.canonical_brand_projection;
create policy "public read canonical brands" on public.canonical_brand_projection
  for select to anon, authenticated
  using (public.release_is_publicly_readable(release_id));

drop policy if exists "public read canonical models" on public.canonical_model_projection;
create policy "public read canonical models" on public.canonical_model_projection
  for select to anon, authenticated
  using (public.release_is_publicly_readable(release_id));

drop policy if exists "public read canonical generations" on public.canonical_generation_projection;
create policy "public read canonical generations" on public.canonical_generation_projection
  for select to anon, authenticated
  using (public.release_is_publicly_readable(release_id));

drop policy if exists "public read canonical market trims" on public.canonical_market_trim_projection;
create policy "public read canonical market trims" on public.canonical_market_trim_projection
  for select to anon, authenticated
  using (public.release_is_publicly_readable(release_id));

drop policy if exists "public read canonical prices" on public.canonical_price_projection;
create policy "public read canonical prices" on public.canonical_price_projection
  for select to anon, authenticated
  using (public.release_is_publicly_readable(release_id));

drop policy if exists "public read canonical specs" on public.canonical_spec_projection;
create policy "public read canonical specs" on public.canonical_spec_projection
  for select to anon, authenticated
  using (public.release_is_publicly_readable(release_id));
