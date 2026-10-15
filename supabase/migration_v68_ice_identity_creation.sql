-- v68: governed creation of new vehicle identities (models) from Ice, with audit and revert.
-- Why: Ice registers cars TDR has no model for (114 owner-decided models, 98,025 units). The old create path was closed by v60.
-- A model needs: a brand, a model row whose payload passes _vm_model_problems, and >= 1 generation (deferred rule vm_rule_structure).
-- New models carry only a name and a lifecycle: payload.incomplete = true, body_type OTHER (the validator allows that only when incomplete),
-- so nothing is invented about body, price or specs. They are real catalogue models; their pages must cope with "no trims yet".
-- Numbering: production ledger ends at v64 (+ v67 scoped crosswalk). v65/v66 exist in the repo but are NOT applied; this file does not need them
-- (it logs through canonical_write_commands + canonical_write_revisions, as production requires).
-- Nothing runs from this file except creating functions. Rollback: supabase/rollback_v68_ice_identity_creation.sql

begin;

-- Production keeps an audit pair: canonical_write_commands (one row per command) and canonical_write_revisions (FK to it, topic limited to catalog/price/spec).
-- Identity creation is logged as topic 'catalog'; the command row uses operation UPSERT_MODEL_BUNDLE (create) or WITHDRAW_MODEL (revert).
create or replace function public._vm_log_identity(p_entity_type text, p_entity_id text, p_before jsonb, p_after jsonb, p_actor text, p_reason text, p_op text)
returns void language plpgsql security definer set search_path = public, pg_temp
as $$
declare cmd uuid := gen_random_uuid(); rev text := 'vmid-' || replace(gen_random_uuid()::text, '-', '');
begin
  insert into canonical_write_commands (id, command_key, canonical_entity_type, canonical_id, operation, payload, actor, reason, status, revision_id, applied_at)
    values (cmd, 'identity:' || p_reason || ':' || p_entity_type || ':' || p_entity_id || ':' || cmd::text, p_entity_type, p_entity_id, p_op, coalesce(p_after, '{}'::jsonb), p_actor, p_reason, 'applied', rev, now());
  insert into canonical_write_revisions (revision_id, command_id, topic, entity_type, entity_id, before_hash, after_hash, before_payload, after_payload, actor, reason)
    values (rev, cmd, 'catalog', p_entity_type, p_entity_id, md5(coalesce(p_before::text, '')), md5(coalesce(p_after::text, '')), p_before, coalesce(p_after, '{}'::jsonb), p_actor, p_reason);
end $$;
revoke all on function public._vm_log_identity(text, text, jsonb, jsonb, text, text, text) from public, anon, authenticated;

create or replace function public.vm_create_identities(p_batch_id text, p_items jsonb, p_actor text default 'owner')
returns jsonb
language plpgsql security definer set search_path = public, pg_temp
as $$
declare
  item jsonb; cid text; b text; m text; nm text; brand_nm text; st text; note text;
  brand_slug text; mslug text; gen_id text; mpayload jsonb; gpayload jsonb; bpayload jsonb;
  created jsonb := '[]'; skipped jsonb := '[]'; brands_created jsonb := '[]';
  seed text := 'ice-identity-' || p_batch_id;
  v_reason text := 'ice-identity:' || p_batch_id;
