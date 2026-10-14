-- v69: monthly Ice routine without AI. After a new package is imported, one call does everything that can be done by rule:
--   1. a model group whose id was only RENAMED by Ice (ice_model_group_redirects, type 'เปลี่ยนรหัส') inherits the owner's existing decision for the old id;
--   2. every other model group that has no decision at all and at least p_min_units registrations (the owner's "<40 units does not count" rule)
--      goes to the owner review queue, with the old matcher's suggestion if there is one;
--   3. queue rows that have since been decided are closed.
-- Nothing here approves a new car by itself: merges, splits and brand-new groups always wait in the queue for the owner.
-- Tables/functions only; nothing runs until the function is called. Rollback: supabase/rollback_v69_ice_monthly_queue.sql
begin;

create table if not exists public.ice_review_queue (
  model_group_id text primary key,
  brand text,
  model_name text,
  total_units bigint not null default 0,
  reg_types text,
  suggestion text,
  suggestion_source text,
  status text not null default 'OPEN' check (status in ('OPEN','DONE')),
  first_seen_master_version text,
  created_at timestamptz not null default now(),
  closed_at timestamptz
);
alter table public.ice_review_queue enable row level security;
grant select, insert, update on public.ice_review_queue to service_role;

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

  -- 3. close queue rows that now have a decision
  update ice_review_queue q set status = 'DONE', closed_at = now()
   where q.status = 'OPEN' and exists (select 1 from ice_model_crosswalk_scoped s where s.model_group_id = q.model_group_id);
  get diagnostics closed = row_count;

  -- 2. everything still undecided and big enough waits for the owner
  select count(*) into skipped_small from ice_dims_model_group d
   where coalesce(d.reg_total_all, 0) < p_min_units
     and not exists (select 1 from ice_model_crosswalk_scoped s where s.model_group_id = d.model_group_id);

  insert into ice_review_queue (model_group_id, brand, model_name, total_units, reg_types, suggestion, suggestion_source, first_seen_master_version)
  select d.model_group_id, d.brand, d.model_name, coalesce(d.reg_total_all, 0),
         (select string_agg(distinct t.reg_type, ',' order by t.reg_type) from ice_reg_trend t where t.model_group_id = d.model_group_id),
         x.canonical_model_id, case when x.canonical_model_id is not null then 'matcher:' || x.status end, mv
    from ice_dims_model_group d
    left join ice_model_crosswalk x on x.model_group_id = d.model_group_id
   where coalesce(d.reg_total_all, 0) >= p_min_units
     and not exists (select 1 from ice_model_crosswalk_scoped s where s.model_group_id = d.model_group_id)
  on conflict (model_group_id) do update
     set total_units = excluded.total_units, reg_types = excluded.reg_types, status = 'OPEN', closed_at = null;
  get diagnostics queued = row_count;

  return jsonb_build_object('master_version', mv, 'carried_over_renames', carried, 'queue_rows_touched', queued,
                            'queue_rows_closed', closed, 'ignored_under_min_units', skipped_small,
                            'open_in_queue', (select count(*) from ice_review_queue where status = 'OPEN'),
                            'open_units', (select coalesce(sum(total_units), 0) from ice_review_queue where status = 'OPEN'));
end $$;

-- Coverage per month under the current decisions (APPROVED / EXCLUDED / not covered).
create or replace function public.ice_coverage_by_period()
returns table (period text, total_units numeric, approved_units numeric, approved_pct numeric, excluded_units numeric, uncovered_units numeric)
language sql stable security definer set search_path = public, pg_temp
as $$
  with t as (select period, reg_type, model_group_id, sum(reg_count) u from ice_reg_trend group by 1,2,3),
  c as (select t.period, t.u,
          (select max(case when s.status = 'APPROVED' then 1 else 2 end) from ice_model_crosswalk_scoped s
            where s.model_group_id = t.model_group_id and s.reg_type_scope in ('ALL', t.reg_type) and s.status in ('APPROVED','EXCLUDED')) st from t)
  select period, sum(u), coalesce(sum(u) filter (where st = 1), 0),
         round(100.0 * coalesce(sum(u) filter (where st = 1), 0) / nullif(sum(u), 0), 2),
         coalesce(sum(u) filter (where st = 2), 0), coalesce(sum(u) filter (where st is null), 0)
    from c group by period order by period desc;
$$;

revoke all on function public.ice_monthly_refresh_queue(integer) from public, anon, authenticated;
revoke all on function public.ice_coverage_by_period() from public, anon, authenticated;
grant execute on function public.ice_monthly_refresh_queue(integer) to service_role;
grant execute on function public.ice_coverage_by_period() to service_role;

commit;
