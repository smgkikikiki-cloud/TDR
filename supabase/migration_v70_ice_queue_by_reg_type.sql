-- v70: the monthly Ice queue now checks every (model group, registration type) pair, not just the group.
-- Defect in v69: a group that already had a decision for one type (e.g. รย.3) was treated as fully decided, so units of the
-- same group under another type (รย.1 / รย.2) never reached the owner queue.
-- New rule: a pair (group, type) is "decided" only when an APPROVED or EXCLUDED scoped row exists for that type or for scope ALL.
-- A group is queued when its undecided pairs add up to >= p_min_units. The queue row records which types are undecided
-- (uncovered_scopes). NULL means the group has no decision at all, so the admin page writes one ALL decision as before;
-- a list such as 'รย.1,รย.2' makes the admin page write one decision per listed type (exact scope always wins in the resolver).
-- Nothing is approved automatically. Rollback: supabase/rollback_v70_ice_queue_by_reg_type.sql (restores the v69 function).
begin;

alter table public.ice_review_queue add column if not exists uncovered_scopes text;

create or replace function public.ice_monthly_refresh_queue(p_min_units integer default 40)
returns jsonb
language plpgsql security definer set search_path = public, pg_temp
as $$
declare
  mv text; carried int := 0; queued int := 0; closed int := 0; skipped_small int := 0;
begin
  select master_version into mv from ice_package_imports order by imported_at desc limit 1;
  if mv is null then raise exception 'no Ice package has been imported yet'; end if;

  -- 1. pure rename: copy the owner's decision of the old id to the new id (same scope, same target)
  insert into ice_model_crosswalk_scoped (model_group_id, reg_type_scope, status, canonical_model_id, master_version, decision_ref, source_sha256, reason)
  select r.new_model_group_id, s.reg_type_scope, 'APPROVED', s.canonical_model_id, mv,
         'carry-over-rename:' || s.decision_ref, encode(sha256(convert_to('carry-over-rename:' || r.old_model_group_id || '>' || r.new_model_group_id, 'UTF8')), 'hex'), 'Ice renamed group ' || r.old_model_group_id || ' -> ' || r.new_model_group_id
    from ice_model_group_redirects r
    join ice_model_crosswalk_scoped s on s.model_group_id = r.old_model_group_id and s.status = 'APPROVED'
   where r.change_type = 'เปลี่ยนรหัส'
     and exists (select 1 from ice_dims_model_group d where d.model_group_id = r.new_model_group_id)
  on conflict do nothing;
  get diagnostics carried = row_count;

  -- undecided (group, type) pairs with their units over the whole data range
  create temporary table _pairs on commit drop as
  select t.model_group_id, t.reg_type, sum(t.reg_count)::bigint as units
    from ice_reg_trend t
   where not exists (select 1 from ice_model_crosswalk_scoped s
                      where s.model_group_id = t.model_group_id
                        and s.reg_type_scope in ('ALL', t.reg_type)
                        and s.status in ('APPROVED', 'EXCLUDED'))
   group by 1, 2;

  create temporary table _need on commit drop as
  select p.model_group_id, sum(p.units)::bigint as units, string_agg(p.reg_type, ',' order by p.reg_type) as scopes
    from _pairs p group by 1;

  -- groups that exist in the dims table but have no trend rows and no decision at all: keep the v69 whole-group rule
  insert into _need
  select d.model_group_id, coalesce(d.reg_total_all, 0)::bigint, null
    from ice_dims_model_group d
   where not exists (select 1 from ice_reg_trend t where t.model_group_id = d.model_group_id)
     and not exists (select 1 from ice_model_crosswalk_scoped s where s.model_group_id = d.model_group_id and s.status in ('APPROVED', 'EXCLUDED'));

  -- 3. close queue rows with nothing left to decide
  update ice_review_queue q set status = 'DONE', closed_at = now()
   where q.status = 'OPEN' and not exists (select 1 from _need n where n.model_group_id = q.model_group_id and n.units >= p_min_units);
  get diagnostics closed = row_count;

  select count(*) into skipped_small from _need n where n.units < p_min_units;

  -- 2. everything still undecided and big enough waits for the owner
  insert into ice_review_queue (model_group_id, brand, model_name, total_units, reg_types, uncovered_scopes, suggestion, suggestion_source, first_seen_master_version)
  select d.model_group_id, d.brand, d.model_name, n.units,
         (select string_agg(distinct t.reg_type, ',' order by t.reg_type) from ice_reg_trend t where t.model_group_id = d.model_group_id),
         -- a group with no decision at all is decided as a whole (ALL); a partly decided group is decided per undecided type
         case when exists (select 1 from ice_model_crosswalk_scoped s where s.model_group_id = d.model_group_id and s.status in ('APPROVED', 'EXCLUDED')) then n.scopes end,
         x.canonical_model_id, case when x.canonical_model_id is not null then 'matcher:' || x.status end, mv
    from _need n
    join ice_dims_model_group d on d.model_group_id = n.model_group_id
    left join ice_model_crosswalk x on x.model_group_id = d.model_group_id
   where n.units >= p_min_units
  on conflict (model_group_id) do update
     set total_units = excluded.total_units, reg_types = excluded.reg_types, uncovered_scopes = excluded.uncovered_scopes,
         status = 'OPEN', closed_at = null;
  get diagnostics queued = row_count;

  return jsonb_build_object('master_version', mv, 'carried_over_renames', carried, 'queue_rows_touched', queued,
                            'queue_rows_closed', closed, 'ignored_under_min_units', skipped_small,
                            'open_in_queue', (select count(*) from ice_review_queue where status = 'OPEN'),
                            'open_units', (select coalesce(sum(total_units), 0) from ice_review_queue where status = 'OPEN'));
end $$;

revoke all on function public.ice_monthly_refresh_queue(integer) from public, anon, authenticated;
grant execute on function public.ice_monthly_refresh_queue(integer) to service_role;

commit;