begin
  if coalesce(btrim(p_batch_id), '') = '' then raise exception 'batch id is required'; end if;
  if jsonb_typeof(p_items) <> 'array' then raise exception 'items must be a json array'; end if;
  for item in select * from jsonb_array_elements(p_items) loop
    cid := item ->> 'canonical_id'; nm := btrim(item ->> 'name_en'); brand_nm := btrim(item ->> 'brand_name_en');
    st := coalesce(item ->> 'status', 'UNVERIFIED'); note := coalesce(item ->> 'note', '');
    if cid is null or cid !~ '^[a-z0-9_]+\.[a-z0-9_]+$' then raise exception 'bad canonical_id: %', coalesce(cid, 'null'); end if;
    if nm is null or nm = '' then raise exception 'name_en is required for %', cid; end if;
    -- CURRENT would need retail evidence we do not have; a new Ice identity is never claimed as on sale.
    if st not in ('UNVERIFIED', 'HISTORICAL') then raise exception 'status for % must be UNVERIFIED or HISTORICAL, got %', cid, st; end if;
    b := split_part(cid, '.', 1); m := split_part(cid, '.', 2);

    if exists (select 1 from vehicle_models where canonical_id = cid) then
      skipped := skipped || jsonb_build_object('canonical_id', cid, 'why', 'EXISTS'); continue;
    end if;

    select slug into brand_slug from vehicle_brands where canonical_id = b and deleted_at is null;
    if brand_slug is null then
      if brand_nm is null or brand_nm = '' then raise exception 'brand % does not exist and brand_name_en was not given (%)', b, cid; end if;
      brand_slug := replace(b, '_', '-');
      bpayload := jsonb_build_object('id', b, 'slug', brand_slug, 'name_en', brand_nm, 'name_th', null);
      insert into vehicle_brands (canonical_id, slug, name_en, payload, served_as_of, revision, seed_release_id)
        values (b, brand_slug, brand_nm, bpayload, current_date, 1, seed);
      perform _vm_log_identity('brand', b, null, bpayload, p_actor, v_reason, 'UPSERT_MODEL_BUNDLE');
      brands_created := brands_created || to_jsonb(b);
    end if;

    mslug := brand_slug || '-' || replace(m, '_', '-');
    if exists (select 1 from vehicle_models where slug = mslug) then
      skipped := skipped || jsonb_build_object('canonical_id', cid, 'why', 'SLUG_TAKEN', 'slug', mslug); continue;
    end if;

    gen_id := cid || '.gen1';
    mpayload := jsonb_build_object(
      'id', cid, 'brand_id', b, 'name_en', nm, 'name_th', null, 'nameplate', nm, 'aliases', jsonb_build_array(nm),
      'brand', (select jsonb_build_object('id', canonical_id, 'slug', slug, 'name_en', name_en, 'name_th', payload -> 'name_th') from vehicle_brands where canonical_id = b),
      'body_type', 'OTHER', 'cab_type', 'NOT_APPLICABLE', 'registration_type', 'RY1', 'market_scope', 'UNKNOWN',
      'retail_status', st, 'retail_source', '', 'retail_checked_at', null, 'powertrain_checked', false, 'powertrains', '[]'::jsonb,
      'incomplete', true, 'featured', false, 'image_url', null, 'overrides', '{}'::jsonb, 'generation', 'gen1',
      'notes', note, 'seats', null, 'launch_year', null, 'launch_quarter', null, 'market_position', null,
      'production_type', null, 'production_country', null, 'consumer_description', null,
      'origin', jsonb_build_object('source', 'ice', 'batch', p_batch_id));
    gpayload := jsonb_build_object('id', gen_id, 'code', 'gen1', 'model_id', cid, 'segment', null, 'launched', null, 'ended', null, 'seats', null, 'overrides', '{}'::jsonb);

    insert into vehicle_models (canonical_id, brand_id, slug, name_en, generation_id, status, segment, body_type, payload, served_as_of, revision, seed_release_id)
      values (cid, b, mslug, nm, gen_id, st, null, 'OTHER', mpayload, current_date, 1, seed);
    insert into vehicle_generations (canonical_id, model_id, code, segment, launched, ended, payload, revision, seed_release_id)
      values (gen_id, cid, 'gen1', null, null, null, gpayload, 1, seed);
    perform _vm_log_identity('model', cid, null, mpayload, p_actor, v_reason, 'UPSERT_MODEL_BUNDLE');
    created := created || jsonb_build_object('canonical_id', cid, 'slug', mslug);
  end loop;
  return jsonb_build_object('batch_id', p_batch_id, 'created', created, 'created_count', jsonb_array_length(created),
                            'brands_created', brands_created, 'skipped', skipped);
end $$;

-- Undo a batch: removes only what that batch created. Refuses while an APPROVED Ice crosswalk row still points at a model it made
-- (revert the crosswalk first, so no unit is silently orphaned).
create or replace function public.vm_revert_identity_batch(p_batch_id text, p_actor text default 'owner')
returns jsonb
language plpgsql security definer set search_path = public, pg_temp
as $$
declare r record; v_reason text := 'ice-identity:' || p_batch_id; n_models int := 0; n_brands int := 0;
begin
  for r in select entity_id from canonical_write_revisions where topic = 'catalog' and entity_type = 'model' and reason = v_reason loop
    if exists (select 1 from ice_model_crosswalk_scoped where canonical_model_id = r.entity_id) then
      raise exception 'cannot revert %: Ice crosswalk still points at it', r.entity_id;
    end if;
  end loop;
  for r in select entity_id, after_payload from canonical_write_revisions where topic = 'catalog' and entity_type = 'model' and reason = v_reason loop
    delete from vehicle_generations where model_id = r.entity_id;
    delete from vehicle_models where canonical_id = r.entity_id;
    perform _vm_log_identity('model', r.entity_id, r.after_payload, '{}'::jsonb, p_actor, 'revert of ' || v_reason, 'WITHDRAW_MODEL');
    n_models := n_models + 1;
  end loop;
  for r in select entity_id, after_payload from canonical_write_revisions where topic = 'catalog' and entity_type = 'brand' and reason = v_reason loop
    if not exists (select 1 from vehicle_models where brand_id = r.entity_id) then
      delete from vehicle_brands where canonical_id = r.entity_id; n_brands := n_brands + 1;
    end if;
  end loop;
  return jsonb_build_object('batch_id', p_batch_id, 'models_removed', n_models, 'brands_removed', n_brands);
end $$;

-- After models exist, owner-decided PENDING Ice rows become APPROVED (the v67 trigger allows only this transition).
create or replace function public.ice_scoped_promote_pending()
returns integer
language plpgsql security definer set search_path = public, pg_temp
as $$
declare n integer;
begin
  update ice_model_crosswalk_scoped c
     set status = 'APPROVED', canonical_model_id = c.pending_target_id, pending_target_id = null
   where c.status = 'PENDING'
     and exists (select 1 from vehicle_models m where m.canonical_id = c.pending_target_id and m.deleted_at is null);
  get diagnostics n = row_count;
  return n;
end $$;

revoke all on function public.vm_create_identities(text, jsonb, text) from public, anon, authenticated;
revoke all on function public.vm_revert_identity_batch(text, text) from public, anon, authenticated;
revoke all on function public.ice_scoped_promote_pending() from public, anon, authenticated;
grant execute on function public.vm_create_identities(text, jsonb, text) to service_role;
grant execute on function public.vm_revert_identity_batch(text, text) to service_role;
grant execute on function public.ice_scoped_promote_pending() to service_role;

commit;
