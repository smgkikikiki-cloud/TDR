-- registration_brand_aliases.brand_id was NOT NULL, so binding a DLT
-- label to a genuinely new brand -- one with no legacy public.brands row
-- at all -- was impossible: assignRegistrationIdentity required a
-- tdr_brand_id before it would even resolve a target, which blocked the
-- exact case a new marque entering the market produces. Mirrors what
-- migration_v41 section 6 already did for registration_model_aliases.
--
-- Additive only. Nothing dropped, every legacy path keeps working: an
-- alias resolved through the legacy brand_id is untouched by this.

alter table public.registration_brand_aliases alter column brand_id drop not null;

alter table public.registration_brand_aliases
  add column if not exists canonical_brand_id text;

alter table public.registration_brand_aliases
  drop constraint if exists registration_brand_aliases_identity_check;
alter table public.registration_brand_aliases
  add constraint registration_brand_aliases_identity_check
  check (brand_id is not null or canonical_brand_id is not null);

comment on column public.registration_brand_aliases.canonical_brand_id is
  'Canonical brand this raw label maps to. Preferred over the legacy brand_id bridge; a brand new enough to have no legacy public.brands row can still be assigned through this alone.';

-- registration_model_aliases.brand_id (the FK it joins registration_
-- brand_aliases through) was also NOT NULL, for the identical reason:
-- a model alias under a brand that has no legacy row could not be
-- written either, even though migration_v41 already let the MODEL half
-- of that same alias go canonical-only. Here brand_id is also part of
-- the table's PRIMARY KEY (brand_id, registration_type, alias_norm) --
-- Postgres refuses NULL in a primary key column outright, so making it
-- nullable means replacing the primary key, not just dropping a NOT
-- NULL. Nothing references this table by foreign key (checked: no other
-- migration does), so the replacement is safe.

alter table public.registration_model_aliases
  add column if not exists canonical_brand_id text;

alter table public.registration_model_aliases drop constraint if exists registration_model_aliases_pkey;
alter table public.registration_model_aliases add column if not exists id uuid not null default gen_random_uuid();
do $$ begin
  alter table public.registration_model_aliases add constraint registration_model_aliases_pkey primary key (id);
exception when invalid_table_definition then null; end $$;

alter table public.registration_model_aliases alter column brand_id drop not null;

alter table public.registration_model_aliases
  drop constraint if exists registration_model_aliases_identity_check;
alter table public.registration_model_aliases
  add constraint registration_model_aliases_identity_check
  check (brand_id is not null or canonical_brand_id is not null);

-- What the old composite primary key actually enforced: one alias per
-- (brand, registration type, label). coalesce so a legacy-brand row and
-- a canonical-only row are compared on whichever identity they carry.
drop index if exists registration_model_aliases_identity_idx;
create unique index registration_model_aliases_identity_idx
  on public.registration_model_aliases (
    coalesce(brand_id::text, canonical_brand_id), registration_type, alias_norm
  );

comment on column public.registration_model_aliases.canonical_brand_id is
  'Canonical brand this model alias belongs to, mirroring registration_brand_aliases.canonical_brand_id -- set together so a model alias under a brand-new marque never has to wait on the legacy brand_id bridge either.';
comment on index public.registration_model_aliases_identity_idx is
  'Replaces the old (brand_id, registration_type, alias_norm) primary key, which could not allow NULL brand_id. Enforces the same one-alias-per-brand-and-label rule using whichever brand identity (legacy or canonical) the row carries.';
