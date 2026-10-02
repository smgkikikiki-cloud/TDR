-- Vehicle DB v3, Phase 0 step 3: serving parity (docs/vehicle-db/VEHICLE_DB_V3.md §2.3).
--
-- The six current_* views stop reading canonical_*_projection through
-- canonical_vehicle_state and read the v57 master tables instead. Their public
-- contract does not change: same column names, types and order (CREATE OR
-- REPLACE VIEW refuses anything else), same rows, same ids, same release_id
-- value, same payloads (docs/vehicle-db/SERVING_CONTRACT.md §4.1).
--
-- release_id is the release the master was seeded from (vehicle_master_state),
-- which is the active release today. Admin actions use it to look up that
-- release's as_of/payload in canonical_vehicle_releases, so it must stay a real
-- release id, not a new marker.
--
-- Access: the views stay security_invoker, as in v15. Browser roles read the
-- master through them under RLS: one select policy per master table admitting
-- only served rows (not soft-deleted; in_release prices; served_in_release
-- facts), and column grants for exactly the served columns plus the filter
-- column each view needs. Unserved state (catalog_payload, retracted prices,
-- fact history, seed bookkeeping, every sidecar table) stays unreadable, and
-- browser roles still have no write privilege on any master table.
--
-- Transition guard: from this switch until the old write path is closed
-- (Phase 0 step 5), activating a release would change nothing the site serves.
-- A trigger on canonical_vehicle_state therefore refuses to move
-- active_release_id away from the master's seed pin, so the release pointer and
-- what is served cannot silently diverge. Releases can still be built and
-- staged; activation fails loudly instead. Workers and the old tables are not
-- touched here.
--
-- Parity: vehicle_serving_parity_check() compares, row for row and value for
-- value, the OLD output (the v15 view body over the projections, kept verbatim
-- inside the check) with the NEW current_* views, and separately proves each
-- view now depends on the master and on no projection, so the comparison is
-- never a view against itself. This migration runs the check after switching
-- and raises -- rolling the whole migration back -- unless every row is ok.

begin;

-- --------------------------------------------------------------------------
-- Parity check: projection output (old) vs current_* (new)
-- --------------------------------------------------------------------------

create or replace function public.vehicle_serving_parity_check()
returns table (view_name text, check_name text, expected bigint, actual bigint, ok boolean, detail jsonb)
language plpgsql
volatile
set search_path = public, pg_temp
set statement_timeout = '120s'
as $$
declare
  v record;
  pin text;
  active_id text;
  r jsonb;
  cols jsonb;
  sources text[];
