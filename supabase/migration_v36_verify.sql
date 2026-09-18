-- Operator runbook for migration_v36_admin_edit_sessions_trim_kind.sql.
--
-- The migration itself is in that file; this one is the evidence around it.
-- Nothing here changes a row: sections 1 and 3 only read, and section 4's
-- write is rolled back. Run it in the Supabase SQL editor (which connects as
-- a superuser role, so it sees grants and can run DDL -- PostgREST cannot,
-- which is why the application's own service-role key is not enough).
--
-- Order:
--   1. run SECTION 1 and keep the output -- it is the "before" state;
--   2. run migration_v36_admin_edit_sessions_trim_kind.sql;
--   3. run SECTION 3 -- every row must read PASS, and the row TOTAL must
--      equal the TOTAL from section 1;
--   4. run SECTION 4 -- proves the shape lib/edit-session-store.ts actually
--      writes is accepted, and leaves nothing behind.
--
-- If SECTION 1 does not match the v35 schema (missing column, different
-- constraint definition, an unexpected kind or status value), STOP: the
-- database has drifted and the migration must be corrected against what is
-- really there before it is applied.


-- ============================================================
-- SECTION 1 -- BEFORE. Run this first, keep the output.
-- Re-usable as-is after the migration; SECTION 3 adds the assertions.
-- ============================================================
select 'column' as section, column_name as item,
       data_type || case when is_nullable = 'YES' then ' NULL' else ' NOT NULL' end as value
  from information_schema.columns
 where table_schema = 'public' and table_name = 'admin_edit_sessions'
union all
select 'constraint', conname, pg_get_constraintdef(oid)
  from pg_constraint where conrelid = 'public.admin_edit_sessions'::regclass
union all
select 'index', indexname, indexdef
  from pg_indexes where schemaname = 'public' and tablename = 'admin_edit_sessions'
union all
select 'rls', 'enabled', relrowsecurity::text
  from pg_class where oid = 'public.admin_edit_sessions'::regclass
union all
select 'rls', 'policy count', count(*)::text
  from pg_policies where schemaname = 'public' and tablename = 'admin_edit_sessions'
union all
select 'privilege', r.rolname || ' ' || p.priv,
       has_table_privilege(r.rolname, 'public.admin_edit_sessions', p.priv)::text
  from (values ('anon'), ('authenticated'), ('service_role')) as r(rolname),
       (values ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')) as p(priv)
union all
select 'rows', kind || ' / ' || status, count(*)::text
  from public.admin_edit_sessions group by 1, 2
union all
select 'rows', 'TOTAL', count(*)::text from public.admin_edit_sessions
union all
select 'rows', 'PENDING_REVIEW missing payload/diff/reason/evidence', count(*)::text
  from public.admin_edit_sessions
 where status = 'PENDING_REVIEW'
   and (batch_payload is null or diff is null or reason is null or evidence is null)
 order by 1, 2;


-- ============================================================
-- SECTION 2 -- apply migration_v36_admin_edit_sessions_trim_kind.sql
-- (that file, verbatim, as its own statement -- it carries its own
-- begin/commit).
-- ============================================================


-- ============================================================
-- SECTION 3 -- AFTER. Every row must read PASS.
-- Then re-run SECTION 1 and check TOTAL is unchanged.
-- ============================================================
with t as (select 'public.admin_edit_sessions'::regclass as rel)
select 'kind is only MODEL_GENERATION or TRIM' as check,
       case when not exists (select 1 from public.admin_edit_sessions
                              where kind not in ('MODEL_GENERATION', 'TRIM'))
            then 'PASS' else 'FAIL' end as result
union all
select 'status is only PENDING_REVIEW or CONSUMED',
       case when not exists (select 1 from public.admin_edit_sessions
                              where status not in ('PENDING_REVIEW', 'CONSUMED'))
            then 'PASS' else 'FAIL' end
union all
select 'draft_entries column is gone',
       case when not exists (select 1 from information_schema.columns
                              where table_schema = 'public' and table_name = 'admin_edit_sessions'
                                and column_name = 'draft_entries') then 'PASS' else 'FAIL' end
union all
select 'default_evidence column is gone',
       case when not exists (select 1 from information_schema.columns
                              where table_schema = 'public' and table_name = 'admin_edit_sessions'
                                and column_name = 'default_evidence') then 'PASS' else 'FAIL' end
union all
select 'kind check rejects the old values',
       case when exists (select 1 from pg_constraint, t
                          where conrelid = t.rel
                            and conname = 'admin_edit_sessions_kind_check'
                            and pg_get_constraintdef(oid) not like '%MARKET_TRIM%'
                            and pg_get_constraintdef(oid) like '%TRIM%')
            then 'PASS' else 'FAIL' end
union all
select 'status check rejects DRAFT',
       case when exists (select 1 from pg_constraint, t
                          where conrelid = t.rel
                            and conname = 'admin_edit_sessions_status_check'
                            and pg_get_constraintdef(oid) not like '%DRAFT%')
            then 'PASS' else 'FAIL' end
union all
select 'pending_review_is_compiled constraint survived',
       case when exists (select 1 from pg_constraint, t
                          where conrelid = t.rel
                            and conname = 'admin_edit_sessions_pending_review_is_compiled')
            then 'PASS' else 'FAIL' end
union all
select 'consumed_has_timestamp constraint survived',
       case when exists (select 1 from pg_constraint, t
                          where conrelid = t.rel
                            and conname = 'admin_edit_sessions_consumed_has_timestamp')
            then 'PASS' else 'FAIL' end
union all
select 'both indexes survived',
       case when (select count(*) from pg_indexes
                   where schemaname = 'public' and tablename = 'admin_edit_sessions'
                     and indexname in ('admin_edit_sessions_owner_idx',
                                       'admin_edit_sessions_expiry_idx')) = 2
            then 'PASS' else 'FAIL' end
union all
select 'every column the app reads survived',
       case when (select count(*) from information_schema.columns
                   where table_schema = 'public' and table_name = 'admin_edit_sessions'
                     and column_name in ('id', 'kind', 'status', 'model_id', 'trim_id',
                                         'actor', 'page_release_id', 'batch_payload', 'diff',
                                         'reason', 'evidence', 'expires_at', 'consumed_at',
                                         'created_at', 'updated_at')) = 15
            then 'PASS' else 'FAIL' end
union all
select 'RLS still enabled',
       case when (select relrowsecurity from pg_class, t where oid = t.rel)
            then 'PASS' else 'FAIL' end
union all
select 'still zero RLS policies (default deny)',
       case when (select count(*) from pg_policies
                   where schemaname = 'public' and tablename = 'admin_edit_sessions') = 0
            then 'PASS' else 'FAIL' end
union all
select 'anon and authenticated hold no privilege',
       case when not exists (
              select 1 from (values ('anon'), ('authenticated')) as r(rolname),
                            (values ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')) as p(priv)
               where has_table_privilege(r.rolname, 'public.admin_edit_sessions', p.priv))
            then 'PASS' else 'FAIL' end
union all
select 'service_role keeps select/insert/update/delete',
       case when (select bool_and(has_table_privilege('service_role',
                                    'public.admin_edit_sessions', p.priv))
                    from (values ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')) as p(priv))
            then 'PASS' else 'FAIL' end
union all
select 'no CONSUMED row without a consumed_at',
       case when not exists (select 1 from public.admin_edit_sessions
                              where status = 'CONSUMED' and consumed_at is null)
            then 'PASS' else 'FAIL' end
union all
select 'no loadable PENDING_REVIEW row lost its payload',
       case when not exists (select 1 from public.admin_edit_sessions
                              where status = 'PENDING_REVIEW'
                                and (batch_payload is null or diff is null
                                     or reason is null or evidence is null))
            then 'PASS' else 'FAIL' end
 order by 1;


-- ============================================================
-- SECTION 4 -- smoke test the shape lib/edit-session-store.ts writes.
-- Wrapped in a transaction that is rolled back, so production keeps no
-- fabricated row. Run the whole block; the last select must report 0.
-- ============================================================
begin;

insert into public.admin_edit_sessions
  (id, kind, status, model_id, trim_id, actor, page_release_id,
   batch_payload, diff, reason, evidence, expires_at)
values
  ('v36-smoke-rollback', 'TRIM', 'PENDING_REVIEW', 'smoke.model',
   'smoke.model.gen.x.trim.y', 'v36-smoke', 'smoke-release',
   '{"commands": []}'::jsonb, '[]'::jsonb, 'v36 smoke test',
   '{"sourceKind": "admin", "reviewedAt": "1970-01-01T00:00:00Z"}'::jsonb,
   now() + interval '1 hour');

-- createProposal's row is loadable exactly the way loadProposal reads it.
select 'loadProposal finds it' as step, count(*)::text as value
  from public.admin_edit_sessions
 where id = 'v36-smoke-rollback' and actor = 'v36-smoke'
   and status = 'PENDING_REVIEW' and expires_at > now();

-- consumeProposal's atomic conditional update.
update public.admin_edit_sessions
   set status = 'CONSUMED', consumed_at = now(), updated_at = now()
 where id = 'v36-smoke-rollback' and actor = 'v36-smoke'
   and status = 'PENDING_REVIEW' and expires_at > now();

select 'consumeProposal left it CONSUMED' as step, status as value
  from public.admin_edit_sessions where id = 'v36-smoke-rollback';

rollback;

-- Must be 0: nothing fabricated is left in production.
select 'rows left behind (must be 0)' as step, count(*)::text as value
  from public.admin_edit_sessions where id = 'v36-smoke-rollback';
