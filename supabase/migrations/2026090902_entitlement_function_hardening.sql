-- The entitlement lookup only needs the caller's own RLS-visible row, so it
-- does not need SECURITY DEFINER privileges.
create or replace function public.has_market_access(requested_product text default 'MARKET_ANALYTICS')
returns boolean
language sql
stable
security invoker
set search_path = public, pg_temp
as $$
  select exists (
    select 1 from public.tdr_entitlements e
    where e.user_id = (select auth.uid())
      and e.product = upper(requested_product)
      and e.status in ('ACTIVE','TRIALING','GRACE')
      and (e.valid_until is null or e.valid_until > now())
  );
$$;

revoke all on function public.has_market_access(text) from public, anon;
grant execute on function public.has_market_access(text) to authenticated, service_role;

-- Existing shared trigger function; pin the lookup path flagged by the DB linter.
alter function public.set_updated_at() set search_path = public, pg_temp;
