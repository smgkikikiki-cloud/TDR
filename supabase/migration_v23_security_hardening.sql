-- Security/performance follow-up found by Supabase advisors.
alter function public.normalize_registration_token(text)
  set search_path = public, pg_temp;

create index if not exists tdr_payment_customers_customer_idx
  on public.tdr_payment_customers(customer_id);
