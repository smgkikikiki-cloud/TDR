-- Phase 3 operational hardening discovered by Supabase security advisor after
-- applying the registration v2 migrations in production. Pin the trigger
-- function search_path so future environments reproduce the live hardening.

alter function public.reject_registration_observation_v2_mutation()
  set search_path = public, pg_temp;
