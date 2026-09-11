-- Retail lifecycle must be evidence-backed, not inferred from presence in a release.
--
-- v15 treated an active canonical release as proof that every model/trim in it
-- was currently sold.  That conflated identity/homologation coverage with the
-- live Thai retail lineup and made LIST_PRICE coverage structurally impossible.
--
-- The enriched release now emits CURRENT/HISTORICAL/UNVERIFIED explicitly.
-- These constraints deliberately reject the old lowercase/default "current"
-- fallback, so any publisher that bypasses the enriched release fails closed.

alter table public.canonical_market_trim_projection
  alter column status set default 'UNVERIFIED';

-- Repair already-published model rows from their canonical Model payload.
-- Vehicle Master validates that CURRENT carries retail_source + checked date.
update public.canonical_model_projection
set status = case
  when upper(coalesce(payload->>'retail_status', 'UNVERIFIED')) in
       ('CURRENT','HISTORICAL','UNVERIFIED')
    then upper(coalesce(payload->>'retail_status', 'UNVERIFIED'))
  else 'UNVERIFIED'
end;

-- Repair existing trim rows using only evidence already present in the active
-- immutable release: historical parent lifecycle or a real current LIST_PRICE.
-- Merely belonging to an un-ended generation is not evidence of current sale.
update public.canonical_market_trim_projection t
set status = case
  when m.status = 'HISTORICAL' then 'HISTORICAL'
  when g.ended is not null and g.ended <= r.as_of then 'HISTORICAL'
  when coalesce(nullif(t.current_list_price->>'amount_thb','')::numeric, 0) > 0
    then 'CURRENT'
  else 'UNVERIFIED'
end
from public.canonical_model_projection m,
     public.canonical_generation_projection g,
     public.canonical_vehicle_releases r
where m.release_id = t.release_id
  and m.canonical_id = t.model_id
  and g.release_id = t.release_id
  and g.canonical_id = t.generation_id
  and r.release_id = t.release_id;

alter table public.canonical_model_projection
  drop constraint if exists canonical_model_projection_retail_status_check;
alter table public.canonical_model_projection
  add constraint canonical_model_projection_retail_status_check
  check (status in ('CURRENT','HISTORICAL','UNVERIFIED'));

alter table public.canonical_market_trim_projection
  drop constraint if exists canonical_market_trim_projection_retail_status_check;
alter table public.canonical_market_trim_projection
  add constraint canonical_market_trim_projection_retail_status_check
  check (status in ('CURRENT','HISTORICAL','UNVERIFIED'));

comment on column public.canonical_model_projection.status is
  'Canonical Thai retail lifecycle: CURRENT/HISTORICAL/UNVERIFIED. Never inherited from legacy editorial status.';
comment on column public.canonical_market_trim_projection.status is
  'Retail trim lifecycle. Identity/ECO presence alone is not CURRENT evidence; unknown state fails closed as UNVERIFIED.';
