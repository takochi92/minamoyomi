begin;
create table public.teilog_premium_owners (
  user_id uuid primary key references auth.users(id) on delete cascade
);
alter table public.teilog_premium_owners enable row level security;
revoke all on public.teilog_premium_owners from public, anon, authenticated;
grant select on public.teilog_premium_owners to service_role;
commit;
