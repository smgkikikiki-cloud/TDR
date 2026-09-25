-- Atomic research-article unlock.
--
-- app/api/research/read/route.ts used to check for an existing
-- research_article_reads row, then call tdr_consume_usage() (migration_v34),
-- then insert the read row, as three separate round trips. Two problems
-- with that:
--
--   1. If the quota spend succeeded but the insert then failed for any
--      reason other than the row already existing (a genuine DB error, not
--      a duplicate key), the member was charged a quota unit with no
--      research_article_reads row to show for it -- no entitlement, no
--      refund, and rereading later would try to charge again.
--   2. tdr_consume_usage's own p_action_id dedup is a 5-second fingerprint
--      time bucket (lib/request-fingerprint.ts). Two unlock attempts for
--      the SAME article landing in different buckets could both run their
--      "does a read exist yet?" check before either had committed its
--      insert, both see "no", and both spend a quota unit -- one would
--      then lose the research_article_reads primary-key race on insert,
--      but the quota unit it spent is not given back.
--
-- tdr_unlock_research_article closes both: the existence check, the quota
-- spend and the insert all happen inside this function's own transaction,
-- and every caller unlocking the same (user, article) serializes on a
-- pg_advisory_xact_lock keyed on that exact pair -- not on the 5-second
-- fingerprint bucket -- so the second caller's existence check always sees
-- the first caller's already-committed insert instead of racing it.
create or replace function public.tdr_unlock_research_article(
  p_user_id uuid,
  p_article_id uuid,
  p_period_key text,
  p_limit integer
) returns table(already_unlocked boolean, allowed boolean, used integer, quota_limit integer)
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_quota record;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || '|research_full|' || p_article_id::text, 0));

  if exists (
    select 1 from public.research_article_reads r
    where r.user_id = p_user_id and r.article_id = p_article_id
  ) then
    return query select true, true, null::integer, p_limit;
    return;
  end if;

  -- p_action_id is deliberately null: the advisory lock plus the existence
  -- check above already guarantee this spends quota at most once per
  -- (user, article), a stronger guarantee than tdr_consume_usage's own
  -- action-id dedup path provides on its own.
  select * into v_quota
  from public.tdr_consume_usage(p_user_id, 'research_full', p_period_key, p_limit, null);

  if v_quota.allowed then
    insert into public.research_article_reads(user_id, article_id, period_key)
    values (p_user_id, p_article_id, p_period_key);
  end if;

  return query select false, v_quota.allowed, v_quota.used, v_quota.quota_limit;
end;
$$;

revoke all on function public.tdr_unlock_research_article(uuid, uuid, text, integer) from public, anon, authenticated;
grant execute on function public.tdr_unlock_research_article(uuid, uuid, text, integer) to service_role;

comment on function public.tdr_unlock_research_article is
  'Atomic "check existing research_article_reads row, else spend research_full quota and record the unlock" for one (user, article) -- race-free under concurrent identical calls via pg_advisory_xact_lock keyed on (user_id, article_id), not on tdr_consume_usage''s own 5-second fingerprint bucket. See app/api/research/read/route.ts.';
