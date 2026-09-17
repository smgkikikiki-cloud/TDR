-- Migrate admin_edit_sessions from the applied v35 schema to the one the
-- unified trim editor uses.
--
-- v35 is live in production with kind in
-- ('MODEL_GENERATION','MARKET_TRIM','SPEC_DRAFT') and a mutable DRAFT status
-- backed by draft_entries/default_evidence. The editor no longer accumulates
-- specs in a draft: one trim is one form, one diff, one proposal, so the
-- only trim-scoped kind now is 'TRIM'.
--
-- Written to run against the real v35 table with real rows in it:
--   * every existing row is preserved, relabelled rather than deleted;
--   * MARKET_TRIM and SPEC_DRAFT both described a trim edit, so both become
--     TRIM;
--   * a row still sitting in the mutable DRAFT status cannot be represented
--     any more (its draft_entries were never compiled into a batch), so it is
--     retired as CONSUMED instead of dropped -- inert, still auditable, and
--     never loadable by the new code, which only reads PENDING_REVIEW;
--   * a PENDING_REVIEW proposal an admin is in the middle of confirming keeps
--     its payload, diff, evidence and expiry untouched, so nothing in flight
--     is lost;
--   * batch_payload/diff/reason/evidence stay nullable, because retired DRAFT
--     rows legitimately have none; the pending_review_is_compiled constraint
--     still guarantees they are present for anything the app can actually
--     load.
--
-- ORDER MATTERS, and not in the obvious direction. The constraints come off
-- FIRST, because it is the OLD check that rejects the NEW values: with v35's
-- `kind in ('MODEL_GENERATION','MARKET_TRIM','SPEC_DRAFT')` still in place,
-- `set kind = 'TRIM'` fails on the very first row. Dropping first, updating,
-- then re-adding is the only order that works on a table that actually has
-- rows in it -- which is why this is covered by a test that applies the real
-- v35 to a real Postgres with real rows, not by reading the file.
--
-- Wrapped in one transaction so a failure part-way leaves the table exactly
-- as it was rather than half-migrated. Re-runnable, and safe to apply to a
-- database that has already had it.

begin;

alter table public.admin_edit_sessions
  drop constraint if exists admin_edit_sessions_kind_check;
alter table public.admin_edit_sessions
  drop constraint if exists admin_edit_sessions_status_check;
alter table public.admin_edit_sessions
  drop constraint if exists admin_edit_sessions_draft_entries_check;

update public.admin_edit_sessions
   set status = 'CONSUMED',
       consumed_at = coalesce(consumed_at, now()),
       updated_at = now()
 where status = 'DRAFT';

update public.admin_edit_sessions
   set kind = 'TRIM',
       updated_at = now()
 where kind in ('MARKET_TRIM', 'SPEC_DRAFT');

alter table public.admin_edit_sessions
  add constraint admin_edit_sessions_kind_check
  check (kind in ('MODEL_GENERATION', 'TRIM'));
alter table public.admin_edit_sessions
  add constraint admin_edit_sessions_status_check
  check (status in ('PENDING_REVIEW', 'CONSUMED'));

alter table public.admin_edit_sessions drop column if exists draft_entries;
alter table public.admin_edit_sessions drop column if exists default_evidence;

comment on table public.admin_edit_sessions is
  'Server-only: pending Canonical Vehicle Editor proposals (MODEL_GENERATION or TRIM) awaiting human review before entering canonical_input_batches. An admin''s review URL carries only this table''s id -- never the payload, diff, evidence or reason.';

commit;
