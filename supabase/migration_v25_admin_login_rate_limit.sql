create table if not exists public.tdr_admin_login_rate_limits (
  key_hash text primary key,
  failure_count integer not null default 0 check (failure_count >= 0),
  window_started_at timestamptz not null default now(),
  locked_until timestamptz,
  updated_at timestamptz not null default now(),
  constraint tdr_admin_login_rate_limits_key_hash_check check (length(key_hash) = 64)
);

alter table public.tdr_admin_login_rate_limits enable row level security;
revoke all on table public.tdr_admin_login_rate_limits from anon, authenticated;

create or replace function public.tdr_admin_login_rate_check(p_key_hash text)
returns table (allowed boolean, retry_after_seconds integer)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_locked_until timestamptz;
begin
  if p_key_hash is null or length(p_key_hash) <> 64 then
    return query select false, 900;
    return;
  end if;

  select locked_until
    into v_locked_until
  from public.tdr_admin_login_rate_limits
  where key_hash = p_key_hash;

  if not found or v_locked_until is null or v_locked_until <= now() then
    return query select true, 0;
    return;
  end if;

  return query
  select false,
         greatest(1, ceil(extract(epoch from (v_locked_until - now())))::integer);
end;
$$;

create or replace function public.tdr_admin_login_rate_record_failure(p_key_hash text)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_failure_count integer;
  v_window_started_at timestamptz;
  v_locked_until timestamptz;
begin
  if p_key_hash is null or length(p_key_hash) <> 64 then
    return;
  end if;

  insert into public.tdr_admin_login_rate_limits (key_hash)
  values (p_key_hash)
  on conflict (key_hash) do nothing;

  select failure_count, window_started_at, locked_until
    into v_failure_count, v_window_started_at, v_locked_until
  from public.tdr_admin_login_rate_limits
  where key_hash = p_key_hash
  for update;

  if v_locked_until is not null and v_locked_until > now() then
    return;
  end if;

  if v_window_started_at <= now() - interval '15 minutes' then
    v_failure_count := 0;
    v_window_started_at := now();
    v_locked_until := null;
  end if;

  v_failure_count := v_failure_count + 1;
  if v_failure_count >= 6 then
    v_locked_until := now() + interval '15 minutes';
  end if;

  update public.tdr_admin_login_rate_limits
  set failure_count = v_failure_count,
      window_started_at = v_window_started_at,
      locked_until = v_locked_until,
      updated_at = now()
  where key_hash = p_key_hash;
end;
$$;

create or replace function public.tdr_admin_login_rate_clear(p_key_hash text)
returns void
language sql
security definer
set search_path = public
as $$
  delete from public.tdr_admin_login_rate_limits where key_hash = p_key_hash;
$$;

revoke all on function public.tdr_admin_login_rate_check(text) from public, anon, authenticated;
revoke all on function public.tdr_admin_login_rate_record_failure(text) from public, anon, authenticated;
revoke all on function public.tdr_admin_login_rate_clear(text) from public, anon, authenticated;

grant execute on function public.tdr_admin_login_rate_check(text) to service_role;
grant execute on function public.tdr_admin_login_rate_record_failure(text) to service_role;
grant execute on function public.tdr_admin_login_rate_clear(text) to service_role;
