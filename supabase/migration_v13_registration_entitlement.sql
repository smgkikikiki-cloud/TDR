-- Phase D: registration entitlement boundary.
--
-- Raw model/month registration facts are paid intelligence, not a public
-- Supabase table.  The public catalogue may advertise that analysis exists,
-- but browser clients must never be able to read the fact table directly.
--
-- IMPORTANT: a Supabase `authenticated` session is not proof of a paid TDR
-- entitlement.  Member reads will be added later through an entitlement-aware
-- server surface; do not add an authenticated SELECT policy here.

alter table public.registrations enable row level security;

drop policy if exists "public read registrations" on public.registrations;

revoke all on table public.registrations from anon, authenticated;
grant select, insert, update, delete on table public.registrations to service_role;

comment on table public.registrations is
  'Raw registration facts. Service-role only. Public/member products must use explicit entitlement-aware projections or server endpoints, never direct anon/authenticated table access.';