begin
  select seed_release_id into pin from public.vehicle_master_state where scope = 'vehicle_master';
  select active_release_id into active_id
    from public.canonical_vehicle_state where scope = 'vehicle_catalog';

  view_name := '*'; check_name := 'master_pin_is_active_release'; expected := 1;
  actual := (pin is not distinct from active_id)::int;
  ok := actual = 1; detail := jsonb_build_object('master_pin', pin, 'active_release_id', active_id);
  return next;

  check_name := 'activation_guard_installed'; expected := 1;
  actual := (exists (select 1 from pg_trigger
                      where tgrelid = 'public.canonical_vehicle_state'::regclass
                        and tgname = 'canonical_vehicle_state_master_pin_guard'
                        and tgenabled <> 'D'))::int;
  ok := actual = 1; detail := null; return next;

  for v in
    select * from (values
      ('current_vehicle_brands',      'canonical_brand_projection',       'vehicle_brands',       'canonical_id'),
      ('current_vehicle_models',      'canonical_model_projection',       'vehicle_models',       'canonical_id'),
      ('current_vehicle_generations', 'canonical_generation_projection',  'vehicle_generations',  'canonical_id'),
      ('current_market_trims',        'canonical_market_trim_projection', 'vehicle_trims',        'canonical_id'),
      ('current_spec_facts',          'canonical_spec_projection',        'vehicle_facts',        'fact_id'),
      ('current_price_ledger',        'canonical_price_projection',       'vehicle_price_ledger', 'record_id')
    ) t(view, projection, master, key)
  loop
    view_name := v.view;

    -- 1. Column contract: the old views were `select p.*` over the projection,
    --    so their columns are the projection's columns, in order.
    select coalesce(jsonb_agg(jsonb_build_object(
             'position', coalesce(o.pos, n.pos),
             'old', case when o.pos is null then null else o.name || ' ' || o.type end,
             'new', case when n.pos is null then null else n.name || ' ' || n.type end)
             order by coalesce(o.pos, n.pos)), '[]'::jsonb)
      into cols
      from (select row_number() over (order by attnum) pos, attname::text name,
                   format_type(atttypid, atttypmod) type
              from pg_attribute where attrelid = ('public.' || v.projection)::regclass
               and attnum > 0 and not attisdropped) o
      full join (select row_number() over (order by attnum) pos, attname::text name,
                        format_type(atttypid, atttypmod) type
                   from pg_attribute where attrelid = ('public.' || v.view)::regclass
                    and attnum > 0 and not attisdropped) n
        on n.pos = o.pos
     where o.pos is null or n.pos is null or o.name <> n.name or o.type <> n.type;
    check_name := 'columns_differ'; expected := 0; actual := jsonb_array_length(cols);
    ok := actual = 0; detail := case when actual = 0 then null else cols end; return next;

    -- 2. Not tautological: the view must read its master table and no projection.
    select array_agg(distinct d.refobjid::regclass::text order by d.refobjid::regclass::text)
      into sources
      from pg_rewrite rw
      join pg_depend d on d.classid = 'pg_rewrite'::regclass and d.objid = rw.oid
                      and d.refclassid = 'pg_class'::regclass and d.refobjid <> rw.ev_class
     where rw.ev_class = ('public.' || v.view)::regclass;
    check_name := 'reads_master_not_projection'; expected := 1;
    actual := (v.master = any(sources)
               and not exists (select 1 from unnest(sources) s where s like 'canonical\_%\_projection'))::int;
    ok := actual = 1; detail := jsonb_build_object('reads', to_jsonb(sources)); return next;

    -- 3. Same access mode as v15: browser roles read under their own RLS.
    check_name := 'security_invoker'; expected := 1;
    actual := (select coalesce('security_invoker=true' = any(reloptions), false)::int
                 from pg_class where oid = ('public.' || v.view)::regclass);
    ok := actual = 1; detail := null; return next;

    -- 4. Rows and values. OLD is the v15 view body, verbatim.
    execute format($q$
      with o as (
        select r.%1$I as k, to_jsonb(r) as j
          from (select p.* from public.%2$I p
                  join public.canonical_vehicle_state s
                    on s.scope = 'vehicle_catalog' and s.active_release_id = p.release_id) r),
      n as (select r.%1$I as k, to_jsonb(r) as j from public.%3$I r),
      diff as (
        select o.k, (select coalesce(jsonb_agg(e.key order by e.key), '[]'::jsonb)
                       from jsonb_each(o.j) e
                      where e.value::text is distinct from (n.j -> e.key)::text) as columns
          from o join n on n.k = o.k
         where o.j::text <> n.j::text)
      select jsonb_build_object(
        'old_rows', (select count(*) from o),
        'new_rows', (select count(*) from n),
        'new_duplicate_ids', (select count(*) - count(distinct k) from n),
        'missing_ids', (select count(*) from o where not exists (select 1 from n where n.k = o.k)),
        'missing_sample', (select coalesce(jsonb_agg(k), '[]'::jsonb) from
                            (select o.k from o where not exists (select 1 from n where n.k = o.k)
                              order by o.k limit 10) x),
        'extra_ids', (select count(*) from n where not exists (select 1 from o where o.k = n.k)),
        'extra_sample', (select coalesce(jsonb_agg(k), '[]'::jsonb) from
                          (select n.k from n where not exists (select 1 from o where o.k = n.k)
                            order by n.k limit 10) x),
        'values_differ', (select count(*) from diff),
        'differ_sample', (select coalesce(jsonb_agg(jsonb_build_object('id', k, 'columns', columns)), '[]'::jsonb)
                            from (select * from diff order by k limit 10) x),
        'old_not_in_new', (select count(*) from (select j::text from o except all select j::text from n) x),
        'new_not_in_old', (select count(*) from (select j::text from n except all select j::text from o) x))
    $q$, v.key, v.projection, v.view) into r;

    check_name := 'row_count'; expected := (r->>'old_rows')::bigint; actual := (r->>'new_rows')::bigint;
    ok := actual = expected; detail := null; return next;
    check_name := 'duplicate_ids'; expected := 0; actual := (r->>'new_duplicate_ids')::bigint;
    ok := actual = 0; return next;
    check_name := 'ids_missing'; expected := 0; actual := (r->>'missing_ids')::bigint;
    ok := actual = 0; detail := case when actual = 0 then null else r->'missing_sample' end; return next;
    check_name := 'ids_extra'; expected := 0; actual := (r->>'extra_ids')::bigint;
    ok := actual = 0; detail := case when actual = 0 then null else r->'extra_sample' end; return next;
    check_name := 'values_differ'; expected := 0; actual := (r->>'values_differ')::bigint;
    ok := actual = 0; detail := case when actual = 0 then null else r->'differ_sample' end; return next;
    -- Whole rows as a multiset: catches anything the keyed checks could miss.
    check_name := 'rows_old_not_in_new'; expected := 0; actual := (r->>'old_not_in_new')::bigint;
    ok := actual = 0; detail := null; return next;
    check_name := 'rows_new_not_in_old'; expected := 0; actual := (r->>'new_not_in_old')::bigint;
    ok := actual = 0; return next;
  end loop;
