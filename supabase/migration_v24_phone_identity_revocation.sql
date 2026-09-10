-- Fail closed when a Supabase Auth phone is removed, unconfirmed or invalid.
-- A phone identity may authorize customer recovery only while Auth confirms it.

create or replace function public.tdr_sync_customer_from_auth()
returns trigger language plpgsql security definer set search_path = public, pg_temp as $$
declare customer_uuid uuid;
begin
  insert into public.tdr_customers(auth_user_id, updated_at)
  values (new.id, now())
  on conflict (auth_user_id) do update set updated_at = now()
  returning id into customer_uuid;

  if new.phone is null or new.phone_confirmed_at is null
     or new.phone !~ '^\+[1-9][0-9]{7,14}$' then
    update public.tdr_customer_phone_identities
    set is_primary = false,
        revoked_at = coalesce(revoked_at, now()),
        updated_at = now()
    where customer_id = customer_uuid and is_primary;
    return new;
  end if;

  update public.tdr_customer_phone_identities
  set is_primary = false,
      revoked_at = coalesce(revoked_at, now()),
      updated_at = now()
  where customer_id = customer_uuid
    and is_primary
    and phone_e164 <> new.phone;

  insert into public.tdr_customer_phone_identities(
    customer_id, phone_e164, verified_at, is_primary, revoked_at, updated_at
  ) values (customer_uuid, new.phone, new.phone_confirmed_at, true, null, now())
  on conflict (phone_e164) do update
    set verified_at = greatest(public.tdr_customer_phone_identities.verified_at, excluded.verified_at),
        is_primary = true,
        revoked_at = null,
        updated_at = now()
    where public.tdr_customer_phone_identities.customer_id = excluded.customer_id;

  return new;
end $$;

revoke all on function public.tdr_sync_customer_from_auth() from public, anon, authenticated;

comment on function public.tdr_sync_customer_from_auth() is
  'Maps confirmed Auth phones to stable customers and revokes the primary identity when confirmation is absent.';
