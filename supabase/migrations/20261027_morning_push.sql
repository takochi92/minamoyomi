-- Separate from private notes. Apply only to the dedicated Teilog project.
begin;
create table public.teilog_push_devices (
  id uuid primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  subscription jsonb not null,
  rules jsonb not null default '{}',
  racer_names jsonb not null default '{}',
  enabled boolean not null default false,
  revision bigint not null default 1,
  updated_at timestamptz not null default now(),
  check (octet_length(subscription::text)<6000 and octet_length(rules::text)<100000)
);
create unique index teilog_push_endpoint on public.teilog_push_devices ((subscription->>'endpoint')) where enabled;
create index teilog_push_owner on public.teilog_push_devices(user_id);
alter table public.teilog_push_devices enable row level security;
revoke all on public.teilog_push_devices from anon, authenticated;
grant select on public.teilog_push_devices to authenticated;
create policy "Own notification devices" on public.teilog_push_devices for select to authenticated using ((select auth.uid())=user_id);
create table public.teilog_push_deliveries (
  device_id uuid references public.teilog_push_devices(id) on delete cascade,
  day date not null,
  kind text not null default 'morning' check(kind in ('morning','test')),
  status text not null default 'claimed' check(status in ('claimed','sent','failed','expired')),
  created_at timestamptz not null default now(),
  primary key(device_id,day,kind)
);
alter table public.teilog_push_deliveries enable row level security;
revoke all on public.teilog_push_deliveries from anon, authenticated;

create function public.teilog_save_push(device_id uuid, push_subscription jsonb, push_rules jsonb,
  turn_on boolean, expected_revision bigint, expected_user_id uuid)
returns bigint language plpgsql security definer set search_path='' as $$
declare owner_id uuid:=auth.uid(); saved bigint; item record; v jsonb; ep text; favorites jsonb; names jsonb;
begin
 if owner_id is null or expected_user_id is distinct from owner_id then raise exception 'Authentication changed' using errcode='28000'; end if;
 ep:=push_subscription->>'endpoint';
 if ep is null or length(ep)>4096 or ep !~ '^https://(fcm[.]googleapis[.]com|updates[.]push[.]services[.]mozilla[.]com|web[.]push[.]apple[.]com|[a-z0-9-]+[.]notify[.]windows[.]com)/[^[:space:]#]+$'
 or jsonb_typeof(push_subscription->'keys') is distinct from 'object'
 or coalesce(push_subscription->'keys'->>'p256dh','') !~ '^[A-Za-z0-9_-]{87,88}$'
 or coalesce(push_subscription->'keys'->>'auth','') !~ '^[A-Za-z0-9_-]{22,24}$'
 or jsonb_typeof(push_rules) is distinct from 'object' or octet_length(push_rules::text)>100000 then raise exception 'Invalid notification settings'; end if;
 for item in select * from jsonb_each(push_rules) loop
  if item.key !~ '^[0-9]{4}$' or jsonb_typeof(item.value) is distinct from 'array' or jsonb_array_length(item.value)>6 then raise exception 'Invalid racer rule'; end if;
  for v in select * from jsonb_array_elements(item.value) loop
   if v::text !~ '^[1-6]$' then raise exception 'Invalid frame'; end if;
  end loop;
 end loop;
 select data->'fav' into favorites from public.teilog_notes where user_id=owner_id;
 select coalesce(jsonb_object_agg(key,value),'{}'::jsonb),
        coalesce(jsonb_object_agg(key,left(coalesce(favorites->key->>'name',key),30)),'{}'::jsonb)
 into push_rules,names from jsonb_each(push_rules) where coalesce(favorites,'{}'::jsonb) ? key;
 if expected_revision=0 then
  insert into public.teilog_push_devices(id,user_id,subscription,rules,racer_names,enabled)
   values(device_id,owner_id,push_subscription,push_rules,names,turn_on) on conflict do nothing returning revision into saved;
 else
  update public.teilog_push_devices set subscription=push_subscription,rules=push_rules,racer_names=names,enabled=turn_on,revision=revision+1,updated_at=now()
   where id=device_id and user_id=owner_id and revision=expected_revision returning revision into saved;
 end if;
 if saved is null then raise exception 'Settings changed; reload' using errcode='40001'; end if;
 return saved;
end $$;
revoke all on function public.teilog_save_push(uuid,jsonb,jsonb,boolean,bigint,uuid) from public,anon;
grant execute on function public.teilog_save_push(uuid,jsonb,jsonb,boolean,bigint,uuid) to authenticated;

-- Runner can claim once per device/day. Private endpoints never enter Git.
create function public.teilog_claim_push(target_device uuid, target_day date, expected_revision bigint, target_kind text default 'morning')
returns boolean language plpgsql security definer set search_path='' as $$
declare claimed uuid;
begin
 perform 1 from public.teilog_push_devices where id=target_device and enabled and revision=expected_revision for update;
 if not found then return false; end if;
 insert into public.teilog_push_deliveries(device_id,day,kind) values(target_device,target_day,target_kind)
 on conflict do nothing returning device_id into claimed;
 return claimed is not null;
end $$;
revoke all on function public.teilog_claim_push(uuid,date,bigint,text) from public,anon,authenticated;
grant execute on function public.teilog_claim_push(uuid,date,bigint,text) to service_role;
grant select,update,delete on public.teilog_push_devices to service_role;
grant select,insert,update,delete on public.teilog_push_deliveries to service_role;
-- Removing a saved favorite removes it from notification rules atomically.
-- The sender has NO new access to the private notes table.
create schema if not exists teilog_private;
revoke all on schema teilog_private from public,anon,authenticated;
create function teilog_private.prune_push_favorites() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 update public.teilog_push_devices d set
  rules=(select coalesce(jsonb_object_agg(key,value),'{}'::jsonb) from jsonb_each(d.rules) where (new.data->'fav') ? key),
  racer_names=(select coalesce(jsonb_object_agg(key,left(coalesce(new.data->'fav'->key->>'name',key),30)),'{}'::jsonb) from jsonb_each(d.rules) where (new.data->'fav') ? key),
  revision=revision+1,updated_at=now()
 where d.user_id=new.user_id and (old.data->'fav') is distinct from (new.data->'fav');
 return new;
end $$;
revoke all on function teilog_private.prune_push_favorites() from public,anon,authenticated,service_role;
create trigger teilog_notification_favorite_removed after update of data on public.teilog_notes
 for each row execute function teilog_private.prune_push_favorites();
commit;
