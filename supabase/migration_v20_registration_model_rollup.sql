-- One canonical model must produce one monthly analytics row even when DLT
-- emits several raw spelling/trim strings that review to that same model.
-- Unmapped rows remain separated by their raw brand/model identity.

create or replace view public.registration_monthly_model
with (security_invoker = true)
as
with normalized as (
  select r.period,
         case when r.model_id is not null then 'model:' || r.model_id::text
              else 'raw:' || public.normalize_registration_token(r.brand_name_raw) || ':' ||
                   public.normalize_registration_token(r.model_name_raw) end as entity_key,
         r.model_id,
         coalesce(b.slug, public.normalize_registration_token(r.brand_name_raw)) as brand_key,
         coalesce(b.name_en, r.brand_name_raw) as brand_name,
         coalesce(m.name_en, r.model_name_raw) as model_name,
         m.segment,
         m.body_type,
         m.powertrains,
         r.registrations
  from public.registrations r
  left join public.models m on m.id = r.model_id
  left join public.registration_brand_aliases rba
    on rba.raw_brand_norm = public.normalize_registration_token(r.brand_name_raw)
  left join public.brands b on b.id = coalesce(m.brand_id, rba.brand_id)
)
select period, entity_key, model_id, brand_key, brand_name, model_name,
       segment, body_type, powertrains,
       sum(registrations)::bigint as registrations,
       count(*)::bigint as source_rows,
       bool_and(model_id is not null) as canonically_mapped
from normalized
group by period, entity_key, model_id, brand_key, brand_name, model_name,
         segment, body_type, powertrains;

comment on view public.registration_monthly_model is
  'One monthly row per canonical model; multiple reviewed DLT raw spellings roll up. Unmapped raw identities remain separate.';