end;
$$;

revoke all on function public.vehicle_serving_parity_check() from public, anon, authenticated;
grant execute on function public.vehicle_serving_parity_check() to service_role;

-- --------------------------------------------------------------------------
-- Browser read access to served master rows/columns only. v57 revoked
-- everything from anon/authenticated; this grants back select on the served
-- columns and the one filter column each view uses, nothing else, and no write.
-- --------------------------------------------------------------------------

grant select (scope, seed_release_id) on public.vehicle_master_state to anon, authenticated;
grant select (canonical_id, tdr_brand_id, slug, name_en, name_th, origin_country, payload, deleted_at)
  on public.vehicle_brands to anon, authenticated;
grant select (canonical_id, tdr_model_id, brand_id, slug, name_en, name_th, generation_id, status,
              segment, body_type, retail_price_min, retail_price_max, payload, deleted_at)
  on public.vehicle_models to anon, authenticated;
grant select (canonical_id, model_id, code, segment, launched, ended, payload, deleted_at)
  on public.vehicle_generations to anon, authenticated;
grant select (canonical_id, model_id, generation_id, variant_id, name, powertrain, status, payload,
              current_list_price, campaign_quote, price_history, source_refs, deleted_at)
  on public.vehicle_trims to anon, authenticated;
grant select (record_id, trim_id, amount_thb, price_type, effective_from, effective_to, observed_at,
              campaign_id, option_id, source, source_ref, payload, in_release)
  on public.vehicle_price_ledger to anon, authenticated;
grant select (fact_id, trim_id, field_key, verification_status, payload, served_in_release)
  on public.vehicle_facts to anon, authenticated;

drop policy if exists "public read master pin" on public.vehicle_master_state;
create policy "public read master pin" on public.vehicle_master_state
  for select to anon, authenticated using (scope = 'vehicle_master');
drop policy if exists "public read served brands" on public.vehicle_brands;
create policy "public read served brands" on public.vehicle_brands
  for select to anon, authenticated using (deleted_at is null);
drop policy if exists "public read served models" on public.vehicle_models;
create policy "public read served models" on public.vehicle_models
  for select to anon, authenticated using (deleted_at is null);
drop policy if exists "public read served generations" on public.vehicle_generations;
create policy "public read served generations" on public.vehicle_generations
  for select to anon, authenticated using (deleted_at is null);
drop policy if exists "public read served trims" on public.vehicle_trims;
create policy "public read served trims" on public.vehicle_trims
  for select to anon, authenticated using (deleted_at is null);
drop policy if exists "public read served prices" on public.vehicle_price_ledger;
create policy "public read served prices" on public.vehicle_price_ledger
  for select to anon, authenticated using (in_release);
drop policy if exists "public read served facts" on public.vehicle_facts;
create policy "public read served facts" on public.vehicle_facts
  for select to anon, authenticated using (served_in_release);

-- --------------------------------------------------------------------------
-- The switch. Column lists are the projection columns in their v15 order.
-- The filters repeat the policies so service_role (which bypasses RLS) sees
-- exactly the same rows as browser roles.
-- --------------------------------------------------------------------------

create or replace view public.current_vehicle_brands
with (security_invoker = true) as
select st.seed_release_id as release_id, m.canonical_id, m.tdr_brand_id, m.slug, m.name_en,
       m.name_th, m.origin_country, m.payload
from public.vehicle_brands m
join public.vehicle_master_state st on st.scope = 'vehicle_master'
where m.deleted_at is null;

create or replace view public.current_vehicle_models
with (security_invoker = true) as
select st.seed_release_id as release_id, m.canonical_id, m.tdr_model_id, m.brand_id, m.slug,
       m.name_en, m.name_th, m.generation_id, m.status, m.segment, m.body_type,
       m.retail_price_min, m.retail_price_max, m.payload
from public.vehicle_models m
join public.vehicle_master_state st on st.scope = 'vehicle_master'
where m.deleted_at is null;

create or replace view public.current_vehicle_generations
with (security_invoker = true) as
select st.seed_release_id as release_id, m.canonical_id, m.model_id, m.code, m.segment,
       m.launched, m.ended, m.payload
from public.vehicle_generations m
join public.vehicle_master_state st on st.scope = 'vehicle_master'
where m.deleted_at is null;

