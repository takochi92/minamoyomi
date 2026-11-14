begin;
create table public.teilog_premium_daily (
  through text primary key check (through ~ '^20[0-9]{6}$'),
  data jsonb not null check (jsonb_typeof(data) = 'object' and data->>'through' is not distinct from through)
);
alter table public.teilog_premium_daily enable row level security;
revoke all on public.teilog_premium_daily from public, anon, authenticated;
grant select, insert, delete on public.teilog_premium_daily to service_role;

create function public.teilog_store_premium_snapshot(payload jsonb)
returns boolean language plpgsql security invoker set search_path = '' as $$
declare
  cutoff text := payload->>'through';
  newest text;
begin
  -- Serialize first publish and retry so a different payload cannot replace that day's record.
  perform pg_catalog.pg_advisory_xact_lock(1157930678, 1);
  select max(through) into newest from public.teilog_premium_daily;
  if cutoff is null or (newest is not null and cutoff < newest) then
    return exists (select 1 from public.teilog_premium_daily where through = cutoff and data = payload);
  end if;
  insert into public.teilog_premium_daily(through,data) values (cutoff,payload)
  on conflict (through) do nothing;
  delete from public.teilog_premium_daily
    where through < pg_catalog.to_char(pg_catalog.to_date(cutoff,'YYYYMMDD') - 35,'YYYYMMDD');
  return exists (select 1 from public.teilog_premium_daily where through = cutoff and data = payload);
end;
$$;
revoke execute on function public.teilog_store_premium_snapshot(jsonb) from public, anon, authenticated;
grant execute on function public.teilog_store_premium_snapshot(jsonb) to service_role;
commit;
