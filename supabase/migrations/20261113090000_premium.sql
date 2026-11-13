begin;
create table public.teilog_premium_customers (
  user_id uuid not null,
  mode text not null check (mode in ('test', 'live')),
  customer_id text not null unique,
  primary key (user_id, mode)
);
create table public.teilog_premium_snapshot (
  id integer primary key check (id = 1),
  through text not null check (through ~ '^20[0-9]{6}$'),
  data jsonb not null
);
alter table public.teilog_premium_customers enable row level security;
alter table public.teilog_premium_snapshot enable row level security;
revoke all on public.teilog_premium_customers, public.teilog_premium_snapshot from public, anon, authenticated;
grant select, insert on public.teilog_premium_customers to service_role;
grant select, insert, update on public.teilog_premium_snapshot to service_role;

create function public.teilog_publish_premium_snapshot(payload jsonb)
returns boolean language sql security invoker set search_path = '' as $$
  with changed as (
    insert into public.teilog_premium_snapshot as old (id, through, data)
    values (1, payload->>'through', payload)
    on conflict (id) do update set through = excluded.through, data = excluded.data
    where old.through <= excluded.through
    returning id
  )
  select exists (select 1 from changed);
$$;
revoke execute on function public.teilog_publish_premium_snapshot(jsonb) from public, anon, authenticated;
grant execute on function public.teilog_publish_premium_snapshot(jsonb) to service_role;
commit;