create or replace view public.current_market_trims
with (security_invoker = true) as
select st.seed_release_id as release_id, m.canonical_id, m.model_id, m.generation_id,
       m.variant_id, m.name, m.powertrain, m.status, m.payload, m.current_list_price,
       m.campaign_quote, m.price_history, m.source_refs
from public.vehicle_trims m
join public.vehicle_master_state st on st.scope = 'vehicle_master'
where m.deleted_at is null;

-- Retracted rows (in_release = false) were never served.
create or replace view public.current_price_ledger
with (security_invoker = true) as
select st.seed_release_id as release_id, m.record_id, m.trim_id, m.amount_thb, m.price_type,
       m.effective_from, m.effective_to, m.observed_at, m.campaign_id, m.option_id,
       m.source, m.source_ref, m.payload
from public.vehicle_price_ledger m
join public.vehicle_master_state st on st.scope = 'vehicle_master'
where m.in_release;

-- PROVISIONAL / superseded / not-yet-effective facts were never served.
create or replace view public.current_spec_facts
with (security_invoker = true) as
select st.seed_release_id as release_id, m.fact_id, m.trim_id, m.field_key,
       m.verification_status, m.payload
from public.vehicle_facts m
join public.vehicle_master_state st on st.scope = 'vehicle_master'
where m.served_in_release;

grant select on public.current_vehicle_brands, public.current_vehicle_models,
  public.current_vehicle_generations, public.current_market_trims,
  public.current_price_ledger, public.current_spec_facts to anon, authenticated, service_role;

-- --------------------------------------------------------------------------
-- Transition guard (step 3 -> step 5): the release pointer may not move away
-- from the master's seed pin. Covers publish_vehicle_release,
-- activate_vehicle_release, rollback_vehicle_release and any direct write.
-- With no pin (an unseeded database) it does nothing.
-- --------------------------------------------------------------------------

create or replace function public._vehicle_master_pin_guard()
returns trigger
language plpgsql
set search_path = public, pg_temp
as $$
declare
  pin text;
  current_id text;
  attempted text;
begin
  select seed_release_id into pin from public.vehicle_master_state where scope = 'vehicle_master';
  if pin is null then
    return case when tg_op = 'DELETE' then old else new end;
  end if;
  if tg_op = 'DELETE' then
    if old.scope = 'vehicle_catalog' then
      raise exception using
        errcode = 'P0001',
        message = format('release pointer change refused: the Vehicle Master is serving '
                         '(seed pin %s); the vehicle_catalog pointer cannot be deleted', pin),
        hint = 'Phase 0 step 3 (migration_v58). See docs/vehicle-db/MASTER_TABLES.md#serving-phase-0-step-3.';
    end if;
    return old;
  end if;
  if new.scope = 'vehicle_catalog' and new.active_release_id is distinct from pin then
    attempted := new.active_release_id;
    select active_release_id into current_id
      from public.canonical_vehicle_state where scope = 'vehicle_catalog';
    raise exception using
      errcode = 'P0001',
      message = format('release activation refused: the Vehicle Master is serving (seed pin %s); '
                       'cannot activate %s', pin, attempted),
      detail = format('active_release_id is %s and must stay %s. Since migration_v58 the current_* '
                      'views read the Vehicle Master, so activating %s would change nothing the site '
                      'serves and the release pointer would silently diverge from what is served. '
                      'The release itself was not changed by this refusal.',
                      coalesce(current_id, '(none)'), pin, attempted),
      hint = 'Phase 0 step 3 transition guard: edits reach the site again once the old write path '
             'is replaced (Phase 0 step 5 / Phase 1). '
             'See docs/vehicle-db/MASTER_TABLES.md#serving-phase-0-step-3.';
  end if;
  return new;
end;
$$;

revoke all on function public._vehicle_master_pin_guard() from public, anon, authenticated;

drop trigger if exists canonical_vehicle_state_master_pin_guard on public.canonical_vehicle_state;
create trigger canonical_vehicle_state_master_pin_guard
  before insert or update or delete on public.canonical_vehicle_state
  for each row execute function public._vehicle_master_pin_guard();

-- --------------------------------------------------------------------------
-- Gate: the migration commits only if the new output equals the old output.
-- --------------------------------------------------------------------------

do $$
declare
  failures text;
begin
  select string_agg(format('%s.%s expected %s actual %s %s', view_name, check_name,
                           coalesce(expected::text, '-'), coalesce(actual::text, '-'),
                           coalesce(detail::text, '')), E'\n' order by view_name, check_name)
    into failures
    from public.vehicle_serving_parity_check() where ok is not true;
  if failures is not null then
    raise exception 'serving parity failed; current_* views not switched:%', E'\n' || failures;
  end if;
end $$;

commit;
