-- Rollback for v68: drops the three functions only. It does NOT remove models they created (use vm_revert_identity_batch for that, first).
begin;
drop function if exists public.vm_create_identities(text, jsonb, text);
drop function if exists public._vm_log_identity(text, text, jsonb, jsonb, text, text, text);
drop function if exists public.vm_revert_identity_batch(text, text);
drop function if exists public.ice_scoped_promote_pending();
commit;
