-- Disposable editorial intelligence, deliberately independent of Vehicle Master.
-- Keep access server-side until the later admin and public access chunks define
-- their respective gates. Neither table has an FK to canonical vehicle data.

create table public.upcoming_cars (
  id bigint generated always as identity primary key,
  vehicle_id text generated always as (
    'UP-' || case when id < 10000 then lpad(id::text, 4, '0') else id::text end
  ) stored unique,
  vehicle_name text not null check (length(btrim(vehicle_name)) > 0),
  status text not null check (status in ('RUMORED', 'CONFIRMED')),
  confidence text not null check (confidence in ('HIGH', 'MEDIUM', 'LOW')),
  rumor_half text check (rumor_half in ('H1', 'H2')),
  launch_year integer not null check (launch_year > 0),
  confirmed_quarter text check (confirmed_quarter in ('Q1', 'Q2', 'Q3', 'Q4')),
  confirmed_month integer check (confirmed_month between 1 and 12),
  confirmed_day integer check (confirmed_day between 1 and 31),
  description text not null default '',
  internal_notes text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint upcoming_cars_timing_check check (
    (status = 'RUMORED' and rumor_half is not null
      and confirmed_quarter is null and confirmed_month is null and confirmed_day is null)
    or
    (status = 'CONFIRMED' and rumor_half is null
      and (confirmed_day is null or confirmed_month is not null)
      and (confirmed_month is null or confirmed_quarter is null
        or confirmed_quarter = ('Q' || ((confirmed_month - 1) / 3 + 1)::text)))
  )
);

create table public.upcoming_car_updates (
  id bigint generated always as identity primary key,
  upcoming_car_id bigint not null references public.upcoming_cars(id) on delete cascade,
  update_date date not null default current_date,
  message text not null check (length(btrim(message)) > 0),
  created_at timestamptz not null default now()
);

create index upcoming_car_updates_car_date_idx
  on public.upcoming_car_updates(upcoming_car_id, update_date desc, id desc);

create function public.set_upcoming_car_updated_at()
returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create trigger upcoming_cars_updated_at
before update on public.upcoming_cars
for each row execute function public.set_upcoming_car_updated_at();

alter table public.upcoming_cars enable row level security;
alter table public.upcoming_car_updates enable row level security;
revoke all on table public.upcoming_cars, public.upcoming_car_updates from public, anon, authenticated;
grant select, insert, update, delete on table public.upcoming_cars, public.upcoming_car_updates to service_role;
revoke all on sequence public.upcoming_cars_id_seq, public.upcoming_car_updates_id_seq from public, anon, authenticated;
grant usage, select on sequence public.upcoming_cars_id_seq, public.upcoming_car_updates_id_seq to service_role;
